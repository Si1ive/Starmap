"""Agent API 时间必须携带明确 UTC 时区。"""

import json
from datetime import UTC, datetime, timedelta, timezone

from app.modules.agent.events import serialize_sse_from_dict
from app.modules.agent.schemas import MessageView, ThreadResponse
from app.modules.agent.time_utils import encode_utc_datetimes, utc_isoformat, utc_now


def test_utc_isoformat_marks_naive_database_time_as_utc():
    value = datetime(2026, 7, 23, 8, 15, 30)

    assert utc_isoformat(value) == "2026-07-23T08:15:30Z"


def test_utc_now_keeps_mysql_compatible_naive_utc_value():
    value = utc_now()

    assert value.tzinfo is None
    assert abs((datetime.now(UTC).replace(tzinfo=None) - value).total_seconds()) < 1


def test_utc_isoformat_converts_aware_time_to_utc():
    shanghai = timezone(timedelta(hours=8))
    value = datetime(2026, 7, 23, 16, 15, 30, tzinfo=shanghai)

    assert utc_isoformat(value) == "2026-07-23T08:15:30Z"


def test_agent_response_models_serialize_all_public_times_with_timezone():
    naive_utc = datetime(2026, 7, 23, 8, 15, 30)
    thread = ThreadResponse(
        id="thread_001",
        user_id="user_001",
        title="测试",
        status="active",
        metadata=None,
        created_at=naive_utc,
        updated_at=naive_utc,
    )
    message = MessageView(
        id="msg_001",
        role="assistant",
        status="completed",
        content="回答",
        created_at=naive_utc,
        updated_at=naive_utc,
        completed_at=naive_utc,
    )

    assert thread.model_dump(mode="json")["created_at"].endswith("Z")
    assert message.model_dump(mode="json")["completed_at"].endswith("Z")


def test_nested_snapshot_and_sse_times_are_serialized_as_utc():
    naive_utc = datetime(2026, 7, 23, 8, 15, 30)
    encoded = encode_utc_datetimes(
        {"items": [{"created_at": naive_utc}], "generated_at": naive_utc}
    )

    assert encoded["items"][0]["created_at"].endswith("Z")
    event = serialize_sse_from_dict(1, "timeline.snapshot", encoded)
    payload = json.loads(event.split("data: ", 1)[1])
    assert payload["generated_at"] == "2026-07-23T08:15:30Z"


def test_existing_aware_utc_is_preserved():
    value = datetime(2026, 7, 23, 8, 15, 30, tzinfo=UTC)

    assert utc_isoformat(value) == "2026-07-23T08:15:30Z"
