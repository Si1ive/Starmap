"""偏好候选抽取、用户治理、冲突优先级和 Snapshot 收口。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.memory_outbox import MemoryOutboxConsumer, MemoryOutboxStore
from app.modules.agent.model_runtime.preference_extractor import (
    PREFERENCE_EXTRACTOR_VERSION,
    PreferenceCandidateProposal,
    PreferenceExtractionBatch,
)
from app.modules.agent.models import (
    AgentMemoryItem,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentPreferenceCandidate,
    AgentRun,
    AgentThread,
)
from app.modules.agent.preference_memory import (
    PREFERENCE_EXTRACTION_TASK,
    PreferenceCandidateProjector,
    decide_preference_candidate,
    enqueue_preference_candidate_extraction,
    extract_explicit_preferences,
    load_preference_bundle,
)

TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemorySnapshotItem.__table__,
    AgentMemoryUpdateOutbox.__table__,
    AgentMemoryItem.__table__,
    AgentPreferenceCandidate.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _conversation_run(
    db_session,
    *,
    run_id: str = "run_preference_001",
    thread_id: str = "thread_preference_001",
    user_id: str = "user_001",
    content: str = "我希望以后讲解更详细一些",
):
    thread = await db_session.get(AgentThread, thread_id)
    if thread is None:
        thread = AgentThread(
            id=thread_id,
            user_id=user_id,
            title="偏好治理",
            status="active",
        )
        db_session.add(thread)
        await db_session.flush()
    message = AgentMessage(
        id=f"msg_{run_id}",
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        status="completed",
        content_text=content,
    )
    db_session.add(message)
    await db_session.flush()
    run = AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id=user_id,
        workflow_name="conversation",
        status="completed",
        input_message=content,
        trigger_message_id=message.id,
    )
    db_session.add(run)
    await db_session.flush()
    return thread, message, run


def _candidate(
    *,
    candidate_id: str,
    source_id: str,
    value,
    status: str,
    key: str = "daily_study_minutes",
    user_id: str = "user_001",
    thread_id: str = "thread_preference_001",
    scope: str = "user",
    decided_at: datetime | None = None,
):
    return AgentPreferenceCandidate(
        id=candidate_id,
        user_id=user_id,
        thread_id=thread_id,
        scope=scope,
        source_kind="message",
        source_id=source_id,
        source_version=1,
        preference_key=key,
        preference_value_json={"value": value},
        confidence=0.91,
        status=status,
        extractor_version=PREFERENCE_EXTRACTOR_VERSION,
        model_name="test-preference-model",
        decided_by=user_id if status in {"approved", "rejected"} else None,
        decided_at=decided_at,
    )


@pytest.mark.asyncio
async def test_memory_outbox_extracts_pending_candidates_with_full_provenance(
    db_session,
):
    thread, message, run = await _conversation_run(db_session)
    batch = PreferenceExtractionBatch(
        candidates=(
            PreferenceCandidateProposal(
                preference_key="response_detail",
                value="detailed",
                scope="user",
                confidence=0.95,
            ),
            PreferenceCandidateProposal(
                preference_key="example_style",
                value="code_first",
                scope="thread",
                confidence=0.42,
            ),
        ),
        extractor_version=PREFERENCE_EXTRACTOR_VERSION,
        model_name="test-preference-model-v2",
        model_config_id="model_config_001",
    )
    runtime = SimpleNamespace(extract=AsyncMock(return_value=batch))
    projector = PreferenceCandidateProjector(runtime=runtime)

    await enqueue_preference_candidate_extraction(db_session, run)
    outbox = await db_session.scalar(
        select(AgentMemoryUpdateOutbox).where(
            AgentMemoryUpdateOutbox.run_id == run.id,
            AgentMemoryUpdateOutbox.event_type == PREFERENCE_EXTRACTION_TASK,
        )
    )
    assert outbox is not None
    store = MemoryOutboxStore()
    assert await store.claim(db_session, outbox.id, "preference_worker") is True
    consumer = MemoryOutboxConsumer(
        store=store,
        preference_projector=projector,
    )

    assert (
        await consumer.process_claimed(
            db_session,
            outbox.id,
            "preference_worker",
        )
        is True
    )

    rows = list(
        (
            await db_session.execute(
                select(AgentPreferenceCandidate).order_by(
                    AgentPreferenceCandidate.preference_key
                )
            )
        ).scalars()
    )
    assert len(rows) == 2
    assert {row.status for row in rows} == {"pending"}
    assert {row.confidence for row in rows} == {0.42, 0.95}
    assert {row.scope for row in rows} == {"user", "thread"}
    assert {row.source_kind for row in rows} == {"message"}
    assert {row.source_id for row in rows} == {message.id}
    assert {row.extractor_version for row in rows} == {PREFERENCE_EXTRACTOR_VERSION}
    assert {row.model_name for row in rows} == {"test-preference-model-v2"}
    assert {row.model_config_id for row in rows} == {"model_config_001"}
    await db_session.refresh(run)
    assert run.status == "completed"

    rejected = rows[0]
    assert (
        await decide_preference_candidate(
            db_session,
            candidate_id=rejected.id,
            user_id=thread.user_id,
            decision="rejected",
        )
        is rejected
    )
    await projector.process_outbox(db_session, outbox)
    runtime.extract.assert_awaited_once()
    await db_session.refresh(rejected)
    assert rejected.status == "rejected"


@pytest.mark.asyncio
async def test_candidate_decision_is_user_scoped_and_rejection_is_a_tombstone(
    db_session,
):
    await _conversation_run(db_session)
    approved = _candidate(
        candidate_id="prefcand_approved",
        source_id="msg_candidate_approved",
        value="detailed",
        status="pending",
        key="response_detail",
    )
    rejected = _candidate(
        candidate_id="prefcand_rejected",
        source_id="msg_candidate_rejected",
        value="concise",
        status="pending",
        key="response_detail",
    )
    db_session.add_all([approved, rejected])
    await db_session.flush()

    assert (
        await decide_preference_candidate(
            db_session,
            candidate_id=approved.id,
            user_id="foreign_user",
            decision="approved",
        )
        is None
    )
    decided = await decide_preference_candidate(
        db_session,
        candidate_id=approved.id,
        user_id="user_001",
        decision="approved",
        reason="这是我的长期偏好",
    )
    assert decided is approved
    assert approved.status == "approved"
    assert approved.decided_by == "user_001"
    item = await db_session.scalar(
        select(AgentMemoryItem).where(
            AgentMemoryItem.item_type == "user_preference",
            AgentMemoryItem.status == "active",
        )
    )
    assert item is not None
    assert item.metadata_json["source_candidate_id"] == approved.id
    assert item.metadata_json["preference_value"] == "detailed"
    assert (
        await decide_preference_candidate(
            db_session,
            candidate_id=approved.id,
            user_id="user_001",
            decision="approved",
        )
        is approved
    )

    rejected_decision = await decide_preference_candidate(
        db_session,
        candidate_id=rejected.id,
        user_id="user_001",
        decision="rejected",
    )
    assert rejected_decision is rejected
    assert rejected.status == "rejected"
    assert (
        await decide_preference_candidate(
            db_session,
            candidate_id=rejected.id,
            user_id="user_001",
            decision="approved",
        )
        is None
    )


@pytest.mark.asyncio
async def test_preference_priority_and_snapshot_replay_are_deterministic(db_session):
    thread, message, root_run = await _conversation_run(
        db_session,
        content="每天学习45分钟，帮我制定学习计划",
    )
    snapshot = AgentMemorySnapshot(
        id="snapshot_preference_priority",
        run_id=root_run.id,
        thread_id=thread.id,
        user_id=thread.user_id,
        state_version=1,
        standalone_request=root_run.input_message,
        understanding_json={"raw_input": root_run.input_message},
    )
    plan_run = AgentRun(
        id="run_preference_plan",
        thread_id=thread.id,
        user_id=thread.user_id,
        workflow_name="plan",
        status="running",
        input_message=root_run.input_message,
        trigger_message_id=message.id,
        parent_run_id=root_run.id,
        root_run_id=root_run.id,
        metadata_json={"memory_snapshot_id": snapshot.id},
    )
    now = datetime(2026, 7, 27, 12, 0, 0)
    old_approved = _candidate(
        candidate_id="prefcand_business_old",
        source_id="msg_business_old",
        value=20,
        status="approved",
        decided_at=now - timedelta(days=2),
    )
    new_approved = _candidate(
        candidate_id="prefcand_business_new",
        source_id="msg_business_new",
        value=30,
        status="approved",
        decided_at=now - timedelta(days=1),
    )
    pending = _candidate(
        candidate_id="prefcand_model_pending",
        source_id="msg_model_pending",
        value=90,
        status="pending",
    )
    cross_thread = _candidate(
        candidate_id="prefcand_cross_thread",
        source_id="msg_cross_thread",
        value=120,
        status="approved",
        scope="thread",
        thread_id="thread_preference_other",
        decided_at=now,
    )
    foreign = _candidate(
        candidate_id="prefcand_foreign",
        source_id="msg_foreign",
        value=180,
        status="approved",
        user_id="user_002",
        decided_at=now,
    )
    other_thread = AgentThread(
        id="thread_preference_other",
        user_id=thread.user_id,
        title="其他线程",
        status="active",
    )
    db_session.add(other_thread)
    await db_session.flush()
    db_session.add_all(
        [
            snapshot,
            plan_run,
            old_approved,
            new_approved,
            pending,
            cross_thread,
            foreign,
        ]
    )
    await db_session.flush()

    bundle = await load_preference_bundle(
        db_session,
        run_id=plan_run.id,
        user_id=thread.user_id,
    )

    assert bundle.values == {"daily_study_minutes": 45}
    assert bundle.selected_sources[0].source_priority == "current_turn_explicit"
    dropped = {
        source.source_id: source.dropped_reason for source in bundle.dropped_sources
    }
    assert dropped[new_approved.id] == "overridden_by_current_turn"
    assert dropped[old_approved.id] == "overridden_by_current_turn"
    assert dropped[pending.id] == "pending_user_approval"
    assert cross_thread.id not in dropped
    assert foreign.id not in dropped

    later = _candidate(
        candidate_id="prefcand_business_later",
        source_id="msg_business_later",
        value=60,
        status="approved",
        decided_at=now + timedelta(days=1),
    )
    db_session.add(later)
    snapshot.understanding_json = {"raw_input": "偏好: daily_study_minutes=10"}
    await db_session.flush()

    replayed = await load_preference_bundle(
        db_session,
        run_id=plan_run.id,
        user_id=thread.user_id,
    )
    assert replayed.values == {"daily_study_minutes": 45}
    frozen = list(
        (
            await db_session.execute(
                select(AgentMemorySnapshotItem).where(
                    AgentMemorySnapshotItem.snapshot_id == snapshot.id
                )
            )
        ).scalars()
    )
    assert any(item.source_kind == "preference_selection_marker" for item in frozen)


@pytest.mark.asyncio
async def test_approved_business_event_beats_pending_model_candidate(db_session):
    thread, message, root_run = await _conversation_run(
        db_session,
        run_id="run_preference_business_priority",
        content="帮我制定计划",
    )
    snapshot = AgentMemorySnapshot(
        id="snapshot_preference_business_priority",
        run_id=root_run.id,
        thread_id=thread.id,
        user_id=thread.user_id,
        state_version=1,
        standalone_request=root_run.input_message,
        understanding_json={"raw_input": root_run.input_message},
    )
    plan_run = AgentRun(
        id="run_preference_business_plan",
        thread_id=thread.id,
        user_id=thread.user_id,
        workflow_name="plan",
        status="running",
        input_message=root_run.input_message,
        trigger_message_id=message.id,
        parent_run_id=root_run.id,
        root_run_id=root_run.id,
        metadata_json={"memory_snapshot_id": snapshot.id},
    )
    approved = _candidate(
        candidate_id="prefcand_business_selected",
        source_id="msg_business_selected",
        value=30,
        status="approved",
        decided_at=datetime(2026, 7, 27, 10, 0, 0),
    )
    pending = _candidate(
        candidate_id="prefcand_model_dropped",
        source_id="msg_model_dropped",
        value=90,
        status="pending",
    )
    db_session.add_all([snapshot, plan_run, approved, pending])
    await db_session.flush()

    bundle = await load_preference_bundle(
        db_session,
        run_id=plan_run.id,
        user_id=thread.user_id,
    )

    assert bundle.values == {"daily_study_minutes": 30}
    assert bundle.selected_sources[0].source_id == approved.id
    assert bundle.selected_sources[0].source_priority == "trusted_business_event"
    assert bundle.dropped_sources[0].source_id == pending.id
    assert bundle.dropped_sources[0].dropped_reason == "pending_user_approval"


def test_explicit_preference_parser_only_accepts_bounded_structured_statements():
    assert extract_explicit_preferences(
        "每天学习50分钟，回答时尽量简洁，偏好: include_examples=true"
    ) == {
        "daily_study_minutes": 50,
        "response_detail": "concise",
        "include_examples": True,
    }
    assert extract_explicit_preferences("这次出一道难题，第三章") == {}
    assert extract_explicit_preferences("每天学习9999分钟") == {}


def test_preference_candidate_routes_are_registered():
    from app.modules.agent.router import router

    routes = {(route.path, tuple(route.methods or ())) for route in router.routes}
    assert any(
        path == "/agent/preferences/candidates" and "GET" in methods
        for path, methods in routes
    )
    assert any(
        path == "/agent/preferences/candidates/{candidate_id}/decision"
        and "POST" in methods
        for path, methods in routes
    )
