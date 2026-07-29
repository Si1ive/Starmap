"""LearningObserver silent Run、非掌握度事实与下一轮诊断快照回归。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.diagnostic import (
    DIAGNOSTIC_CHECK_VERSION,
    schedule_diagnostic_check,
)
from app.modules.agent.learning_observer import schedule_learning_observation
from app.modules.agent.learning_snapshot import load_learning_snapshot_summary
from app.modules.agent.model_runtime.observer import (
    OBSERVER_VERSION,
    TurnObservation,
    TurnObservationOutput,
)
from app.modules.agent.models import (
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMessage,
    AgentRun,
    AgentRunOutbox,
    AgentStep,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
    UserLearningMastery,
)
from app.modules.agent.worker import AgentWorker
from app.modules.learning.models import LearningActivityEvent
from app.modules.identity.models import User

OBSERVER_TABLES = [
    User.__table__,
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentEvent.__table__,
    AgentRunOutbox.__table__,
    AgentCheckpoint.__table__,
    AgentStep.__table__,
    AgentThreadEvent.__table__,
    AgentThreadItem.__table__,
    AgentArtifact.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemorySnapshotItem.__table__,
    UserLearningMastery.__table__,
    LearningActivityEvent.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=OBSERVER_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _completed_conversation(db_session, *, user_message: str):
    user_id = str(uuid.uuid4())
    thread = AgentThread(
        id="thread_observer_001",
        user_id=user_id,
        title="Observer 测试",
        status="active",
    )
    message = AgentMessage(
        id="message_observer_001",
        thread_id=thread.id,
        user_id=user_id,
        role="user",
        status="completed",
        content_text=user_message,
    )
    run = AgentRun(
        id="run_observer_source_001",
        thread_id=thread.id,
        user_id=user_id,
        workflow_name="conversation",
        workflow_key="conversation",
        workflow_version="v1",
        status="completed",
        input_message=user_message,
        trigger_message_id=message.id,
        presentation="silent",
        metadata_json={
            "context_audit": {"selected_message_ids": []},
            "learning_snapshot": {
                "snapshot_id": "source_snapshot_001",
                "active_topic": None,
                "mastery_signals": [],
            },
        },
    )
    db_session.add_all([thread, message])
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    run.root_run_id = run.id
    await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_completed_root_conversation_creates_one_silent_observer_run(db_session):
    source_run = await _completed_conversation(
        db_session,
        user_message="我还是不理解二分查找为什么必须保持循环不变量",
    )

    first = await schedule_learning_observation(db_session, source_run=source_run)
    second = await schedule_learning_observation(db_session, source_run=source_run)

    assert first is not None
    assert second.id == first.id
    assert first.workflow_name == "learning_observation"
    assert first.workflow_version == "v1"
    assert first.presentation == "silent"
    assert first.parent_run_id == source_run.id
    assert first.root_run_id == source_run.id
    assert first.client_idempotency_key == (
        f"observe:{source_run.id}:{OBSERVER_VERSION}"
    )
    assert (
        await db_session.scalar(
            select(func.count(AgentRun.id)).where(
                AgentRun.workflow_name == "learning_observation"
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_explain_then_micro_check_creates_one_validate_child_with_source_link(
    db_session,
):
    source_run = await _completed_conversation(
        db_session,
        user_message="请讲解二分查找的循环不变量",
    )
    source_run.workflow_name = "explain"
    source_run.workflow_key = "explain"
    source_run.metadata_json = {
        "memory_snapshot_id": "source_snapshot_001",
        "context_snapshot": {
            "active_topic": {
                "entity_type": "knowledge_point",
                "entity_id": "kp_binary_search",
                "title": "二分查找",
            },
            "selected_message_ids": [source_run.trigger_message_id],
            "selected_artifact_ids": [],
        },
        "teaching_policy": {
            "policy_version": "conversation-tutor-v1",
            "workflow_action": "explain",
            "teaching_mode": "explain_then_micro_check",
            "target_knowledge_point_ids": ["kp_binary_search"],
            "need_diagnostic_check": True,
            "read_tool_intents": [],
            "reason_codes": ["confusion"],
        },
    }
    artifact = AgentArtifact(
        id="artifact_explain_diagnostic_001",
        run_id=source_run.id,
        artifact_type="explanation",
        content_json={"title": "二分查找讲解", "content": "讲解正文"},
    )
    db_session.add(artifact)
    await db_session.flush()

    first = await schedule_diagnostic_check(
        db_session,
        source_run=source_run,
        source_artifact=artifact,
    )
    second = await schedule_diagnostic_check(
        db_session,
        source_run=source_run,
        source_artifact=artifact,
    )

    assert first is not None
    assert second.id == first.id
    assert first.workflow_name == "validate"
    assert first.parent_run_id == source_run.id
    assert first.presentation == "compact"
    assert first.client_idempotency_key == (
        f"diagnostic:{source_run.id}:{DIAGNOSTIC_CHECK_VERSION}"
    )
    assert first.metadata_json["diagnostic_context"] == {
        "kind": "micro_check",
        "version": DIAGNOSTIC_CHECK_VERSION,
        "source_run_id": source_run.id,
        "source_artifact_id": artifact.id,
        "target_knowledge_point_ids": ["kp_binary_search"],
        "topic_title": "二分查找",
    }
    assert first.metadata_json["teaching_policy"]["workflow_action"] == "validate"
    assert (
        first.metadata_json["teaching_policy"]["teaching_mode"] == "practice_weakness"
    )


@pytest.mark.asyncio
async def test_observer_confusion_is_zero_strength_and_visible_in_next_snapshot(
    db_session,
    monkeypatch,
):
    source_run = await _completed_conversation(
        db_session,
        user_message="我还是不理解二分查找为什么必须保持循环不变量",
    )
    observer_run = await schedule_learning_observation(
        db_session,
        source_run=source_run,
    )
    output = TurnObservationOutput(
        observations=[
            TurnObservation(
                knowledge_point_id=None,
                signal="confusion",
                outcome="unknown",
                error_tags=["concept_gap"],
                model_confidence=0.86,
                diagnostic_need=True,
                source_message_id=source_run.trigger_message_id,
            )
        ],
        public_activity_summary="表达了困惑，建议后续进行一次诊断检查。",
    )
    observe = AsyncMock(return_value=output)
    monkeypatch.setattr(
        "app.modules.agent.workflows.learning_observation."
        "learning_observer_runtime.observe",
        observe,
    )

    assert await AgentWorker().process_run(db_session, observer_run) is True
    assert observer_run.status == "completed"
    assert observer_run.result_artifact_id is None
    assert observer_run.metadata_json["observer_input_snapshot"]["source_message"] == {
        "id": source_run.trigger_message_id,
        "role": "user",
        "content": "我还是不理解二分查找为什么必须保持循环不变量",
    }
    assert (
        observer_run.metadata_json["turn_observation"]["observations"][0][
            "diagnostic_need"
        ]
        is True
    )

    event = await db_session.scalar(
        select(LearningActivityEvent).where(
            LearningActivityEvent.event_type == "agent_turn_observed"
        )
    )
    assert event is not None
    assert event.run_id == observer_run.id
    assert event.source_id == f"{source_run.id}:{OBSERVER_VERSION}"
    assert event.evidence_type == "observation"
    assert event.evidence_outcome == "unknown"
    assert event.evidence_strength == 0.0
    assert event.is_correct is None
    assert event.payload_json["source_run_id"] == source_run.id
    assert event.payload_json["diagnostic_hypotheses"][0]["signal"] == "confusion"
    assert await db_session.scalar(select(func.count(UserLearningMastery.id))) == 0

    next_run = AgentRun(
        id="run_observer_next_001",
        thread_id=source_run.thread_id,
        user_id=source_run.user_id,
        workflow_name="conversation",
        workflow_key="conversation",
        workflow_version="v1",
        status="running",
        input_message="那你先检查一下我哪里没理解",
        presentation="silent",
    )
    db_session.add(next_run)
    await db_session.flush()
    next_run.root_run_id = next_run.id
    snapshot = AgentMemorySnapshot(
        id="snapshot_observer_next_001",
        run_id=next_run.id,
        thread_id=next_run.thread_id,
        user_id=next_run.user_id,
        state_version=2,
        standalone_request=next_run.input_message,
        understanding_json={"raw_input": next_run.input_message},
    )
    db_session.add(snapshot)
    await db_session.flush()

    summary = await load_learning_snapshot_summary(
        db_session,
        snapshot_id=snapshot.id,
        user_id=next_run.user_id,
        thread_id=next_run.thread_id,
    )

    assert len(summary.diagnostic_hypotheses) == 1
    hypothesis = summary.diagnostic_hypotheses[0]
    assert hypothesis["signal"] == "confusion"
    assert hypothesis["diagnostic_need"] is True
    assert hypothesis["source_run_id"] == source_run.id
    frozen = await db_session.scalar(
        select(AgentMemorySnapshotItem).where(
            AgentMemorySnapshotItem.snapshot_id == snapshot.id,
            AgentMemorySnapshotItem.memory_partition == "learning_hypothesis",
        )
    )
    assert frozen is not None
    assert frozen.payload_json == hypothesis


@pytest.mark.asyncio
async def test_observer_failure_does_not_change_completed_source_run(
    db_session,
    monkeypatch,
):
    source_run = await _completed_conversation(
        db_session,
        user_message="二分查找的循环不变量是什么？",
    )
    observer_run = await schedule_learning_observation(
        db_session,
        source_run=source_run,
    )
    monkeypatch.setattr(
        "app.modules.agent.workflows.learning_observation."
        "learning_observer_runtime.observe",
        AsyncMock(side_effect=RuntimeError("observer model unavailable")),
    )

    # Worker 已可靠处理这个 outbox 项，所以返回 True；失败事实留在 silent child。
    assert await AgentWorker().process_run(db_session, observer_run) is True
    assert observer_run.status == "failed"
    assert "observer model unavailable" in observer_run.error_message
    assert source_run.status == "completed"
    assert source_run.error_message is None
    assert await db_session.scalar(select(func.count(LearningActivityEvent.id))) == 0
    assert await db_session.scalar(select(func.count(UserLearningMastery.id))) == 0


def test_turn_observation_forbids_mastery_fields_and_verdicts():
    with pytest.raises(ValidationError, match="mastery_score"):
        TurnObservation.model_validate(
            {
                "signal": "confusion",
                "outcome": "unknown",
                "model_confidence": 0.8,
                "diagnostic_need": True,
                "source_message_id": "message_001",
                "mastery_score": 0.1,
            }
        )

    with pytest.raises(ValidationError, match="outcome"):
        TurnObservation(
            signal="open_response_candidate",
            outcome="correct",
            model_confidence=0.9,
            source_message_id="message_001",
        )
