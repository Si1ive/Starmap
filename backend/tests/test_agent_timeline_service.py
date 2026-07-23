"""Agent 对话 turn 与 thread 时间线服务测试。"""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentEvent,
    AgentInput,
    AgentMessage,
    AgentRun,
    AgentRunOutbox,
    AgentStep,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
)
from app.modules.agent.service import AgentService
from app.modules.agent.events import event_store
from app.modules.agent.thread_events import thread_event_store
from app.modules.agent.timeline import AgentTimelineService, TurnConflictError

TIMELINE_SERVICE_TABLES = [
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentThreadItem.__table__,
    AgentThreadEvent.__table__,
    AgentStep.__table__,
    AgentEvent.__table__,
    AgentRunOutbox.__table__,
    AgentArtifact.__table__,
    AgentInput.__table__,
    AgentApproval.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=TIMELINE_SERVICE_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_thread(db_session, thread_id: str = "thread_001") -> AgentThread:
    thread = AgentThread(
        id=thread_id,
        user_id="user_001",
        title="新会话",
        status="active",
    )
    db_session.add(thread)
    await db_session.flush()
    return thread


async def _create_turn(
    db_session,
    *,
    content: str = "解释循环队列",
    client_message_id: str = "client_001",
):
    return await AgentTimelineService(db_session).create_turn(
        user_id="user_001",
        thread_id="thread_001",
        content=content,
        client_message_id=client_message_id,
        attachments=[],
        context_refs=[],
        preferred_action=None,
    )


@pytest.mark.asyncio
async def test_create_turn_writes_message_run_timeline_event_and_outbox(db_session):
    thread = await _create_thread(db_session)

    creation = await _create_turn(db_session)

    assert creation.timeline_cursor == 3
    assert creation.message.status == "completed"
    assert creation.message.run_id == creation.run.id
    assert creation.run.root_run_id == creation.run.id
    assert creation.run.workflow_key == "conversation"
    assert thread.last_item_sequence == 3
    assert thread.title == "解释循环队列"

    items = list(
        (
            await db_session.execute(
                select(AgentThreadItem).order_by(AgentThreadItem.sequence)
            )
        ).scalars()
    )
    assert [(item.sequence, item.item_type) for item in items] == [
        (1, "message"),
        (2, "workflow"),
    ]
    assert await db_session.scalar(select(func.count(AgentEvent.id))) == 1
    assert await db_session.scalar(select(func.count(AgentRunOutbox.id))) == 1


@pytest.mark.asyncio
async def test_create_turn_is_idempotent_by_client_message_id(db_session):
    await _create_thread(db_session)

    first = await _create_turn(db_session)
    second = await _create_turn(db_session)

    assert second.message.id == first.message.id
    assert second.run.id == first.run.id
    assert second.timeline_cursor == 3
    assert await db_session.scalar(select(func.count(AgentMessage.id))) == 1
    assert await db_session.scalar(select(func.count(AgentRun.id))) == 1
    assert await db_session.scalar(select(func.count(AgentThreadItem.id))) == 2
    assert await db_session.scalar(select(func.count(AgentRunOutbox.id))) == 1


@pytest.mark.asyncio
async def test_create_turn_rejects_reused_id_with_different_content(db_session):
    await _create_thread(db_session)
    await _create_turn(db_session)

    with pytest.raises(TurnConflictError):
        await _create_turn(db_session, content="换一个问题")


@pytest.mark.asyncio
async def test_timeline_aggregates_child_workflow_into_root_item(db_session):
    await _create_thread(db_session)
    creation = await _create_turn(db_session)
    creation.run.status = "completed"

    child = await AgentService(db_session).create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="explain",
        input_message="解释循环队列",
        workflow_key="explain",
        workflow_version="v1",
        trigger_message_id=creation.message.id,
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
        public_title="整理讲解",
    )
    child.status = "waiting_for_user"
    child.public_summary = "需要确认讲解范围"
    child.current_public_step = "generate_explanation"
    now = datetime.utcnow()
    db_session.add_all(
        [
            AgentStep(
                id="step_001",
                run_id=child.id,
                node_name="generate_explanation",
                node_type="action",
                status="running",
                started_at=now,
            ),
            AgentInput(
                id="input_001",
                run_id=child.id,
                input_key="scope",
                input_schema_version="v1",
                prompt_ref="你希望讲解到什么深度？",
                status="pending",
            ),
            AgentArtifact(
                id="artifact_001",
                run_id=child.id,
                artifact_type="message",
                content_json={"title": "已有结果", "content": "可继续编辑"},
            ),
        ]
    )
    await db_session.flush()

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=50,
    )

    assert [item["type"] for item in page.items] == ["message", "workflow"]
    workflow = page.items[1]["workflow"]
    assert workflow["root_run_id"] == creation.run.id
    assert workflow["status"] == "waiting_for_user"
    assert workflow["title"] == "整理讲解"
    assert workflow["current_step"] == "组织讲解"
    assert workflow["steps"][0]["label"] == "组织讲解"
    assert workflow["pending_input"]["input_key"] == "scope"
    assert workflow["artifacts"][0]["type"] == "message"


@pytest.mark.asyncio
async def test_timeline_uses_sequence_cursor_for_pagination(db_session):
    await _create_thread(db_session)
    await _create_turn(db_session)
    await _create_turn(
        db_session,
        content="再给我三道练习题",
        client_message_id="client_002",
    )
    service = AgentTimelineService(db_session)

    latest = await service.get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=2,
    )
    earlier = await service.get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=latest.previous_cursor,
        limit=2,
    )

    assert [item["sequence"] for item in latest.items] == [4, 5]
    assert latest.previous_cursor == 4
    assert latest.latest_cursor == 6
    assert latest.has_more is True
    assert [item["sequence"] for item in earlier.items] == [1, 2]
    assert earlier.previous_cursor is None
    assert earlier.has_more is False


@pytest.mark.asyncio
async def test_run_events_project_to_thread_cursor_and_assistant_message(db_session):
    await _create_thread(db_session)
    creation = await _create_turn(db_session)
    child = await AgentService(db_session).create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="explain",
        input_message="解释循环队列",
        workflow_key="explain",
        workflow_version="v1",
        trigger_message_id=creation.message.id,
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
        public_title="整理讲解",
    )

    await event_store.append(
        db_session,
        child.id,
        "step.started",
        {"step_id": "step_public", "node_name": "generate_explanation"},
    )
    await event_store.append(
        db_session,
        child.id,
        "message.completed",
        {"content": "循环队列通过取模复用数组空间。"},
    )

    events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=20,
    )
    assert [event.event_type for event in events] == [
        "workflow.updated",
        "workflow.step.updated",
        "timeline.item.created",
        "message.completed",
    ]
    assert events[1].payload["label"] == "组织讲解"
    assert "node_name" not in events[1].payload
    assert [event.sequence for event in events] == [4, 5, 6, 7]

    assistant = await db_session.scalar(
        select(AgentMessage).where(
            AgentMessage.run_id == child.id,
            AgentMessage.role == "assistant",
        )
    )
    assert assistant is not None
    assert assistant.status == "completed"
    assert assistant.content_text == "循环队列通过取模复用数组空间。"

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=50,
    )
    assert [item["type"] for item in page.items] == [
        "message",
        "workflow",
        "message",
    ]
    assert page.items[-1]["message"]["role"] == "assistant"
    assert page.latest_cursor == 7
