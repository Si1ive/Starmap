"""
API 调用统计中间件

把每次 HTTP 请求的（endpoint, method, latency, status）按小时桶聚合到 api_call_stats。

写入策略：
- 内存累加（hour_bucket -> {count, errors, total, max, histogram}）
- 每 30 秒由后台 flush task 把累计写到库（UPSERT）
- 固定桶直方图可跨刷新合并，用于真实计算 P50/P95/P99
"""

import asyncio
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, Optional, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.modules.monitoring.latency_histogram import (
    histogram_percentile,
    merge_histograms,
    record_latency,
)

DEFAULT_FLUSH_INTERVAL = 30.0

# 内存累计桶；key = (endpoint, method, hour_bucket)
_buckets: Dict[Tuple[str, str, datetime], dict] = defaultdict(
    lambda: {
        "count": 0,
        "errors": 0,
        "total_ms": 0,
        "max_ms": 0,
        "latency_histogram": {},
    }
)
_flush_task: Optional[asyncio.Task] = None
_flush_running = False


def _hour_bucket(ts: Optional[datetime] = None) -> datetime:
    ts = ts or datetime.now(timezone.utc).replace(tzinfo=None)
    return ts.replace(minute=0, second=0, microsecond=0)


def _normalize_endpoint(request: Request) -> str:
    """优先用路由模板（/users/{id}），fallback 到原 path。"""
    route = request.scope.get("route") if request.scope else None
    path = getattr(route, "path", None)
    if path:
        return path[:255]
    return str(request.url.path)[:255]


class APIStatsMiddleware(BaseHTTPMiddleware):
    """收集每个请求的 endpoint/latency/status，写入内存桶。"""

    SKIP_PATHS = ("/admin/monitor/", "/health", "/docs", "/openapi.json", "/redoc")

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = str(request.url.path)
        # 跳过监控自身和静态端点，避免污染
        if any(path.startswith(prefix) for prefix in self.SKIP_PATHS):
            return await call_next(request)

        start = time.perf_counter()
        is_error = False
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                is_error = True
            return response
        except Exception:
            is_error = True
            raise
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            try:
                endpoint = _normalize_endpoint(request)
                method = request.method
                bucket_key = (endpoint, method, _hour_bucket())
                bucket = _buckets[bucket_key]
                bucket["count"] += 1
                if is_error:
                    bucket["errors"] += 1
                bucket["total_ms"] += latency_ms
                if latency_ms > bucket["max_ms"]:
                    bucket["max_ms"] = latency_ms
                record_latency(bucket["latency_histogram"], latency_ms)
            except Exception:
                # 统计失败不能影响业务
                pass


async def _flush_to_db() -> None:
    """把内存桶写到库；UPSERT 累加而非覆盖。"""
    if not _buckets:
        return

    snapshot = list(_buckets.items())
    _buckets.clear()

    try:
        from app.db.mysql import mysql_client
        from app.models.mysql_models import ApiCallStat
        from sqlalchemy import select

        async with mysql_client.session() as session:
            for (endpoint, method, hour_bucket), data in snapshot:
                if data["count"] == 0:
                    continue
                # UPSERT：先 select，再 insert/update
                existing = await session.execute(
                    select(ApiCallStat).where(
                        ApiCallStat.endpoint == endpoint,
                        ApiCallStat.method == method,
                        ApiCallStat.hour_bucket == hour_bucket,
                    )
                )
                row = existing.scalar_one_or_none()
                if row:
                    merged_histogram = merge_histograms(
                        row.latency_histogram,
                        data["latency_histogram"],
                    )
                    row.call_count += data["count"]
                    row.error_count += data["errors"]
                    row.total_latency_ms += data["total_ms"]
                    if data["max_ms"] > row.max_latency_ms:
                        row.max_latency_ms = data["max_ms"]
                    row.latency_histogram = merged_histogram
                    row.p95_sample_ms = (
                        histogram_percentile(
                            merged_histogram,
                            0.95,
                            overflow_value=row.max_latency_ms,
                        )
                        or 0
                    )
                else:
                    p95 = (
                        histogram_percentile(
                            data["latency_histogram"],
                            0.95,
                            overflow_value=data["max_ms"],
                        )
                        or 0
                    )
                    session.add(ApiCallStat(
                        endpoint=endpoint,
                        method=method,
                        hour_bucket=hour_bucket,
                        call_count=data["count"],
                        error_count=data["errors"],
                        total_latency_ms=data["total_ms"],
                        max_latency_ms=data["max_ms"],
                        p95_sample_ms=p95,
                        latency_histogram=data["latency_histogram"],
                    ))
            await session.commit()
    except Exception as e:
        # 失败的桶丢弃；下个周期累积新数据
        print(f"[api_stats_middleware] flush failed: {e}", file=sys.stderr)


async def _flush_loop(interval: float) -> None:
    global _flush_running
    _flush_running = True
    try:
        while _flush_running:
            await asyncio.sleep(interval)
            await _flush_to_db()
        # 收尾
        await _flush_to_db()
    except asyncio.CancelledError:
        await _flush_to_db()
        raise


async def start_api_stats_flusher(interval: float = DEFAULT_FLUSH_INTERVAL) -> None:
    global _flush_task
    if _flush_task and not _flush_task.done():
        return
    _flush_task = asyncio.create_task(_flush_loop(interval))


async def stop_api_stats_flusher() -> None:
    global _flush_running, _flush_task
    _flush_running = False
    if _flush_task:
        try:
            _flush_task.cancel()
            await _flush_task
        except (asyncio.CancelledError, Exception):
            pass
    _flush_task = None
