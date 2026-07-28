from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.modules.practice.router import _normalize_answer, _owned_session, _submit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" A. 页表 ", "A"),
        ("b、选项", "B"),
        ("正确", "TRUE"),
        ("错", "FALSE"),
        ("  42  ", "42"),
    ],
)
def test_normalize_answer_supports_objective_question_formats(raw, expected):
    assert _normalize_answer(raw) == expected


@pytest.mark.asyncio
async def test_owned_session_always_filters_by_current_user():
    db = AsyncMock()
    db.scalar.return_value = None

    with pytest.raises(HTTPException) as error:
        await _owned_session(
            db,
            "session-1",
            "01900000-0000-7000-8000-000000000001",
        )

    statement = str(db.scalar.await_args.args[0])
    assert "practice_sessions.id =" in statement
    assert "practice_sessions.user_id =" in statement
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_grades_against_frozen_snapshot_not_changed_question():
    answer = SimpleNamespace(
        user_answer="A",
        is_correct=None,
        awarded_score=None,
    )
    link = SimpleNamespace(max_score=2, snapshot_json={"answer": "A"})
    changed_question = SimpleNamespace(id="q-1", answer="B")
    execute_result = Mock()
    execute_result.all.return_value = [(link, changed_question, answer)]
    db = AsyncMock()
    db.execute.return_value = execute_result
    session = SimpleNamespace(
        id="session-1",
        status="active",
        awarded_score=None,
        submitted_at=None,
    )

    await _submit(db, session)

    assert answer.is_correct is True
    assert answer.awarded_score == 2
    assert session.awarded_score == 2
    assert session.status == "submitted"
