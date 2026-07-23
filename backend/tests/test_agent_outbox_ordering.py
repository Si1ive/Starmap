"""Agent outbox 的 thread 级 root run tree 顺序测试。"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.models import (
    AgentMessage,
    AgentRun,
    AgentRunOutbox,
    AgentThread,
)
from app.modules.agent.outbox import outbox_store

OUTBOX_TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentRunOutbox.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=OUTBOX_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


def _root_run(
    *,
    run_id: str,
    thread_id: str,
    status: str,
    created_at: datetime,
) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id="user_001",
        workflow_name="conversation",
        workflow_key="conversation",
        workflow_version="v1",
        status=status,
        presentation="silent",
        created_at=created_at,
        updated_at=created_at,
    )


def _outbox(run_id: str, scheduled_at: datetime) -> AgentRunOutbox:
    return AgentRunOutbox(
        run_id=run_id,
        status="pending",
        scheduled_at=scheduled_at,
    )


@pytest.mark.asyncio
async def test_scan_pending_serializes_root_trees_per_thread(db_session):
    now = datetime.utcnow()
    db_session.add_all(
        [
            AgentThread(
                id="thread_001",
                user_id="user_001",
                title="会话一",
                status="active",
            ),
            AgentThread(
                id="thread_002",
                user_id="user_001",
                title="会话二",
                status="active",
            ),
        ]
    )
    await db_session.flush()
    first = _root_run(
        run_id="run_first",
        thread_id="thread_001",
        status="queued",
        created_at=now - timedelta(seconds=3),
    )
    second = _root_run(
        run_id="run_second",
        thread_id="thread_001",
        status="queued",
        created_at=now - timedelta(seconds=2),
    )
    other_thread = _root_run(
        run_id="run_other",
        thread_id="thread_002",
        status="queued",
        created_at=now - timedelta(seconds=1),
    )
    db_session.add_all([first, second, other_thread])
    await db_session.flush()
    first.root_run_id = first.id
    second.root_run_id = second.id
    other_thread.root_run_id = other_thread.id
    db_session.add_all(
        [
            _outbox(first.id, now - timedelta(seconds=3)),
            _outbox(second.id, now - timedelta(seconds=2)),
            _outbox(other_thread.id, now - timedelta(seconds=1)),
        ]
    )
    await db_session.flush()

    pending = await outbox_store.scan_pending(db_session, limit=10)

    assert [item.run_id for item in pending] == ["run_first", "run_other"]


@pytest.mark.asyncio
async def test_active_child_blocks_next_root_until_tree_is_stable(db_session):
    now = datetime.utcnow()
    thread = AgentThread(
        id="thread_001",
        user_id="user_001",
        title="会话",
        status="active",
    )
    first = _root_run(
        run_id="run_first",
        thread_id=thread.id,
        status="completed",
        created_at=now - timedelta(seconds=3),
    )
    child = AgentRun(
        id="run_child",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        workflow_key="validate",
        workflow_version="v1",
        status="queued",
        parent_run_id=first.id,
        root_run_id=first.id,
        presentation="compact",
        created_at=now - timedelta(seconds=2),
        updated_at=now - timedelta(seconds=2),
    )
    second = _root_run(
        run_id="run_second",
        thread_id=thread.id,
        status="queued",
        created_at=now - timedelta(seconds=1),
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add_all([first, second])
    await db_session.flush()
    first.root_run_id = first.id
    second.root_run_id = second.id
    db_session.add(child)
    await db_session.flush()
    db_session.add_all(
        [
            _outbox(child.id, now - timedelta(seconds=2)),
            _outbox(second.id, now - timedelta(seconds=1)),
        ]
    )
    await db_session.flush()

    active_pending = await outbox_store.scan_pending(db_session, limit=10)
    assert [item.run_id for item in active_pending] == ["run_child"]

    child.status = "waiting_for_approval"
    await db_session.flush()
    stable_pending = await outbox_store.scan_pending(db_session, limit=10)
    assert [item.run_id for item in stable_pending] == ["run_second"]
