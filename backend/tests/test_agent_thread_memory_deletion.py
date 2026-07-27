"""删除线程时的分层记忆失效、保留边界和向量重试。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.memory_outbox import MemoryOutboxConsumer, MemoryOutboxStore
from app.modules.agent.memory_vector import (
    MEMORY_VECTOR_COLLECTION,
    MemoryVectorLifecycle,
    memory_vector_point_id,
)
from app.modules.agent.models import (
    AgentConversationSummary,
    AgentMemoryItem,
    AgentMessage,
    AgentMemorySnapshot,
    AgentMemoryUpdateOutbox,
    AgentPreferenceCandidate,
    AgentRun,
    AgentThread,
    AgentThreadMemoryState,
    UserLearningMastery,
)
from app.modules.agent.thread_memory_deletion import (
    THREAD_MEMORY_DELETE_TASK,
    ThreadMemoryDeletionProcessor,
    delete_thread_memory,
)

TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentMemorySnapshot.__table__,
    AgentThreadMemoryState.__table__,
    AgentConversationSummary.__table__,
    AgentMemoryItem.__table__,
    AgentPreferenceCandidate.__table__,
    UserLearningMastery.__table__,
    AgentMemoryUpdateOutbox.__table__,
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
            get_collections=Mock(
                return_value=SimpleNamespace(
                    collections=[SimpleNamespace(name=MEMORY_VECTOR_COLLECTION)]
                )
            ),
            delete=Mock(),
        )


async def _seed_thread_memory(db_session):
    thread = AgentThread(
        id="thread_delete_001",
        user_id="user_001",
        title="待删除线程",
        status="active",
    )
    other_thread = AgentThread(
        id="thread_delete_other",
        user_id="user_001",
        title="保留线程",
        status="active",
    )
    foreign_thread = AgentThread(
        id="thread_delete_foreign",
        user_id="user_002",
        title="其他用户线程",
        status="active",
    )
    db_session.add_all([thread, other_thread, foreign_thread])
    await db_session.flush()
    run = AgentRun(
        id="run_thread_delete_001",
        thread_id=thread.id,
        user_id=thread.user_id,
        workflow_name="conversation",
        status="completed",
    )
    db_session.add(run)
    await db_session.flush()
    state = AgentThreadMemoryState(
        thread_id=thread.id,
        user_id=thread.user_id,
        version=3,
        active_topic_json={"title": "二分查找"},
        latest_understanding_run_id=run.id,
    )
    summary = AgentConversationSummary(
        id="summary_thread_delete",
        thread_id=thread.id,
        user_id=thread.user_id,
        start_sequence=1,
        end_sequence=10,
        summary_text="待删除摘要",
        source_message_ids_json=["msg_delete_001"],
        version=2,
    )
    topic_item = AgentMemoryItem(
        id="memory_thread_topic_delete",
        user_id=thread.user_id,
        thread_id=thread.id,
        scope="thread",
        item_type="topic_context",
        item_key="topic:delete",
        status="active",
        content_text="二分查找",
        metadata_json={"source_memory_event_id": 7},
        last_confirmed_run_id=run.id,
    )
    user_preference = AgentMemoryItem(
        id="memory_user_preference_delete",
        user_id=thread.user_id,
        scope="user",
        item_type="user_preference",
        item_key="preference:detail",
        status="active",
        content_text="response_detail=detailed",
        metadata_json={"source_thread_id": thread.id},
    )
    user_goal = AgentMemoryItem(
        id="memory_user_goal_keep",
        user_id=thread.user_id,
        scope="user",
        item_type="learning_goal",
        item_key="goal:approved",
        status="active",
        content_text="用户批准的独立目标",
        metadata_json={"source_thread_id": thread.id},
    )
    other_item = AgentMemoryItem(
        id="memory_other_thread_keep",
        user_id=thread.user_id,
        thread_id=other_thread.id,
        scope="thread",
        item_type="topic_context",
        item_key="topic:keep",
        status="active",
        content_text="红黑树",
        metadata_json={"source_memory_event_id": 9},
    )
    candidate = AgentPreferenceCandidate(
        id="prefcand_thread_delete",
        user_id=thread.user_id,
        thread_id=thread.id,
        run_id=run.id,
        scope="user",
        source_kind="message",
        source_id="msg_delete_001",
        source_version=1,
        preference_key="response_detail",
        preference_value_json={"value": "detailed"},
        confidence=0.9,
        status="approved",
        extractor_version="preference-extractor-v1",
        model_name="test-model",
    )
    mastery = UserLearningMastery(
        user_id=thread.user_id,
        subject_id="subject_ds",
        knowledge_point_id="kp_binary_search",
        mastery_score=0.7,
        evidence_count=2,
    )
    db_session.add_all(
        [
            state,
            summary,
            topic_item,
            user_preference,
            user_goal,
            other_item,
            candidate,
            mastery,
        ]
    )
    await db_session.flush()
    return {
        "thread": thread,
        "state": state,
        "summary": summary,
        "topic_item": topic_item,
        "user_preference": user_preference,
        "user_goal": user_goal,
        "other_item": other_item,
        "candidate": candidate,
        "mastery": mastery,
    }


@pytest.mark.asyncio
async def test_delete_thread_invalidates_scoped_memory_and_retries_vector_delete(
    db_session,
):
    seeded = await _seed_thread_memory(db_session)

    deleted = await delete_thread_memory(
        db_session,
        thread_id=seeded["thread"].id,
        user_id=seeded["thread"].user_id,
    )

    assert deleted is seeded["thread"]
    assert deleted.status == "deleted"
    assert await db_session.get(AgentThreadMemoryState, seeded["state"].id) is None
    assert seeded["summary"].superseded_by_id == seeded["summary"].id
    assert seeded["topic_item"].status == "deleted"
    assert seeded["user_preference"].status == "deleted"
    assert seeded["candidate"].status == "invalidated"
    assert seeded["user_goal"].status == "active"
    assert seeded["other_item"].status == "active"
    assert (
        await db_session.get(UserLearningMastery, seeded["mastery"].id)
        is seeded["mastery"]
    )

    task = await db_session.scalar(
        select(AgentMemoryUpdateOutbox).where(
            AgentMemoryUpdateOutbox.event_type == THREAD_MEMORY_DELETE_TASK
        )
    )
    assert task is not None
    assert task.run_id is None
    assert task.task_key == (f"thread_memory_delete:{deleted.user_id}:{deleted.id}")
    assert task.payload_json["delete_sources"] == [
        {
            "source_kind": "conversation_summary",
            "source_id": seeded["summary"].id,
            "source_version": 2,
        },
        {
            "source_kind": "memory_item",
            "source_id": seeded["topic_item"].id,
            "source_version": 7,
        },
    ]

    qdrant = QdrantStub()
    qdrant.client.delete.side_effect = RuntimeError("qdrant unavailable")
    processor = ThreadMemoryDeletionProcessor(
        vector_lifecycle=MemoryVectorLifecycle(qdrant=qdrant)
    )
    store = MemoryOutboxStore()
    assert await store.claim(db_session, task.id, "thread_delete_worker") is True
    consumer = MemoryOutboxConsumer(
        store=store,
        thread_deletion_processor=processor,
        retry_delay_seconds=0,
    )
    assert (
        await consumer.process_claimed(
            db_session,
            task.id,
            "thread_delete_worker",
        )
        is False
    )
    await db_session.refresh(task)
    assert task.status == "pending"
    assert task.retry_count == 1
    assert seeded["topic_item"].status == "deleted"

    qdrant.client.delete.side_effect = None
    assert await store.claim(db_session, task.id, "thread_delete_worker_2") is True
    assert (
        await consumer.process_claimed(
            db_session,
            task.id,
            "thread_delete_worker_2",
        )
        is True
    )
    deleted_points = qdrant.client.delete.call_args.kwargs["points_selector"].points
    assert deleted_points == [
        memory_vector_point_id("conversation_summary", seeded["summary"].id, 2),
        memory_vector_point_id("memory_item", seeded["topic_item"].id, 7),
    ]


@pytest.mark.asyncio
async def test_delete_thread_is_idempotent_and_user_scoped(db_session):
    seeded = await _seed_thread_memory(db_session)

    assert (
        await delete_thread_memory(
            db_session,
            thread_id=seeded["thread"].id,
            user_id="user_002",
        )
        is None
    )
    first = await delete_thread_memory(
        db_session,
        thread_id=seeded["thread"].id,
        user_id=seeded["thread"].user_id,
    )
    second = await delete_thread_memory(
        db_session,
        thread_id=seeded["thread"].id,
        user_id=seeded["thread"].user_id,
    )

    assert first is second is seeded["thread"]
    tasks = list(
        (
            await db_session.execute(
                select(AgentMemoryUpdateOutbox).where(
                    AgentMemoryUpdateOutbox.event_type == THREAD_MEMORY_DELETE_TASK
                )
            )
        ).scalars()
    )
    assert len(tasks) == 1


def test_thread_delete_route_is_registered():
    from app.modules.agent.router import router

    assert any(
        route.path == "/agent/threads/{thread_id}" and "DELETE" in (route.methods or ())
        for route in router.routes
    )
