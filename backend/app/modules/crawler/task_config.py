"""Crawler task configuration normalization and validation rules."""

from typing import Any, Dict, List, Mapping, Optional, Set

from app.modules.crawler.cleanup_service import CrawlerCleanupService

TASK_TYPES = {"full", "incremental", "targeted", "health_check", "cleanup"}
SPIDER_SOURCES = {
    "github": {"github"},
    "knowledge": {"github", "pdf"},
}
SOURCE_CODE_ALIASES = {
    "wikipedia": "wikipedia_zh",
    "douban": "douban_movie",
    "baike": "baidu_baike",
}


def source_code_candidates(source_code: str) -> List[str]:
    """Return database source code candidates for a Scrapy source key."""
    return [
        code
        for code in {
            source_code,
            SOURCE_CODE_ALIASES.get(source_code),
        }
        if code
    ]


def normalize_source_ids(source_ids: Any) -> List[str]:
    """Normalize source ID input into a list."""
    if isinstance(source_ids, list):
        return [str(source_id) for source_id in source_ids if str(source_id).strip()]
    if isinstance(source_ids, str) and source_ids.strip():
        return [source_ids.strip()]
    return []


def normalize_keywords(keywords: Any) -> List[str]:
    """Normalize keyword input into a list."""
    if isinstance(keywords, list):
        return [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
    if isinstance(keywords, str):
        return [keyword.strip() for keyword in keywords.split(",") if keyword.strip()]
    return []


def validate_crawl_config(
    config: Dict[str, Any],
    *,
    spider_sources: Mapping[str, Set[str]] = SPIDER_SOURCES,
) -> Dict[str, Any]:
    """Validate supported spider inputs before persisting a task."""
    normalized = dict(config)
    spider_type = str(normalized.get("spider_type") or "github").strip()
    if spider_type not in spider_sources:
        supported = ", ".join(sorted(spider_sources))
        raise ValueError(f"不支持的爬虫类型: {spider_type}，当前支持: {supported}")
    normalized["spider_type"] = spider_type

    if spider_type == "github":
        if not normalized.get("repo_url") and not normalized.get("search_query"):
            raise ValueError("GitHub 爬虫必须填写仓库地址或搜索关键词")
    elif spider_type == "knowledge" and not normalized.get("pdf_path"):
        raise ValueError("知识抽取爬虫必须填写 PDF 路径")
    return normalized


def normalize_task_config(
    task_type: str,
    target_config: Optional[Dict[str, Any]],
    *,
    task_types: Set[str] = TASK_TYPES,
    spider_sources: Mapping[str, Set[str]] = SPIDER_SOURCES,
) -> Dict[str, Any]:
    """Normalize configuration shared by manual and scheduled tasks."""
    if task_type not in task_types:
        raise ValueError(f"不支持的任务类型: {task_type}")

    config = dict(target_config or {})
    if task_type in {"full", "incremental", "targeted"}:
        return validate_crawl_config(
            config,
            spider_sources=spider_sources,
        )
    if task_type == "cleanup":
        cleanup_types, retention_days = CrawlerCleanupService.validate_options(
            config.get("cleanup_types"),
            config.get("retention_days", 90),
        )
        config["cleanup_types"] = cleanup_types
        config["retention_days"] = retention_days
    return config


def is_supported_source(
    spider_type: str,
    source_code: str,
    *,
    spider_sources: Mapping[str, Set[str]] = SPIDER_SOURCES,
) -> bool:
    """Check whether a Scrapy spider supports the selected source."""
    return source_code in spider_sources.get(spider_type, set())


__all__ = [
    "SOURCE_CODE_ALIASES",
    "SPIDER_SOURCES",
    "TASK_TYPES",
    "is_supported_source",
    "normalize_keywords",
    "normalize_source_ids",
    "normalize_task_config",
    "source_code_candidates",
    "validate_crawl_config",
]
