"""
Agent Router：创建/查询 run，SSE events
+
P0 核心 API 路由。
"""

from typing import AsyncGenerator, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.modules.identity.dependencies import require_current_user
from app.modules.identity.models import User
from .models import AgentThread, AgentRun, AgentEvent, AgentArtifact, AgentApproval
from .model_configs import (
    AgentModelConfigError,
    AgentModelConfigNotFoundError,
    AgentModelConfigService,
)
from .schemas import (
    ThreadCreateRequest, ThreadResponse, RunCreateRequest,
    RunStatusResponse, EventResponse, ArtifactResponse,
    ThreadEventsResponse, TimelineResponse, TurnCreateRequest, TurnCreateResponse,
    PreferenceCandidateDecisionRequest,
)
from .preference_memory import (
    decide_preference_candidate,
    list_preference_candidates,
)
from .service import AgentService
from .timeline import AgentTimelineService, ThreadNotFoundError, TurnConflictError
from .events import event_store, serialize_sse, serialize_sse_from_dict
from .state_machine import RunStatus
from .thread_events import thread_event_store
from .time_utils import encode_utc_datetimes, utc_isoformat
from .thread_memory_deletion import delete_thread_memory

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["Agent"])


async def get_db():
    """获取数据库session"""
    async with mysql_client.session() as session:
        yield session


async def get_current_user_id(user: User = Depends(require_current_user)) -> str:
    """获取当前认证用户ID（identity 的 UUID → 32 位 hex，匹配 agent_* 表的 String(32)）"""
    return user.id.hex


# ==================== Thread API ====================


@router.get("/models")
async def list_selectable_models(
    _user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """返回用户当前可选择的 Agent 模型，不暴露连接凭据。"""
    service = AgentModelConfigService(db)
    records = await service.list_public()
    return {"items": [service.to_public_dict(record) for record in records]}


@router.post("/threads", response_model=ThreadResponse)
async def create_thread(
    request: ThreadCreateRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """创建线程"""
    service = AgentService(db)
    thread = await service.create_thread(user_id=user_id, title=request.title)
    return ThreadResponse(
        id=thread.id,
        user_id=thread.user_id,
        title=thread.title,
        status=thread.status,
        metadata=thread.metadata_json,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.get("/threads/{thread_id}/runs")
async def list_thread_runs(
    thread_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """列出线程的所有 Run"""
    service = AgentService(db)
    runs = await service.list_runs(thread_id, user_id)
    return {
        "items": [
            {
                "id": r.id,
                "thread_id": r.thread_id,
                "user_id": r.user_id,
                "workflow_name": r.workflow_name,
                "status": r.status,
                "input_message": r.input_message,
                "result_artifact_id": r.result_artifact_id,
                "error_message": r.error_message,
                "model_call_count": r.model_call_count,
                "created_at": utc_isoformat(r.created_at),
                "updated_at": utc_isoformat(r.updated_at),
            }
            for r in runs
        ],
        "total": len(runs),
    }


@router.get("/threads")
async def list_threads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """列出用户的线程"""
    service = AgentService(db)
    threads = await service.list_threads(user_id=user_id, limit=limit, offset=offset)
    return {
        "items": [
            {
                "id": t.id,
                "user_id": t.user_id,
                "title": t.title,
                "status": t.status,
                "metadata": t.metadata_json,
                "created_at": utc_isoformat(t.created_at),
                "updated_at": utc_isoformat(t.updated_at),
            }
            for t in threads
        ],
        "total": len(threads),
        "limit": limit,
        "offset": offset,
    }


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取线程详情"""
    service = AgentService(db)
    thread = await service.get_thread(thread_id, user_id)
    if not thread:
        raise HTTPException(status_code=404, detail="线程不存在")
    return ThreadResponse(
        id=thread.id,
        user_id=thread.user_id,
        title=thread.title,
        status=thread.status,
        metadata=thread.metadata_json,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.post(
    "/threads/{thread_id}/turns",
    response_model=TurnCreateResponse,
    status_code=201,
)
async def create_turn(
    thread_id: str,
    request: TurnCreateRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """创建一轮用户对话，并原子写入消息、workflow 与时间线。"""
    service = AgentTimelineService(db)
    try:
        creation = await service.create_turn(
            user_id=user_id,
            thread_id=thread_id,
            content=request.content,
            client_message_id=request.client_message_id,
            attachments=request.attachments,
            context_refs=request.context_refs,
            model_config_id=request.model_config_id,
        )
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail="线程不存在") from exc
    except TurnConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="client_message_id 已被其他消息使用",
        ) from exc
    except (AgentModelConfigError, AgentModelConfigNotFoundError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc) or "所选模型不可用",
        ) from exc

    return TurnCreateResponse(
        user_message=AgentTimelineService.message_view(creation.message),
        root_run={
            "id": creation.run.id,
            "status": creation.run.status,
            "presentation": creation.run.presentation,
            "public_title": creation.run.public_title,
        },
        timeline_cursor=creation.timeline_cursor,
    )


@router.get("/threads/{thread_id}/timeline", response_model=TimelineResponse)
async def get_thread_timeline(
    thread_id: str,
    before: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取经过权限过滤和公开字段裁剪的 thread 时间线。"""
    service = AgentTimelineService(db)
    try:
        page = await service.get_timeline(
            user_id=user_id,
            thread_id=thread_id,
            before=before,
            limit=limit,
        )
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail="线程不存在") from exc

    return TimelineResponse(
        thread={
            "id": page.thread.id,
            "title": page.thread.title,
            "updated_at": page.thread.updated_at,
        },
        items=page.items,
        previous_cursor=page.previous_cursor,
        latest_cursor=page.latest_cursor,
        has_more=page.has_more,
    )


@router.get("/threads/{thread_id}/events", response_model=ThreadEventsResponse)
async def get_thread_events(
    thread_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """按统一 cursor 补拉 thread 事件。"""
    agent_service = AgentService(db)
    thread = await agent_service.get_thread(thread_id, user_id)
    if not thread:
        raise HTTPException(status_code=404, detail="线程不存在")
    events = await thread_event_store.get_events(
        db, thread_id, after_sequence=after_sequence, limit=limit
    )
    return ThreadEventsResponse(
        thread_id=thread_id,
        events=[
            {
                "id": event.id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": event.payload or {},
                "created_at": event.created_at,
            }
            for event in events
        ],
        latest_cursor=thread.last_item_sequence,
    )


@router.get("/threads/{thread_id}/events/stream")
async def stream_thread_events(
    thread_id: str,
    after_sequence: int = Query(default=0, ge=0),
    last_event_id: Optional[int] = Header(default=None, alias="Last-Event-ID"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """发送 thread snapshot，并持续推送 cursor 之后的公开事件。"""
    thread = await AgentService(db).get_thread(thread_id, user_id)
    if not thread:
        raise HTTPException(status_code=404, detail="线程不存在")
    requested_cursor = max(after_sequence, last_event_id or 0)

    async def event_generator() -> AsyncGenerator[str, None]:
        import asyncio

        last_sequence = requested_cursor
        idle_polls = 0
        try:
            async with mysql_client.session() as session:
                page = await AgentTimelineService(session).get_timeline(
                    user_id=user_id,
                    thread_id=thread_id,
                    before=None,
                    limit=100,
                )
                snapshot = {
                    "latest_sequence": page.latest_cursor,
                    "items": page.items,
                    "has_more": page.has_more,
                }
                yield serialize_sse_from_dict(
                    page.latest_cursor,
                    "timeline.snapshot",
                    encode_utc_datetimes(snapshot),
                )
                last_sequence = page.latest_cursor

            while True:
                async with mysql_client.session() as session:
                    events = await thread_event_store.get_events(
                        session,
                        thread_id,
                        after_sequence=last_sequence,
                        limit=200,
                    )
                    for event in events:
                        yield serialize_sse(event)
                        last_sequence = event.sequence

                if events:
                    idle_polls = 0
                else:
                    idle_polls += 1
                    if idle_polls >= 15:
                        yield ": keep-alive\n\n"
                        idle_polls = 0
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("thread SSE 客户端断开", thread_id=thread_id)
            raise
        except Exception as exc:
            logger.error("thread SSE 推送异常", thread_id=thread_id, error=str(exc))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== Run API ====================

@router.post("/runs")
async def create_run(
    request: RunCreateRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """创建 Run"""
    service = AgentService(db)
        
    # 检查线程是否存在
    thread = await service.get_thread(request.thread_id, user_id)
    if not thread:
        raise HTTPException(status_code=404, detail="线程不存在")
        
    run = await service.create_run(
        user_id=user_id,
        thread_id=request.thread_id,
        workflow_name=request.workflow_name,
        input_message=request.input_message,
        client_idempotency_key=request.client_idempotency_key,
    )
    return {
        "id": run.id,
        "thread_id": run.thread_id,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "input_message": run.input_message,
        "created_at": utc_isoformat(run.created_at),
        "updated_at": utc_isoformat(run.updated_at),
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取 Run 详情"""
    service = AgentService(db)
    run = await service.get_run(run_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run不存在")
    return {
        "id": run.id,
        "thread_id": run.thread_id,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "input_message": run.input_message,
        "result_artifact_id": run.result_artifact_id,
        "error_message": run.error_message,
        "model_call_count": run.model_call_count,
        "created_at": utc_isoformat(run.created_at),
        "updated_at": utc_isoformat(run.updated_at),
    }


@router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取 Run 的事件（支持断线重放）"""
    service = AgentService(db)
    events = await service.get_events(run_id, user_id, after_sequence, limit)
    return {
        "run_id": run_id,
        "events": [
            {
                "id": e.id,
                "sequence": e.sequence,
                "event_type": e.event_type,
                "payload": e.payload,
                "created_at": utc_isoformat(e.created_at),
            }
            for e in events
        ],
        "total": len(events),
    }


@router.get("/runs/{run_id}/events/stream")
async def stream_run_events(
    run_id: str,
    after_sequence: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """SSE 实时推送 Run 的事件"""
    async def event_generator() -> AsyncGenerator[str, None]:
        last_sequence = after_sequence
        import asyncio
        
        while True:
            try:
                async with mysql_client.session() as session:
                    service = AgentService(session)
                    events = await service.get_events(run_id, user_id, last_sequence, limit=100)
                    
                    for event in events:
                        yield serialize_sse(event)
                        last_sequence = max(last_sequence, event.sequence)
                    
                    # 如果run已完成，结束流
                    run_result = await session.execute(
                        select(AgentRun.status).where(AgentRun.id == run_id)
                    )
                    run_status = run_result.scalar_one_or_none()
                    if run_status in ["completed", "failed"]:
                        break
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error("SSE 推送异常", run_id=run_id, error=str(e))
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/submit")
async def submit_input(
    run_id: str,
    request: dict,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """提交用户输入"""
    input_text = request.get("input_text", "")
    if not input_text:
        raise HTTPException(status_code=400, detail="input_text 不能为空")
    
    service = AgentService(db)
    run = await service.submit_input(run_id, user_id, input_text)
    if not run:
        raise HTTPException(status_code=404, detail="Run不存在或无权访问")
    return {
        "run_id": run.id,
        "status": run.status,
        "message": "输入已提交",
    }


# ==================== Artifact API ====================

@router.get("/runs/{run_id}/artifacts")
async def get_run_artifacts(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取 Run 的产物"""
    service = AgentService(db)
    # 先校验run权限
    run = await service.get_run(run_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run不存在")
        
    artifacts = await service.get_artifacts_by_run(run_id)
    return {
        "run_id": run_id,
        "artifacts": [
            {
                "id": a.id,
                "run_id": a.run_id,
                "artifact_type": a.artifact_type,
                "content": a.content_json,
                "metadata": a.metadata_json,
                "created_at": utc_isoformat(a.created_at),
            }
            for a in artifacts
        ],
    }


# ==================== Input API ====================

@router.post("/runs/{run_id}/inputs/{input_key}/answer")
async def submit_input_answer(
    run_id: str,
    input_key: str,
    request: dict,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """提交结构化输入答案"""
    answer = request.get("answer", "")
    if not answer:
        raise HTTPException(status_code=400, detail="answer 不能为空")
    service = AgentService(db)
    agent_input = await service.submit_input_answer(run_id, input_key, answer, user_id)
    if not agent_input:
        raise HTTPException(status_code=404, detail="输入不存在、已过期或已回答")
    return {
        "id": agent_input.id,
        "run_id": agent_input.run_id,
        "input_key": agent_input.input_key,
        "status": agent_input.status,
        "message": "答案已提交，运行已恢复",
    }


# ==================== Approval API ====================

@router.get("/runs/{run_id}/approvals")
async def list_run_approvals(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """列出Run的所有审批请求"""
    service = AgentService(db)
    # 先校验run权限
    run = await service.get_run(run_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run不存在")

    approvals = await service.get_run_approvals(run_id)
    return {
        "run_id": run_id,
        "approvals": [
            {
                "id": a.id,
                "run_id": a.run_id,
                "action_key": a.action_key,
                "status": a.status,
                "diff_ref": a.diff_ref,
                "precondition_ref": a.precondition_ref,
                "decided_by": a.decided_by,
                "expires_at": utc_isoformat(a.expires_at),
                "created_at": utc_isoformat(a.created_at),
                "updated_at": utc_isoformat(a.updated_at),
            }
            for a in approvals
        ],
    }

@router.post("/runs/{run_id}/approvals/{approval_id}/approve")
async def approve_approval(
    run_id: str,
    approval_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """批准审批请求"""
    service = AgentService(db)
    approval = await service.decide_approval(run_id, approval_id, "approved", user_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批不存在或已处理")
    return {
        "id": approval.id,
        "status": approval.status,
        "message": "已批准",
    }


@router.post("/runs/{run_id}/approvals/{approval_id}/reject")
async def reject_approval(
    run_id: str,
    approval_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """拒绝审批请求"""
    service = AgentService(db)
    approval = await service.decide_approval(run_id, approval_id, "rejected", user_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批不存在或已处理")
    return {
        "id": approval.id,
        "status": approval.status,
        "message": "已拒绝",
    }


# ==================== Preference Candidate API ====================


def _serialize_preference_candidate(candidate) -> dict:
    return {
        "id": candidate.id,
        "thread_id": candidate.thread_id,
        "scope": candidate.scope,
        "source_kind": candidate.source_kind,
        "source_id": candidate.source_id,
        "source_version": candidate.source_version,
        "preference_key": candidate.preference_key,
        "preference_value": (candidate.preference_value_json or {}).get("value"),
        "confidence": candidate.confidence,
        "status": candidate.status,
        "extractor_version": candidate.extractor_version,
        "model_name": candidate.model_name,
        "decided_at": utc_isoformat(candidate.decided_at),
        "created_at": utc_isoformat(candidate.created_at),
        "updated_at": utc_isoformat(candidate.updated_at),
    }


@router.get("/preferences/candidates")
async def get_preference_candidates(
    status: Optional[
        Literal["pending", "approved", "rejected", "invalidated"]
    ] = Query(default=None),
    limit: int = Query(100, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    candidates = await list_preference_candidates(
        db,
        user_id=user_id,
        status=status,
        limit=limit,
    )
    return {
        "items": [_serialize_preference_candidate(item) for item in candidates],
        "total": len(candidates),
    }


@router.post("/preferences/candidates/{candidate_id}/decision")
async def decide_user_preference_candidate(
    candidate_id: str,
    request: PreferenceCandidateDecisionRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    candidate = await decide_preference_candidate(
        db,
        candidate_id=candidate_id,
        user_id=user_id,
        decision=request.decision,
        reason=request.reason,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="偏好候选不存在或已完成治理")
    return _serialize_preference_candidate(candidate)


@router.delete("/threads/{thread_id}")
async def delete_agent_thread(
    thread_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    thread = await delete_thread_memory(
        db,
        thread_id=thread_id,
        user_id=user_id,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="线程不存在")
    return {"id": thread.id, "status": thread.status}
