"""Compatibility exports for catalog chapter mapping."""

from app.modules.catalog.canonical_chapter_service import CanonicalChapterService
from app.modules.catalog.chapter_diagnostics_service import (
    DIAG_OPTION_BLOCK_RE,
    DIAG_QUESTION_CUE_RE,
    DIAG_QUESTION_NUMERIC_RE,
    DIAG_QUESTION_PAREN_RE,
    DIAG_QUESTION_TITLE_RE,
    EXAM_DOC_TYPES,
    ChapterOwnershipDiagnosticsService,
    _block_text,
    _float_or_none,
    _looks_like_option_block,
    _looks_like_question_start,
    _text_excerpt,
)
from app.modules.catalog.chapter_mapping_service import (
    ChapterMappingService,
    generate_id,
)

__all__ = [
    "DIAG_OPTION_BLOCK_RE",
    "DIAG_QUESTION_CUE_RE",
    "DIAG_QUESTION_NUMERIC_RE",
    "DIAG_QUESTION_PAREN_RE",
    "DIAG_QUESTION_TITLE_RE",
    "EXAM_DOC_TYPES",
    "CanonicalChapterService",
    "ChapterMappingService",
    "ChapterOwnershipDiagnosticsService",
    "_block_text",
    "_float_or_none",
    "_looks_like_option_block",
    "_looks_like_question_start",
    "_text_excerpt",
    "generate_id",
]
