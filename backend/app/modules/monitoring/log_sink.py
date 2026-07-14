"""服务日志数据库 Sink。

把 structlog 输出异步批量写入 service_logs 表，供前端查询。

设计要点：
- 日志写库走独立的内存队列 + 后台 worker，不阻塞调用方
- worker 批量提交（默认 5 秒一批，500 条上限），降低 IO 压力
- 写库失败仅 stderr 提示，绝不再 logger.error 形成递归
- structlog processor 形态：调用 logger.info(...) 时把 event_dict 拷贝入队
"""

import asyncio
import json
import sys
import time
import traceback as tb_module
from datetime import datetime
from queue import Queue, Empty, Full
from typing import Any, Dict, List, Optional

# 队列大小：超过则丢弃最旧的（生产环境可调）
DEFAULT_QUEUE_SIZE = 5000
DEFAULT_BATCH_SIZE = 500
DEFAULT_FLUSH_INTERVAL = 5.0  # 秒
TRACEBACK_MAX_LEN = 8000
MESSAGE_MAX_LEN = 4000

_log_queue: Queue = Queue(maxsize=DEFAULT_QUEUE_SIZE)
_dropped_count = 0
_worker_task: Optional[asyncio.Task] = None
_worker_running = False


def queue_log(event_dict: Dict[str, Any]) -> None:
    """structlog processor 调用入口，必须不抛异常。"""
    global _dropped_count
    try:
        _log_queue.put_nowait(event_dict)
    except Full:
        _dropped_count += 1


def db_log_processor(
    _logger: Any,
    _method: str,
    event_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """
    structlog processor。把日志事件入队，但不修改原 event_dict（继续走后续 processors 输出到 stdout）。

    用法：在 configure_logging() 的 shared_processors 末尾追加。
    """
    try:
        snapshot = dict(event_dict)
        snapshot["_logger_name"] = (
            _logger.name if hasattr(_logger, "name") else str(_logger)
        )
        snapshot["_method"] = _method
        queue_log(snapshot)
    except Exception:
        # 任何异常都吞掉，不影响日志主链路
        pass
    return event_dict


def _serialize_context(event_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 event_dict 抽出非内置字段作为 context。"""
    ctx = {}
    skip_keys = {
        "event",
        "level",
        "timestamp",
        "logger",
        "_record",
        "_logger_name",
        "_method",
        "exc_info",
        "stack_info",
        "request_id",
    }
    for key, value in event_dict.items():
        if key in skip_keys:
            continue
        try:
            json.dumps(value, ensure_ascii=False)
            ctx[key] = value
        except (TypeError, ValueError):
            ctx[key] = repr(value)[:500]
    return ctx or None


def _extract_traceback(event_dict: Dict[str, Any]) -> Optional[str]:
    exc_info = event_dict.get("exc_info") or event_dict.get("exception")
    if not exc_info:
        return None
    if isinstance(exc_info, str):
        return exc_info[:TRACEBACK_MAX_LEN]
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        try:
            return "".join(tb_module.format_exception(*exc_info))[:TRACEBACK_MAX_LEN]
        except Exception:
            return None
    return None


def _drain_queue(max_items: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    while len(items) < max_items:
        try:
            items.append(_log_queue.get_nowait())
        except Empty:
            break
    return items


async def _flush_batch(items: List[Dict[str, Any]]) -> None:
    if not items:
        return

    # 延迟导入，避免循环依赖（service_logs 模型在 mysql_models 中）
    from app.db.mysql import mysql_client
    from app.models.mysql_models import ServiceLog

    rows = []
    for ev in items:
        level = str(ev.get("level") or "INFO").upper()
        # 兼容 logging 模块和 structlog
        event_name = ev.get("event") or ""
        message = str(event_name)[:MESSAGE_MAX_LEN]
        logger_name = (ev.get("_logger_name") or ev.get("logger") or "")[:120]
        request_id = ev.get("request_id")
        request_id = str(request_id)[:64] if request_id else None
        traceback = _extract_traceback(ev)
        context = _serialize_context(ev)
        rows.append(
            ServiceLog(
                level=level[:16],
                logger_name=logger_name or None,
                event=str(event_name)[:255] or None,
                message=message,
                request_id=request_id,
                context=context,
                traceback=traceback,
                created_at=datetime.utcnow(),
            )
        )

    try:
        async with mysql_client.session() as session:
            session.add_all(rows)
            await session.commit()
    except Exception as e:
        # 不能再用 logger，否则递归
        print(f"[db_log_sink] flush failed: {e}", file=sys.stderr)


async def _worker_loop(batch_size: int, flush_interval: float) -> None:
    global _worker_running
    _worker_running = True
    last_flush = time.time()
    try:
        while _worker_running:
            await asyncio.sleep(0.2)
            now = time.time()
            should_flush_full = _log_queue.qsize() >= batch_size
            should_flush_time = (now - last_flush) >= flush_interval
            if should_flush_full or should_flush_time:
                items = _drain_queue(batch_size)
                if items:
                    await _flush_batch(items)
                last_flush = now
        # 收尾
        items = _drain_queue(batch_size * 4)
        if items:
            await _flush_batch(items)
    except asyncio.CancelledError:
        items = _drain_queue(batch_size * 4)
        if items:
            await _flush_batch(items)
        raise


async def start_db_log_sink(
    batch_size: int = DEFAULT_BATCH_SIZE,
    flush_interval: float = DEFAULT_FLUSH_INTERVAL,
) -> None:
    """启动后台 worker（在 lifespan startup 调用）"""
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop(batch_size, flush_interval))


async def stop_db_log_sink() -> None:
    """关闭 worker（在 lifespan shutdown 调用）"""
    global _worker_running, _worker_task
    _worker_running = False
    if _worker_task:
        try:
            _worker_task.cancel()
            await _worker_task
        except (asyncio.CancelledError, Exception):
            pass
    _worker_task = None


def get_dropped_count() -> int:
    return _dropped_count


def get_queue_size() -> int:
    return _log_queue.qsize()
