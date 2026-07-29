from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.learning.events import (
    record_agent_grade_activity,
    record_explanation_activity,
    record_practice_submission,
)
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
    assert event.evidence_type == "exposure"
    assert event.evidence_outcome == "unknown"
    assert event.evidence_strength == 0.0
    assert event.knowledge_point_coverage_json == {"kp_binary_search": 1.0}
    assert event.knowledge_point_ids_json == ["kp_binary_search"]
    db.add.assert_called_once_with(event)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_practice_activity_records_hint_weight_and_multi_point_coverage():
    db = AsyncMock()
    db.add = Mock()
    db.scalar.return_value = None
    session = SimpleNamespace(
        id="session_001",
        user_id="01900000-0000-7000-8000-000000000001",
        source_type="document",
        agent_thread_id=None,
        agent_run_id=None,
        title="二分查找练习",
    )
    link = SimpleNamespace(
        item_id="item_001",
        question_id="question_001",
        snapshot_json={
            "content": "题面",
            "answer_source": "manual",
            "topic_terms": ["二分查找"],
            "knowledge_point_ids": ["kp-1", "kp-2"],
            "knowledge_point_coverage": {"kp-1": 0.25, "kp-2": 0.75},
        },
    )
    answer = SimpleNamespace(
        user_answer="A",
        is_correct=True,
        saved_at=datetime(2026, 7, 28, 12, 0, 0),
        hint_levels_used_json=["concept"],
    )

    events = await record_practice_submission(
        db,
        session=session,
        rows=[(link, None, answer)],
    )

    assert len(events) == 1
    assert events[0].evidence_type == "hint_assisted"
    assert events[0].evidence_strength == 0.595
    assert events[0].knowledge_point_coverage_json == {"kp-1": 0.25, "kp-2": 0.75}


@pytest.mark.asyncio
async def test_generated_question_records_model_version_and_answer_confidence():
    db = AsyncMock()
    db.add = Mock()
    db.scalar.return_value = None
    session = SimpleNamespace(
        id="session_generated_001",
        user_id="01900000-0000-7000-8000-000000000001",
        source_type="agent",
        agent_thread_id="thread_001",
        agent_run_id="run_generated_001",
        title="诊断检查",
    )
    link = SimpleNamespace(
        item_id="item_generated_001",
        question_id=None,
        snapshot_json={
            "content": "UDP 是否保证可靠交付？",
            "answer_source": "llm",
            "answer_confidence": 0.4,
            "model_version": "question-model-v1",
            "topic_terms": ["UDP"],
            "knowledge_point_ids": ["kp-udp"],
            "provenance": {"source_type": "agent_generated"},
        },
    )
    answer = SimpleNamespace(
        user_answer="A",
        is_correct=False,
        saved_at=datetime(2026, 7, 29, 12, 0, 0),
        hint_levels_used_json=[],
    )

    events = await record_practice_submission(
        db,
        session=session,
        rows=[(link, None, answer)],
    )

    assert len(events) == 1
    event = events[0]
    assert event.assessment_source == "generated_question"
    assert event.model_version == "question-model-v1"
    assert event.evidence_strength == 0.2
    assert (
        event.payload_json["learning_evidence"]["context"]["answer_confidence"] == 0.4
    )


@pytest.mark.asyncio
async def test_agent_grade_activity_preserves_wrong_evidence_for_weakness_projection():
    db = AsyncMock()
    db.add = Mock()
    db.scalar.return_value = None
    run = SimpleNamespace(
        id="run_grade_001",
        user_id="01900000000070008000000000000001",
        thread_id="thread_001",
        metadata_json={
            "context_snapshot": {
                "active_topic": {"title": "二分查找", "aliases": ["折半查找"]}
            }
        },
    )
    artifact = SimpleNamespace(
        id="artifact_grade_001",
        created_at=datetime(2026, 7, 28, 11, 0, 0),
        content_json={
            "content": {
                "overall": "回答错误",
                "weaknesses": ["边界更新条件错误"],
            }
        },
    )

    event = await record_agent_grade_activity(
        db,
        run=run,
        artifact=artifact,
        grading={
            "verdict": "incorrect",
            "evidence_id": "grade-evidence-1",
            "question_id": "generated-question-1",
            "knowledge_point_ids": ["kp-binary"],
            "error_types": ["boundary_condition"],
        },
    )

    assert event is not None
    assert event.source_type == "agent_grade"
    assert event.is_correct is False
    assert event.evidence_type == "objective_assessment"
    assert event.evidence_outcome == "incorrect"
    assert event.assessment_source == "deterministic"
    assert event.evidence_strength == 1.0
    assert event.knowledge_point_coverage_json == {"kp-binary": 1.0}
    assert event.topic_keywords_json == ["二分查找", "折半查找"]
    assert event.payload_json["content"] == "边界更新条件错误"
