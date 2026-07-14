"""
监控查询服务

为 /admin/monitor/* 端点提供数据查询能力：
- 服务日志（service_logs）：分页查询、按时间清理、归档到文件
- 系统资源（system_metrics）：最新 + 时序
- API 统计（api_call_stats）：聚合排行、QPS 趋势
"""

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.monitoring.latency_histogram import (
    histogram_count,
    histogram_percentile,
    merge_histograms,
)
from app.models.mysql_models import (
    ServiceLog, SystemMetric, ApiCallStat, LLMCallLog,
)

logger = get_logger(__name__)


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """把 utcnow 写入的 naive datetime 序列化成带 Z 的 ISO 8601，前端按 UTC 解析。"""
    if dt is None:
        return None
    return dt.isoformat() + "Z"


# ===== 服务日志 =====


async def query_service_logs(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    level: Optional[str] = None,
    logger_name: Optional[str] = None,
    keyword: Optional[str] = None,
    request_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    query = select(ServiceLog).order_by(ServiceLog.id.desc())
    count_query = select(func.count(ServiceLog.id))

    if level:
        query = query.where(ServiceLog.level == level.upper())
        count_query = count_query.where(ServiceLog.level == level.upper())
    if logger_name:
        query = query.where(ServiceLog.logger_name == logger_name)
        count_query = count_query.where(ServiceLog.logger_name == logger_name)
    if request_id:
        query = query.where(ServiceLog.request_id == request_id)
        count_query = count_query.where(ServiceLog.request_id == request_id)
    if keyword:
        like = f"%{keyword}%"
        query = query.where(ServiceLog.message.like(like))
        count_query = count_query.where(ServiceLog.message.like(like))
    if start_time:
        query = query.where(ServiceLog.created_at >= start_time)
        count_query = count_query.where(ServiceLog.created_at >= start_time)
    if end_time:
        query = query.where(ServiceLog.created_at <= end_time)
        count_query = count_query.where(ServiceLog.created_at <= end_time)

    total = (await session.execute(count_query)).scalar_one() or 0
    rows = (await session.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return {
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "level": r.level,
                "logger_name": r.logger_name,
                "event": r.event,
                "message": r.message,
                "request_id": r.request_id,
                "context": r.context,
                "traceback": r.traceback,
                "created_at": _iso_utc(r.created_at),
            }
            for r in rows
        ],
    }


async def get_service_log_stats(session: AsyncSession, hours: int = 24) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(hours=hours)

    by_level = (await session.execute(
        select(ServiceLog.level, func.count(ServiceLog.id))
        .where(ServiceLog.created_at >= since)
        .group_by(ServiceLog.level)
    )).all()

    by_logger = (await session.execute(
        select(ServiceLog.logger_name, func.count(ServiceLog.id))
        .where(ServiceLog.created_at >= since)
        .group_by(ServiceLog.logger_name)
        .order_by(func.count(ServiceLog.id).desc())
        .limit(10)
    )).all()

    return {
        "window_hours": hours,
        "by_level": [{"level": lvl, "count": int(c)} for lvl, c in by_level],
        "top_loggers": [{"logger": l or "unknown", "count": int(c)} for l, c in by_logger],
    }


async def delete_service_logs(
    session: AsyncSession,
    older_than_days: Optional[int] = None,
    level: Optional[str] = None,
) -> int:
    if older_than_days is None and not level:
        return 0
    stmt = delete(ServiceLog)
    if older_than_days is not None and older_than_days >= 0:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        stmt = stmt.where(ServiceLog.created_at < cutoff)
    if level:
        stmt = stmt.where(ServiceLog.level == level.upper())
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount or 0)


async def archive_service_logs(
    session: AsyncSession,
    older_than_days: int,
    archive_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """把 N 天前的日志导出到 .ndjson.gz 后清库。"""
    if older_than_days < 0:
        return {"archived": 0, "deleted": 0, "path": None}

    archive_dir = archive_dir or str(Path(settings.UPLOAD_DIR if hasattr(settings, "UPLOAD_DIR") else "uploads") / "log_archives")
    Path(archive_dir).mkdir(parents=True, exist_ok=True)

    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    rows = (await session.execute(
        select(ServiceLog).where(ServiceLog.created_at < cutoff).order_by(ServiceLog.id)
    )).scalars().all()

    if not rows:
        return {"archived": 0, "deleted": 0, "path": None}

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = Path(archive_dir) / f"service_logs_{timestamp}.ndjson.gz"

    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({
                "id": r.id,
                "level": r.level,
                "logger_name": r.logger_name,
                "event": r.event,
                "message": r.message,
                "request_id": r.request_id,
                "context": r.context,
                "traceback": r.traceback,
                "created_at": _iso_utc(r.created_at),
            }, ensure_ascii=False) + "\n")

    # 归档完成才清库（至少导出成功了）
    deleted = (await session.execute(
        delete(ServiceLog).where(ServiceLog.created_at < cutoff)
    )).rowcount
    await session.commit()

    return {
        "archived": len(rows),
        "deleted": int(deleted or 0),
        "path": str(out_path),
    }


# ===== 系统资源 =====


async def get_system_metrics_latest(session: AsyncSession) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(SystemMetric).order_by(SystemMetric.id.desc()).limit(1)
    )).scalar_one_or_none()
    if not row:
        return None
    return _metric_to_dict(row)


async def get_system_metrics_series(
    session: AsyncSession,
    hours: int = 24,
    max_points: int = 200,
) -> List[Dict[str, Any]]:
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = (await session.execute(
        select(SystemMetric).where(SystemMetric.sampled_at >= since).order_by(SystemMetric.id)
    )).scalars().all()
    if not rows:
        return []

    if len(rows) <= max_points:
        return [_metric_to_dict(r) for r in rows]

    # 抽样：等距取点
    step = len(rows) / max_points
    sampled = [rows[int(i * step)] for i in range(max_points)]
    return [_metric_to_dict(r) for r in sampled]


def _metric_to_dict(row: SystemMetric) -> Dict[str, Any]:
    return {
        "cpu_percent": float(row.cpu_percent or 0),
        "mem_used_mb": float(row.mem_used_mb or 0),
        "mem_total_mb": float(row.mem_total_mb or 0),
        "mem_percent": float(row.mem_percent or 0),
        "disk_used_gb": float(row.disk_used_gb or 0),
        "disk_total_gb": float(row.disk_total_gb or 0),
        "disk_percent": float(row.disk_percent or 0),
        "process_rss_mb": float(row.process_rss_mb or 0),
        "process_cpu_percent": float(row.process_cpu_percent or 0),
        "sampled_at": _iso_utc(row.sampled_at),
    }


# ===== API 统计 =====


async def get_api_stats_overview(session: AsyncSession, hours: int = 24) -> Dict[str, Any]:
    since_bucket = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    ).replace(minute=0, second=0, microsecond=0)
    rows = (await session.execute(
        select(ApiCallStat).where(ApiCallStat.hour_bucket >= since_bucket)
    )).scalars().all()

    total_calls = sum(int(r.call_count or 0) for r in rows)
    total_errors = sum(int(r.error_count or 0) for r in rows)
    total_ms = sum(int(r.total_latency_ms or 0) for r in rows)
    avg_latency = int(total_ms / total_calls) if total_calls else 0
    error_rate = round(total_errors / total_calls, 4) if total_calls else 0

    latency_histogram = merge_histograms(
        *(r.latency_histogram for r in rows)
    )
    histogram_samples = histogram_count(latency_histogram)
    legacy_p95 = max((int(r.p95_sample_ms or 0) for r in rows), default=0)
    histogram_p95 = histogram_percentile(
        latency_histogram,
        0.95,
        overflow_value=max((int(r.max_latency_ms or 0) for r in rows), default=0),
    )

    # 每小时桶时序
    qps_by_hour: Dict[str, int] = {}
    for r in rows:
        key = _iso_utc(r.hour_bucket) or "unknown"
        qps_by_hour[key] = qps_by_hour.get(key, 0) + int(r.call_count or 0)
    qps_trend = [{"date": k, "count": v} for k, v in sorted(qps_by_hour.items())]

    # 接口排行
    endpoint_aggregate: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r.method} {r.endpoint}"
        slot = endpoint_aggregate.setdefault(key, {
            "endpoint": r.endpoint, "method": r.method,
            "calls": 0,
            "errors": 0,
            "total_ms": 0,
            "max_ms": 0,
            "legacy_p95": 0,
            "latency_histogram": {},
        })
        slot["calls"] += int(r.call_count or 0)
        slot["errors"] += int(r.error_count or 0)
        slot["total_ms"] += int(r.total_latency_ms or 0)
        slot["max_ms"] = max(slot["max_ms"], int(r.max_latency_ms or 0))
        slot["legacy_p95"] = max(
            slot["legacy_p95"],
            int(r.p95_sample_ms or 0),
        )
        slot["latency_histogram"] = merge_histograms(
            slot["latency_histogram"],
            r.latency_histogram,
        )

    endpoints = []
    for slot in endpoint_aggregate.values():
        calls = slot["calls"] or 1
        endpoint_p95 = histogram_percentile(
            slot["latency_histogram"],
            0.95,
            overflow_value=slot["max_ms"],
        )
        endpoints.append({
            "endpoint": slot["endpoint"],
            "method": slot["method"],
            "calls": slot["calls"],
            "avg_latency": int(slot["total_ms"] / calls),
            "max_latency": slot["max_ms"],
            "p95": max(endpoint_p95 or 0, slot["legacy_p95"]),
            "error_rate": round(slot["errors"] / calls * 100, 2),
        })
    endpoints.sort(key=lambda x: x["calls"], reverse=True)

    return {
        "window_hours": hours,
        "total_requests": total_calls,
        "avg_latency": avg_latency,
        "error_rate": round(error_rate * 100, 2),
        "qps": round(total_calls / max(1, hours * 3600), 4),
        "latency_stats": {
            "p50": histogram_percentile(
                latency_histogram,
                0.50,
                overflow_value=max(
                    (int(r.max_latency_ms or 0) for r in rows),
                    default=0,
                ),
            ),
            "p95": max(histogram_p95 or 0, legacy_p95),
            "p99": histogram_percentile(
                latency_histogram,
                0.99,
                overflow_value=max(
                    (int(r.max_latency_ms or 0) for r in rows),
                    default=0,
                ),
            ),
            "sample_count": histogram_samples,
            "coverage_percent": min(
                100.0,
                round(histogram_samples / total_calls * 100, 2),
            ) if total_calls else 0.0,
        },
        "endpoints": endpoints[:20],  # 调用 top20
        "slow_queries": sorted(
            [e for e in endpoints if e["max_latency"] >= 1000],
            key=lambda e: e["max_latency"], reverse=True,
        )[:20],
        "qps_trend": qps_trend,
    }


# ===== 数据库状态（用于覆盖原 monitor/database 接口） =====


async def get_database_status_extended() -> Dict[str, Any]:
    """对当前已接入的数据库（MySQL/Redis/Qdrant/Neo4j）做轻量探活。"""
    databases: List[Dict[str, Any]] = []

    # MySQL
    try:
        from app.db.mysql import mysql_client
        ok = await mysql_client.health_check()
        databases.append({
            "name": "MySQL",
            "type": "RDBMS",
            "status": "connected" if ok else "disconnected",
            "version": "-",
            "uptime": "-",
            "connections": 0,
            "max_connections": 0,
            "size": "-",
            "operations_per_sec": 0,
            "cache_hit_rate": 0,
            "last_check": datetime.utcnow().isoformat(),
        })
    except Exception:
        databases.append({"name": "MySQL", "type": "RDBMS", "status": "disconnected"})

    # Redis
    try:
        from app.db.redis import redis_client
        info = await redis_client.client.info()
        databases.append({
            "name": "Redis",
            "type": "Cache",
            "status": "connected",
            "version": info.get("redis_version", "-"),
            "uptime": str(info.get("uptime_in_seconds", "-")) + "s",
            "connections": int(info.get("connected_clients", 0)),
            "max_connections": int(info.get("maxclients", 0) or 10000),
            "size": info.get("used_memory_human", "-"),
            "operations_per_sec": int(info.get("instantaneous_ops_per_sec", 0)),
            "cache_hit_rate": 0,
            "last_check": datetime.utcnow().isoformat(),
        })
    except Exception:
        databases.append({"name": "Redis", "type": "Cache", "status": "disconnected"})

    # Qdrant（项目里 ChromaDB 字段，但实际是 Qdrant）
    try:
        from app.db.qdrant import qdrant_client
        if qdrant_client and qdrant_client.client:
            collections = await qdrant_client.list_collections()
            databases.append({
                "name": "Qdrant",
                "type": "Vector",
                "status": "connected",
                "version": "-",
                "uptime": "-",
                "connections": 0,
                "max_connections": 0,
                "size": f"{len(collections)} collections",
                "operations_per_sec": 0,
                "cache_hit_rate": 0,
                "last_check": datetime.utcnow().isoformat(),
            })
    except Exception:
        pass

    return {
        "status": "connected" if all(d.get("status") == "connected" for d in databases) else "degraded",
        "databases": databases,
    }
