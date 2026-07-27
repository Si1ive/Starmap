"""监控系统自身的丢批保护与进程树采样测试。"""

from contextlib import asynccontextmanager, nullcontext
from queue import Queue
from types import SimpleNamespace

import pytest

from app.modules.monitoring import api_stats, log_sink, system_metrics


def test_log_queue_keeps_newest_events_and_counts_eviction(monkeypatch):
    monkeypatch.setattr(log_sink, "_log_queue", Queue(maxsize=2))
    monkeypatch.setattr(log_sink, "_dropped_count", 0)

    log_sink.queue_log({"event": "oldest"})
    log_sink.queue_log({"event": "middle"})
    log_sink.queue_log({"event": "newest"})

    assert log_sink._drain_queue(10) == [
        {"event": "middle"},
        {"event": "newest"},
    ]
    assert log_sink.get_sink_health()["dropped_count"] == 1


@pytest.mark.asyncio
async def test_api_stats_flush_failure_merges_snapshot_back(monkeypatch):
    api_stats._buckets.clear()
    key = ("/api/test", "GET", api_stats._hour_bucket())
    api_stats._buckets[key]["count"] = 3
    api_stats._buckets[key]["errors"] = 1
    api_stats._buckets[key]["total_ms"] = 90
    api_stats._buckets[key]["max_ms"] = 50
    api_stats._buckets[key]["latency_histogram"] = {"50": 3}

    @asynccontextmanager
    async def failed_session():
        raise RuntimeError("monitor db unavailable")
        yield

    monkeypatch.setattr("app.db.mysql.mysql_client.session", failed_session)
    await api_stats._flush_to_db()

    assert api_stats._buckets[key]["count"] == 3
    assert api_stats._buckets[key]["errors"] == 1
    assert api_stats.get_api_stats_health()["flush_failures"] >= 1
    api_stats._buckets.clear()


def test_system_metrics_sums_current_process_and_children(monkeypatch):
    import psutil

    class Process:
        def __init__(self, rss, cpu, children=()):
            self._rss = rss
            self._cpu = cpu
            self._children = list(children)
        def children(self, recursive=False):
            return self._children
        def oneshot(self):
            return nullcontext()
        def memory_info(self):
            return SimpleNamespace(rss=self._rss)
        def cpu_percent(self, interval=None):
            return self._cpu

    child = Process(20 * 1024 * 1024, 3.5)
    root = Process(30 * 1024 * 1024, 5.5, [child])
    monkeypatch.setattr(psutil, "Process", lambda _pid: root)

    sample = system_metrics._safe_psutil_sample()

    assert sample["process_rss_mb"] == 50.0
    assert sample["process_cpu_percent"] == 9.0
