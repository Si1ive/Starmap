"""Stable response serializers for managed and reviewed content entities."""

from datetime import datetime
from typing import Any, Dict, Optional

from app.models.mysql_models import KnowledgePoint, Question


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _serialize_text(
    value: Optional[str],
    *,
    limit: Optional[int],
    empty_value: Optional[str],
) -> Optional[str]:
    if not value:
        return empty_value
    return value[:limit] if limit is not None else value


def _serialize_knowledge_point_base(
    point: KnowledgePoint,
    *,
    content_limit: Optional[int],
    empty_content: Optional[str],
) -> Dict[str, Any]:
    return {
        "id": point.id,
        "chapter_id": point.chapter_id,
        "subject_id": point.subject_id,
        "primary_chapter_id": point.primary_chapter_id,
        "source_document_id": point.source_document_id,
        "source_section_path": point.source_section_path,
        "title": point.title,
        "canonical_title": point.canonical_title,
        "content": _serialize_text(
            point.content,
            limit=content_limit,
            empty_value=empty_content,
        ),
        "difficulty": point.difficulty,
        "exam_frequency": point.exam_frequency,
        "topic_terms": point.topic_terms,
        "aliases": point.aliases,
        "tags": point.tags,
        "key_points": point.key_points,
        "related_point_ids": point.related_point_ids,
        "review_status": point.review_status,
        "review_notes": point.review_notes,
        "reviewed_by": point.reviewed_by,
        "reviewed_at": _isoformat(point.reviewed_at),
        "status": point.status,
        "created_at": _isoformat(point.created_at),
        "updated_at": _isoformat(point.updated_at),
    }


def serialize_managed_knowledge_point(
    point: KnowledgePoint,
    *,
    truncate: bool = False,
) -> Dict[str, Any]:
    """Serialize a knowledge point for the content management APIs."""
    data = _serialize_knowledge_point_base(
        point,
        content_limit=200 if truncate else None,
        empty_content="",
    )
    data.update(
        {
            "summary": point.summary,
            "source": point.source,
            "source_page": point.source_page,
        }
    )
    return data


def serialize_review_knowledge_point(point: KnowledgePoint) -> Dict[str, Any]:
    """Serialize a knowledge point for the focused review list."""
    return _serialize_knowledge_point_base(
        point,
        content_limit=500,
        empty_content=None,
    )


def _serialize_question_base(
    question: Question,
    *,
    content_limit: Optional[int],
    explanation_limit: Optional[int],
    empty_text: Optional[str],
) -> Dict[str, Any]:
    return {
        "id": question.id,
        "subject_id": question.subject_id,
        "chapter_id": question.chapter_id,
        "primary_chapter_id": question.primary_chapter_id,
        "source_document_id": question.source_document_id,
        "source_section_path": question.source_section_path,
        "type": question.type,
        "content": _serialize_text(
            question.content,
            limit=content_limit,
            empty_value=empty_text,
        ),
        "options": question.options,
        "answer": question.answer,
        "explanation": _serialize_text(
            question.explanation,
            limit=explanation_limit,
            empty_value=empty_text,
        ),
        "difficulty": question.difficulty,
        "source": question.source,
        "exam_scope": question.exam_scope,
        "exam_year": question.exam_year,
        "paper_name": question.paper_name,
        "question_no": question.question_no,
        "topic_terms": question.topic_terms,
        "knowledge_point_ids": question.knowledge_point_ids,
        "review_status": question.review_status,
        "review_notes": question.review_notes,
        "reviewed_by": question.reviewed_by,
        "reviewed_at": _isoformat(question.reviewed_at),
        "status": question.status,
        "created_at": _isoformat(question.created_at),
        "updated_at": _isoformat(question.updated_at),
    }


def serialize_managed_question(
    question: Question,
    *,
    truncate: bool = False,
) -> Dict[str, Any]:
    """Serialize a question for the content management APIs."""
    data = _serialize_question_base(
        question,
        content_limit=200 if truncate else None,
        explanation_limit=300 if truncate else None,
        empty_text="",
    )
    data.update(
        {
            "answer_source": question.answer_source,
            "explanation_source": question.explanation_source,
            "enrich_status": question.enrich_status,
            "tags": question.tags,
            "extraction_meta": question.extraction_meta,
        }
    )
    return data


def serialize_review_question(question: Question) -> Dict[str, Any]:
    """Serialize a question for the focused review list."""
    return _serialize_question_base(
        question,
        content_limit=500,
        explanation_limit=300,
        empty_text=None,
    )


__all__ = [
    "serialize_managed_knowledge_point",
    "serialize_managed_question",
    "serialize_review_knowledge_point",
    "serialize_review_question",
]
