from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.learning.events import record_explanation_activity
from app.modules.learning.models import LearningActivityEvent


@pytest.mark.asyncio
async def test_explanation_activity_records_topic_exposure_without_mastery_verdict():
    db = AsyncMock()
    db.add = Mock()
    db.scalar.return_value = None
    run = SimpleNamespace(
        id="run_explain_001",
        user_id="01900000000070008000000000000001",
        thread_id="thread_001",
        metadata_json={
            "context_snapshot": {
                "active_topic": {
                    "entity_type": "knowledge_point",
                    "entity_id": "kp_binary_search",
                    "title": "二分查找",
                    "aliases": ["折半查找"],
                }
            }
        },
    )
    artifact = SimpleNamespace(
        id="artifact_explain_001",
        created_at=datetime(2026, 7, 28, 10, 0, 0),
        content_json={"title": "二分查找讲解"},
    )

    event = await record_explanation_activity(db, run=run, artifact=artifact)

    assert isinstance(event, LearningActivityEvent)
    assert event.event_type == "agent_explanation_completed"
    assert event.source_type == "agent_discussion"
    assert event.topic_keywords_json == ["二分查找", "折半查找"]
    assert event.quality == 0.35
    assert event.is_correct is None
    assert event.knowledge_point_ids_json == ["kp_binary_search"]
    db.add.assert_called_once_with(event)
    db.flush.assert_awaited_once()
