from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.learning.weaknesses import WeaknessService, project_weakness_rows
from app.modules.learning.weaknesses import project_weakness_events, project_weakness_evidence
from app.modules.learning.models import LearningActivityEvent


def _row(*, correct: bool, saved_at: datetime, session_id: str = "session-1"):
    answer = SimpleNamespace(
        user_answer="A",
        is_correct=correct,
        saved_at=saved_at,
        hint_levels_used_json=["concept"] if not correct else [],
    )
    session = SimpleNamespace(id=session_id, title="2024 年真题")
    session.agent_thread_id = None
    session.agent_run_id = None
    link = SimpleNamespace(
        item_id="item-1",
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


def test_weakness_projection_merges_agent_grade_evidence_with_practice_semantics():
    now = datetime(2026, 7, 28, 12, 0, 0)
    event = LearningActivityEvent(
        id=1,
        user_id="01900000-0000-7000-8000-000000000001",
        event_type="agent_grade_confirmed",
        source_type="agent_grade",
        source_id="grade-1",
        thread_id="thread-1",
        run_id="run-1",
        topic_keywords_json=["二分查找"],
        knowledge_point_ids_json=["kp-binary"],
        quality=0.25,
        is_correct=False,
        occurred_at=now - timedelta(days=2),
        payload_json={
            "question_id": "generated-1",
            "content": "边界更新错误",
            "source": "Agent 对话内批改",
        },
    )

    payload = project_weakness_events([event], now)

    assert payload["summary"]["wrong_answer_count"] == 1
    assert payload["clusters"][0]["keyword"] == "二分查找"
    assert payload["clusters"][0]["representative"]["session_id"] is None
    assert payload["clusters"][0]["representative"]["thread_id"] == "thread-1"
    assert payload["clusters"][0]["representative"]["source_type"] == "agent_grade"


def test_later_practice_success_verifies_earlier_agent_grade_error():
    now = datetime(2026, 7, 28, 12, 0, 0)
    payload = project_weakness_evidence(
        [
            {
                "source_type": "agent_grade",
                "source_id": "grade-1",
                "session_id": None,
                "session_title": "Agent 对话练习",
                "question_id": "generated-1",
                "question_no": None,
                "content": "边界处理错误",
                "source": "Agent 对话内批改",
                "is_correct": False,
                "occurred_at": now - timedelta(days=3),
                "hint_levels_used": [],
                "thread_id": "thread-1",
                "run_id": "run-1",
                "keywords": ["二分查找"],
            },
            {
                "source_type": "agent_practice",
                "source_id": "session-1:item-1",
                "session_id": "session-1",
                "session_title": "二分查找专项练习",
                "question_id": "item-1",
                "question_no": None,
                "content": "边界条件验证",
                "source": "Agent 练习",
                "is_correct": True,
                "occurred_at": now - timedelta(days=1),
                "hint_levels_used": [],
                "thread_id": "thread-1",
                "run_id": "run-2",
                "keywords": ["二分查找"],
            },
        ],
        now,
    )

    assert payload["clusters"][0]["attempt_count"] == 2
    assert payload["clusters"][0]["status"] == "awaiting_interval_verification"


@pytest.mark.asyncio
async def test_weakness_service_filters_submitted_answers_by_current_user():
    execute_result = Mock()
    execute_result.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = execute_result
    scalar_result = Mock()
    scalar_result.all.return_value = []
    db.scalars.return_value = scalar_result

    payload = await WeaknessService(db).get(
        "01900000-0000-7000-8000-000000000001",
        now=datetime(2026, 7, 28, 12, 0, 0),
    )

    statement = str(db.execute.await_args.args[0])
    assert "practice_sessions.user_id =" in statement
    assert "practice_sessions.status =" in statement
    assert payload["summary"]["cluster_count"] == 0
