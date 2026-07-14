from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.modules.content.chapter_assignment import (
    PrimaryChapterAssignmentService,
)
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
        primary_chapter_id="canonical-chapter-1",
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
        "primary_chapter_id": "canonical-chapter-1",
        "type": "choice",
        "source": "2025 真题",
        "exam_year": 2025,
        "status": "pending",
    }
    assert "primary_chapter_id" in ContentService.QUESTION_INDEX_FIELDS


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
async def test_primary_assignment_syncs_question_and_link(monkeypatch):
    chapter = SimpleNamespace(
        id="canonical-new",
        subject_id="subject-new",
        status="active",
    )
    question = SimpleNamespace(
        id="question-1",
        subject_id="subject-old",
        chapter_id="chapter-old",
        primary_chapter_id="canonical-old",
    )
    old_link = SimpleNamespace(is_primary=True)
    clear_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [old_link])
    )
    existing_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = chapter
    db.execute.side_effect = [clear_result, existing_result]

    resolve_legacy = AsyncMock(return_value="chapter-new")
    monkeypatch.setattr(
        "app.modules.content.chapter_assignment.resolve_legacy_chapter_id",
        resolve_legacy,
    )

    await PrimaryChapterAssignmentService(db).assign_question(
        question,
        chapter.id,
    )

    assert question.primary_chapter_id == chapter.id
    assert question.subject_id == chapter.subject_id
    assert question.chapter_id == "chapter-new"
    assert old_link.is_primary is False
    new_link = db.add.call_args.args[0]
    assert new_link.question_id == question.id
    assert new_link.canonical_chapter_id == chapter.id
    assert new_link.is_primary is True
    assert new_link.source == "manual"
    assert new_link.created_by == "admin"


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
async def test_question_update_assigns_primary_chapter_before_rebuilding(monkeypatch):
    events = []
    question = SimpleNamespace(
        id="question-2",
        status="active",
        subject_id="subject-old",
        chapter_id="chapter-old",
        primary_chapter_id="canonical-old",
    )
    db = AsyncMock()
    db.get.return_value = question

    async def assign(_service, item, primary_chapter_id):
        events.append(("assign", primary_chapter_id))
        item.subject_id = "subject-new"
        item.chapter_id = "chapter-new"
        item.primary_chapter_id = primary_chapter_id

    async def commit():
        events.append("commit")

    async def rebuild(entity_type, entity_id):
        events.append(("rebuild", entity_type, entity_id))
        return {"status": "success", "segments_count": 1}

    monkeypatch.setattr(
        PrimaryChapterAssignmentService,
        "assign_question",
        assign,
    )
    db.commit.side_effect = commit
    service = ContentService(db)
    monkeypatch.setattr(service, "_rebuild_entity_index", rebuild)

    result = await service.update_question(
        question.id,
        {"primary_chapter_id": "canonical-new"},
    )

    assert question.subject_id == "subject-new"
    assert question.chapter_id == "chapter-new"
    assert question.primary_chapter_id == "canonical-new"
    assert events == [
        ("assign", "canonical-new"),
        "commit",
        ("rebuild", "question", question.id),
    ]
    assert result == {"status": "success", "segments_count": 1}


@pytest.mark.asyncio
async def test_question_update_keeps_subject_aligned_with_existing_primary(
    monkeypatch,
):
    question = SimpleNamespace(
        id="question-3",
        status="active",
        subject_id="subject-old",
        chapter_id="chapter-old",
        primary_chapter_id="canonical-current",
    )
    db = AsyncMock()
    db.get.return_value = question
    assigned = []

    async def assign(_service, item, primary_chapter_id):
        assigned.append(primary_chapter_id)
        item.subject_id = "subject-canonical"
        item.chapter_id = "chapter-canonical"

    monkeypatch.setattr(
        PrimaryChapterAssignmentService,
        "assign_question",
        assign,
    )
    service = ContentService(db)
    monkeypatch.setattr(
        service,
        "_rebuild_entity_index",
        AsyncMock(return_value={"status": "success"}),
    )

    await service.update_question(
        question.id,
        {
            "subject_id": "subject-mismatched",
        },
    )

    assert assigned == ["canonical-current"]
    assert question.subject_id == "subject-canonical"
    assert question.chapter_id == "chapter-canonical"


@pytest.mark.asyncio
async def test_question_list_can_filter_exact_question_id():
    db = AsyncMock()
    db.scalar.return_value = 0
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [])
    )

    result = await ContentService(db).list_questions(
        page=1,
        page_size=20,
        question_id="question-focus",
    )

    count_query = db.scalar.await_args.args[0]
    compiled_query = str(
        count_query.compile(compile_kwargs={"literal_binds": True})
    )
    assert "questions.id = 'question-focus'" in compiled_query
    assert result == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
    }


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
