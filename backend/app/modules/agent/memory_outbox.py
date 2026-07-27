"""Memory Outbox 的扫描、租约认领与可靠消费。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client

from .conversation_summary import (
    CONVERSATION_SUMMARY_TASK,
    ConversationSummaryMaintainer,
    conversation_summary_maintainer,
)
from .admin_memory import safe_error_summary
from .memory_item_projection import project_trusted_memory_event
from .memory_vector import (
    MemoryVectorLifecycle,
    is_memory_vector_task,
    memory_vector_lifecycle,
)
from .models import AgentMemoryEvent, AgentMemoryUpdateOutbox, AgentRun
from .preference_memory import (
    PREFERENCE_EXTRACTION_TASK,
    PreferenceCandidateProjector,
    preference_candidate_projector,
)
from .time_utils import utc_now
from .thread_memory_deletion import (
    THREAD_MEMORY_DELETE_TASK,
    ThreadMemoryDeletionProcessor,
    thread_memory_deletion_processor,
)

logger = get_logger(__name__)

MEMORY_WORKER_ID = f"memory_worker_{uuid.uuid4().hex[:16]}"
MemoryProjector = Callable[[AsyncSession, AgentMemoryEvent], Awaitable[None]]


class MemoryOutboxStore:
    """Memory Outbox 的数据库状态机。"""

    @staticmethod
    def _claimable(now):
        return or_(
            and_(
                AgentMemoryUpdateOutbox.status == "pending",
                AgentMemoryUpdateOutbox.scheduled_at <= now,
            ),
            and_(
                AgentMemoryUpdateOutbox.status == "processing",
                AgentMemoryUpdateOutbox.scheduled_at <= now,
            ),
        )

    async def _expire_exhausted_processing(
        self,
        db: AsyncSession,
        now,
        max_retries: int,
        *,
        outbox_id: int | None = None,
    ) -> None:
        statement = (
            update(AgentMemoryUpdateOutbox)
            .where(AgentMemoryUpdateOutbox.status == "processing")
            .where(AgentMemoryUpdateOutbox.scheduled_at <= now)
            .where(AgentMemoryUpdateOutbox.retry_count >= max_retries)
            .values(status="failed", processed_at=now)
            .execution_options(synchronize_session=False)
        )
        if outbox_id is not None:
            statement = statement.where(AgentMemoryUpdateOutbox.id == outbox_id)
        await db.execute(statement)

    async def scan_due(
        self,
        db: AsyncSession,
        *,
        limit: int = 10,
        max_retries: int = 3,
    ) -> list[AgentMemoryUpdateOutbox]:
        """扫描到期 pending 任务和租约已过期的 processing 任务。"""
        now = utc_now()
        await self._expire_exhausted_processing(db, now, max_retries)
        result = await db.execute(
            select(AgentMemoryUpdateOutbox)
            .where(self._claimable(now))
            .where(AgentMemoryUpdateOutbox.retry_count < max_retries)
            .order_by(
                AgentMemoryUpdateOutbox.scheduled_at,
                AgentMemoryUpdateOutbox.id,
            )
            .limit(limit)
        )
        return list(result.scalars())

    async def claim(
        self,
        db: AsyncSession,
        outbox_id: int,
        worker_id: str,
        *,
        lease_seconds: int = 300,
        max_retries: int = 3,
    ) -> bool:
        """原子认领任务；接管过期 processing 时把崩溃计为一次重试。"""
        now = utc_now()
        await self._expire_exhausted_processing(
            db,
            now,
            max_retries,
            outbox_id=outbox_id,
        )
        result = await db.execute(
            update(AgentMemoryUpdateOutbox)
            .where(AgentMemoryUpdateOutbox.id == outbox_id)
            .where(self._claimable(now))
            .where(AgentMemoryUpdateOutbox.retry_count < max_retries)
            .values(
                status="processing",
                worker_id=worker_id,
                retry_count=case(
                    (
                        AgentMemoryUpdateOutbox.status == "processing",
                        AgentMemoryUpdateOutbox.retry_count + 1,
                    ),
                    else_=AgentMemoryUpdateOutbox.retry_count,
                ),
                scheduled_at=now + timedelta(seconds=lease_seconds),
                processed_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)

    async def complete(
        self,
        db: AsyncSession,
        outbox_id: int,
        worker_id: str,
    ) -> bool:
        """只有当前租约拥有者可以完成 processing 任务。"""
        result = await db.execute(
            update(AgentMemoryUpdateOutbox)
            .where(AgentMemoryUpdateOutbox.id == outbox_id)
            .where(AgentMemoryUpdateOutbox.status == "processing")
            .where(AgentMemoryUpdateOutbox.worker_id == worker_id)
            .values(status="completed", processed_at=utc_now())
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)

    async def fail(
        self,
        db: AsyncSession,
        outbox_id: int,
        worker_id: str,
        *,
        error_message: str | None = None,
        retry_delay_seconds: int = 30,
        max_retries: int = 3,
    ) -> bool:
        """记录失败；预算内延迟重试，耗尽后进入 failed 终态。"""
        now = utc_now()
        next_retry_count = AgentMemoryUpdateOutbox.retry_count + 1
        exhausted = next_retry_count >= max_retries
        result = await db.execute(
            update(AgentMemoryUpdateOutbox)
            .where(AgentMemoryUpdateOutbox.id == outbox_id)
            .where(AgentMemoryUpdateOutbox.status == "processing")
            .where(AgentMemoryUpdateOutbox.worker_id == worker_id)
            .values(
                status=case((exhausted, "failed"), else_="pending"),
                retry_count=next_retry_count,
                worker_id=case(
                    (exhausted, AgentMemoryUpdateOutbox.worker_id),
                    else_=None,
                ),
                scheduled_at=case(
                    (exhausted, AgentMemoryUpdateOutbox.scheduled_at),
                    else_=now + timedelta(seconds=retry_delay_seconds),
                ),
                processed_at=case((exhausted, now), else_=None),
                last_error_message=safe_error_summary(error_message),
            )
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)


class MemoryOutboxConsumer:
    """消费已认领的 Memory Outbox，并隔离投影失败。"""

    def __init__(
        self,
        *,
        store: MemoryOutboxStore | None = None,
        projector: MemoryProjector = project_trusted_memory_event,
        summary_maintainer: ConversationSummaryMaintainer = (
            conversation_summary_maintainer
        ),
        vector_lifecycle: MemoryVectorLifecycle = memory_vector_lifecycle,
        preference_projector: PreferenceCandidateProjector = (
            preference_candidate_projector
        ),
        thread_deletion_processor: ThreadMemoryDeletionProcessor = (
            thread_memory_deletion_processor
        ),
        lease_seconds: int = 300,
        retry_delay_seconds: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.store = store or MemoryOutboxStore()
        self.projector = projector
        self.summary_maintainer = summary_maintainer
        self.vector_lifecycle = vector_lifecycle
        self.preference_projector = preference_projector
        self.thread_deletion_processor = thread_deletion_processor
        self.lease_seconds = lease_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.max_retries = max_retries

    async def process_claimed(
        self,
        db: AsyncSession,
        outbox_id: int,
        worker_id: str,
    ) -> bool:
        """在 SAVEPOINT 中投影一个已认领任务，失败只改变 Outbox。"""
        outbox = await db.scalar(
            select(AgentMemoryUpdateOutbox).where(
                AgentMemoryUpdateOutbox.id == outbox_id,
                AgentMemoryUpdateOutbox.status == "processing",
                AgentMemoryUpdateOutbox.worker_id == worker_id,
            )
        )
        if outbox is None:
            return False

        try:
            async with db.begin_nested():
                if outbox.event_type == THREAD_MEMORY_DELETE_TASK:
                    await self.thread_deletion_processor.process_outbox(db, outbox)
                elif outbox.event_type == PREFERENCE_EXTRACTION_TASK:
                    await self.preference_projector.process_outbox(db, outbox)
                elif is_memory_vector_task(outbox.event_type):
                    await self.vector_lifecycle.process_outbox(db, outbox)
                elif outbox.event_type == CONVERSATION_SUMMARY_TASK:
                    trigger_run_id = str(
                        outbox.payload_json.get("trigger_run_id") or ""
                    )
                    task_type = str(outbox.payload_json.get("task_type") or "")
                    trigger_run = await db.scalar(
                        select(AgentRun).where(
                            AgentRun.id == trigger_run_id,
                            AgentRun.id == outbox.run_id,
                            AgentRun.thread_id == outbox.thread_id,
                            AgentRun.user_id == outbox.user_id,
                            AgentRun.status == "completed",
                        )
                    )
                    if trigger_run is None or task_type != CONVERSATION_SUMMARY_TASK:
                        raise ValueError("对话摘要 Outbox 与已完成 Run 不匹配")
                    await self.summary_maintainer.maintain(
                        db,
                        thread_id=outbox.thread_id,
                        user_id=outbox.user_id,
                        trigger_run_id=trigger_run.id,
                    )
                else:
                    memory_event_id = int(outbox.payload_json.get("memory_event_id"))
                    fact_type = str(outbox.payload_json.get("fact_type") or "")
                    memory_event = await db.scalar(
                        select(AgentMemoryEvent).where(
                            AgentMemoryEvent.id == memory_event_id,
                            AgentMemoryEvent.run_id == outbox.run_id,
                            AgentMemoryEvent.thread_id == outbox.thread_id,
                            AgentMemoryEvent.user_id == outbox.user_id,
                            AgentMemoryEvent.fact_type == outbox.event_type,
                            AgentMemoryEvent.fact_type == fact_type,
                        )
                    )
                    if memory_event is None:
                        raise ValueError("Memory Outbox 与可信事实不匹配")
                    await self.projector(db, memory_event)
        except Exception as error:
            logger.error(
                "Memory Outbox 投影失败",
                outbox_id=outbox_id,
                worker_id=worker_id,
                error=str(error),
                exc_info=True,
            )
            await self.store.fail(
                db,
                outbox_id,
                worker_id,
                error_message=str(error),
                retry_delay_seconds=self.retry_delay_seconds,
                max_retries=self.max_retries,
            )
            return False

        return await self.store.complete(db, outbox_id, worker_id)

    async def scan_and_process(
        self,
        *,
        limit: int = 10,
        worker_id: str = MEMORY_WORKER_ID,
    ) -> int:
        """用独立认领事务和处理事务消费一批到期任务。"""
        async with mysql_client.session() as db:
            due = await self.store.scan_due(
                db,
                limit=limit,
                max_retries=self.max_retries,
            )
            due_ids = [item.id for item in due]

        processed = 0
        for outbox_id in due_ids:
            async with mysql_client.session() as db:
                claimed = await self.store.claim(
                    db,
                    outbox_id,
                    worker_id,
                    lease_seconds=self.lease_seconds,
                    max_retries=self.max_retries,
                )
            if not claimed:
                continue
            async with mysql_client.session() as db:
                await self.process_claimed(db, outbox_id, worker_id)
            processed += 1
        return processed


memory_outbox_consumer = MemoryOutboxConsumer()
