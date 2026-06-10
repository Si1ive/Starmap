"""
Scrapy Items for 408考研学习平台.

Define the data models for scraped items using Scrapy's standard Item class.
"""

import scrapy
from datetime import datetime


class FileDownloadItem(scrapy.Item):
    """File downloaded from GitHub or other sources."""

    repo_name = scrapy.Field()       # "user/repo"
    repo_url = scrapy.Field()        # "https://github.com/user/repo"
    file_path = scrapy.Field()       # "docs/chapter1/data_structures.pdf"
    file_name = scrapy.Field()       # "data_structures.pdf"
    file_type = scrapy.Field()       # "pdf", "doc", "ppt"
    file_size = scrapy.Field()       # bytes
    download_url = scrapy.Field()    # raw download URL
    local_path = scrapy.Field()      # downloaded local path
    task_id = scrapy.Field()         #关联任务ID
    status = scrapy.Field()          # "downloaded", "skipped", "failed"
    metadata = scrapy.Field()        # extra info

    created_at = scrapy.Field()
    updated_at = scrapy.Field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setdefault("status", "downloaded")
        self.setdefault("metadata", {})
        self.setdefault("created_at", datetime.utcnow().isoformat())
        self.setdefault("updated_at", datetime.utcnow().isoformat())


class CrawlLogItem(scrapy.Item):
    """Log item for crawl operations."""

    task_id = scrapy.Field()
    source_id = scrapy.Field()
    level = scrapy.Field()
    stage = scrapy.Field()

    resource_url = scrapy.Field()
    resource_name = scrapy.Field()
    resource_type = scrapy.Field()

    action = scrapy.Field()
    status = scrapy.Field()
    duration_ms = scrapy.Field()
    message = scrapy.Field()

    error_type = scrapy.Field()
    error_detail = scrapy.Field()
    retry_count = scrapy.Field()
    details = scrapy.Field()

    created_at = scrapy.Field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setdefault("level", "INFO")
        self.setdefault("status", "pending")
        self.setdefault("retry_count", 0)
        self.setdefault("created_at", datetime.utcnow().isoformat())


class KnowledgePointItem(scrapy.Item):
    """Knowledge point item parsed from PDF or web sources."""

    id = scrapy.Field()
    chapter_id = scrapy.Field()
    subject_id = scrapy.Field()
    title = scrapy.Field()
    content = scrapy.Field()
    difficulty = scrapy.Field()
    exam_frequency = scrapy.Field()
    tags = scrapy.Field()
    key_points = scrapy.Field()
    related_point_ids = scrapy.Field()
    source = scrapy.Field()
    source_page = scrapy.Field()
    crawl_task_id = scrapy.Field()

    status = scrapy.Field()

    created_at = scrapy.Field()
    updated_at = scrapy.Field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setdefault("id", None)
        self.setdefault("status", "pending")
        self.setdefault("difficulty", "medium")
        self.setdefault("exam_frequency", "medium")
        self.setdefault("tags", [])
        self.setdefault("key_points", [])
        self.setdefault("related_point_ids", [])
        self.setdefault("created_at", datetime.utcnow().isoformat())
        self.setdefault("updated_at", datetime.utcnow().isoformat())


class QuestionItem(scrapy.Item):
    """Question item parsed from exam papers or exercise sources."""

    id = scrapy.Field()
    subject_id = scrapy.Field()
    chapter_id = scrapy.Field()
    type = scrapy.Field()
    content = scrapy.Field()
    options = scrapy.Field()
    answer = scrapy.Field()
    explanation = scrapy.Field()
    difficulty = scrapy.Field()
    source = scrapy.Field()
    exam_year = scrapy.Field()
    knowledge_point_ids = scrapy.Field()
    tags = scrapy.Field()

    status = scrapy.Field()

    created_at = scrapy.Field()
    updated_at = scrapy.Field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setdefault("id", None)
        self.setdefault("status", "pending")
        self.setdefault("difficulty", "medium")
        self.setdefault("exam_year", 0)
        self.setdefault("options", [])
        self.setdefault("knowledge_point_ids", [])
        self.setdefault("tags", [])
        self.setdefault("created_at", datetime.utcnow().isoformat())
        self.setdefault("updated_at", datetime.utcnow().isoformat())
