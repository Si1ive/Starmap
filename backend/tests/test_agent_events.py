"""Tests for agent event store and SSE serialization."""

import json
import asyncio
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.events import (
    EventStore,
    EventPublisher,
    serialize_sse,
    serialize_sse_from_dict,
)
from app.modules.agent.models import AgentEvent, AgentMessage, AgentRun, AgentThread

# Agent tables needed for tests
AGENT_TABLES = [
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentEvent.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite database with agent tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=AGENT_TABLES,
            )
        )
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_thread_and_run(db_session, *, run_id="run_test_001", thread_id="thread_001", user_id="user_001"):
    """Helper to create a thread and run for testing."""
    thread = AgentThread(
        id=thread_id,
        user_id=user_id,
        title="Test Thread",
    )
    db_session.add(thread)
    await db_session.flush()  # Flush thread first to get it in DB
    
    run = AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id=user_id,
        workflow_name="conversation",
        status="queued",
    )
    db_session.add(run)
    await db_session.flush()  # Flush run after thread
    return thread, run


@pytest.mark.asyncio
async def test_append_creates_event_with_incrementing_sequence(db_session):
    """append() should assign monotonically increasing sequence per run."""
    store = EventStore()
    _, run = await _create_thread_and_run(db_session, run_id="run_seq")

    event1 = await store.append(db_session, run.id, "run.created", {"key": "v1"})
    event2 = await store.append(db_session, run.id, "step.started", {"key": "v2"})

    assert event1.sequence == 1
    assert event2.sequence == 2
    assert event1.run_id == run.id
    assert event2.run_id == run.id


@pytest.mark.asyncio
async def test_append_independent_sequences_per_run(db_session):
    """Each run should have its own independent sequence."""
    store = EventStore()
    _, run_a = await _create_thread_and_run(db_session, run_id="run_a", thread_id="thread_a")
    _, run_b = await _create_thread_and_run(db_session, run_id="run_b", thread_id="thread_b")

    await store.append(db_session, run_a.id, "run.created")
    await store.append(db_session, run_b.id, "run.created")
    await store.append(db_session, run_a.id, "step.started")

    assert (await store.get_event_count(db_session, run_a.id)) == 2
    assert (await store.get_event_count(db_session, run_b.id)) == 1


@pytest.mark.asyncio
async def test_get_events_returns_events_after_sequence(db_session):
    """get_events() should return events after the specified sequence."""
    store = EventStore()
    _, run = await _create_thread_and_run(db_session, run_id="run_get")

    await store.append(db_session, run.id, "run.created")
    await store.append(db_session, run.id, "step.started")
    await store.append(db_session, run.id, "step.completed")

    events = await store.get_events(db_session, run.id, after_sequence=1)

    assert len(events) == 2
    assert events[0].event_type == "step.started"
    assert events[0].sequence == 2
    assert events[1].event_type == "step.completed"
    assert events[1].sequence == 3


@pytest.mark.asyncio
async def test_get_events_with_default_sequence_returns_all(db_session):
    """get_events() with default after_sequence=0 should return all events."""
    store = EventStore()
    _, run = await _create_thread_and_run(db_session, run_id="run_all")

    await store.append(db_session, run.id, "run.created")
    await store.append(db_session, run.id, "step.started")

    events = await store.get_events(db_session, run.id)

    assert len(events) == 2
    assert events[0].sequence == 1
    assert events[1].sequence == 2


@pytest.mark.asyncio
async def test_get_events_empty_run_returns_empty(db_session):
    """get_events() for a run with no events should return empty list."""
    store = EventStore()
    _, run = await _create_thread_and_run(db_session, run_id="run_empty")

    events = await store.get_events(db_session, run.id)

    assert events == []


@pytest.mark.asyncio
async def test_get_event_count(db_session):
    """get_event_count() should return the correct number of events."""
    store = EventStore()
    _, run = await _create_thread_and_run(db_session, run_id="run_count")

    assert await store.get_event_count(db_session, run.id) == 0
    await store.append(db_session, run.id, "run.created")
    assert await store.get_event_count(db_session, run.id) == 1
    await store.append(db_session, run.id, "step.started")
    assert await store.get_event_count(db_session, run.id) == 2


class TestSerializeSSE:
    """Tests for SSE serialization helpers."""

    def test_serialize_sse_from_agent_event(self):
        """serialize_sse() should produce valid SSE format from an AgentEvent."""
        event = AgentEvent(
            id=1,
            run_id="run_1",
            sequence=5,
            event_type="message.completed",
            payload={"content": "hello"},
        )
        result = serialize_sse(event)
        lines = result.strip().split("\n")

        assert "id: 5" in lines
        assert "event: message.completed" in lines
        assert 'data: {"content": "hello"}' in lines

    def test_serialize_sse_from_dict(self):
        """serialize_sse_from_dict() should produce valid SSE format from a dict."""
        result = serialize_sse_from_dict(10, "run.status_changed", {"status": "running"})
        lines = result.strip().split("\n")

        assert "id: 10" in lines
        assert "event: run.status_changed" in lines
        assert 'data: {"status": "running"}' in lines


class TestEventPublisher:
    """Tests for EventPublisher in-memory pub/sub."""

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self):
        """Publisher should deliver events to all subscribed queues."""
        pub = EventPublisher()
        queue = asyncio.Queue()

        pub.subscribe("run_1", queue)
        await pub.publish("run_1", {("type", "test"), ("data", "hello")})

        event = await asyncio.wait_for(queue.get(), timeout=0.5)
        assert event == {("type", "test"), ("data", "hello")}

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self):
        """After unsubscribe, events should not be delivered."""
        pub = EventPublisher()
        queue = asyncio.Queue()

        pub.subscribe("run_2", queue)
        pub.unsubscribe("run_2", queue)
        await pub.publish("run_2", {"type": "test"})

        # Queue should be empty after a brief wait
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_publish_does_not_cross_runs(self):
        """Events for one run should not be sent to subscribers of another run."""
        pub = EventPublisher()
        queue_a = asyncio.Queue()
        queue_b = asyncio.Queue()

        pub.subscribe("run_a", queue_a)
        pub.subscribe("run_b", queue_b)
        await pub.publish("run_a", {"type": "a"})

        event_a = await asyncio.wait_for(queue_a.get(), timeout=0.5)
        assert event_a == {"type": "a"}
        assert queue_b.empty()

    @pytest.mark.asyncio
    async def test_publish_to_run_without_subscribers_is_safe(self):
        """Publishing to a run with no subscribers should not raise."""
        pub = EventPublisher()
        # Should not raise
        await pub.publish("run_no_subscribers", {"type": "test"})
