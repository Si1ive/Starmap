"""
系统资源采集器

后台 task 每 N 秒一次用 psutil 采样 CPU / 内存 / 磁盘 / 进程级 RSS，写入 system_metrics。

设计要点：
- 用户的服务跑在单机，psutil 是默认依赖，零增量包
- 采样间隔默认 10s，足够看趋势又不会爆库（一天 8640 条）
- 进程级数据用当前 process 的 children + self（uvicorn 的 worker 模式只看父）
- 写库失败仅 stderr，不再 logger 防递归
"""

import asyncio
import os
import sys
from datetime import datetime
from typing import Optional

DEFAULT_SAMPLE_INTERVAL = 10.0  # 秒
SAMPLE_TIMEOUT = 5.0

_collector_task: Optional[asyncio.Task] = None
_running = False


def _safe_psutil_sample() -> dict:
    """采样一次资源数据；任何异常都返回零值。"""
    try:
        import psutil
    except Exception:
        return {}

    data = {
        "cpu_percent": 0.0,
        "mem_used_mb": 0.0,
        "mem_total_mb": 0.0,
        "mem_percent": 0.0,
        "disk_used_gb": 0.0,
        "disk_total_gb": 0.0,
        "disk_percent": 0.0,
        "process_rss_mb": 0.0,
        "process_cpu_percent": 0.0,
    }

    try:
        cpu = psutil.cpu_percent(interval=None)  # 非阻塞
        data["cpu_percent"] = float(cpu)
    except Exception:
        pass

    try:
        mem = psutil.virtual_memory()
        data["mem_used_mb"] = round(mem.used / (1024 * 1024), 2)
        data["mem_total_mb"] = round(mem.total / (1024 * 1024), 2)
        data["mem_percent"] = float(mem.percent)
    except Exception:
        pass

    try:
        disk = psutil.disk_usage("/")
        data["disk_used_gb"] = round(disk.used / (1024 ** 3), 2)
        data["disk_total_gb"] = round(disk.total / (1024 ** 3), 2)
        data["disk_percent"] = float(disk.percent)
    except Exception:
        pass

    try:
        proc = psutil.Process(os.getpid())
        with proc.oneshot():
            data["process_rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 2)
            data["process_cpu_percent"] = float(proc.cpu_percent(interval=None))
    except Exception:
        pass

    return data


async def _collect_once() -> None:
    sample = _safe_psutil_sample()
    if not sample:
        return

    try:
        from app.db.mysql import mysql_client
        from app.models.mysql_models import SystemMetric

        row = SystemMetric(
            cpu_percent=sample.get("cpu_percent", 0.0),
            mem_used_mb=sample.get("mem_used_mb", 0.0),
            mem_total_mb=sample.get("mem_total_mb", 0.0),
            mem_percent=sample.get("mem_percent", 0.0),
            disk_used_gb=sample.get("disk_used_gb", 0.0),
            disk_total_gb=sample.get("disk_total_gb", 0.0),
            disk_percent=sample.get("disk_percent", 0.0),
            process_rss_mb=sample.get("process_rss_mb", 0.0),
            process_cpu_percent=sample.get("process_cpu_percent", 0.0),
            sampled_at=datetime.utcnow(),
        )
        async with mysql_client.session() as session:
            session.add(row)
            await session.commit()
    except Exception as e:
        print(f"[system_metrics_collector] persist failed: {e}", file=sys.stderr)


async def _loop(interval: float) -> None:
    global _running
    _running = True
    try:
        while _running:
            try:
                await asyncio.wait_for(_collect_once(), timeout=SAMPLE_TIMEOUT)
            except asyncio.TimeoutError:
                print("[system_metrics_collector] sample timeout", file=sys.stderr)
            except Exception as e:
                print(f"[system_metrics_collector] sample error: {e}", file=sys.stderr)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise


async def start_metrics_collector(interval: float = DEFAULT_SAMPLE_INTERVAL) -> None:
    global _collector_task
    if _collector_task and not _collector_task.done():
        return
    _collector_task = asyncio.create_task(_loop(interval))


async def stop_metrics_collector() -> None:
    global _running, _collector_task
    _running = False
    if _collector_task:
        try:
            _collector_task.cancel()
            await _collector_task
        except (asyncio.CancelledError, Exception):
            pass
    _collector_task = None
