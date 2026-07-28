from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.modules.agent.admin_router import _build_turns, _serialize_run, get_run_stats


class _Result:
    def __init__(self, *, scalar_value=None, rows=None):
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar(self):
        return self._scalar_value

    def all(self):
        return self._rows


class _StatsSession:
    def __init__(self):
        self._results = iter(
            [
                _Result(scalar_value=5),
                _Result(rows=[("completed", 3), ("running", 1), ("failed", 1)]),
            ]
        )

    async def execute(self, _statement):
        return next(self._results)


def _run(run_id: str, created_at: datetime, **overrides):
    values = {
        "id": run_id,
        "thread_id": "thread-1",
        "user_id": "user-1",
        "workflow_key": "conversation",
        "workflow_name": "conversation",
        "workflow_version": "v1",
        "status": "completed",
        "input_message": "问题",
        "trigger_message_id": None,
        "parent_run_id": None,
        "root_run_id": run_id,
        "presentation": "silent",
        "public_title": None,
        "public_summary": None,
        "current_public_step": "answer",
        "metadata_json": {
            "model_config_id": "model-1",
            "capability_snapshot": {
                "policy_version": "agent-capabilities-v1",
                "selected": "practice.prepare",
                "available": [
                    {"key": "practice.prepare", "tools": ["retrieve_knowledge"]}
                ],
            },
        },
        "error_message": None,
        "started_at": created_at,
        "completed_at": created_at + timedelta(seconds=2),
        "created_at": created_at,
        "updated_at": created_at + timedelta(seconds=2),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _message(message_id: str, run_id: str, role: str, content: str, created_at: datetime):
    return SimpleNamespace(
        id=message_id,
        run_id=run_id,
        role=role,
        status="completed",
        content_text=content,
        error_code=None,
        created_at=created_at,
        completed_at=created_at,
    )


def test_serialize_run_uses_current_agent_run_fields():
    started_at = datetime(2026, 7, 23, 8, 0, 0)
    run = _run("run-1", started_at, workflow_version="v2")

    payload = _serialize_run(run, event_count=7)

    assert payload["workflow_key"] == "conversation"
    assert payload["workflow_version"] == "v2"
    assert payload["current_step_key"] == "answer"
    assert payload["event_count"] == 7
    assert payload["model_config_id"] == "model-1"
    assert payload["capability_snapshot"]["selected"] == "practice.prepare"
    assert payload["capability_snapshot"]["available"][0]["tools"] == [
        "retrieve_knowledge"
    ]
    assert payload["started_at"] == "2026-07-23T08:00:00Z"
    assert payload["completed_at"] == "2026-07-23T08:00:02Z"


def test_build_turns_groups_child_runs_and_events_under_each_question():
    started_at = datetime(2026, 7, 23, 8, 0, 0)
    root_one = _run("run-root-1", started_at, trigger_message_id="msg-user-1")
    child_one = _run(
        "run-child-1",
        started_at + timedelta(seconds=1),
        workflow_key="explain",
        workflow_name="explain",
        parent_run_id=root_one.id,
        root_run_id=root_one.id,
    )
    root_two = _run(
        "run-root-2",
        started_at + timedelta(minutes=1),
        trigger_message_id="msg-user-2",
        input_message="第二个问题",
    )
    messages = [
        _message("msg-user-1", root_one.id, "user", "第一个问题", started_at),
        _message("msg-answer-1", root_one.id, "assistant", "第一个回答", started_at),
        _message("msg-user-2", root_two.id, "user", "第二个问题", root_two.created_at),
    ]
    events = [
        SimpleNamespace(
            id=1,
            run_id=child_one.id,
            sequence=1,
            event_type="step.started",
            payload={"node": "explain"},
            created_at=child_one.created_at,
        )
    ]

    turns = _build_turns(
        [root_one, child_one, root_two],
        messages,
        events,
        [],
        [],
    )

    assert len(turns) == 2
    assert turns[0]["root_run_id"] == root_one.id
    assert [run["id"] for run in turns[0]["runs"]] == [root_one.id, child_one.id]
    assert turns[0]["user_message"]["content"] == "第一个问题"
    assert turns[0]["assistant_messages"][0]["content"] == "第一个回答"
    assert turns[0]["events"][0]["run_id"] == child_one.id
    assert turns[1]["root_run_id"] == root_two.id


@pytest.mark.asyncio
async def test_run_stats_classify_each_session_by_latest_turn_status():
    response = await get_run_stats(db=_StatsSession())

    assert response == {
        "data": {
            "total": 5,
            "queued": 0,
            "running": 1,
            "completed": 3,
            "failed": 1,
            "waiting_for_user": 0,
            "waiting_for_approval": 0,
        }
    }
