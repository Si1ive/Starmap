from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.mysql_models import KnowledgePoint, Question
from app.services.review_service import ReviewService
from app.services.segment_service import SegmentService


class _ScalarOneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _ScalarsResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


def _compiled_sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def test_content_models_default_to_active_while_review_starts_pending():
    assert Question.__table__.c.status.default.arg == "active"
    assert KnowledgePoint.__table__.c.status.default.arg == "active"
    assert Question.__table__.c.review_status.default.arg == "pending"
    assert KnowledgePoint.__table__.c.review_status.default.arg == "pending"


@pytest.mark.asyncio
async def test_rejecting_question_records_audit_without_disabling_content():
    question = SimpleNamespace(
        id="question-1",
        status="active",
        primary_chapter_id=None,
        review_status="pending",
        review_notes=None,
        reviewed_by=None,
        reviewed_at=None,
    )
    db = AsyncMock()
    db.execute.return_value = _ScalarOneResult(question)

    result = await ReviewService(db).review_question(
        question_id=question.id,
        review_status="rejected",
        review_notes="题干需要人工复核",
        reviewed_by="admin-1",
    )

    assert question.status == "active"
    assert question.review_status == "rejected"
    assert question.review_notes == "题干需要人工复核"
    assert question.reviewed_by == "admin-1"
    assert question.reviewed_at is not None
    assert result["status"] == "active"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_approving_knowledge_point_records_audit_without_publishing_side_effects():
    point = SimpleNamespace(
        id="knowledge-1",
        status="active",
        primary_chapter_id=None,
        review_status="pending",
        review_notes=None,
        reviewed_by=None,
        reviewed_at=None,
        topic_terms=None,
    )
    db = AsyncMock()
    db.execute.return_value = _ScalarOneResult(point)

    result = await ReviewService(db).review_knowledge_point(
        knowledge_point_id=point.id,
        review_status="approved",
        review_notes="内容核验通过",
        reviewed_by="admin-1",
    )

    assert point.status == "active"
    assert point.review_status == "approved"
    assert point.review_notes == "内容核验通过"
    assert point.reviewed_by == "admin-1"
    assert point.reviewed_at is not None
    assert result["status"] == "active"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_list_filter_does_not_reintroduce_publication_gate():
    db = AsyncMock()
    db.scalar.return_value = 0
    db.execute.return_value = _ScalarsResult([])

    await ReviewService(db).get_questions_for_review(
        review_status="rejected",
        page=1,
        page_size=20,
    )

    sql = _compiled_sql(db.execute.await_args.args[0])
    assert "questions.review_status = 'rejected'" in sql
    assert "questions.status = 'active'" not in sql
    assert "questions.status = 'pending'" not in sql


@pytest.mark.asyncio
async def test_segment_build_uses_active_content_regardless_of_review_status():
    db = AsyncMock()
    db.execute.return_value = _ScalarsResult([])

    result = await SegmentService(db).build_question_segments()

    sql = _compiled_sql(db.execute.await_args.args[0])
    where_clause = sql.partition("WHERE")[2]
    assert "questions.status = 'active'" in where_clause
    assert "questions.review_status" not in where_clause
    assert result == {"segments_count": 0, "message": "没有可用的题目"}
