"""Compatibility exports for document section extraction."""

from app.modules.corpus.document_section_service import (
    EXAM_DOC_TYPES,
    DocumentSectionService,
    generate_id,
)
from app.modules.corpus.section_heading import (
    HEADING_PATTERNS,
    LEVEL_KEYWORDS,
    OPTION_MARKER_RE,
    QUESTION_CUE_RE,
    SCORED_QUESTION_RE,
    _build_section_path,
    _detect_heading_level,
    _looks_like_question_or_option,
    build_section_path,
    detect_heading_level,
    looks_like_question_or_option,
)

__all__ = [
    "EXAM_DOC_TYPES",
    "HEADING_PATTERNS",
    "LEVEL_KEYWORDS",
    "OPTION_MARKER_RE",
    "QUESTION_CUE_RE",
    "SCORED_QUESTION_RE",
    "DocumentSectionService",
    "_build_section_path",
    "_detect_heading_level",
    "_looks_like_question_or_option",
    "build_section_path",
    "detect_heading_level",
    "generate_id",
    "looks_like_question_or_option",
]
