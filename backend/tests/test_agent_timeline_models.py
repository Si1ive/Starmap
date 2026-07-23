"""Agent 对话消息与 thread 时间线模型测试。"""

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.models import (
    AgentMessage,
    AgentRun,
    AgentThread,
    AgentThreadItem,
)


TIMELINE_TABLES = [
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentThreadItem.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=TIMELINE_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_thread(db_session, thread_id: str = "thread_001") -> AgentThread:
    thread = AgentThread(id=thread_id, user_id="user_001", title="测试线程")
    db_session.add(thread)
    await db_session.flush()
    return thread


@pytest.mark.asyncio
async def test_message_and_workflow_items_share_thread_sequence(db_session):
    thread = await _create_thread(db_session)
    message = AgentMessage(
        id="msg_001",
        thread_id=thread.id,
        user_id=thread.user_id,
        role="user",
        status="completed",
        content_text="解释循环队列",
        client_message_id="client_001",
    )
    run = AgentRun(
        id="run_001",
        thread_id=thread.id,
        user_id=thread.user_id,
        workflow_name="conversation@v1",
        trigger_message_id=message.id,
        presentation="workflow",
    )
    db_session.add_all([message, run])
    await db_session.flush()

    db_session.add_all([
        AgentThreadItem(
            id="item_001",
            thread_id=thread.id,
            sequence=1,
            item_type="message",
            ref_id=message.id,
        ),
        AgentThreadItem(
            id="item_002",
            thread_id=thread.id,
            sequence=2,
            item_type="workflow",
            ref_id=run.id,
            run_id=run.id,
        ),
    ])
    await db_session.flush()

    assert run.trigger_message_id == message.id
    assert thread.last_item_sequence == 0


@pytest.mark.asyncio
async def test_thread_sequence_must_be_unique(db_session):
    thread = await _create_thread(db_session)
    db_session.add_all([
        AgentThreadItem(
            id="item_001",
            thread_id=thread.id,
            sequence=1,
            item_type="notice",
            ref_id="notice_001",
        ),
        AgentThreadItem(
            id="item_002",
            thread_id=thread.id,
            sequence=1,
            item_type="notice",
            ref_id="notice_002",
        ),
    ])

    with pytest.raises(IntegrityError):
        await db_session.flush()
