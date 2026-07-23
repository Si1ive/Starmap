"""
Outbox 投递 + 扫描恢复
+
P0 使用 MySQL outbox + 定时扫描，避免引入 Redis Stream。
"""

from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from .models import AgentRun, AgentRunOutbox

logger = get_logger(__name__)


class OutboxStore:
    """Outbox 存储"""

    async def enqueue(
        self,
        session: AsyncSession,
        run_id: str,
        scheduled_at: Optional[datetime] = None,
    ) -> AgentRunOutbox:
        """投递任务到outbox"""
        if scheduled_at is None:
            scheduled_at = datetime.utcnow()

        outbox = AgentRunOutbox(
            run_id=run_id,
            status="pending",
            scheduled_at=scheduled_at,
        )
        session.add(outbox)
        await session.flush()
        await session.refresh(outbox)

        logger.debug("Outbox 投递", run_id=run_id, outbox_id=outbox.id)
        return outbox

    async def scan_pending(
        self,
        session: AsyncSession,
        limit: int = 10,
        max_retries: int = 3,
    ) -> List[AgentRunOutbox]:
        """
        扫描待处理的outbox任务

        同一 thread 只返回最早尚未稳定的 root run tree 中的任务。

        queued/running 会阻塞后续 tree；等待用户或审批表示事实已稳定，
        不阻塞用户在同一 thread 继续发起下一轮对话。
        """
        candidate_run = aliased(AgentRun)
        candidate_root = aliased(AgentRun)
        earlier_root = aliased(AgentRun)
        earlier_tree_run = aliased(AgentRun)
        earlier_active_tree = exists(
            select(1)
            .select_from(earlier_root)
            .join(
                earlier_tree_run,
                or_(
                    earlier_tree_run.root_run_id == earlier_root.id,
                    earlier_tree_run.id == earlier_root.id,
                ),
            )
            .where(
                earlier_root.thread_id == candidate_root.thread_id,
                earlier_root.parent_run_id.is_(None),
                or_(
                    earlier_root.created_at < candidate_root.created_at,
                    and_(
                        earlier_root.created_at == candidate_root.created_at,
                        earlier_root.id < candidate_root.id,
                    ),
                ),
                earlier_tree_run.status.in_(("queued", "running")),
            )
        )
        result = await session.execute(
            select(AgentRunOutbox)
            .join(candidate_run, candidate_run.id == AgentRunOutbox.run_id)
            .join(
                candidate_root,
                candidate_root.id
                == func.coalesce(candidate_run.root_run_id, candidate_run.id),
            )
            .where(AgentRunOutbox.status == "pending")
            .where(AgentRunOutbox.scheduled_at <= datetime.utcnow())
            .where(AgentRunOutbox.retry_count < max_retries)
            .where(candidate_run.status.in_(("queued", "running")))
            .where(~earlier_active_tree)
            .order_by(AgentRunOutbox.scheduled_at, AgentRunOutbox.id)
            .limit(limit)
        )
        return result.scalars().all()

    async def claim(
        self,
        session: AsyncSession,
        outbox_id: int,
        worker_id: str,
    ) -> bool:
        """
        尝试认领一个outbox任务

        使用原子更新防止多Worker竞争
        """
        result = await session.execute(
            update(AgentRunOutbox)
            .where(AgentRunOutbox.id == outbox_id)
            .where(AgentRunOutbox.status == "pending")
            .values(
                status="processing",
                worker_id=worker_id,
            )
        )
        return result.rowcount > 0

    async def complete(
        self,
        session: AsyncSession,
        outbox_id: int,
    ) -> None:
        """标记outbox任务完成"""
        await session.execute(
            update(AgentRunOutbox)
            .where(AgentRunOutbox.id == outbox_id)
            .values(
                status="completed",
                processed_at=datetime.utcnow(),
            )
        )

    async def fail(
        self,
        session: AsyncSession,
        outbox_id: int,
        retry_delay_seconds: int = 30,
    ) -> None:
        """标记outbox任务失败（增加重试计数，稍后重试）"""
        await session.execute(
            update(AgentRunOutbox)
            .where(AgentRunOutbox.id == outbox_id)
            .values(
                status="pending",
                retry_count=AgentRunOutbox.retry_count + 1,
                scheduled_at=datetime.utcnow() + timedelta(seconds=retry_delay_seconds),
            )
        )


# 全局实例
outbox_store = OutboxStore()
