from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.learning.weaknesses import WeaknessService, project_weakness_rows


def _row(*, correct: bool, saved_at: datetime, session_id: str = "session-1"):
    answer = SimpleNamespace(
        user_answer="A",
        is_correct=correct,
        saved_at=saved_at,
        hint_levels_used_json=["concept"] if not correct else [],
    )
    session = SimpleNamespace(id=session_id, title="2024 年真题")
    link = SimpleNamespace(
        snapshot_json={
            "content": "进程调度应选择哪种算法？",
            "source": "试卷.pdf",
            "question_no": "3",
            "topic_terms": ["进程调度"],
            "tags": [],
        }
    )
    question = SimpleNamespace(
        id="question-1",
        content="当前题面不应覆盖快照",
        source=None,
        topic_terms=[],
        tags=[],
        source_section_path=None,
    )
    return answer, session, link, question


def test_weakness_projection_groups_real_wrong_answers_and_preserves_evidence():
    now = datetime(2026, 7, 28, 12, 0, 0)
    rows = [
        _row(correct=False, saved_at=now - timedelta(days=3)),
        _row(correct=False, saved_at=now - timedelta(days=2), session_id="session-2"),
    ]

    payload = project_weakness_rows(rows, now)

    assert payload["summary"] == {
        "cluster_count": 1,
        "wrong_answer_count": 2,
        "due_count": 1,
    }
    cluster = payload["clusters"][0]
    assert cluster["keyword"] == "进程调度"
    assert cluster["wrong_count"] == 2
    assert cluster["status"] == "due"
    assert cluster["representative"]["content"] == "进程调度应选择哪种算法？"
    assert cluster["representative"]["hint_levels_used"] == ["concept"]


def test_weakness_projection_does_not_mark_one_later_correct_answer_resolved():
    now = datetime(2026, 7, 28, 12, 0, 0)
    payload = project_weakness_rows(
        [
            _row(correct=False, saved_at=now - timedelta(days=3)),
            _row(correct=True, saved_at=now - timedelta(days=1)),
        ],
        now,
    )

    assert payload["clusters"][0]["status"] == "awaiting_interval_verification"


@pytest.mark.asyncio
async def test_weakness_service_filters_submitted_answers_by_current_user():
    execute_result = Mock()
    execute_result.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = execute_result

    payload = await WeaknessService(db).get(
        "01900000-0000-7000-8000-000000000001",
        now=datetime(2026, 7, 28, 12, 0, 0),
    )

    statement = str(db.execute.await_args.args[0])
    assert "practice_sessions.user_id =" in statement
    assert "practice_sessions.status =" in statement
    assert payload["summary"]["cluster_count"] == 0
