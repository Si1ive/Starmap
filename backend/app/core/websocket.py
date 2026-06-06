"""
WebSocket 日志管理器

提供实时日志推送功能，支持：
- 多客户端连接管理
- 按任务/源过滤推送
- 连接心跳检测
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional, Callable
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class LogWebSocketManager:
    """
    日志 WebSocket 连接管理器

    管理所有 WebSocket 连接，支持按任务ID和源ID过滤推送日志。
    单例模式，全局共享。
    """

    def __init__(self):
        # 所有活跃连接: {websocket: {"task_ids": set(), "source_ids": set(), "levels": set()}}
        self._connections: Dict[WebSocket, Dict[str, Set[str]]] = {}
        # 消息队列，用于广播
        self._message_queue: asyncio.Queue = asyncio.Queue()
        # 广播任务
        self._broadcast_task: Optional[asyncio.Task] = None

    async def connect(
        self,
        websocket: WebSocket,
        task_ids: Optional[Set[str]] = None,
        source_ids: Optional[Set[str]] = None,
        levels: Optional[Set[str]] = None,
    ):
        """
        接受新的 WebSocket 连接

        Args:
            websocket: FastAPI WebSocket 对象
            task_ids: 只接收这些任务的日志，None 表示接收所有
            source_ids: 只接收这些源的日志，None 表示接收所有
            levels: 只接收这些级别的日志，None 表示接收所有
        """
        await websocket.accept()
        self._connections[websocket] = {
            "task_ids": task_ids or set(),
            "source_ids": source_ids or set(),
            "levels": levels or set(),
        }
        logger.info(
            f"WebSocket connected: {len(self._connections)} clients. "
            f"Filters: task_ids={task_ids}, source_ids={source_ids}, levels={levels}"
        )

        # 启动广播任务（如果还没启动）
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())

    async def disconnect(self, websocket: WebSocket):
        """断开 WebSocket 连接"""
        if websocket in self._connections:
            del self._connections[websocket]
            logger.info(f"WebSocket disconnected: {len(self._connections)} clients remaining")

    async def broadcast(self, log_data: Dict):
        """
        广播日志消息到所有符合条件的客户端

        Args:
            log_data: 日志数据字典，必须包含 task_id, source_id, level 等字段
        """
        await self._message_queue.put(log_data)

    async def _broadcast_loop(self):
        """后台广播循环，从队列取出消息并推送给客户端"""
        while True:
            try:
                log_data = await self._message_queue.get()
                await self._send_to_matching_clients(log_data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Broadcast error: {e}")

    async def _send_to_matching_clients(self, log_data: Dict):
        """将日志发送给所有匹配的客户端"""
        task_id = log_data.get("task_id")
        source_id = log_data.get("source_id")
        level = log_data.get("level")

        # 序列化消息
        message = json.dumps({
            "type": "log",
            "data": log_data,
            "timestamp": datetime.utcnow().isoformat(),
        }, ensure_ascii=False, default=str)

        disconnected = []
        for websocket, filters in self._connections.items():
            # 检查过滤条件
            if filters["task_ids"] and task_id not in filters["task_ids"]:
                continue
            if filters["source_ids"] and source_id not in filters["source_ids"]:
                continue
            if filters["levels"] and level not in filters["levels"]:
                continue

            try:
                await websocket.send_text(message)
            except Exception:
                disconnected.append(websocket)

        # 清理断开的连接
        for websocket in disconnected:
            await self.disconnect(websocket)

    async def send_heartbeat(self, websocket: WebSocket):
        """发送心跳消息"""
        try:
            await websocket.send_text(json.dumps({
                "type": "heartbeat",
                "timestamp": datetime.utcnow().isoformat(),
            }))
        except Exception:
            await self.disconnect(websocket)

    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return len(self._connections)

    async def disconnect_all(self):
        """断开所有 WebSocket 连接并停止广播任务"""
        for websocket in list(self._connections.keys()):
            await self.disconnect(websocket)

        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        self._broadcast_task = None


# 全局单例
log_websocket_manager = LogWebSocketManager()
