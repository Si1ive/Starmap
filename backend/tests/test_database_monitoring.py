from unittest.mock import AsyncMock, patch

import pytest

from app.modules.monitoring.queries import get_database_status_extended


@pytest.mark.asyncio
async def test_database_monitor_reports_redis_info_from_public_client_api():
    redis_info = {
        "redis_version": "7.2.0",
        "uptime_in_seconds": 120,
        "connected_clients": 3,
        "maxclients": 10000,
        "used_memory_human": "1.25M",
        "instantaneous_ops_per_sec": 9,
    }

    with (
        patch(
            "app.db.mysql.mysql_client.health_check",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.db.redis.redis_client.info",
            new=AsyncMock(return_value=redis_info),
        ) as redis_info_mock,
    ):
        result = await get_database_status_extended()

    redis_status = next(
        database for database in result["databases"] if database["name"] == "Redis"
    )
    assert redis_status == {
        "name": "Redis",
        "type": "Cache",
        "status": "connected",
        "version": "7.2.0",
        "uptime": "120s",
        "connections": 3,
        "max_connections": 10000,
        "size": "1.25M",
        "operations_per_sec": 9,
        "cache_hit_rate": 0,
        "last_check": redis_status["last_check"],
    }
    redis_info_mock.assert_awaited_once()
    assert result["status"] == "connected"


@pytest.mark.asyncio
async def test_database_monitor_marks_redis_disconnected_when_info_fails():
    with (
        patch(
            "app.db.mysql.mysql_client.health_check",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.db.redis.redis_client.info",
            new=AsyncMock(side_effect=ConnectionError("redis unavailable")),
        ),
    ):
        result = await get_database_status_extended()

    redis_status = next(
        database for database in result["databases"] if database["name"] == "Redis"
    )
    assert redis_status["status"] == "disconnected"
    assert redis_status["last_check"]
    assert result["status"] == "degraded"
