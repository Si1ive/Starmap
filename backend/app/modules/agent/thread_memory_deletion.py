"""线程软删除时的分层记忆失效与向量删除交接。"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from .memory_vector import MemoryVectorLifecycle, memory_vector_lifecycle
from .models import (
    AgentConversationSummary,
    AgentMemoryItem,
    AgentMemoryUpdateOutbox,
    AgentPreferenceCandidate,
    AgentThread,
    AgentThreadMemoryState,
)

logger = get_logger(__name__)

THREAD_MEMORY_DELETE_TASK = "thread_memory_delete"


def _thread_delete_task_key(user_id: str, thread_id: str) -> str:
    return f"thread_memory_delete:{user_id}:{thread_id}"


async def delete_thread_memory(
    db: AsyncSession,
    *,
    thread_id: str,
    user_id: str,
) -> AgentThread | None:
    """同事务软删线程、失效线程来源记忆并写唯一治理 Outbox。"""
    thread = await db.scalar(
        select(AgentThread)
        .where(AgentThread.id == thread_id, AgentThread.user_id == user_id)
        .with_for_update()
    )
    if thread is None:
        return None
    thread.status = "deleted"
    await db.execute(
        delete(AgentThreadMemoryState).where(
            AgentThreadMemoryState.thread_id == thread_id,
            AgentThreadMemoryState.user_id == user_id,
        )
    )

    summaries = list(
        (
            await db.execute(
                select(AgentConversationSummary).where(
                    AgentConversationSummary.thread_id == thread_id,
                    AgentConversationSummary.user_id == user_id,
                )
            )
        ).scalars()
    )
    delete_sources: list[dict] = []
    for summary in summaries:
        summary.superseded_by_id = summary.id
        delete_sources.append(
            {
                "source_kind": "conversation_summary",
                "source_id": summary.id,
                "source_version": summary.version,
            }
        )

    items = list(
        (
            await db.execute(
                select(AgentMemoryItem).where(AgentMemoryItem.user_id == user_id)
            )
        ).scalars()
    )
    for item in items:
        metadata = item.metadata_json or {}
        belongs_to_thread = item.thread_id == thread_id or (
            metadata.get("source_thread_id") == thread_id
        )
        if not belongs_to_thread:
            continue
        if (
            item.scope == "user"
            and item.thread_id is None
            and item.item_type == "learning_goal"
        ):
            continue
        item.status = "deleted"
        source_version = int(metadata.get("source_memory_event_id") or 0)
        if source_version > 0:
            delete_sources.append(
                {
                    "source_kind": "memory_item",
                    "source_id": item.id,
                    "source_version": source_version,
                }
            )

    candidates = list(
        (
            await db.execute(
                select(AgentPreferenceCandidate).where(
                    AgentPreferenceCandidate.user_id == user_id,
                    AgentPreferenceCandidate.thread_id == thread_id,
                )
            )
        ).scalars()
    )
    for candidate in candidates:
        candidate.status = "invalidated"

    task_key = _thread_delete_task_key(user_id, thread_id)
    payload = {
        "task_type": THREAD_MEMORY_DELETE_TASK,
        "task_key": task_key,
        "thread_id": thread_id,
        "user_id": user_id,
        "delete_sources": list(
            {
                (
                    source["source_kind"],
                    source["source_id"],
                    source["source_version"],
                ): source
                for source in delete_sources
            }.values()
        ),
    }
    existing = await db.scalar(
        select(AgentMemoryUpdateOutbox).where(
            AgentMemoryUpdateOutbox.task_key == task_key
        )
    )
    if existing is not None:
        if existing.payload_json != payload:
            # 重放时 source 集合可能已被前一次事务固定；不扩写已提交任务，消费者仍按当时全集删除。
            logger.info("线程删除治理任务已存在", task_key=task_key)
        await db.flush()
        return thread
    try:
        async with db.begin_nested():
            db.add(
                AgentMemoryUpdateOutbox(
                    run_id=None,
                    thread_id=thread_id,
                    user_id=user_id,
                    event_type=THREAD_MEMORY_DELETE_TASK,
                    task_key=task_key,
                    status="pending",
                    payload_json=payload,
                )
            )
            await db.flush()
    except IntegrityError:
        logger.info("线程删除治理任务并发幂等命中", task_key=task_key)
    return thread


class ThreadMemoryDeletionProcessor:
    def __init__(
        self,
        vector_lifecycle: MemoryVectorLifecycle = memory_vector_lifecycle,
    ) -> None:
        self.vector_lifecycle = vector_lifecycle

    async def process_outbox(
        self,
        db: AsyncSession,
        outbox: AgentMemoryUpdateOutbox,
    ) -> None:
        payload = outbox.payload_json or {}
        expected_key = _thread_delete_task_key(outbox.user_id, outbox.thread_id)
        if (
            outbox.event_type != THREAD_MEMORY_DELETE_TASK
            or outbox.task_key != expected_key
            or payload.get("task_type") != THREAD_MEMORY_DELETE_TASK
            or payload.get("task_key") != expected_key
            or payload.get("thread_id") != outbox.thread_id
            or payload.get("user_id") != outbox.user_id
        ):
            raise ValueError("线程删除 Memory Outbox 契约不匹配")
        thread = await db.scalar(
            select(AgentThread).where(
                AgentThread.id == outbox.thread_id,
                AgentThread.user_id == outbox.user_id,
                AgentThread.status == "deleted",
            )
        )
        if thread is None:
            raise ValueError("线程删除任务找不到同作用域 deleted 线程")
        self.vector_lifecycle.delete_sources(payload.get("delete_sources") or [])


thread_memory_deletion_processor = ThreadMemoryDeletionProcessor()
