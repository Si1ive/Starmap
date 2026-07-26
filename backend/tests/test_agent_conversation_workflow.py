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
from app.modules.agent.model_runtime.config import AgentModelConfigurationError
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentInput,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMessage,
    AgentRun,
    AgentRunOutbox,
    AgentStep,
    AgentThreadMemoryState,
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
    AgentThreadMemoryState.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemorySnapshotItem.__table__,
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
        self.inputs = []

    async def decide(self, current_input, *, deps, message_history=(), db=None):
        self.inputs.append(current_input)
        self.histories.append(list(message_history))
        return self.decisions.pop(0)


class AnswerStub:
    def __init__(self, answers):
        self.answers = list(answers)
        self.histories = []

    async def answer(
        self,
        current_input,
        *,
        deps,
        message_history=(),
        db=None,
        on_delta=None,
    ):
        self.histories.append(list(message_history))
        return self.answers.pop(0)


class StreamingAnswerStub:
    async def answer(
        self,
        current_input,
        *,
        deps,
        message_history=(),
        db=None,
        on_delta=None,
    ):
        assert on_delta is not None
        await on_delta("循环队列通过")
        await on_delta("取模复用数组空间。")
        return DirectAnswerOutput(
            content="循环队列通过取模复用数组空间。",
            public_summary="说明循环队列",
        )


class FailingRouterStub:
    async def decide(self, current_input, *, deps, message_history=(), db=None):
        raise AgentModelConfigurationError(
            "Agent 没有可用模型：请在管理员端启用问答 LLM"
        )


class TokenLimitStreamingAnswerStub:
    async def answer(
        self,
        current_input,
        *,
        deps,
        message_history=(),
        db=None,
        on_delta=None,
    ):
        assert on_delta is not None
        await on_delta("红黑树是一种近似平衡二叉搜索树。")
        await on_delta("这里是已经生成但尚未完成的正文。")
        raise RuntimeError(
            "Exceeded the total_tokens_limit of 4096 (total_tokens=4863)."
        )


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
async def test_direct_answer_persists_deltas_before_completed_message(
    db_session,
    monkeypatch,
):
    await _create_thread(db_session)
    monkeypatch.setattr(
        conversation,
        "router_runtime",
        RouterStub(
            [
                RouterDecision(
                    action="direct_answer",
                    confidence=0.95,
                    reason_code="simple_question",
                )
            ]
        ),
    )
    monkeypatch.setattr(conversation, "direct_answer_runtime", StreamingAnswerStub())
    creation = await _create_turn(
        db_session,
        content="什么是循环队列？",
        client_message_id="client_stream_001",
    )

    assert await AgentWorker().process_run(db_session, creation.run) is True

    events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=20,
    )
    assert [event.event_type for event in events] == [
        "timeline.item.created",
        "message.delta",
        "message.delta",
        "message.completed",
    ]
    assert [
        event.payload.get("delta")
        for event in events
        if event.event_type == "message.delta"
    ] == ["循环队列通过", "取模复用数组空间。"]

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=20,
    )
    assert page.items[-1]["message"]["status"] == "completed"
    assert page.items[-1]["message"]["content"] == "循环队列通过取模复用数组空间。"


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


@pytest.mark.parametrize(
    ("action", "title"),
    [
        ("explain", "整理讲解"),
        ("validate", "生成专项练习"),
        ("grade", "分析作答"),
        ("plan", "调整学习计划"),
    ],
)
@pytest.mark.asyncio
async def test_business_action_creates_context_bound_inline_workflow(
    db_session,
    monkeypatch,
    action,
    title,
):
    await _create_thread(db_session)
    router = RouterStub(
        [
            RouterDecision(
                action=action,
                confidence=0.93,
                reason_code=f"needs_{action}",
            )
        ]
    )
    monkeypatch.setattr(conversation, "router_runtime", router)
    creation = await AgentTimelineService(db_session).create_turn(
        user_id="user_001",
        thread_id="thread_001",
        content=f"请帮我执行 {action}",
        client_message_id="client_001",
        attachments=[{"id": "attachment_001", "name": "题目截图.png"}],
        context_refs=[{"type": "question", "id": "question_001"}],
    )
    creation.run.metadata_json = {
        **(creation.run.metadata_json or {}),
        "model_config_id": "model_selected",
    }

    assert await AgentWorker().process_run(db_session, creation.run) is True

    child = await db_session.scalar(
        select(AgentRun).where(AgentRun.parent_run_id == creation.run.id)
    )
    assert child is not None
    assert child.workflow_name == action
    assert child.workflow_key == action
    assert child.workflow_version == "v1"
    assert child.trigger_message_id == creation.message.id
    assert child.root_run_id == creation.run.id
    assert child.presentation == "compact"
    assert child.public_title == title
    assert child.metadata_json["model_config_id"] == "model_selected"
    assert child.metadata_json["context_policy_version"] == "thread-context-v1"
    snapshot = child.metadata_json["context_snapshot"]
    assert snapshot["attachment_refs"][0]["id"] == "attachment_001"
    assert snapshot["context_refs"][0]["id"] == "question_001"
    assert snapshot["permission_scope"]["root_run_id"] == creation.run.id

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=20,
    )
    assert [item["type"] for item in page.items] == ["message", "workflow"]
    workflow = page.items[1]["workflow"]
    assert workflow["root_run_id"] == creation.run.id
    assert workflow["title"] == title
    assert workflow["status"] == "queued"
    assert workflow["steps"] == []

    events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=20,
    )
    assert [event.event_type for event in events] == [
        "workflow.updated",
        "timeline.item.created",
    ]


@pytest.mark.asyncio
async def test_follow_up_validate_request_uses_active_topic_snapshot_for_child_run(
    db_session,
    monkeypatch,
):
    await _create_thread(db_session)
    db_session.add(
        AgentThreadMemoryState(
            thread_id="thread_001",
            user_id="user_001",
            version=3,
            active_topic_json={
                "entity_type": "knowledge_point",
                "entity_id": "kp_binary_search",
                "title": "二分查找",
                "source": "thread_memory",
            },
        )
    )
    await db_session.flush()
    router = RouterStub(
        [
            RouterDecision(
                action="validate",
                confidence=0.91,
                reason_code="needs_practice",
            )
        ]
    )
    monkeypatch.setattr(conversation, "router_runtime", router)
    creation = await _create_turn(
        db_session,
        content="给我出道题",
        client_message_id="client_follow_up_validate",
    )

    assert await AgentWorker().process_run(db_session, creation.run) is True

    child = await db_session.scalar(
        select(AgentRun).where(AgentRun.parent_run_id == creation.run.id)
    )
    snapshot = await db_session.scalar(
        select(AgentMemorySnapshot).where(AgentMemorySnapshot.run_id == creation.run.id)
    )
    state = await db_session.scalar(
        select(AgentThreadMemoryState).where(
            AgentThreadMemoryState.thread_id == "thread_001"
        )
    )
    snapshot_item = await db_session.scalar(
        select(AgentMemorySnapshotItem).where(
            AgentMemorySnapshotItem.snapshot_id == snapshot.id
        )
    )

    assert router.inputs == ["给用户出一道关于二分查找的练习题"]
    assert creation.run.metadata_json["memory_snapshot_id"] == snapshot.id
    assert creation.run.metadata_json["turn_understanding"]["standalone_request"] == (
        "给用户出一道关于二分查找的练习题"
    )
    assert child is not None
    assert child.input_message == "给用户出一道关于二分查找的练习题"
    assert child.metadata_json["memory_snapshot_id"] == snapshot.id
    assert child.metadata_json["context_snapshot"]["active_topic"]["title"] == "二分查找"
    assert child.metadata_json["context_snapshot"]["standalone_request"] == (
        "给用户出一道关于二分查找的练习题"
    )
    assert snapshot is not None
    assert snapshot.state_version == 4
    assert snapshot.standalone_request == "给用户出一道关于二分查找的练习题"
    assert snapshot.understanding_json["topic_entities"][0]["title"] == "二分查找"
    assert snapshot_item is not None
    assert snapshot_item.memory_partition == "current_turn_understanding"
    assert state is not None
    assert state.version == 4
    assert state.latest_understanding_run_id == creation.run.id


@pytest.mark.asyncio
async def test_thread_continues_with_answer_and_another_workflow_after_completion(
    db_session,
    monkeypatch,
):
    await _create_thread(db_session)
    router = RouterStub(
        [
            RouterDecision(
                action="validate",
                confidence=0.9,
                reason_code="needs_practice",
            ),
            RouterDecision(
                action="direct_answer",
                confidence=0.9,
                reason_code="follow_up_question",
            ),
            RouterDecision(
                action="plan",
                confidence=0.9,
                reason_code="needs_plan",
            ),
        ]
    )
    answer = AnswerStub(
        [DirectAnswerOutput(content="可以，先完成练习再根据结果调整计划。")]
    )
    monkeypatch.setattr(conversation, "router_runtime", router)
    monkeypatch.setattr(conversation, "direct_answer_runtime", answer)

    first = await _create_turn(
        db_session,
        content="给我生成一组专项练习",
        client_message_id="client_001",
    )
    assert await AgentWorker().process_run(db_session, first.run) is True
    first_child = await db_session.scalar(
        select(AgentRun).where(AgentRun.parent_run_id == first.run.id)
    )
    first_child.status = "completed"

    second = await _create_turn(
        db_session,
        content="做完以后可以调整计划吗？",
        client_message_id="client_002",
    )
    assert await AgentWorker().process_run(db_session, second.run) is True

    third = await _create_turn(
        db_session,
        content="那就帮我调整接下来七天的计划",
        client_message_id="client_003",
    )
    assert await AgentWorker().process_run(db_session, third.run) is True

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=20,
    )
    assert [item["type"] for item in page.items] == [
        "message",
        "workflow",
        "message",
        "message",
        "message",
        "workflow",
    ]
    workflows = [item["workflow"] for item in page.items if item["workflow"]]
    assert [workflow["title"] for workflow in workflows] == [
        "生成专项练习",
        "调整学习计划",
    ]
    assert page.thread.status == "active"


@pytest.mark.asyncio
async def test_model_configuration_failure_creates_visible_failed_message(
    db_session,
    monkeypatch,
):
    await _create_thread(db_session)
    monkeypatch.setattr(conversation, "router_runtime", FailingRouterStub())
    creation = await _create_turn(
        db_session,
        content="为什么 Agent 没有回复？",
        client_message_id="client_failed",
    )

    assert await AgentWorker().process_run(db_session, creation.run) is True
    assert creation.run.status == "failed"
    assert creation.run.metadata_json["error_code"] == "agent_model_unavailable"

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=20,
    )
    assert [item["type"] for item in page.items] == ["message", "message"]
    failed_message = page.items[1]["message"]
    assert failed_message["status"] == "failed"
    assert failed_message["error_code"] == "agent_model_unavailable"
    assert failed_message["content"] == ""
    assert "Agent 模型配置" in failed_message["error_message"]

    events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=20,
    )
    assert [event.event_type for event in events] == [
        "timeline.item.created",
        "message.failed",
    ]


@pytest.mark.asyncio
async def test_streaming_failure_retains_partial_content_and_explains_reason(
    db_session,
    monkeypatch,
):
    await _create_thread(db_session)
    monkeypatch.setattr(
        conversation,
        "router_runtime",
        RouterStub(
            [
                RouterDecision(
                    action="direct_answer",
                    confidence=0.95,
                    reason_code="simple_question",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        conversation,
        "direct_answer_runtime",
        TokenLimitStreamingAnswerStub(),
    )
    creation = await _create_turn(
        db_session,
        content="给我讲解一下红黑树",
        client_message_id="client_token_limit",
    )

    assert await AgentWorker().process_run(db_session, creation.run) is True

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=20,
    )
    failed_message = page.items[-1]["message"]
    assert failed_message["status"] == "failed"
    assert failed_message["error_code"] == "agent_response_too_long"
    assert failed_message["content"] == (
        "红黑树是一种近似平衡二叉搜索树。"
        "这里是已经生成但尚未完成的正文。"
    )
    assert "长度" in failed_message["error_message"]
    assert "已生成的内容会保留" in failed_message["error_message"]

    events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=20,
    )
    assert [event.event_type for event in events] == [
        "timeline.item.created",
        "message.delta",
        "message.delta",
        "message.failed",
    ]
    failed_event = events[-1]
    assert failed_event.payload["message"]["content"].startswith("红黑树")
    assert failed_event.payload["error_code"] == "agent_response_too_long"
    assert "长度" in failed_event.payload["error_message"]
