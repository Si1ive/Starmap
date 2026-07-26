"""Memory Outbox 消费者的认领、租约、重试与事务隔离测试。"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.memory_outbox import (
    MemoryOutboxConsumer,
    MemoryOutboxStore,
)
from app.modules.agent.memory_item_projection import project_trusted_memory_event
from app.modules.agent.models import (
    AgentArtifact,
    AgentMemoryEvent,
    AgentMemoryItem,
    AgentMemorySnapshot,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentRun,
    AgentThread,
)
from app.modules.agent.time_utils import utc_now


MEMORY_OUTBOX_TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentArtifact.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemoryEvent.__table__,
    AgentMemoryUpdateOutbox.__table__,
    AgentMemoryItem.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=MEMORY_OUTBOX_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_memory_task(db_session, *, outbox_id: int = 1):
    thread = AgentThread(
        id="thread_memory_outbox_001",
        user_id="user_001",
        title="Memory Outbox 测试",
        status="active",
    )
    run = AgentRun(
        id="run_memory_outbox_001",
        thread_id=thread.id,
        user_id=thread.user_id,
        workflow_name="conversation",
        workflow_key="conversation",
        workflow_version="v1",
        status="completed",
        input_message="讲解二分查找",
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    event = AgentMemoryEvent(
        user_id=run.user_id,
        thread_id=run.thread_id,
        run_id=run.id,
        memory_scope="thread",
        source_kind="message",
        fact_type="topic_confirmed",
        idempotency_key=f"topic_confirmed:{run.id}",
        payload_json={"topic": {"title": "二分查找"}},
    )
    db_session.add(event)
    await db_session.flush()
    outbox = AgentMemoryUpdateOutbox(
        id=outbox_id,
        run_id=run.id,
        thread_id=run.thread_id,
        user_id=run.user_id,
        event_type=event.fact_type,
        status="pending",
        payload_json={
            "memory_event_id": event.id,
            "fact_type": event.fact_type,
        },
    )
    db_session.add(outbox)
    await db_session.flush()
    return run, event, outbox


@pytest.mark.asyncio
async def test_claim_is_atomic_and_recovers_expired_processing_task(db_session):
    _, _, outbox = await _create_memory_task(db_session)
    store = MemoryOutboxStore()

    due = await store.scan_due(db_session, limit=10)
    assert [item.id for item in due] == [outbox.id]
    assert await store.claim(db_session, outbox.id, "memory_worker_1") is True
    assert await store.claim(db_session, outbox.id, "memory_worker_2") is False

    outbox.scheduled_at = utc_now() - timedelta(seconds=1)
    await db_session.flush()

    assert await store.claim(db_session, outbox.id, "memory_worker_2") is True
    await db_session.refresh(outbox)
    assert outbox.status == "processing"
    assert outbox.worker_id == "memory_worker_2"
    assert outbox.retry_count == 1
    assert outbox.scheduled_at > utc_now()
    assert await store.complete(db_session, outbox.id, "memory_worker_1") is False

    outbox.retry_count = 3
    outbox.scheduled_at = utc_now() - timedelta(seconds=1)
    await db_session.flush()

    assert await store.claim(db_session, outbox.id, "memory_worker_3") is False
    await db_session.refresh(outbox)
    assert outbox.status == "failed"
    assert outbox.worker_id == "memory_worker_2"
    assert outbox.processed_at is not None


@pytest.mark.asyncio
async def test_consumer_completes_once_and_replay_does_not_project_twice(db_session):
    _, event, outbox = await _create_memory_task(db_session)
    store = MemoryOutboxStore()

    assert await store.claim(db_session, outbox.id, "memory_worker_1") is True
    consumer = MemoryOutboxConsumer(store=store)
    assert await consumer.process_claimed(
        db_session,
        outbox.id,
        "memory_worker_1",
    ) is True
    assert await consumer.process_claimed(
        db_session,
        outbox.id,
        "memory_worker_1",
    ) is False

    await db_session.refresh(outbox)
    assert outbox.status == "completed"
    assert outbox.worker_id == "memory_worker_1"
    assert outbox.processed_at is not None
    items = list((await db_session.execute(select(AgentMemoryItem))).scalars())
    assert len(items) == 1
    assert items[0].scope == "thread"
    assert items[0].thread_id == outbox.thread_id
    assert items[0].item_type == "topic_context"
    assert items[0].item_key == event.idempotency_key
    assert items[0].content_text == "二分查找"
    assert items[0].metadata_json == {
        "source_memory_event_id": event.id,
        "fact_type": "topic_confirmed",
        "entity_type": None,
        "entity_id": None,
        "aliases": [],
    }
    await project_trusted_memory_event(db_session, event)
    replayed_items = list(
        (await db_session.execute(select(AgentMemoryItem))).scalars()
    )
    assert len(replayed_items) == 1


@pytest.mark.asyncio
async def test_consumer_projects_confirmed_plan_to_user_goal(db_session):
    _, event, outbox = await _create_memory_task(db_session)
    artifact = AgentArtifact(
        id="art_plan_memory_001",
        run_id=outbox.run_id,
        artifact_type="plan",
        content_json={
            "type": "plan",
            "approval_id": "approval_plan_001",
            "title": "数据结构复习计划",
            "content": {
                "period": "7天",
                "goals": [
                    {
                        "subject": "二叉树",
                        "target": "掌握遍历",
                        "daily_minutes": 30,
                    }
                ],
                "schedule": [],
            },
            "summary": "包含 1 个目标",
        },
    )
    db_session.add(artifact)
    event.memory_scope = "user"
    event.source_kind = "artifact"
    event.fact_type = "plan_confirmed"
    event.idempotency_key = "plan_confirmed:approval_plan_001"
    event.payload_json = {
        "artifact_id": artifact.id,
        "approval_id": "approval_plan_001",
        "memory_snapshot_id": None,
    }
    outbox.event_type = event.fact_type
    outbox.payload_json = {
        "memory_event_id": event.id,
        "fact_type": event.fact_type,
    }
    await db_session.flush()

    store = MemoryOutboxStore()
    assert await store.claim(db_session, outbox.id, "memory_worker_1") is True
    assert await MemoryOutboxConsumer(store=store).process_claimed(
        db_session,
        outbox.id,
        "memory_worker_1",
    ) is True

    item = await db_session.scalar(select(AgentMemoryItem))
    assert item is not None
    assert item.scope == "user"
    assert item.thread_id is None
    assert item.item_type == "learning_goal"
    assert item.item_key == event.idempotency_key
    assert item.content_text == "数据结构复习计划\n二叉树：掌握遍历"
    assert item.metadata_json == {
        "source_memory_event_id": event.id,
        "fact_type": "plan_confirmed",
        "artifact_id": artifact.id,
        "approval_id": "approval_plan_001",
        "period": "7天",
        "goal_count": 1,
    }


@pytest.mark.asyncio
async def test_projection_failure_retries_without_changing_completed_run(db_session):
    run, _, outbox = await _create_memory_task(db_session)
    store = MemoryOutboxStore()

    async def failing_projector(db, _memory_event):
        persisted_run = await db.get(AgentRun, run.id)
        persisted_run.status = "failed"
        raise RuntimeError("embedding service unavailable")

    assert await store.claim(db_session, outbox.id, "memory_worker_1") is True
    consumer = MemoryOutboxConsumer(
        store=store,
        projector=failing_projector,
        retry_delay_seconds=45,
        max_retries=3,
    )
    assert await consumer.process_claimed(
        db_session,
        outbox.id,
        "memory_worker_1",
    ) is False

    await db_session.refresh(run)
    await db_session.refresh(outbox)
    assert run.status == "completed"
    assert outbox.status == "pending"
    assert outbox.retry_count == 1
    assert outbox.worker_id is None
    assert outbox.scheduled_at > utc_now() + timedelta(seconds=40)
    assert outbox.processed_at is None


@pytest.mark.asyncio
async def test_consumer_marks_task_failed_after_retry_budget_is_exhausted(db_session):
    _, _, outbox = await _create_memory_task(db_session)
    outbox.retry_count = 2
    store = MemoryOutboxStore()

    async def failing_projector(_db, _memory_event):
        raise RuntimeError("permanent projection failure")

    assert await store.claim(db_session, outbox.id, "memory_worker_1") is True
    consumer = MemoryOutboxConsumer(
        store=store,
        projector=failing_projector,
        max_retries=3,
    )
    assert await consumer.process_claimed(
        db_session,
        outbox.id,
        "memory_worker_1",
    ) is False

    await db_session.refresh(outbox)
    assert outbox.status == "failed"
    assert outbox.retry_count == 3
    assert outbox.worker_id == "memory_worker_1"
    assert outbox.processed_at is not None
    assert await store.scan_due(db_session, limit=10) == []
