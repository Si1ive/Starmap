import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.crawler.cleanup_service import CrawlerCleanupService
from app.services.schedule_service import CrawlerScheduleService
from app.services.scrapy_bridge import ScrapyBridgeService
from app.services.task_service import CrawlerTaskService


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
async def test_scrapy_bridge_defaults_missing_spider_type_to_github():
    redis = SimpleNamespace(lpush=AsyncMock())
    db_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    service = ScrapyBridgeService(db)
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

    published = await service.publish_task(task)

    assert published is True
    payload = json.loads(redis.lpush.await_args.args[1])
    assert payload["spider_type"] == "github"
