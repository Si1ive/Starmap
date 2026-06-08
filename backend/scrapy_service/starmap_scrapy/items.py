"""
Scrapy Items for StarMap project.

Define the data models for scraped items using Scrapy's standard Item class.
"""

import scrapy
from datetime import datetime
from typing import Optional, List


class PersonItem(scrapy.Item):
    """Person item scraped from various sources."""
    
    # Identification
    id = scrapy.Field()
    name = scrapy.Field()
    name_en = scrapy.Field()
    
    # Basic info
    avatar = scrapy.Field()
    gender = scrapy.Field()
    birth_date = scrapy.Field()
    birth_place = scrapy.Field()
    nationality = scrapy.Field()
    height = scrapy.Field()
    
    # Content
    summary = scrapy.Field()
    biography = scrapy.Field()
    
    # Classification
    categories = scrapy.Field()
    
    # Metadata
    source = scrapy.Field()
    source_url = scrapy.Field()
    crawl_task_id = scrapy.Field()
    raw_data = scrapy.Field()
    
    # Status
    status = scrapy.Field()
    data_quality_score = scrapy.Field()
    
    # Timestamps
    created_at = scrapy.Field()
    updated_at = scrapy.Field()
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setdefault("id", None)
        self.setdefault("status", "pending")
        self.setdefault("data_quality_score", 0.0)
        self.setdefault("categories", [])
        self.setdefault("created_at", datetime.utcnow().isoformat())
        self.setdefault("updated_at", datetime.utcnow().isoformat())


class WorkItem(scrapy.Item):
    """Work item (movie, TV, music, book) scraped from various sources."""
    
    # Identification
    id = scrapy.Field()
    title = scrapy.Field()
    title_en = scrapy.Field()
    
    # Basic info
    type = scrapy.Field()  # movie, tv, album, single, book
    release_date = scrapy.Field()
    genre = scrapy.Field()
    
    # Ratings
    rating = scrapy.Field()
    rating_count = scrapy.Field()
    
    # Media
    poster = scrapy.Field()
    summary = scrapy.Field()
    
    # Movie/TV specific
    director = scrapy.Field()
    actors = scrapy.Field()
    episodes = scrapy.Field()
    platform = scrapy.Field()
    box_office = scrapy.Field()
    
    # Music specific
    artist = scrapy.Field()
    record_company = scrapy.Field()
    track_list = scrapy.Field()
    
    # Book specific
    author = scrapy.Field()
    publisher = scrapy.Field()
    isbn = scrapy.Field()
    
    # Relations
    related_persons = scrapy.Field()
    
    # Metadata
    source = scrapy.Field()
    source_url = scrapy.Field()
    crawl_task_id = scrapy.Field()
    raw_data = scrapy.Field()
    
    # Status
    status = scrapy.Field()
    
    # Timestamps
    created_at = scrapy.Field()
    updated_at = scrapy.Field()
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setdefault("id", None)
        self.setdefault("status", "pending")
        self.setdefault("director", [])
        self.setdefault("actors", [])
        self.setdefault("artist", [])
        self.setdefault("track_list", [])
        self.setdefault("author", [])
        self.setdefault("related_persons", [])
        self.setdefault("created_at", datetime.utcnow().isoformat())
        self.setdefault("updated_at", datetime.utcnow().isoformat())


class RelationItem(scrapy.Item):
    """Relationship between persons and works."""
    
    id = scrapy.Field()
    source_id = scrapy.Field()  # Person ID
    target_id = scrapy.Field()  # Work ID or Person ID
    relation_type = scrapy.Field()  # acted_in, directed, wrote, etc.
    role = scrapy.Field()  # Specific role (e.g., "主角", "配角")
    
    # Metadata
    source = scrapy.Field()
    crawl_task_id = scrapy.Field()
    
    # Timestamps
    created_at = scrapy.Field()
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setdefault("created_at", datetime.utcnow().isoformat())


class CrawlLogItem(scrapy.Item):
    """Log item for crawl operations."""
    
    task_id = scrapy.Field()
    source_id = scrapy.Field()
    level = scrapy.Field()  # INFO, WARNING, ERROR, DEBUG
    stage = scrapy.Field()  # fetch, parse, validate, store
    
    resource_url = scrapy.Field()
    resource_name = scrapy.Field()
    resource_type = scrapy.Field()
    
    action = scrapy.Field()
    status = scrapy.Field()  # success, failed, retry, pending
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
    difficulty = scrapy.Field()  # easy, medium, hard
    exam_frequency = scrapy.Field()  # high, medium, low, never
    tags = scrapy.Field()
    key_points = scrapy.Field()
    related_point_ids = scrapy.Field()
    source = scrapy.Field()
    source_page = scrapy.Field()
    crawl_task_id = scrapy.Field()

    # Status
    status = scrapy.Field()

    # Timestamps
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
    type = scrapy.Field()  # choice, fill, judge, short_answer, design, analysis
    content = scrapy.Field()
    options = scrapy.Field()
    answer = scrapy.Field()
    explanation = scrapy.Field()
    difficulty = scrapy.Field()  # easy, medium, hard
    source = scrapy.Field()
    exam_year = scrapy.Field()
    knowledge_point_ids = scrapy.Field()
    tags = scrapy.Field()

    # Status
    status = scrapy.Field()

    # Timestamps
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
