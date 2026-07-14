from datetime import datetime
from types import SimpleNamespace

from app.modules.content.entity_serializers import (
    serialize_managed_knowledge_point,
    serialize_managed_question,
    serialize_review_knowledge_point,
    serialize_review_question,
)


def _review_fields():
    return {
        "review_status": "pending",
        "review_notes": None,
        "reviewed_by": None,
        "reviewed_at": datetime(2026, 7, 14, 12, 0, 0),
        "status": "active",
        "created_at": datetime(2026, 7, 14, 10, 0, 0),
        "updated_at": datetime(2026, 7, 14, 11, 0, 0),
    }


def _knowledge_point(**overrides):
    values = {
        "id": "knowledge-1",
        "chapter_id": "legacy-chapter-1",
        "subject_id": "subject-1",
        "primary_chapter_id": "chapter-1",
        "source_document_id": "document-1",
        "source_section_path": "第一章",
        "title": "循环队列",
        "canonical_title": "循环队列",
        "content": "知" * 600,
        "difficulty": "medium",
        "exam_frequency": "high",
        "topic_terms": ["队列"],
        "aliases": ["环形队列"],
        "tags": ["数据结构"],
        "key_points": ["队首计算"],
        "related_point_ids": [],
        "summary": "知识点摘要",
        "source": "试卷4.pdf",
        "source_page": 1,
        **_review_fields(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _question(**overrides):
    values = {
        "id": "question-1",
        "subject_id": "subject-1",
        "chapter_id": "legacy-chapter-1",
        "primary_chapter_id": "chapter-1",
        "source_document_id": "document-1",
        "source_section_path": "第一章",
        "type": "choice",
        "content": "题" * 600,
        "options": [{"key": "A", "text": "选项A"}],
        "answer": "A",
        "explanation": "解" * 400,
        "answer_source": "pdf",
        "explanation_source": "llm",
        "enrich_status": "completed",
        "difficulty": "medium",
        "source": "试卷4.pdf",
        "exam_scope": "408",
        "exam_year": 2026,
        "paper_name": "试卷4",
        "question_no": "1",
        "topic_terms": ["循环队列"],
        "knowledge_point_ids": ["knowledge-1"],
        "tags": ["数据结构"],
        "extraction_meta": {"fixed_by_llm": True},
        **_review_fields(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_knowledge_point_serializers_keep_distinct_response_profiles():
    point = _knowledge_point()

    managed = serialize_managed_knowledge_point(point, truncate=True)
    reviewed = serialize_review_knowledge_point(point)

    assert len(managed["content"]) == 200
    assert len(reviewed["content"]) == 500
    assert set(managed) - set(reviewed) == {
        "summary",
        "source",
        "source_page",
    }
    assert reviewed["reviewed_at"] == "2026-07-14T12:00:00"


def test_question_serializers_keep_distinct_response_profiles():
    question = _question()

    managed = serialize_managed_question(question, truncate=True)
    reviewed = serialize_review_question(question)

    assert len(managed["content"]) == 200
    assert len(reviewed["content"]) == 500
    assert len(managed["explanation"]) == 300
    assert len(reviewed["explanation"]) == 300
    assert set(managed) - set(reviewed) == {
        "answer_source",
        "explanation_source",
        "enrich_status",
        "tags",
        "extraction_meta",
    }


def test_serializers_preserve_existing_empty_text_semantics():
    point = _knowledge_point(content=None)
    question = _question(content=None, explanation=None)

    assert serialize_managed_knowledge_point(point)["content"] == ""
    assert serialize_review_knowledge_point(point)["content"] is None
    assert serialize_managed_question(question)["content"] == ""
    assert serialize_managed_question(question)["explanation"] == ""
    assert serialize_review_question(question)["content"] is None
    assert serialize_review_question(question)["explanation"] is None
