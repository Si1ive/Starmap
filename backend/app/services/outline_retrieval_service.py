"""Compatibility exports for outline-assisted retrieval."""

from app.modules.retrieval.outline_service import (
    OutlineExpansionResult,
    ScopeChapter,
    SemanticRelation,
    expand_chapter_scope,
    expand_query_with_outline,
    expand_related_chapters,
    fallback_chapter_similarity,
    retrieve_by_chapters,
    retrieve_by_question,
    validate_cross_references,
)

__all__ = [
    "OutlineExpansionResult",
    "ScopeChapter",
    "SemanticRelation",
    "expand_chapter_scope",
    "expand_query_with_outline",
    "expand_related_chapters",
    "fallback_chapter_similarity",
    "retrieve_by_chapters",
    "retrieve_by_question",
    "validate_cross_references",
]
