"""Memory Outbox 管理列表、失败详情与原记录幂等重放。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import AuditLog

from .admin_memory import redact_admin_value, safe_error_summary
from .models import AgentMemoryUpdateOutbox
from .time_utils import utc_isoformat, utc_now


def _replay_state(row: AgentMemoryUpdateOutbox, *, now: datetime) -> tuple[bool, str | None]:
    if row.status == "completed":
        return False, "已完成任务不可重放"
    if row.status == "processing" and row.scheduled_at > now:
        return False, "任务仍在有效处理租约内"
    if row.status not in {"failed", "pending", "processing"}:
        return False, "当前状态不可重放"
    return True, None


def serialize_memory_outbox(
    row: AgentMemoryUpdateOutbox,
    *,
    include_payload: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or utc_now()
    replay_allowed, replay_block_reason = _replay_state(row, now=effective_now)
    payload = {
        "id": row.id,
        "run_id": row.run_id,
        "thread_id": row.thread_id,
        "user_id": row.user_id,
        "event_type": row.event_type,
        "task_key": row.task_key,
        "status": row.status,
        "retry_count": row.retry_count,
        "worker_id": row.worker_id,
        "safe_error_summary": safe_error_summary(row.last_error_message),
        "scheduled_at": utc_isoformat(row.scheduled_at),
        "processed_at": utc_isoformat(row.processed_at),
        "created_at": utc_isoformat(row.created_at),
        "replay_allowed": replay_allowed,
        "replay_block_reason": replay_block_reason,
    }
    if include_payload:
        payload["payload"] = redact_admin_value(row.payload_json or {})
    return payload


async def list_memory_outbox(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    event_type: str | None = None,
    status: str | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    source_id: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    """按运维字段分页筛选 Outbox，不返回原始异常堆栈。"""
    filters = []
    if event_type:
        filters.append(AgentMemoryUpdateOutbox.event_type == event_type)
    if status:
        filters.append(AgentMemoryUpdateOutbox.status == status)
    if run_id:
        filters.append(AgentMemoryUpdateOutbox.run_id == run_id)
    if thread_id:
        filters.append(AgentMemoryUpdateOutbox.thread_id == thread_id)
    if source_id:
        source_fields = (
            "source_id",
            "memory_event_id",
            "trigger_run_id",
            "candidate_id",
        )
        filters.append(
            or_(
                *[
                    cast(
                        AgentMemoryUpdateOutbox.payload_json[field].as_string(),
                        String,
                    )
                    == source_id
                    for field in source_fields
                ]
            )
        )
    if start_at:
        filters.append(AgentMemoryUpdateOutbox.created_at >= start_at)
    if end_at:
        filters.append(AgentMemoryUpdateOutbox.created_at <= end_at)

    total = int(
        await db.scalar(
            select(func.count(AgentMemoryUpdateOutbox.id)).where(*filters)
        )
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(AgentMemoryUpdateOutbox)
                .where(*filters)
                .order_by(
                    AgentMemoryUpdateOutbox.created_at.desc(),
                    AgentMemoryUpdateOutbox.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    now = utc_now()
    return {
        "items": [serialize_memory_outbox(row, now=now) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_memory_outbox_detail(
    db: AsyncSession,
    outbox_id: int,
) -> dict[str, Any]:
    row = await db.scalar(
        select(AgentMemoryUpdateOutbox).where(
            AgentMemoryUpdateOutbox.id == outbox_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Memory Outbox 不存在")
    return serialize_memory_outbox(row, include_payload=True)


async def replay_memory_outbox(
    db: AsyncSession,
    *,
    outbox_id: int,
    admin_user_id: str,
    ip_address: str | None,
    user_agent: str | None,
) -> dict[str, Any]:
    """锁定并恢复原 Outbox 记录；保留 run/type 或 task_key 幂等身份。"""
    row = await db.scalar(
        select(AgentMemoryUpdateOutbox)
        .where(AgentMemoryUpdateOutbox.id == outbox_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Memory Outbox 不存在")
    now = utc_now()
    replay_allowed, replay_block_reason = _replay_state(row, now=now)
    if not replay_allowed:
        raise HTTPException(status_code=409, detail=replay_block_reason)

    previous = {
        "status": row.status,
        "retry_count": row.retry_count,
        "worker_id": row.worker_id,
        "scheduled_at": utc_isoformat(row.scheduled_at),
        "processed_at": utc_isoformat(row.processed_at),
    }
    row.status = "pending"
    row.retry_count = 0
    row.worker_id = None
    row.scheduled_at = now
    row.processed_at = None
    db.add(
        AuditLog(
            user_id=admin_user_id,
            action="agent_memory_outbox_replay",
            resource_type="agent_memory_outbox",
            resource_id=str(row.id),
            old_values=previous,
            new_values={
                "outbox_id": row.id,
                "status": row.status,
                "retry_count": row.retry_count,
                "run_id": row.run_id,
                "thread_id": row.thread_id,
                "event_type": row.event_type,
                "task_key": row.task_key,
                "scheduled_at": utc_isoformat(row.scheduled_at),
            },
            ip_address=ip_address,
            user_agent=(user_agent or "")[:500] or None,
        )
    )
    await db.flush()
    return serialize_memory_outbox(row, include_payload=True, now=now)
