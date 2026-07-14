"""Compatibility exports for catalog chapter linking."""

from app.modules.catalog.chapter_link_service import (
    HIGH_CONFIDENCE_KEYWORD_THRESHOLD,
    SUBJECT_FALLBACK_MARGIN,
    VECTOR_MATCH_THRESHOLD,
    ChapterLinkService,
)

__all__ = [
    "HIGH_CONFIDENCE_KEYWORD_THRESHOLD",
    "SUBJECT_FALLBACK_MARGIN",
    "VECTOR_MATCH_THRESHOLD",
    "ChapterLinkService",
]
