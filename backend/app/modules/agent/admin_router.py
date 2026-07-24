"""Agent 管理后台路由。

管理端以 Thread（完整会话）为监控主实体；每个 Thread 详情按根 Run 聚合为多轮问答，
并保留使用旧 Run ID 打开详情的兼容能力。
"""

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client

from .events import event_store
from .time_utils import utc_isoformat

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/agent-runs", tags=["Admin Agent Runs"])


async def get_db():
    async with mysql_client.session() as session:
        yield session


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _metadata_value(run: Any, key: str) -> Any:
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    return metadata.get(key)


def _serialize_run(run: Any, *, event_count: int = 0) -> dict[str, Any]:
    """将 AgentRun 映射为管理端会话详情中的运行节点。"""
    return {
        "id": run.id,
        "thread_id": run.thread_id,
        "user_id": run.user_id,
        "workflow_key": run.workflow_key or run.workflow_name,
        "workflow_version": run.workflow_version or "v1",
        "status": run.status,
        "input_message": run.input_message,
        "trigger_message_id": run.trigger_message_id,
        "parent_run_id": run.parent_run_id,
        "root_run_id": run.root_run_id or run.id,
        "presentation": run.presentation,
        "public_title": run.public_title,
        "public_summary": run.public_summary,
        "current_step_key": run.current_public_step,
        "event_count": event_count,
        "model_config_id": _metadata_value(run, "model_config_id"),
        "error_code": _metadata_value(run, "error_code"),
        "safe_error_summary": run.error_message,
        "started_at": utc_isoformat(run.started_at),
        "completed_at": utc_isoformat(run.completed_at),
        "created_at": utc_isoformat(run.created_at),
        "updated_at": utc_isoformat(run.updated_at),
    }


def _serialize_message(message: Any) -> dict[str, Any]:
    return {
        "id": message.id,
        "run_id": message.run_id,
        "role": message.role,
        "status": message.status,
        "content": message.content_text or "",
        "error_code": message.error_code,
        "created_at": utc_isoformat(message.created_at),
        "completed_at": utc_isoformat(message.completed_at),
    }


def _serialize_event(event: Any) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": event.payload or {},
        "created_at": utc_isoformat(event.created_at),
    }


def _serialize_approval(approval: Any) -> dict[str, Any]:
    return {
        "id": approval.id,
        "run_id": approval.run_id,
        "action_key": approval.action_key,
        "status": approval.status,
        "diff_ref": approval.diff_ref,
        "precondition_ref": approval.precondition_ref,
        "decided_by": approval.decided_by,
        "expires_at": utc_isoformat(approval.expires_at),
        "created_at": utc_isoformat(approval.created_at),
        "updated_at": utc_isoformat(approval.updated_at),
    }


def _serialize_artifact(artifact: Any) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "run_id": artifact.run_id,
        "type": artifact.artifact_type,
        "content": artifact.content_json,
        "metadata": artifact.metadata_json or {},
        "created_at": utc_isoformat(artifact.created_at),
    }


def _root_id(run: Any) -> str:
    return run.root_run_id or (run.id if run.parent_run_id is None else run.parent_run_id)


def _build_turns(
    runs: list[Any],
    messages: list[Any],
    events: list[Any],
    approvals: list[Any],
    artifacts: list[Any],
) -> list[dict[str, Any]]:
    """按根 Run 把一次用户提问引起的全部运行数据聚合成一轮问答。"""
    runs_by_root: dict[str, list[Any]] = defaultdict(list)
    for run in runs:
        runs_by_root[_root_id(run)].append(run)

    messages_by_run: dict[str, list[Any]] = defaultdict(list)
    for item in messages:
        if item.run_id:
            messages_by_run[item.run_id].append(item)

    events_by_run: dict[str, list[Any]] = defaultdict(list)
    for item in events:
        events_by_run[item.run_id].append(item)
    approvals_by_run: dict[str, list[Any]] = defaultdict(list)
    for item in approvals:
        approvals_by_run[item.run_id].append(item)
    artifacts_by_run: dict[str, list[Any]] = defaultdict(list)
    for item in artifacts:
        artifacts_by_run[item.run_id].append(item)

    root_runs = [run for run in runs if run.parent_run_id is None]
    root_runs.sort(key=lambda item: (item.created_at, item.id))
    turns: list[dict[str, Any]] = []
    for turn_number, root_run in enumerate(root_runs, start=1):
        turn_runs = sorted(
            runs_by_root.get(root_run.id, [root_run]),
            key=lambda item: (item.created_at, item.id),
        )
        run_ids = {run.id for run in turn_runs}
        turn_messages = [
            message for run_id in run_ids for message in messages_by_run.get(run_id, [])
        ]
        turn_messages.sort(key=lambda item: (item.created_at, item.id))
        user_message = next(
            (
                message
                for message in turn_messages
                if message.id == root_run.trigger_message_id
            ),
            next((message for message in turn_messages if message.role == "user"), None),
        )
        assistant_messages = [
            _serialize_message(message)
            for message in turn_messages
            if message.role == "assistant"
        ]
        turn_events = [
            event for run_id in run_ids for event in events_by_run.get(run_id, [])
        ]
        turn_events.sort(key=lambda item: (item.created_at, item.run_id, item.sequence))
        turn_approvals = [
            approval
            for run_id in run_ids
            for approval in approvals_by_run.get(run_id, [])
        ]
        turn_artifacts = [
            artifact
            for run_id in run_ids
            for artifact in artifacts_by_run.get(run_id, [])
        ]
        turns.append(
            {
                "turn_number": turn_number,
                "root_run_id": root_run.id,
                "status": root_run.status,
                "input_message": root_run.input_message or "",
                "user_message": _serialize_message(user_message) if user_message else None,
                "assistant_messages": assistant_messages,
                "runs": [
                    _serialize_run(run, event_count=len(events_by_run.get(run.id, [])))
                    for run in turn_runs
                ],
                "events": [_serialize_event(event) for event in turn_events],
                "approvals": [
                    _serialize_approval(approval) for approval in turn_approvals
                ],
                "artifacts": [
                    _serialize_artifact(artifact) for artifact in turn_artifacts
                ],
                "created_at": utc_isoformat(root_run.created_at),
                "completed_at": utc_isoformat(root_run.completed_at),
            }
        )
    return turns


async def _resolve_thread(db: AsyncSession, identifier: str):
    """优先按 Thread ID 查找，并兼容把旧 Run ID 解析到所属会话。"""
    from .models import AgentRun, AgentThread

    result = await db.execute(sa_select(AgentThread).where(AgentThread.id == identifier))
    thread = result.scalar_one_or_none()
    if thread:
        return thread
    result = await db.execute(sa_select(AgentRun).where(AgentRun.id == identifier))
    run = result.scalar_one_or_none()
    if not run:
        return None
    result = await db.execute(sa_select(AgentThread).where(AgentThread.id == run.thread_id))
    return result.scalar_one_or_none()


@router.get("/stats")
async def get_run_stats(db: AsyncSession = Depends(get_db)):
    """按每个会话最新一轮的状态统计会话数。"""
    from .models import AgentRun, AgentThread

    total_result = await db.execute(sa_select(func.count(AgentThread.id)))
    total = int(total_result.scalar() or 0)
    ranked_runs = (
        sa_select(
            AgentRun.thread_id.label("thread_id"),
            AgentRun.status.label("status"),
            func.row_number()
            .over(
                partition_by=AgentRun.thread_id,
                order_by=(AgentRun.created_at.desc(), AgentRun.id.desc()),
            )
            .label("rank_no"),
        )
        .where(AgentRun.parent_run_id.is_(None))
        .subquery()
    )
    status_result = await db.execute(
        sa_select(ranked_runs.c.status, func.count())
        .where(ranked_runs.c.rank_no == 1)
        .group_by(ranked_runs.c.status)
    )
    status_counts = {status: int(count) for status, count in status_result.all()}
    return {
        "data": {
            "total": total,
            "queued": status_counts.get("queued", 0),
            "running": status_counts.get("running", 0),
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
            "waiting_for_user": status_counts.get("waiting_for_user", 0),
            "waiting_for_approval": status_counts.get("waiting_for_approval", 0),
        }
    }


@router.get("")
async def list_all_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    workflow_key: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """按完整会话列出 Agent 监控记录，一条记录对应一个 Thread。"""
    from .models import AgentEvent, AgentRun, AgentThread

    query = sa_select(AgentThread)
    if user_id:
        query = query.where(AgentThread.user_id == user_id)
    start_at = _parse_datetime(start_date)
    end_at = _parse_datetime(end_date)
    if start_at:
        query = query.where(AgentThread.created_at >= start_at)
    if end_at:
        query = query.where(AgentThread.created_at <= end_at)
    if status or workflow_key:
        matching_turn = sa_select(AgentRun.id).where(
            AgentRun.thread_id == AgentThread.id,
            AgentRun.parent_run_id.is_(None),
        )
        if status:
            matching_turn = matching_turn.where(AgentRun.status == status)
        if workflow_key:
            matching_turn = matching_turn.where(
                (AgentRun.workflow_key == workflow_key)
                | (AgentRun.workflow_name == workflow_key)
            )
        query = query.where(exists(matching_turn))

    total_result = await db.execute(
        sa_select(func.count()).select_from(query.order_by(None).subquery())
    )
    total = int(total_result.scalar() or 0)
    result = await db.execute(
        query.order_by(AgentThread.updated_at.desc(), AgentThread.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    threads = result.scalars().all()
    thread_ids = [thread.id for thread in threads]
    if not thread_ids:
        return {"data": {"items": [], "total": total, "page": page, "page_size": page_size}}

    run_result = await db.execute(
        sa_select(AgentRun)
        .where(AgentRun.thread_id.in_(thread_ids))
        .order_by(AgentRun.created_at, AgentRun.id)
    )
    runs = run_result.scalars().all()
    runs_by_thread: dict[str, list[Any]] = defaultdict(list)
    for run in runs:
        runs_by_thread[run.thread_id].append(run)
    event_counts: dict[str, int] = defaultdict(int)
    run_ids = [run.id for run in runs]
    if run_ids:
        event_result = await db.execute(
            sa_select(AgentRun.thread_id, func.count(AgentEvent.id))
            .join(AgentEvent, AgentEvent.run_id == AgentRun.id)
            .where(AgentRun.id.in_(run_ids))
            .group_by(AgentRun.thread_id)
        )
        event_counts.update({thread_id: int(count) for thread_id, count in event_result.all()})

    items = []
    for thread in threads:
        thread_runs = runs_by_thread.get(thread.id, [])
        root_runs = [run for run in thread_runs if run.parent_run_id is None]
        latest_run = root_runs[-1] if root_runs else (thread_runs[-1] if thread_runs else None)
        items.append(
            {
                "id": thread.id,
                "thread_id": thread.id,
                "title": thread.title or "未命名会话",
                "user_id": thread.user_id,
                "thread_status": thread.status,
                "latest_status": latest_run.status if latest_run else "queued",
                "latest_workflow_key": (
                    (latest_run.workflow_key or latest_run.workflow_name)
                    if latest_run
                    else None
                ),
                "current_step_key": latest_run.current_public_step if latest_run else None,
                "turn_count": len(root_runs),
                "total_run_count": len(thread_runs),
                "event_count": event_counts.get(thread.id, 0),
                "created_at": utc_isoformat(thread.created_at),
                "updated_at": utc_isoformat(thread.updated_at),
            }
        )
    return {"data": {"items": items, "total": total, "page": page, "page_size": page_size}}


@router.get("/{run_id}")
async def get_run_detail(run_id: str, db: AsyncSession = Depends(get_db)):
    """获取完整会话详情；run_id 可为 Thread ID 或历史 Run ID。"""
    from .models import (
        AgentApproval,
        AgentArtifact,
        AgentEvent,
        AgentMessage,
        AgentRun,
    )

    thread = await _resolve_thread(db, run_id)
    if not thread:
        raise HTTPException(status_code=404, detail="会话不存在")
    run_result = await db.execute(
        sa_select(AgentRun)
        .where(AgentRun.thread_id == thread.id)
        .order_by(AgentRun.created_at, AgentRun.id)
    )
    runs = run_result.scalars().all()
    message_result = await db.execute(
        sa_select(AgentMessage)
        .where(AgentMessage.thread_id == thread.id)
        .order_by(AgentMessage.created_at, AgentMessage.id)
    )
    messages = message_result.scalars().all()
    run_ids = [run.id for run in runs]
    events: list[Any] = []
    approvals: list[Any] = []
    artifacts: list[Any] = []
    if run_ids:
        event_result = await db.execute(
            sa_select(AgentEvent)
            .where(AgentEvent.run_id.in_(run_ids))
            .order_by(AgentEvent.created_at, AgentEvent.run_id, AgentEvent.sequence)
        )
        events = event_result.scalars().all()
        approval_result = await db.execute(
            sa_select(AgentApproval)
            .where(AgentApproval.run_id.in_(run_ids))
            .order_by(AgentApproval.created_at)
        )
        approvals = approval_result.scalars().all()
        artifact_result = await db.execute(
            sa_select(AgentArtifact)
            .where(AgentArtifact.run_id.in_(run_ids))
            .order_by(AgentArtifact.created_at)
        )
        artifacts = artifact_result.scalars().all()
    turns = _build_turns(runs, messages, events, approvals, artifacts)
    latest_status = turns[-1]["status"] if turns else "queued"
    return {
        "data": {
            "id": thread.id,
            "thread_id": thread.id,
            "title": thread.title or "未命名会话",
            "user_id": thread.user_id,
            "thread_status": thread.status,
            "latest_status": latest_status,
            "turn_count": len(turns),
            "total_run_count": len(runs),
            "event_count": len(events),
            "created_at": utc_isoformat(thread.created_at),
            "updated_at": utc_isoformat(thread.updated_at),
            "turns": turns,
        }
    }


@router.get("/{run_id}/events")
async def get_run_events_admin(
    run_id: str,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """保留单 Run 事件接口，兼容外部诊断工具。"""
    events = await event_store.get_events(db, run_id, after_sequence, limit)
    return {"data": {"run_id": run_id, "events": [_serialize_event(e) for e in events], "total": len(events)}}


@router.get("/{run_id}/artifacts")
async def get_run_artifacts_admin(run_id: str, db: AsyncSession = Depends(get_db)):
    """保留单 Run 产物接口，兼容外部诊断工具。"""
    from .models import AgentArtifact

    result = await db.execute(
        sa_select(AgentArtifact)
        .where(AgentArtifact.run_id == run_id)
        .order_by(AgentArtifact.created_at.desc())
    )
    artifacts = result.scalars().all()
    return {
        "data": {
            "run_id": run_id,
            "artifacts": [_serialize_artifact(artifact) for artifact in artifacts],
            "total": len(artifacts),
        }
    }


@router.post("/{run_id}/replay")
async def replay_run(run_id: str, db: AsyncSession = Depends(get_db)):
    """重放指定的一轮根 Run（当前仍为评估占位实现）。"""
    from .models import AgentRun

    result = await db.execute(sa_select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run 不存在")
    logger.info("Run 重放请求", run_id=run_id)
    return {"data": {"eval_run_id": run_id, "message": "重放任务已创建（简化版）"}}
