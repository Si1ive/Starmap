"""Agent 记忆向量生成、召回、版本替换与失败隔离。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.memory_contracts import MemoryNeed
from app.modules.agent.memory_item_projection import project_trusted_memory_event
from app.modules.agent.memory_outbox import MemoryOutboxConsumer, MemoryOutboxStore
from app.modules.agent.memory_vector import (
    MEMORY_VECTOR_COLLECTION,
    MemoryVectorLifecycle,
    memory_item_vector_task_type,
    memory_vector_point_id,
    summary_vector_task_type,
)
from app.modules.agent.models import (
    AgentConversationSummary,
    AgentMemoryEvent,
    AgentMemoryItem,
    AgentMessage,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMemoryUpdateOutbox,
    AgentRun,
    AgentThread,
)

TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemorySnapshotItem.__table__,
    AgentMemoryEvent.__table__,
    AgentMemoryUpdateOutbox.__table__,
    AgentConversationSummary.__table__,
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
                tables=TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


class QdrantStub:
    def __init__(self):
        self.client = SimpleNamespace(
            create_payload_index=Mock(),
            delete=Mock(),
            get_collections=Mock(
                return_value=SimpleNamespace(
                    collections=[SimpleNamespace(name=MEMORY_VECTOR_COLLECTION)]
                )
            ),
        )
        self.ensure_collection = Mock()
        self.upsert_points = Mock()
        self.search = Mock(return_value=[])


def _lifecycle(qdrant: QdrantStub) -> MemoryVectorLifecycle:
    embedding = SimpleNamespace(
        dimension=2,
        embed_text=AsyncMock(return_value=[0.1, 0.2]),
    )

    async def embedding_factory(_db):
        return embedding

    lifecycle = MemoryVectorLifecycle(
        qdrant=qdrant,
        embedding_factory=embedding_factory,
    )
    lifecycle.embedding = embedding
    return lifecycle


async def _thread_and_run(db_session, *, run_id: str = "run_vector_001"):
    thread = await db_session.get(AgentThread, "thread_vector_001")
    if thread is None:
        thread = AgentThread(
            id="thread_vector_001",
            user_id="user_001",
            title="向量记忆",
            status="active",
        )
        db_session.add(thread)
        await db_session.flush()
    run = AgentRun(
        id=run_id,
        thread_id=thread.id,
        user_id=thread.user_id,
        workflow_name="conversation",
        status="completed",
    )
    db_session.add(run)
    await db_session.flush()
    return thread, run


@pytest.mark.asyncio
async def test_summary_vector_upsert_then_deletes_superseded_point(db_session):
    thread, run = await _thread_and_run(db_session)
    summary = AgentConversationSummary(
        id="summary_vector_v2",
        thread_id=thread.id,
        user_id=thread.user_id,
        start_sequence=1,
        end_sequence=20,
        summary_text="用户在复习二分查找的边界条件。",
        source_message_ids_json=["msg_001"],
        version=2,
    )
    db_session.add(summary)
    await db_session.flush()
    task_type = summary_vector_task_type(2)
    outbox = AgentMemoryUpdateOutbox(
        run_id=run.id,
        thread_id=thread.id,
        user_id=thread.user_id,
        event_type=task_type,
        status="processing",
        worker_id="memory_worker_1",
        payload_json={
            "task_type": task_type,
            "source_kind": "conversation_summary",
            "source_id": summary.id,
            "source_version": 2,
            "delete_sources": [
                {
                    "source_kind": "conversation_summary",
                    "source_id": "summary_vector_v1",
                    "source_version": 1,
                }
            ],
        },
    )
    db_session.add(outbox)
    await db_session.flush()
    qdrant = QdrantStub()
    lifecycle = _lifecycle(qdrant)

    await lifecycle.process_outbox(db_session, outbox)

    lifecycle.embedding.embed_text.assert_awaited_once_with(summary.summary_text)
    points = qdrant.upsert_points.call_args.args[1]
    assert qdrant.upsert_points.call_args.args[0] == MEMORY_VECTOR_COLLECTION
    assert len(points) == 1
    assert str(points[0].id) == memory_vector_point_id(
        "conversation_summary",
        summary.id,
        2,
    )
    assert points[0].payload == {
        "user_id": "user_001",
        "thread_id": "thread_vector_001",
        "scope": "thread",
        "memory_partition": "topic_summary",
        "source_kind": "conversation_summary",
        "source_id": summary.id,
        "source_version": 2,
        "status": "active",
    }
    assert "content_text" not in points[0].payload
    deleted = qdrant.client.delete.call_args.kwargs["points_selector"].points
    assert deleted == [
        memory_vector_point_id("conversation_summary", "summary_vector_v1", 1)
    ]


@pytest.mark.asyncio
async def test_vector_recall_rechecks_scope_version_and_freezes_snapshot(db_session):
    thread, run = await _thread_and_run(db_session)
    item = AgentMemoryItem(
        id="memory_item_vector_001",
        user_id=thread.user_id,
        thread_id=thread.id,
        scope="thread",
        item_type="topic_context",
        item_key="topic_confirmed:vector",
        status="active",
        content_text="二分查找需要有序表。",
        metadata_json={"source_memory_event_id": 7},
        last_confirmed_run_id=run.id,
    )
    snapshot = AgentMemorySnapshot(
        id="snapshot_vector_recall",
        run_id=run.id,
        thread_id=thread.id,
        user_id=thread.user_id,
        state_version=1,
        standalone_request="继续复习二分查找",
        understanding_json={},
    )
    db_session.add_all([item, snapshot])
    await db_session.flush()
    qdrant = QdrantStub()
    valid_payload = {
        "user_id": thread.user_id,
        "thread_id": thread.id,
        "scope": "thread",
        "memory_partition": "thread_topic_state",
        "source_kind": "memory_item",
        "source_id": item.id,
        "source_version": 7,
        "status": "active",
    }
    qdrant.search.return_value = [
        {"id": "point_valid", "score": 0.91, "payload": valid_payload},
        {
            "id": "point_foreign",
            "score": 0.99,
            "payload": {**valid_payload, "user_id": "user_002"},
        },
        {
            "id": "point_stale",
            "score": 0.95,
            "payload": {**valid_payload, "source_version": 6},
        },
    ]
    lifecycle = _lifecycle(qdrant)

    hits = await lifecycle.recall_for_snapshot(
        db_session,
        snapshot_id=snapshot.id,
        memory_need=MemoryNeed.CONVERSATION_CONTINUITY,
        query="二分查找",
        user_id=thread.user_id,
        thread_id=thread.id,
        memory_partitions=["thread_topic_state"],
    )

    assert [(hit.source_id, hit.source_version) for hit in hits] == [(item.id, 7)]
    frozen = await db_session.scalar(
        select(AgentMemorySnapshotItem).where(
            AgentMemorySnapshotItem.snapshot_id == snapshot.id,
            AgentMemorySnapshotItem.selection_reason == "semantic_vector_recall",
        )
    )
    assert frozen is not None
    assert frozen.payload_json["content_text"] == "二分查找需要有序表。"
    item.content_text = "当前来源已经被改写。"
    item.metadata_json = {"source_memory_event_id": 8}
    await db_session.flush()
    qdrant.search.side_effect = AssertionError("Snapshot 重放不应再次访问 Qdrant")

    replayed = await lifecycle.recall_for_snapshot(
        db_session,
        snapshot_id=snapshot.id,
        memory_need=MemoryNeed.CONVERSATION_CONTINUITY,
        query="任意新查询",
        user_id=thread.user_id,
        thread_id=thread.id,
        memory_partitions=["thread_topic_state"],
    )
    assert replayed[0].content_text == "二分查找需要有序表。"
    assert qdrant.search.call_count == 1


@pytest.mark.asyncio
async def test_topic_projection_supersedes_item_and_enqueues_vector_delete(db_session):
    thread, first_run = await _thread_and_run(db_session, run_id="run_topic_vector_1")
    first_event = AgentMemoryEvent(
        user_id=thread.user_id,
        thread_id=thread.id,
        run_id=first_run.id,
        memory_scope="thread",
        source_kind="message",
        fact_type="topic_confirmed",
        idempotency_key="topic_confirmed:vector:1",
        payload_json={"topic": {"title": "二分查找"}},
    )
    db_session.add(first_event)
    await db_session.flush()
    await project_trusted_memory_event(db_session, first_event)
    second_run = AgentRun(
        id="run_topic_vector_2",
        thread_id=thread.id,
        user_id=thread.user_id,
        workflow_name="conversation",
        status="completed",
    )
    db_session.add(second_run)
    await db_session.flush()
    second_event = AgentMemoryEvent(
        user_id=thread.user_id,
        thread_id=thread.id,
        run_id=second_run.id,
        memory_scope="thread",
        source_kind="message",
        fact_type="topic_confirmed",
        idempotency_key="topic_confirmed:vector:2",
        payload_json={"topic": {"title": "红黑树"}},
    )
    db_session.add(second_event)
    await db_session.flush()

    await project_trusted_memory_event(db_session, second_event)

    items = list(
        (
            await db_session.execute(
                select(AgentMemoryItem).order_by(AgentMemoryItem.id)
            )
        ).scalars()
    )
    items_by_version = {
        item.metadata_json["source_memory_event_id"]: item for item in items
    }
    first_item = items_by_version[first_event.id]
    second_item = items_by_version[second_event.id]
    assert first_item.status == "superseded"
    assert second_item.status == "active"
    task = await db_session.scalar(
        select(AgentMemoryUpdateOutbox).where(
            AgentMemoryUpdateOutbox.run_id == second_run.id,
            AgentMemoryUpdateOutbox.event_type
            == memory_item_vector_task_type(second_event.id),
        )
    )
    assert task is not None
    assert task.payload_json["source_id"] == second_item.id
    assert task.payload_json["delete_sources"] == [
        {
            "source_kind": "memory_item",
            "source_id": first_item.id,
            "source_version": first_event.id,
        }
    ]


@pytest.mark.asyncio
async def test_vector_failure_retries_without_failing_completed_run(db_session):
    thread, run = await _thread_and_run(db_session, run_id="run_vector_failure")
    task_type = summary_vector_task_type(1)
    outbox = AgentMemoryUpdateOutbox(
        run_id=run.id,
        thread_id=thread.id,
        user_id=thread.user_id,
        event_type=task_type,
        status="pending",
        payload_json={
            "task_type": task_type,
            "source_kind": "conversation_summary",
            "source_id": "summary_missing",
            "source_version": 1,
            "delete_sources": [],
        },
    )
    db_session.add(outbox)
    await db_session.flush()
    vector_lifecycle = SimpleNamespace(
        process_outbox=AsyncMock(side_effect=RuntimeError("qdrant unavailable"))
    )
    store = MemoryOutboxStore()
    assert await store.claim(db_session, outbox.id, "memory_worker_1") is True
    consumer = MemoryOutboxConsumer(
        store=store,
        vector_lifecycle=vector_lifecycle,
        retry_delay_seconds=1,
    )

    assert (
        await consumer.process_claimed(
            db_session,
            outbox.id,
            "memory_worker_1",
        )
        is False
    )

    await db_session.refresh(run)
    await db_session.refresh(outbox)
    assert run.status == "completed"
    assert outbox.status == "pending"
    assert outbox.retry_count == 1


@pytest.mark.asyncio
async def test_stale_source_delete_succeeds_when_collection_does_not_exist(db_session):
    thread, run = await _thread_and_run(db_session, run_id="run_vector_delete_absent")
    task_type = summary_vector_task_type(1)
    outbox = AgentMemoryUpdateOutbox(
        run_id=run.id,
        thread_id=thread.id,
        user_id=thread.user_id,
        event_type=task_type,
        status="processing",
        worker_id="memory_worker_1",
        payload_json={
            "task_type": task_type,
            "source_kind": "conversation_summary",
            "source_id": "summary_already_deleted",
            "source_version": 1,
            "delete_sources": [],
        },
    )
    db_session.add(outbox)
    await db_session.flush()
    qdrant = QdrantStub()
    qdrant.client.get_collections.return_value = SimpleNamespace(collections=[])
    lifecycle = _lifecycle(qdrant)

    await lifecycle.process_outbox(db_session, outbox)

    lifecycle.embedding.embed_text.assert_not_awaited()
    qdrant.client.delete.assert_not_called()
