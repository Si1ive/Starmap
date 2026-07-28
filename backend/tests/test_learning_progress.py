from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from app.modules.learning.service import (
    LearningEvidence,
    LearningProgressService,
    normalize_keyword,
    project_ebbinghaus,
)


def evidence(at, *, quality=1.0, correct=True, source_id="q-1"):
    return LearningEvidence(
        keyword="循环队列",
        occurred_at=at,
        quality=quality,
        correct=correct,
        source_type="question",
        source_id=source_id,
    )


def test_keyword_normalization_merges_question_and_knowledge_labels():
    assert normalize_keyword(" 循环 队列：判空 ") == "循环队列判空"
    assert normalize_keyword("循环队列/判空") == "循环队列判空"


def test_ebbinghaus_retention_declines_monotonically_without_new_evidence():
    learned_at = datetime(2026, 7, 1, 9, 0, 0)
    projection = project_ebbinghaus(
        [evidence(learned_at)], learned_at + timedelta(hours=6)
    )

    curve = [point["retention"] for point in projection["curve"]]
    assert curve == sorted(curve, reverse=True)
    assert curve[0] > curve[-1]


def test_spaced_correct_recall_extends_strength_more_than_an_error():
    first = datetime(2026, 7, 1, 9, 0, 0)
    now = first + timedelta(days=3)
    correct = project_ebbinghaus(
        [evidence(first), evidence(first + timedelta(days=1), source_id="q-2")],
        now,
    )
    incorrect = project_ebbinghaus(
        [
            evidence(first),
            evidence(
                first + timedelta(days=1), quality=0.25, correct=False, source_id="q-2"
            ),
        ],
        now,
    )

    assert correct["strength_hours"] > incorrect["strength_hours"]
    assert correct["retention"] > incorrect["retention"]


def test_projection_rejects_empty_evidence():
    with pytest.raises(ValueError, match="至少需要一条学习证据"):
        project_ebbinghaus([], datetime(2026, 7, 1))


@pytest.mark.asyncio
async def test_question_totals_are_scoped_to_current_user_and_submitted_sessions():
    result = Mock()
    result.one.return_value = (3, 2)
    db = AsyncMock()
    db.execute.return_value = result
    user_id = UUID("01900000-0000-7000-8000-000000000001")

    totals = await LearningProgressService(db)._question_totals(user_id)

    statement = str(db.execute.await_args.args[0])
    assert totals == (3, 2)
    assert "practice_sessions.user_id =" in statement
    assert "practice_sessions.status =" in statement
