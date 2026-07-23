from datetime import datetime
from types import SimpleNamespace

import pytest

from app.modules.agent.admin_router import _serialize_run, get_run_stats


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _StatsSession:
    def __init__(self, values):
        self._values = iter(values)

    async def execute(self, _statement):
        return _ScalarResult(next(self._values))


def test_serialize_run_uses_current_agent_run_fields():
    started_at = datetime(2026, 7, 23, 8, 0, 0)
    completed_at = datetime(2026, 7, 23, 8, 0, 2)
    run = SimpleNamespace(
        id="run-1",
        thread_id="thread-1",
        user_id="user-1",
        workflow_key="conversation",
        workflow_name="legacy-conversation",
        workflow_version="v2",
        status="completed",
        client_idempotency_key="request-1",
        current_public_step="answer",
        lease_owner=None,
        lease_expires_at=None,
        metadata_json={"model_config_id": "model-1", "error_code": "none"},
        started_at=started_at,
        completed_at=completed_at,
        error_message=None,
        created_at=started_at,
        updated_at=completed_at,
    )

    payload = _serialize_run(run, last_event_sequence=7)

    assert payload["workflow_key"] == "conversation"
    assert payload["workflow_version"] == "v2"
    assert payload["current_step_key"] == "answer"
    assert payload["last_event_sequence"] == 7
    assert payload["model_config_id"] == "model-1"
    assert payload["started_at"] == "2026-07-23T08:00:00Z"
    assert payload["completed_at"] == "2026-07-23T08:00:02Z"


def test_serialize_run_falls_back_to_legacy_workflow_fields():
    timestamp = datetime(2026, 7, 23, 8, 0, 0)
    run = SimpleNamespace(
        id="run-2",
        thread_id="thread-1",
        user_id="user-1",
        workflow_key=None,
        workflow_name="conversation",
        workflow_version=None,
        status="queued",
        client_idempotency_key=None,
        current_public_step=None,
        lease_owner=None,
        lease_expires_at=None,
        metadata_json=None,
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=timestamp,
        updated_at=timestamp,
    )

    payload = _serialize_run(run)

    assert payload["workflow_key"] == "conversation"
    assert payload["workflow_version"] == "v1"
    assert payload["model_config_id"] is None
    assert payload["started_at"] is None
    assert payload["completed_at"] is None


@pytest.mark.asyncio
async def test_run_stats_follow_admin_api_data_envelope():
    session = _StatsSession([8, 1, 2, 3, 1, 1, 0])

    response = await get_run_stats(db=session)

    assert response == {
        "data": {
            "total": 8,
            "queued": 1,
            "running": 2,
            "completed": 3,
            "failed": 1,
            "waiting_for_user": 1,
            "waiting_for_approval": 0,
        }
    }
