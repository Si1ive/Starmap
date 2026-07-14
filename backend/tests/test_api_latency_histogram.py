from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.monitoring.latency_histogram import (
    histogram_count,
    histogram_percentile,
    merge_histograms,
    record_latency,
)
from app.services.monitor_service import get_api_stats_overview


def test_latency_histogram_merges_and_calculates_real_percentiles():
    first = {}
    for latency_ms in (10, 20, 30):
        record_latency(first, latency_ms)

    second = {}
    for latency_ms in (40, 1000):
        record_latency(second, latency_ms)

    merged = merge_histograms(first, second)

    assert histogram_count(merged) == 5
    assert histogram_percentile(merged, 0.50, overflow_value=1000) == 50
    assert histogram_percentile(merged, 0.95, overflow_value=1000) == 1000
    assert histogram_percentile(merged, 0.99, overflow_value=1000) == 1000


@pytest.mark.asyncio
async def test_api_stats_overview_uses_histogram_instead_of_estimated_percentiles():
    histogram = {}
    for latency_ms in (10, 20, 30, 40, 1000):
        record_latency(histogram, latency_ms)

    row = SimpleNamespace(
        endpoint="/api/items",
        method="GET",
        hour_bucket=SimpleNamespace(isoformat=lambda: "2026-07-14T01:00:00"),
        call_count=5,
        error_count=1,
        total_latency_ms=1100,
        max_latency_ms=1000,
        p95_sample_ms=999,
        latency_histogram=histogram,
    )
    result = Mock()
    result.scalars.return_value.all.return_value = [row]
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    overview = await get_api_stats_overview(session, hours=24)

    assert overview["latency_stats"] == {
        "p50": 50,
        "p95": 1000,
        "p99": 1000,
        "sample_count": 5,
        "coverage_percent": 100.0,
    }
    assert overview["endpoints"][0]["p95"] == 1000


@pytest.mark.asyncio
async def test_api_stats_overview_does_not_fabricate_missing_p50_or_p99():
    legacy_row = SimpleNamespace(
        endpoint="/api/legacy",
        method="GET",
        hour_bucket=SimpleNamespace(isoformat=lambda: "2026-07-14T01:00:00"),
        call_count=10,
        error_count=0,
        total_latency_ms=1000,
        max_latency_ms=300,
        p95_sample_ms=250,
        latency_histogram=None,
    )
    result = Mock()
    result.scalars.return_value.all.return_value = [legacy_row]
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    overview = await get_api_stats_overview(session, hours=24)

    assert overview["latency_stats"] == {
        "p50": None,
        "p95": 250,
        "p99": None,
        "sample_count": 0,
        "coverage_percent": 0.0,
    }
