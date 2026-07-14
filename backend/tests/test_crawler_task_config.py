import pytest

from app.modules.crawler.task_config import (
    is_supported_source,
    normalize_keywords,
    normalize_source_ids,
    normalize_task_config,
    source_code_candidates,
    validate_crawl_config,
)
from app.modules.crawler.task_service import CrawlerTaskService


def test_crawler_task_config_normalizes_source_ids_and_keywords():
    assert normalize_source_ids(["source-1", "", 2]) == [
        "source-1",
        "2",
    ]
    assert normalize_source_ids(" source-1 ") == ["source-1"]
    assert normalize_source_ids(None) == []
    assert normalize_keywords([" 操作系统 ", "", 408]) == [
        "操作系统",
        "408",
    ]
    assert normalize_keywords("操作系统, 数据结构,") == [
        "操作系统",
        "数据结构",
    ]


def test_crawler_task_config_resolves_source_aliases():
    assert set(source_code_candidates("wikipedia")) == {
        "wikipedia",
        "wikipedia_zh",
    }
    assert source_code_candidates("github") == ["github"]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"spider_type": "person"}, "不支持的爬虫类型"),
        ({"spider_type": "github"}, "仓库地址或搜索关键词"),
        ({"spider_type": "knowledge"}, "PDF 路径"),
    ],
)
def test_crawler_task_config_rejects_unsupported_or_incomplete_spiders(
    config,
    message,
):
    with pytest.raises(ValueError, match=message):
        validate_crawl_config(config)


def test_crawler_task_config_normalizes_manual_and_cleanup_tasks():
    crawl_config = normalize_task_config(
        "targeted",
        {"search_query": "fastapi"},
    )
    cleanup_config = normalize_task_config(
        "cleanup",
        {
            "cleanup_types": ["duplicates", "orphan"],
            "retention_days": "120",
        },
    )

    assert crawl_config == {
        "search_query": "fastapi",
        "spider_type": "github",
    }
    assert cleanup_config == {
        "cleanup_types": ["duplicate", "orphan"],
        "retention_days": 120,
    }
    assert is_supported_source("knowledge", "pdf")
    assert not is_supported_source("github", "pdf")


def test_crawler_task_service_keeps_task_config_compatibility_methods():
    config = {"repo_url": "https://github.com/example/repo"}

    assert CrawlerTaskService._validate_crawl_config(config) == (
        validate_crawl_config(config)
    )
    assert CrawlerTaskService._normalize_keywords("a,b") == ["a", "b"]
    assert CrawlerTaskService._normalize_source_ids("source-1") == ["source-1"]
    assert CrawlerTaskService._is_supported_source("github", "github")


def test_crawler_task_service_does_not_expose_legacy_local_crawl_path():
    assert not hasattr(CrawlerTaskService, "_crawl_source")
