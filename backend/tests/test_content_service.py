from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.modules.content.schemas import (
    UpdateKnowledgePointRequest,
    UpdateQuestionRequest,
)
from app.modules.content.service import ContentService
from app.modules.retrieval.segment_service import SegmentService


def test_content_update_schemas_keep_editable_assignment_fields():
    knowledge = UpdateKnowledgePointRequest(
        subject_id="subject-1",
        chapter_id="chapter-1",
        status="active",
    )
    question = UpdateQuestionRequest(
        subject_id="subject-1",
        chapter_id="chapter-1",
        type="choice",
        source="2025 真题",
        exam_year=2025,
        status="pending",
    )

    assert knowledge.model_dump(exclude_unset=True) == {
        "subject_id": "subject-1",
        "chapter_id": "chapter-1",
        "status": "active",
    }
    assert question.model_dump(exclude_unset=True) == {
        "subject_id": "subject-1",
        "chapter_id": "chapter-1",
        "type": "choice",
        "source": "2025 真题",
        "exam_year": 2025,
        "status": "pending",
    }


def test_content_update_schema_rejects_unsupported_draft_status():
    with pytest.raises(ValidationError):
        UpdateKnowledgePointRequest(status="draft")


@pytest.mark.parametrize(
    ("schema", "field", "value"),
    [
        (UpdateKnowledgePointRequest, "difficulty", "extreme"),
        (UpdateKnowledgePointRequest, "exam_frequency", "always"),
        (UpdateQuestionRequest, "type", "essay"),
        (UpdateQuestionRequest, "difficulty", "extreme"),
    ],
)
def test_content_update_schema_rejects_values_outside_database_enums(
    schema,
    field,
    value,
):
    with pytest.raises(ValidationError):
        schema(**{field: value})


@pytest.mark.asyncio
async def test_question_update_commits_before_rebuilding_index(monkeypatch):
    events = []
    question = SimpleNamespace(
        id="question-1",
        status="active",
        content="旧题干",
        exam_year=2024,
    )
    db = AsyncMock()
    db.get.return_value = question

    async def commit():
        events.append("commit")

    async def rebuild(entity_type, entity_id):
        events.append(("rebuild", entity_type, entity_id))
        return {"status": "success", "segments_count": 2}

    db.commit.side_effect = commit
    service = ContentService(db)
    monkeypatch.setattr(service, "_rebuild_entity_index", rebuild)

    result = await service.update_question(
        question.id,
        {"content": "新题干", "exam_year": 2025},
    )

    assert question.content == "新题干"
    assert question.exam_year == 2025
    assert events == [
        "commit",
        ("rebuild", "question", question.id),
    ]
    assert result == {"status": "success", "segments_count": 2}


@pytest.mark.asyncio
async def test_disabling_content_commits_with_segment_removal(monkeypatch):
    point = SimpleNamespace(
        id="knowledge-1",
        status="active",
    )
    db = AsyncMock()
    db.get.return_value = point
    calls = []

    async def remove_segments(_service, entity_type, entity_ids):
        calls.append((entity_type, entity_ids, point.status))
        return {"status": "success", "segments_count": 2}

    monkeypatch.setattr(
        SegmentService,
        "commit_entity_segment_removal",
        remove_segments,
    )

    result = await ContentService(db).update_knowledge_point(
        point.id,
        {"status": "pending"},
    )

    assert calls == [("knowledge_point", [point.id], "pending")]
    assert result == {"status": "success", "segments_count": 2}
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_question_commits_content_and_index_removal_together(monkeypatch):
    question = SimpleNamespace(id="question-2", status="active")
    db = AsyncMock()
    db.get.return_value = question
    service = ContentService(db)
    service._delete_question_dependencies = AsyncMock()

    async def remove_segments(_service, entity_type, entity_ids):
        return {"status": "warning", "cleanup_warning": "qdrant unavailable"}

    monkeypatch.setattr(
        SegmentService,
        "commit_entity_segment_removal",
        remove_segments,
    )

    result = await service.delete_question(question.id)

    assert question.status == "deleted"
    service._delete_question_dependencies.assert_awaited_once_with([question.id])
    assert result == {
        "id": question.id,
        "indexing": {
            "status": "warning",
            "cleanup_warning": "qdrant unavailable",
        },
    }
