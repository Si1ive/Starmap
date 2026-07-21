"""
Outbox 投递 + 扫描恢复
+
P0 使用 MySQL outbox + 定时扫描，避免引入 Redis Stream。
"""

from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .models import AgentRunOutbox

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
        
        只返回 status=pending 且 scheduled_at <= now 且 retry_count < max_retries 的任务
        """
        result = await session.execute(
            select(AgentRunOutbox)
            .where(AgentRunOutbox.status == "pending")
            .where(AgentRunOutbox.scheduled_at <= datetime.utcnow())
            .where(AgentRunOutbox.retry_count < max_retries)
            .order_by(AgentRunOutbox.scheduled_at)
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
