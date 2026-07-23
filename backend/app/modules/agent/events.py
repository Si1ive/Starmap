"""
事件追加 + SSE 序列化
+
事件是SSE推送的事实源，sequence单调递增，支持断线重放。
"""

import json
from typing import AsyncGenerator, Optional, List
from datetime import datetime

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .models import AgentEvent

logger = get_logger(__name__)


class EventStore:
    """事件存储"""

    async def append(
        self,
        session: AsyncSession,
        run_id: str,
        event_type: str,
        payload: Optional[dict] = None,
    ) -> AgentEvent:
        """
        追加事件到事件表
        
        sequence 通过当前run的最大sequence+1计算
        """
        # 获取当前run的最大sequence
        result = await session.execute(
            select(AgentEvent.sequence)
            .where(AgentEvent.run_id == run_id)
            .order_by(desc(AgentEvent.sequence))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        sequence = (row or 0) + 1

        event = AgentEvent(
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload or {},
        )
        session.add(event)
        await session.flush()
        await session.refresh(event)

        # 同事务生成 thread 级公开投影，供完整对话订阅和断线恢复。
        from .thread_events import thread_event_store

        await thread_event_store.project_run_event(
            session, run_id, event_type, payload or {}
        )
        
        logger.debug(
            "事件追加",
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
        )
        return event

    async def get_events(
        self,
        session: AsyncSession,
        run_id: str,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> List[AgentEvent]:
        """获取指定run的事件（支持断线重放）"""
        result = await session.execute(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id)
            .where(AgentEvent.sequence > after_sequence)
            .order_by(AgentEvent.sequence)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_event_count(self, session: AsyncSession, run_id: str) -> int:
        """获取指定run的事件数量"""
        result = await session.execute(
            select(AgentEvent).where(AgentEvent.run_id == run_id)
        )
        return len(result.scalars().all())


def serialize_sse(event: AgentEvent) -> str:
    """
    将AgentEvent序列化为SSE格式
    
    Format:
        id: <sequence>
        event: <event_type>
        data: <json_payload>
    """
    payload_json = json.dumps(event.payload or {}, ensure_ascii=False)
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload_json}\n\n"


def serialize_sse_from_dict(event_id: int, event_type: str, data: dict) -> str:
    """从字典构造SSE事件"""
    payload_json = json.dumps(data, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload_json}\n\n"


class EventPublisher:
    """事件发布器（内存级别，用于同进程SSE推送）"""

    def __init__(self):
        self._subscribers: dict = {}

    async def publish(self, run_id: str, event: dict):
        """发布事件到所有订阅者"""
        subscribers = self._subscribers.get(run_id, set())
        for queue in subscribers:
            try:
                await queue.put(event)
            except Exception as e:
                logger.warning("事件发布失败", run_id=run_id, error=str(e))

    def subscribe(self, run_id: str, queue):
        """订阅run的事件"""
        if run_id not in self._subscribers:
            self._subscribers[run_id] = set()
        self._subscribers[run_id].add(queue)

    def unsubscribe(self, run_id: str, queue):
        """取消订阅"""
        if run_id in self._subscribers:
            self._subscribers[run_id].discard(queue)


# 全局实例
event_store = EventStore()
event_publisher = EventPublisher()
