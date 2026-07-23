"""
系统监控模块

提供 API 性能监控和数据库状态监控功能。
"""

import time
from typing import Dict, Any, Optional
from datetime import datetime

from app.core.logging import get_logger
from app.db.redis import redis_client
from app.db.mysql import mysql_client

logger = get_logger(__name__)

# API 请求统计
_request_stats = {
    "total_requests": 0,
    "total_response_time": 0,
    "error_count": 0,
    "start_time": time.time(),
}


def record_request(response_time: float, is_error: bool = False) -> None:
    """
    记录 API 请求统计
    
    Args:
        response_time: 响应时间（毫秒）
        is_error: 是否错误
    """
    _request_stats["total_requests"] += 1
    _request_stats["total_response_time"] += response_time
    if is_error:
        _request_stats["error_count"] += 1


async def get_api_metrics() -> Dict[str, Any]:
    """
    获取 API 性能指标
    
    Returns:
        API 性能数据
    """
    total_requests = _request_stats["total_requests"]
    total_response_time = _request_stats["total_response_time"]
    error_count = _request_stats["error_count"]
    elapsed = time.time() - _request_stats["start_time"]
    
    avg_response_time = total_response_time / total_requests if total_requests > 0 else 0
    error_rate = error_count / total_requests if total_requests > 0 else 0
    qps = total_requests / elapsed if elapsed > 0 else 0
    
    return {
        "total_requests": total_requests,
        "avg_response_time": round(avg_response_time, 2),
        "error_rate": round(error_rate, 4),
        "qps": round(qps, 2),
        "uptime_seconds": int(elapsed),
    }


async def get_database_status() -> Dict[str, Any]:
    """
    获取数据库状态
    
    Returns:
        各数据库连接状态
    """
    status = {
        "status": "connected",
        "redis": {"status": "unknown"},
        "mysql": {"status": "unknown"},
    }

    # Redis 状态
    try:
        from app.db.redis import redis_client
        info = await redis_client.info()
        memory = info.get("used_memory_human", "unknown")
        status["redis"] = {
            "status": "up",
            "memory": memory,
        }
    except Exception as e:
        status["redis"] = {
            "status": "down",
            "error": str(e),
        }
        status["status"] = "degraded"
    
    # MySQL 状态
    try:
        from app.db.mysql import mysql_client
        healthy = await mysql_client.health_check()
        status["mysql"] = {
            "status": "up" if healthy else "down",
        }
    except Exception as e:
        status["mysql"] = {
            "status": "down",
            "error": str(e),
        }
        status["status"] = "degraded"
    
    return status
