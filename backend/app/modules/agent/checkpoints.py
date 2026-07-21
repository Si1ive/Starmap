"""
断点读写（context -> JSON）
+
用于崩溃恢复：将Run的当前上下文持久化到checkpoints表。
"""

from typing import Optional, Dict, Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .models import AgentCheckpoint

logger = get_logger(__name__)


class CheckpointStore:
    """断点存储"""

    async def save(
        self,
        session: AsyncSession,
        run_id: str,
        context: Dict[str, Any],
        checkpoint_id: str,
    ) -> AgentCheckpoint:
        """保存断点"""
        checkpoint = AgentCheckpoint(
            id=checkpoint_id,
            run_id=run_id,
            context_json=context,
        )
        session.add(checkpoint)
        await session.flush()
        await session.refresh(checkpoint)
        
        logger.debug("断点保存", run_id=run_id, checkpoint_id=checkpoint_id)
        return checkpoint

    async def load_latest(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> Optional[Dict[str, Any]]:
        """加载最新断点"""
        result = await session.execute(
            select(AgentCheckpoint)
            .where(AgentCheckpoint.run_id == run_id)
            .order_by(AgentCheckpoint.created_at.desc())
            .limit(1)
        )
        checkpoint = result.scalar_one_or_none()
        if checkpoint:
            return checkpoint.context_json
        return None

    async def delete_by_run(self, session: AsyncSession, run_id: str) -> None:
        """删除指定run的所有断点"""
        await session.execute(
            delete(AgentCheckpoint).where(AgentCheckpoint.run_id == run_id)
        )


# 全局实例
checkpoint_store = CheckpointStore()
