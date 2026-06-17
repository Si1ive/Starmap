"""
日志配置

使用 structlog 提供结构化日志输出，支持：
- JSON格式（生产环境）
- 彩色控制台输出（开发环境）
- 请求追踪ID
- 性能计时
"""

import logging
import sys
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Optional

import structlog

from app.core.config import settings

# 请求追踪ID
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    获取结构化日志记录器
    
    Args:
        name: 模块名称（通常使用 __name__）
        
    Returns:
        BoundLogger: 绑定上下文的日志记录器
        
    Usage:
        logger = get_logger(__name__)
        logger.info("事件描述", key="value")
    """
    return structlog.get_logger(name)


def configure_logging() -> None:
    """
    配置全局日志系统
    
    根据环境选择输出格式：
    - 开发环境：彩色控制台输出
    - 生产环境：JSON格式
    """
    # 配置标准库logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    )
    
    # 配置structlog
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
    ]

    # 把日志事件入队到 DB（异步 worker 批量入库；写库失败不影响主链路）
    try:
        from app.services.db_log_sink import db_log_processor
        shared_processors.append(db_log_processor)
    except Exception:
        # 启动早期 db_log_sink 不可用时静默退化
        pass

    if settings.DEBUG:
        # 开发环境：彩色控制台
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]
    else:
        # 生产环境：JSON
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer()
        ]
    
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True
    )
    
    # 抑制第三方库日志
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def set_request_id(request_id: str) -> None:
    """
    设置当前请求的追踪ID
    
    Args:
        request_id: 请求唯一标识（如UUID）
    """
    request_id_var.set(request_id)
    structlog.contextvars.bind_contextvars(request_id=request_id)


def get_request_id() -> str:
    """获取当前请求的追踪ID"""
    return request_id_var.get() or ""


def clear_request_id() -> None:
    """清除当前请求的追踪ID"""
    request_id_var.set(None)
    structlog.contextvars.unbind_contextvars("request_id")


def log_execution_time(
    logger: structlog.stdlib.BoundLogger,
    operation: str
) -> Callable:
    """
    装饰器：记录函数执行时间
    
    Args:
        logger: 日志记录器
        operation: 操作名称
        
    Usage:
        @log_execution_time(logger, "数据库查询")
        async def query_db():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start
                logger.info(
                    f"{operation}完成",
                    duration_ms=round(duration * 1000, 2),
                    status="success"
                )
                return result
            except Exception as e:
                duration = time.time() - start
                logger.error(
                    f"{operation}失败",
                    duration_ms=round(duration * 1000, 2),
                    error=str(e),
                    status="error"
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                logger.info(
                    f"{operation}完成",
                    duration_ms=round(duration * 1000, 2),
                    status="success"
                )
                return result
            except Exception as e:
                duration = time.time() - start
                logger.error(
                    f"{operation}失败",
                    duration_ms=round(duration * 1000, 2),
                    error=str(e),
                    status="error"
                )
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


# 导入asyncio用于检测异步函数
import asyncio
