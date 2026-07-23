"""conversation 动态路由、普通回答与澄清的 Worker 级测试。"""

import pytest
import pytest_asyncio
from pydantic_ai.messages import ModelRequest, ModelResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.model_runtime.schema import (
    DirectAnswerOutput,
    RouterDecision,
)
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentCheckpoint,
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
from app.modules.agent.thread_events import thread_event_store
from app.modules.agent.timeline import AgentTimelineService
from app.modules.agent.worker import AgentWorker
from app.modules.agent.workflows import conversation

CONVERSATION_TABLES = [
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentThreadItem.__table__,
    AgentThreadEvent.__table__,
    AgentStep.__table__,
    AgentEvent.__table__,
    AgentRunOutbox.__table__,
    AgentCheckpoint.__table__,
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
                tables=CONVERSATION_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


class RouterStub:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.histories = []

    async def decide(self, current_input, *, deps, message_history=()):
        self.histories.append(list(message_history))
        return self.decisions.pop(0)


class AnswerStub:
    def __init__(self, answers):
        self.answers = list(answers)
        self.histories = []

    async def answer(self, current_input, *, deps, message_history=()):
        self.histories.append(list(message_history))
        return self.answers.pop(0)


async def _create_thread(db_session):
    thread = AgentThread(
        id="thread_001",
        user_id="user_001",
        title="新会话",
        status="active",
    )
    db_session.add(thread)
    await db_session.flush()


async def _create_turn(db_session, *, content: str, client_message_id: str):
    return await AgentTimelineService(db_session).create_turn(
        user_id="user_001",
        thread_id="thread_001",
        content=content,
        client_message_id=client_message_id,
        attachments=[],
        context_refs=[],
    )


@pytest.mark.asyncio
async def test_direct_answer_is_message_without_visible_workflow_and_reuses_history(
    db_session,
    monkeypatch,
):
    await _create_thread(db_session)
    router = RouterStub(
        [
            RouterDecision(
                action="direct_answer",
                confidence=0.95,
                reason_code="simple_question",
            ),
            RouterDecision(
                action="direct_answer",
                confidence=0.9,
                reason_code="follow_up",
            ),
        ]
    )
    answer = AnswerStub(
        [
            DirectAnswerOutput(content="队列是先进先出的线性结构。"),
            DirectAnswerOutput(content="循环队列用取模复用数组空间。"),
        ]
    )
    monkeypatch.setattr(conversation, "router_runtime", router)
    monkeypatch.setattr(conversation, "direct_answer_runtime", answer)

    first = await _create_turn(
        db_session,
        content="什么是队列？",
        client_message_id="client_001",
    )
    assert await AgentWorker().process_run(db_session, first.run) is True

    first_events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=first.timeline_cursor,
        limit=20,
    )
    assert [event.event_type for event in first_events] == [
        "timeline.item.created",
        "message.completed",
    ]

    second = await _create_turn(
        db_session,
        content="那循环队列呢？",
        client_message_id="client_002",
    )
    assert await AgentWorker().process_run(db_session, second.run) is True

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=20,
    )
    assert [item["type"] for item in page.items] == [
        "message",
        "message",
        "message",
        "message",
    ]
    assert [item["message"]["content"] for item in page.items] == [
        "什么是队列？",
        "队列是先进先出的线性结构。",
        "那循环队列呢？",
        "循环队列用取模复用数组空间。",
    ]
    assert all(item["type"] != "workflow" for item in page.items)

    second_history = router.histories[1]
    assert isinstance(second_history[0], ModelRequest)
    assert isinstance(second_history[1], ModelResponse)
    assert second_history[0].parts[0].content == "什么是队列？"
    assert second_history[1].parts[0].content == "队列是先进先出的线性结构。"
    assert second.run.metadata_json["router_decision"]["action"] == "direct_answer"
    assert second.run.metadata_json["context_audit"]["selected_message_ids"]


@pytest.mark.asyncio
async def test_clarify_outputs_question_without_calling_answer_agent(
    db_session,
    monkeypatch,
):
    await _create_thread(db_session)
    router = RouterStub(
        [
            RouterDecision(
                action="clarify",
                confidence=0.7,
                reason_code="missing_target",
                clarification_question="你希望我讲解哪一道题？",
            )
        ]
    )
    answer = AnswerStub([])
    monkeypatch.setattr(conversation, "router_runtime", router)
    monkeypatch.setattr(conversation, "direct_answer_runtime", answer)
    creation = await _create_turn(
        db_session,
        content="帮我讲一下",
        client_message_id="client_001",
    )

    assert await AgentWorker().process_run(db_session, creation.run) is True

    messages = list(
        (
            await db_session.execute(
                select(AgentMessage).order_by(AgentMessage.created_at)
            )
        ).scalars()
    )
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].content_text == "你希望我讲解哪一道题？"
    assert answer.histories == []
    assert creation.run.status == "completed"
