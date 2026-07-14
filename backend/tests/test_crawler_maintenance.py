import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.modules.crawler.cleanup_service import CrawlerCleanupService
from app.modules.crawler import stats_router
from app.modules.crawler.schedule_service import CrawlerScheduleService
from app.modules.crawler.scrapy_task_bridge import ScrapyTaskBridge
from app.modules.crawler.task_service import CrawlerTaskService
from app.modules.operations.settings_service import SystemSettingsService


@pytest.mark.asyncio
async def test_stats_router_closes_scrapy_task_bridge_when_status_query_fails(
    monkeypatch,
):
    bridge = SimpleNamespace(
        get_scrapy_status=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        stats_router,
        "ScrapyTaskBridge",
        lambda _db: bridge,
    )

    with pytest.raises(RuntimeError, match="redis unavailable"):
        await stats_router._get_scrapy_status(SimpleNamespace())

    bridge.close.assert_awaited_once()


def test_cleanup_options_normalize_aliases_and_defaults():
    cleanup_types, retention_days = CrawlerCleanupService.validate_options(
        ["duplicates", "orphan", "orphan"],
        30,
    )

    assert cleanup_types == ["duplicate", "orphan"]
    assert retention_days == 30
    assert CrawlerCleanupService.validate_options(None, None) == (
        ["duplicate", "expired", "orphan"],
        90,
    )


@pytest.mark.parametrize(
    ("cleanup_types", "retention_days", "message"),
    [
        ([], 90, "至少选择"),
        (["content"], 90, "不支持的清理类型"),
        (["expired"], 0, "1-3650"),
        (["expired"], 1.5, "必须是整数"),
    ],
)
def test_cleanup_options_reject_unsafe_configuration(
    cleanup_types,
    retention_days,
    message,
):
    with pytest.raises(ValueError, match=message):
        CrawlerCleanupService.validate_options(
            cleanup_types,
            retention_days,
        )


@pytest.mark.asyncio
async def test_cleanup_run_commits_current_operational_cleanup(monkeypatch):
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service = CrawlerCleanupService(db)
    service._remove_duplicate_download_records = AsyncMock(return_value=2)
    service._remove_expired_records = AsyncMock(
        return_value={
            "expired_logs": 3,
            "expired_failed_downloads": 1,
        }
    )
    service._remove_orphan_references = AsyncMock(
        return_value={
            "orphan_logs": 4,
            "detached_downloads": 2,
        }
    )

    result = await service.run(
        cleanup_types=["duplicate", "expired", "orphan"],
        retention_days=45,
    )

    assert result == {
        "cleanup_types": ["duplicate", "expired", "orphan"],
        "retention_days": 45,
        "total_cleaned": 12,
        "duplicate_downloads": 2,
        "expired_logs": 3,
        "expired_failed_downloads": 1,
        "orphan_logs": 4,
        "detached_downloads": 2,
    }
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_run_rolls_back_on_failure():
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service = CrawlerCleanupService(db)
    service._remove_duplicate_download_records = AsyncMock(
        side_effect=RuntimeError("database unavailable")
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.run(cleanup_types=["duplicate"])

    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"spider_type": "person", "keywords": ["Ada"]}, "不支持的爬虫类型"),
        ({"spider_type": "github"}, "仓库地址或搜索关键词"),
        ({"spider_type": "knowledge"}, "PDF 路径"),
    ],
)
def test_crawl_config_rejects_removed_or_incomplete_spiders(config, message):
    with pytest.raises(ValueError, match=message):
        CrawlerTaskService._validate_crawl_config(config)


def test_crawl_config_normalizes_supported_spider_and_source_contract():
    config = CrawlerTaskService._validate_crawl_config(
        {
            "repo_url": "https://github.com/example/repo",
        }
    )

    assert config["spider_type"] == "github"
    assert CrawlerTaskService._is_supported_source("github", "github")
    assert not CrawlerTaskService._is_supported_source("person", "github")


def test_task_config_normalizes_cleanup_for_manual_and_scheduled_tasks():
    config = CrawlerTaskService.normalize_task_config(
        "cleanup",
        {
            "cleanup_types": ["duplicates", "orphan"],
            "retention_days": "120",
        },
    )

    assert config == {
        "cleanup_types": ["duplicate", "orphan"],
        "retention_days": 120,
    }


@pytest.mark.asyncio
async def test_schedule_rejects_removed_spider_before_database_write():
    db = SimpleNamespace(add=AsyncMock(), commit=AsyncMock())
    service = CrawlerScheduleService(db)

    with pytest.raises(ValueError, match="不支持的爬虫类型"):
        await service.create_schedule(
            {
                "name": "legacy schedule",
                "task_type": "targeted",
                "target_config": {
                    "spider_type": "person",
                    "keywords": ["Ada"],
                },
                "cron_expression": "0 2 * * *",
            }
        )

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_cleanup_records_current_model_statistics(monkeypatch):
    task = SimpleNamespace(
        id="task-cleanup",
        config={
            "cleanup_types": ["duplicate", "expired"],
            "retention_days": 60,
        },
        target_count=0,
        completed_count=0,
    )
    service = CrawlerTaskService(SimpleNamespace())
    service.update_task_progress = AsyncMock()
    service.log_service.create_log = AsyncMock()
    cleanup_result = {
        "cleanup_types": ["duplicate", "expired"],
        "retention_days": 60,
        "total_cleaned": 7,
        "duplicate_downloads": 2,
        "expired_logs": 4,
        "expired_failed_downloads": 1,
        "orphan_logs": 0,
        "detached_downloads": 0,
    }

    async def run_cleanup(_cleanup_service, **kwargs):
        assert kwargs == {
            "cleanup_types": ["duplicate", "expired"],
            "retention_days": 60,
        }
        return cleanup_result

    monkeypatch.setattr(CrawlerCleanupService, "run", run_cleanup)

    await service._execute_cleanup(task)

    assert task.target_count == 7
    assert task.completed_count == 7
    assert service.update_task_progress.await_args_list[0].args == (
        task.id,
        10,
    )
    assert service.update_task_progress.await_args_list[1].args == (
        task.id,
        100,
    )
    assert service.update_task_progress.await_args_list[1].kwargs == {
        "total_requests": 7,
        "success_count": 7,
        "failed_count": 0,
    }
    log_data = service.log_service.create_log.await_args.args[0]
    assert log_data["details"] == cleanup_result


@pytest.mark.asyncio
async def test_scrapy_task_bridge_defaults_missing_spider_type_to_github():
    redis = SimpleNamespace(lpush=AsyncMock())
    db_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    service = ScrapyTaskBridge(db)
    service._redis = redis
    service.log_service.create_log = AsyncMock()
    task = SimpleNamespace(
        id="task-1",
        task_type="targeted",
        config={"repo_url": "https://github.com/example/repo"},
        source_id=None,
        source="github",
        name="GitHub crawl",
    )

    runtime_config = SystemSettingsService.normalize_crawler_settings({})
    with patch.object(
        SystemSettingsService,
        "get_crawler_runtime_config",
        AsyncMock(return_value=runtime_config),
    ):
        published = await service.publish_task(task)

    assert published is True
    payload = json.loads(redis.lpush.await_args.args[1])
    assert payload["spider_type"] == "github"


def test_crawler_runtime_config_normalizes_supported_settings():
    config = SystemSettingsService.normalize_crawler_settings(
        {
            "concurrent_requests": 8,
            "concurrent_requests_per_domain": 4,
            "download_delay_seconds": 0.5,
            "request_timeout_seconds": 90,
            "retry_times": 5,
            "rotate_user_agent": False,
            "user_agent": "StudyCrawler/2.0",
            "obey_robots_txt": True,
            "follow_redirects": False,
            "max_redirect_times": 10,
            "max_depth": 7,
            "proxy_enabled": True,
            "proxy_url": "http://127.0.0.1:7890",
            "log_level": "debug",
        }
    )

    assert config == {
        "concurrent_requests": 8,
        "concurrent_requests_per_domain": 4,
        "download_delay_seconds": 0.5,
        "request_timeout_seconds": 90,
        "retry_times": 5,
        "rotate_user_agent": False,
        "user_agent": "StudyCrawler/2.0",
        "obey_robots_txt": True,
        "follow_redirects": False,
        "max_redirect_times": 10,
        "max_depth": 7,
        "proxy_enabled": True,
        "proxy_url": "http://127.0.0.1:7890",
        "log_level": "DEBUG",
    }


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"concurrent_requests": 0}, "concurrent_requests"),
        ({"concurrent_requests": 1.5}, "必须是整数"),
        ({"download_delay_seconds": float("nan")}, "有限数字"),
        (
            {
                "concurrent_requests": 2,
                "concurrent_requests_per_domain": 3,
            },
            "不能大于",
        ),
        ({"proxy_enabled": True, "proxy_url": ""}, "proxy_url"),
        (
            {"proxy_enabled": True, "proxy_url": "socks5://127.0.0.1:1080"},
            "http 或 https",
        ),
        ({"storage_batch_size": 100}, "不支持的配置项"),
    ],
)
def test_crawler_runtime_config_rejects_invalid_or_fake_settings(config, message):
    with pytest.raises(ValueError, match=message):
        SystemSettingsService.normalize_crawler_settings(config)


@pytest.mark.asyncio
async def test_crawler_runtime_config_update_writes_redacted_audit_log():
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    service = SystemSettingsService(db)
    current = SystemSettingsService._default_settings()
    service.load = AsyncMock(return_value=current)
    service.save = AsyncMock(side_effect=lambda data: data)
    next_config = {
        **current["crawler"],
        "proxy_enabled": True,
        "proxy_url": "http://user:secret@127.0.0.1:7890",
    }

    saved = await service.update_crawler_settings(
        next_config,
        user_id="admin-1",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert saved == next_config
    audit = db.add.call_args.args[0]
    assert audit.action == "crawler_settings_update"
    assert audit.resource_id == "crawler"
    assert audit.new_values["proxy_url"] == "[configured]"
    assert "secret" not in json.dumps(audit.new_values)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_scrapy_task_bridge_publishes_runtime_config_snapshot():
    redis = SimpleNamespace(lpush=AsyncMock())
    db_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    service = ScrapyTaskBridge(db)
    service._redis = redis
    service.log_service.create_log = AsyncMock()
    task = SimpleNamespace(
        id="task-runtime",
        task_type="targeted",
        config={"repo_url": "https://github.com/example/repo"},
        source_id=None,
        source="github",
        name="Runtime config crawl",
    )
    runtime_config = {
        "concurrent_requests": 6,
        "concurrent_requests_per_domain": 3,
        "download_delay_seconds": 0.25,
        "request_timeout_seconds": 45,
        "retry_times": 2,
        "rotate_user_agent": True,
        "user_agent": "StudyCrawler/2.0",
        "obey_robots_txt": False,
        "follow_redirects": True,
        "max_redirect_times": 12,
        "max_depth": 6,
        "proxy_enabled": False,
        "proxy_url": "",
        "log_level": "INFO",
    }

    with patch.object(
        SystemSettingsService,
        "get_crawler_runtime_config",
        AsyncMock(return_value=runtime_config),
    ):
        published = await service.publish_task(task)

    assert published is True
    payload = json.loads(redis.lpush.await_args.args[1])
    assert payload["runtime_config"] == runtime_config
    log_data = service.log_service.create_log.await_args.args[0]
    assert log_data["details"]["runtime_config"] == runtime_config


@pytest.mark.asyncio
async def test_task_execution_closes_scrapy_task_bridge(monkeypatch):
    task = SimpleNamespace(
        id="task-publish",
        name="Publish task",
        task_type="targeted",
        status="pending",
        started_at=None,
        completed_at=None,
        error_message=None,
    )
    db = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    service = CrawlerTaskService(db)
    service.get_task_by_id = AsyncMock(return_value=task)
    bridge = SimpleNamespace(
        publish_task=AsyncMock(return_value=True),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        "app.modules.crawler.task_service.ScrapyTaskBridge",
        lambda _db: bridge,
    )

    result = await service.execute_task(task.id)

    assert result is task
    assert task.status == "running"
    bridge.publish_task.assert_awaited_once_with(task)
    bridge.close.assert_awaited_once()


def test_scrapy_runtime_config_maps_to_real_scrapy_settings():
    module_path = (
        Path(__file__).parents[1]
        / "scrapy_service"
        / "runtime_config.py"
    )
    spec = importlib.util.spec_from_file_location("crawler_runtime_config", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    overrides = module.build_scrapy_setting_overrides(
        {
            "concurrent_requests": 8,
            "concurrent_requests_per_domain": 4,
            "download_delay_seconds": 0.5,
            "request_timeout_seconds": 90,
            "retry_times": 5,
            "rotate_user_agent": False,
            "user_agent": "StudyCrawler/2.0",
            "obey_robots_txt": True,
            "follow_redirects": False,
            "max_redirect_times": 10,
            "max_depth": 7,
            "proxy_enabled": True,
            "proxy_url": "http://127.0.0.1:7890",
            "log_level": "DEBUG",
        }
    )

    assert overrides == {
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "DOWNLOAD_DELAY": 0.5,
        "DOWNLOAD_TIMEOUT": 90,
        "RETRY_TIMES": 5,
        "ROTATE_USER_AGENT_ENABLED": False,
        "USER_AGENT": "StudyCrawler/2.0",
        "ROBOTSTXT_OBEY": True,
        "REDIRECT_ENABLED": False,
        "REDIRECT_MAX_TIMES": 10,
        "DEPTH_LIMIT": 7,
        "HTTPPROXY_ENABLED": True,
        "GLOBAL_PROXY_URL": "http://127.0.0.1:7890",
        "LOG_LEVEL": "DEBUG",
    }
