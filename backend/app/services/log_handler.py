"""
统一日志处理服务

整合数据库写入和 WebSocket 广播，为爬虫提供统一的日志处理入口。
解决 BaseCrawler（同步）与异步服务（数据库、WebSocket）之间的调用问题。
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.logging import get_logger
from app.core.websocket import LogWebSocketManager
from app.db.mysql import mysql_client
from app.services.log_service import CrawlerLogService

logger = get_logger(__name__)

# 全局 WebSocket 管理器实例
_log_websocket_manager: Optional[LogWebSocketManager] = None


def get_log_websocket_manager() -> LogWebSocketManager:
    """获取全局 WebSocket 管理器实例（单例）"""
    global _log_websocket_manager
    if _log_websocket_manager is None:
        _log_websocket_manager = LogWebSocketManager()
    return _log_websocket_manager


class UnifiedLogHandler:
    """
    统一日志处理器
    
    将爬虫日志同时写入数据库和广播到 WebSocket。
    由于 BaseCrawler 是同步类，使用 asyncio.run_coroutine_threadsafe 处理异步操作。
    """

    def __init__(self):
        self.ws_manager = get_log_websocket_manager()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """设置事件循环（用于同步代码调用异步操作）"""
        self._loop = loop

    def handle_log(self, log_data: Dict[str, Any]) -> None:
        """
        处理日志（同步入口）
        
        此方法设计为同步调用，可被 BaseCrawler 的 log_callback 使用。
        内部通过事件循环执行异步操作。
        
        Args:
            log_data: 日志数据字典
        """
        # 添加时间戳
        if "created_at" not in log_data:
            log_data["created_at"] = datetime.utcnow().isoformat()
        
        # 获取当前事件循环
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop or asyncio.new_event_loop()
        
        # 在事件循环中执行异步操作
        if loop.is_running():
            # 如果循环正在运行，使用 run_coroutine_threadsafe
            asyncio.run_coroutine_threadsafe(
                self._async_handle_log(log_data),
                loop
            )
        else:
            # 如果循环未运行，直接运行
            loop.run_until_complete(self._async_handle_log(log_data))

    async def _async_handle_log(self, log_data: Dict[str, Any]) -> None:
        """
        异步处理日志
        
        同时执行：
        1. 写入数据库
        2. 广播到 WebSocket
        
        Args:
            log_data: 日志数据字典
        """
        # 1. 写入数据库
        try:
            async with mysql_client.session() as session:
                log_service = CrawlerLogService(session)
                await log_service.create_log(log_data)
        except Exception as e:
            logger.error(f"Failed to write log to database: {e}")
        
        # 2. 广播到 WebSocket
        try:
            await self.ws_manager.broadcast(log_data)
        except Exception as e:
            logger.error(f"Failed to broadcast log via WebSocket: {e}")

    async def handle_log_async(self, log_data: Dict[str, Any]) -> None:
        """
        异步处理日志（直接调用）
        
        适用于已经在异步上下文中的代码。
        
        Args:
            log_data: 日志数据字典
        """
        # 添加时间戳
        if "created_at" not in log_data:
            log_data["created_at"] = datetime.utcnow().isoformat()
        
        # 1. 写入数据库
        try:
            async with mysql_client.session() as session:
                log_service = CrawlerLogService(session)
                await log_service.create_log(log_data)
        except Exception as e:
            logger.error(f"Failed to write log to database: {e}")
        
        # 2. 广播到 WebSocket
        try:
            await self.ws_manager.broadcast(log_data)
        except Exception as e:
            logger.error(f"Failed to broadcast log via WebSocket: {e}")


# 全局处理器实例
_unified_log_handler: Optional[UnifiedLogHandler] = None


def get_unified_log_handler() -> UnifiedLogHandler:
    """获取全局统一日志处理器实例（单例）"""
    global _unified_log_handler
    if _unified_log_handler is None:
        _unified_log_handler = UnifiedLogHandler()
    return _unified_log_handler


def create_log_callback() -> callable:
    """
    创建适用于 BaseCrawler 的日志回调函数
    
    Returns:
        同步回调函数，可直接赋值给 BaseCrawler.log_callback
    """
    handler = get_unified_log_handler()
    
    def callback(log_data: Dict[str, Any]) -> None:
        handler.handle_log(log_data)
    
    return callback


async def init_log_handler() -> None:
    """
    初始化日志处理器
    
    在应用启动时调用，设置事件循环。
    """
    handler = get_unified_log_handler()
    handler.set_event_loop(asyncio.get_event_loop())
    logger.info("Unified log handler initialized")


async def shutdown_log_handler() -> None:
    """
    关闭日志处理器
    
    在应用关闭时调用，清理资源。
    """
    global _unified_log_handler, _log_websocket_manager
    
    # 关闭 WebSocket 管理器
    if _log_websocket_manager:
        await _log_websocket_manager.disconnect_all()
        _log_websocket_manager = None
    
    _unified_log_handler = None
    logger.info("Unified log handler shut down")
