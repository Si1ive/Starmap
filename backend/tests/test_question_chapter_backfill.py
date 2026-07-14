"""Historical question chapter backfill tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.modules.catalog.question_chapter_backfill import (
    QuestionChapterBackfillService,
)


def make_question(
    question_id: str,
    *,
    subject_id="subject-1",
    primary_chapter_id=None,
    chapter_id=None,
):
    return SimpleNamespace(
        id=question_id,
        content="进程调度算法题",
        subject_id=subject_id,
        primary_chapter_id=primary_chapter_id,
        chapter_id=chapter_id,
        topic_terms=["进程调度"],
        options=[],
    )


def make_question_result(questions):
    scalars = Mock()
    scalars.all.return_value = questions
    result = Mock()
    result.scalars.return_value = scalars
    return result


@pytest.mark.asyncio
async def test_backfill_skips_existing_chapter_without_force():
    resolver = AsyncMock()
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=make_question_result(
                [
                    make_question(
                        "question-1",
                        primary_chapter_id="chapter-1",
                    )
                ]
            )
        ),
        commit=AsyncMock(),
    )

    result = await QuestionChapterBackfillService(
        db,
        resolver,
    ).backfill()

    assert result["scanned"] == 1
    assert result["skipped_existing"] == 1
    assert result["items"] == []
    resolver.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_updates_resolved_chapter_and_legacy_assignment():
    question = make_question("question-1")
    resolver = AsyncMock(
        return_value={
            "chapter_id": "chapter-2",
            "subject_id": "subject-2",
            "source": "vector_search",
            "confidence": 0.91,
        }
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=make_question_result([question])
        ),
        commit=AsyncMock(),
    )

    with patch(
        "app.modules.catalog.question_chapter_backfill."
        "resolve_legacy_chapter_id",
        new=AsyncMock(return_value="legacy-2"),
    ):
        result = await QuestionChapterBackfillService(
            db,
            resolver,
        ).backfill()

    assert result["updated"] == 1
    assert result["items"][0] == {
        "id": "question-1",
        "status": "updated",
        "old_subject_id": "subject-1",
        "new_subject_id": "subject-2",
        "old_primary_chapter_id": None,
        "new_primary_chapter_id": "chapter-2",
        "old_chapter_id": None,
        "new_chapter_id": "legacy-2",
        "source": "vector_search",
        "confidence": 0.91,
    }
    assert question.subject_id == "subject-2"
    assert question.primary_chapter_id == "chapter-2"
    assert question.chapter_id == "legacy-2"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_dry_run_reports_update_without_mutating_or_committing():
    question = make_question("question-1")
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=make_question_result([question])
        ),
        commit=AsyncMock(),
    )
    resolver = AsyncMock(
        return_value={
            "chapter_id": "chapter-2",
            "subject_id": "subject-2",
        }
    )

    with patch(
        "app.modules.catalog.question_chapter_backfill."
        "resolve_legacy_chapter_id",
        new=AsyncMock(return_value="legacy-2"),
    ):
        result = await QuestionChapterBackfillService(
            db,
            resolver,
        ).backfill(dry_run=True)

    assert result["updated"] == 1
    assert result["dry_run"] is True
    assert question.subject_id == "subject-1"
    assert question.primary_chapter_id is None
    assert question.chapter_id is None
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_counts_resolution_failure_and_miss():
    questions = [
        make_question("question-failed"),
        make_question("question-missed"),
    ]
    resolver = AsyncMock(
        side_effect=[RuntimeError("向量服务不可用"), None]
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=make_question_result(questions)
        ),
        commit=AsyncMock(),
    )

    result = await QuestionChapterBackfillService(
        db,
        resolver,
    ).backfill()

    assert result["failed"] == 1
    assert result["missed"] == 1
    assert result["items"] == [
        {
            "id": "question-failed",
            "status": "failed",
            "error": "向量服务不可用",
        },
        {
            "id": "question-missed",
            "status": "missed",
            "old_primary_chapter_id": None,
        },
    ]
    db.commit.assert_awaited_once()
