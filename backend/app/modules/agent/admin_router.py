"""
Agent 管理后台路由（Admin Router）

提供管理员视角的 Agent Run 查询、统计、回放接口。
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client
from .service import AgentService
from .events import event_store

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/agent-runs", tags=["Admin Agent Runs"])


async def get_db():
    async with mysql_client.session() as session:
        yield session


def _metadata_value(run: Any, key: str) -> Any:
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    return metadata.get(key)


def _serialize_run(run: Any, *, last_event_sequence: int = 0) -> dict[str, Any]:
    """将当前 AgentRun 模型稳定映射为管理员前端契约。"""
    return {
        "id": run.id,
        "thread_id": run.thread_id,
        "user_id": run.user_id,
        "workflow_key": run.workflow_key or run.workflow_name,
        "workflow_version": run.workflow_version or "v1",
        "status": run.status,
        "request_id": run.client_idempotency_key or "",
        "current_step_key": run.current_public_step,
        "last_event_sequence": last_event_sequence,
        "lease_owner": run.lease_owner,
        "lease_expires_at": (
            run.lease_expires_at.isoformat() if run.lease_expires_at else None
        ),
        "model_config_id": _metadata_value(run, "model_config_id"),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_code": _metadata_value(run, "error_code"),
        "safe_error_summary": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


async def _last_event_sequences(
    db: AsyncSession,
    run_ids: list[str],
) -> dict[str, int]:
    if not run_ids:
        return {}

    from .models import AgentEvent

    result = await db.execute(
        sa_select(AgentEvent.run_id, func.max(AgentEvent.sequence))
        .where(AgentEvent.run_id.in_(run_ids))
        .group_by(AgentEvent.run_id)
    )
    return {run_id: int(sequence or 0) for run_id, sequence in result.all()}


@router.get("/stats")
async def get_run_stats(
    db: AsyncSession = Depends(get_db),
):
    """获取 Run 统计信息"""
    from .models import AgentRun

    total_result = await db.execute(sa_select(func.count(AgentRun.id)))
    total = total_result.scalar() or 0

    status_counts = {}
    for status in ["queued", "running", "completed", "failed", "waiting_for_user", "waiting_for_approval"]:
        result = await db.execute(
            sa_select(func.count(AgentRun.id)).where(AgentRun.status == status)
        )
        status_counts[status] = result.scalar() or 0

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
    """列出所有 Agent Runs（管理员视图）"""
    from .models import AgentRun

    query = sa_select(AgentRun)

    if status:
        query = query.where(AgentRun.status == status)
    if workflow_key:
        query = query.where(AgentRun.workflow_name == workflow_key)
    if user_id:
        query = query.where(AgentRun.user_id == user_id)
    if start_date:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            query = query.where(AgentRun.created_at >= dt)
        except ValueError:
            pass
    if end_date:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            query = query.where(AgentRun.created_at <= dt)
        except ValueError:
            pass

    # Get total count
    count_query = query.order_by(None).subquery()
    total_result = await db.execute(
        sa_select(func.count()).select_from(count_query)
    )
    total = total_result.scalar() or 0

    # Get paginated results
    offset = (page - 1) * page_size
    query = query.order_by(AgentRun.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    runs = result.scalars().all()
    event_sequences = await _last_event_sequences(db, [run.id for run in runs])

    return {
        "data": {
            "items": [
                _serialize_run(
                    run,
                    last_event_sequence=event_sequences.get(run.id, 0),
                )
                for run in runs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    }


@router.get("/{run_id}")
async def get_run_detail(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 Run 详情（管理员视图）"""
    from .models import AgentRun
    result = await db.execute(
        sa_select(AgentRun).where(AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run 不存在")

    event_sequences = await _last_event_sequences(db, [run.id])
    return {
        "data": _serialize_run(
            run,
            last_event_sequence=event_sequences.get(run.id, 0),
        )
    }


@router.get("/{run_id}/events")
async def get_run_events_admin(
    run_id: str,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """获取 Run 事件（管理员视图）"""
    events = await event_store.get_events(db, run_id, after_sequence, limit)
    return {
        "data": {
            "run_id": run_id,
            "events": [
                {
                    "id": e.id,
                    "run_id": e.run_id,
                    "sequence": e.sequence,
                    "event_type": e.event_type,
                    "payload": e.payload,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
            "total": len(events),
        }
    }


@router.get("/{run_id}/artifacts")
async def get_run_artifacts_admin(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 Run 产物（管理员视图）"""
    from sqlalchemy import select as sa_select
    from .models import AgentArtifact

    result = await db.execute(
        sa_select(AgentArtifact).where(AgentArtifact.run_id == run_id).order_by(AgentArtifact.created_at.desc())
    )
    artifacts = result.scalars().all()
    return {
        "data": {
            "run_id": run_id,
            "artifacts": [
                {
                    "id": a.id,
                    "type": a.artifact_type,
                    "content": a.content_json,
                    "metadata": a.metadata_json,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in artifacts
            ],
            "total": len(artifacts),
        }
    }


@router.post("/{run_id}/replay")
async def replay_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """重放 Run（创建评估副本）"""
    from sqlalchemy import select as sa_select
    from .models import AgentRun

    result = await db.execute(sa_select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run 不存在")

    # P0/P1: 简化重放，返回原始 run_id 作为 eval_run_id
    # 后续可扩展为创建新的评估 run
    logger.info("Run 重放请求", run_id=run_id)
    return {
        "data": {
            "eval_run_id": run_id,
            "message": "重放任务已创建（简化版）",
        }
    }
