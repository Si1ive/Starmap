"""Agent 线程上下文构建器测试。"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.context_builder import (
    ContextIntegrityError,
    ContextNotFoundError,
    ThreadContextBuilder,
)
from app.modules.agent.model_runtime.router import RouterDeps, RouterRuntime
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentInput,
    AgentMessage,
    AgentRun,
    AgentThread,
    AgentThreadItem,
)

CONTEXT_TABLES = [
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentThreadItem.__table__,
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
                tables=CONTEXT_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _add_thread(db_session, *, thread_id: str, user_id: str) -> AgentThread:
    thread = AgentThread(
        id=thread_id,
        user_id=user_id,
        title="测试会话",
        status="active",
    )
    db_session.add(thread)
    await db_session.flush()
    return thread


async def _add_message(
    db_session,
    *,
    message_id: str,
    thread_id: str,
    user_id: str,
    role: str,
    content: str | None,
    sequence: int,
    status: str = "completed",
    created_at: datetime,
) -> AgentMessage:
    message = AgentMessage(
        id=message_id,
        thread_id=thread_id,
        user_id=user_id,
        role=role,
        status=status,
        content_text=content,
        created_at=created_at,
        completed_at=created_at if status == "completed" else None,
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        AgentThreadItem(
            id=f"item_{message_id}",
            thread_id=thread_id,
            sequence=sequence,
            item_type="message",
            ref_id=message_id,
            visibility="visible",
            created_at=created_at,
        )
    )
    await db_session.flush()
    return message


async def _add_current_turn(
    db_session,
    *,
    thread_id: str = "thread_001",
    user_id: str = "user_001",
    message_id: str = "msg_current",
    run_id: str = "run_current",
    sequence: int = 100,
    content: str = "继续讲一下",
    metadata: dict | None = None,
) -> tuple[AgentMessage, AgentRun]:
    now = datetime(2026, 7, 23, 10, 0)
    message = await _add_message(
        db_session,
        message_id=message_id,
        thread_id=thread_id,
        user_id=user_id,
        role="user",
        content=content,
        sequence=sequence,
        created_at=now,
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id=user_id,
        workflow_name="conversation",
        workflow_key="conversation",
        status="queued",
        input_message=content,
        trigger_message_id=message.id,
        metadata_json=metadata or {},
    )
    db_session.add(run)
    await db_session.flush()
    run.root_run_id = run.id
    message.run_id = run.id
    await db_session.flush()
    return message, run


@pytest.mark.asyncio
async def test_context_filters_owner_thread_status_and_current_message(
    db_session,
):
    now = datetime(2026, 7, 23, 9, 0)
    await _add_thread(db_session, thread_id="thread_001", user_id="user_001")
    await _add_thread(db_session, thread_id="thread_other", user_id="user_001")
    await _add_thread(db_session, thread_id="thread_foreign", user_id="user_002")

    await _add_message(
        db_session,
        message_id="msg_user",
        thread_id="thread_001",
        user_id="user_001",
        role="user",
        content="什么是循环队列？",
        sequence=1,
        created_at=now,
    )
    await _add_message(
        db_session,
        message_id="msg_assistant",
        thread_id="thread_001",
        user_id="user_001",
        role="assistant",
        content="循环队列复用数组空间。",
        sequence=2,
        created_at=now + timedelta(minutes=1),
    )
    await _add_message(
        db_session,
        message_id="msg_failed",
        thread_id="thread_001",
        user_id="user_001",
        role="assistant",
        content="不完整输出",
        sequence=3,
        status="failed",
        created_at=now + timedelta(minutes=2),
    )
    await _add_message(
        db_session,
        message_id="msg_empty",
        thread_id="thread_001",
        user_id="user_001",
        role="assistant",
        content="   ",
        sequence=4,
        created_at=now + timedelta(minutes=3),
    )
    await _add_message(
        db_session,
        message_id="msg_other_thread",
        thread_id="thread_other",
        user_id="user_001",
        role="user",
        content="不应读取的同用户消息",
        sequence=1,
        created_at=now,
    )
    await _add_message(
        db_session,
        message_id="msg_foreign",
        thread_id="thread_foreign",
        user_id="user_002",
        role="user",
        content="不应读取的其他用户消息",
        sequence=1,
        created_at=now,
    )
    _, run = await _add_current_turn(db_session)

    context = await ThreadContextBuilder(db_session).build(
        user_id="user_001",
        thread_id="thread_001",
        turn_id=run.id,
    )

    assert context.selected_message_ids == ["msg_user", "msg_assistant"]
    assert context.current_message_id not in context.selected_message_ids
    assert [message.content for message in context.recent_messages] == [
        "什么是循环队列？",
        "循环队列复用数组空间。",
    ]
    history = context.to_message_history()
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)
    assert history[0].parts[0].content == "什么是循环队列？"
    assert history[1].parts[0].content == "循环队列复用数组空间。"


@pytest.mark.asyncio
async def test_context_rejects_cross_user_and_mismatched_trigger(db_session):
    await _add_thread(db_session, thread_id="thread_001", user_id="user_001")
    _, run = await _add_current_turn(db_session)

    with pytest.raises(ContextNotFoundError, match="线程不存在"):
        await ThreadContextBuilder(db_session).build(
            user_id="user_002",
            thread_id="thread_001",
            turn_id=run.id,
        )

    with pytest.raises(ContextIntegrityError, match="触发消息"):
        await ThreadContextBuilder(db_session).build(
            user_id="user_001",
            thread_id="thread_001",
            turn_id=run.id,
            current_message_id="msg_forged",
        )


@pytest.mark.asyncio
async def test_context_budget_keeps_latest_complete_turn(db_session):
    now = datetime(2026, 7, 23, 9, 0)
    await _add_thread(db_session, thread_id="thread_001", user_id="user_001")
    messages = [
        ("old_user", "较早用户消息一二三四", "user", 1),
        ("old_assistant", "较早回答内容一二三四", "assistant", 2),
        ("recent_user", "最近用户消息一二三四", "user", 3),
        ("recent_assistant", "最近回答内容一二三四", "assistant", 4),
    ]
    for offset, (message_id, content, role, sequence) in enumerate(messages):
        await _add_message(
            db_session,
            message_id=message_id,
            thread_id="thread_001",
            user_id="user_001",
            role=role,
            content=content,
            sequence=sequence,
            created_at=now + timedelta(minutes=offset),
        )
    _, run = await _add_current_turn(db_session, content="当前")
    builder = ThreadContextBuilder(db_session)
    recent_cost = sum(
        builder.estimate_tokens(content) for _, content, _, _ in messages[-2:]
    )
    budget = builder.estimate_tokens("当前") + recent_cost

    context = await builder.build(
        user_id="user_001",
        thread_id="thread_001",
        turn_id=run.id,
        token_budget=budget,
    )

    assert context.selected_message_ids == ["recent_user", "recent_assistant"]
    assert context.dropped_message_ids == ["old_user", "old_assistant"]
    assert [message.content for message in context.recent_messages] == [
        "最近用户消息一二三四",
        "最近回答内容一二三四",
    ]
    assert context.estimated_tokens <= budget


@pytest.mark.asyncio
async def test_context_loads_root_metadata_artifacts_and_pending_items(
    db_session,
):
    await _add_thread(db_session, thread_id="thread_001", user_id="user_001")
    await _add_thread(db_session, thread_id="thread_other", user_id="user_001")
    _, root_run = await _add_current_turn(
        db_session,
        metadata={
            "attachments": [{"id": "attachment_001", "name": "题目.png"}],
            "context_refs": [{"type": "question", "id": "question_001"}],
        },
    )
    child_run = AgentRun(
        id="run_child",
        thread_id="thread_001",
        user_id="user_001",
        workflow_name="grade",
        status="waiting_for_user",
        parent_run_id=root_run.id,
        root_run_id=root_run.id,
        metadata_json={"attachments": [{"id": "forged"}]},
    )
    silent_run = AgentRun(
        id="run_silent",
        thread_id="thread_001",
        user_id="user_001",
        workflow_name="router",
        status="completed",
        presentation="silent",
        root_run_id=root_run.id,
        metadata_json={},
    )
    other_run = AgentRun(
        id="run_other",
        thread_id="thread_other",
        user_id="user_001",
        workflow_name="conversation",
        status="completed",
        metadata_json={},
    )
    db_session.add_all([child_run, silent_run, other_run])
    await db_session.flush()
    db_session.add_all(
        [
            AgentArtifact(
                id="artifact_public",
                run_id=child_run.id,
                artifact_type="feedback",
                content_json={"title": "批改结果", "summary": "还需复习循环队列"},
            ),
            AgentArtifact(
                id="artifact_hidden",
                run_id=child_run.id,
                artifact_type="message",
                content_json={"content": "内部产物"},
                metadata_json={"visibility": "hidden"},
            ),
            AgentArtifact(
                id="artifact_other_thread",
                run_id=other_run.id,
                artifact_type="message",
                content_json={"content": "其他线程产物"},
            ),
            AgentArtifact(
                id="artifact_silent",
                run_id=silent_run.id,
                artifact_type="message",
                content_json={"content": "内部路由产物"},
            ),
            AgentInput(
                id="input_pending",
                run_id=child_run.id,
                input_key="answer",
                prompt_ref="请补充你的答案",
                status="pending",
            ),
            AgentInput(
                id="input_answered",
                run_id=child_run.id,
                input_key="scope",
                prompt_ref="已完成输入",
                status="answered",
            ),
            AgentInput(
                id="input_expired",
                run_id=child_run.id,
                input_key="expired_answer",
                prompt_ref="已经过期的输入",
                status="pending",
                expires_at=datetime(2020, 1, 1),
            ),
            AgentApproval(
                id="approval_pending",
                run_id=child_run.id,
                action_key="apply_plan",
                diff_ref="把循环队列加入复习计划",
                status="pending",
            ),
            AgentApproval(
                id="approval_rejected",
                run_id=child_run.id,
                action_key="replace_plan",
                status="rejected",
            ),
            AgentApproval(
                id="approval_expired",
                run_id=child_run.id,
                action_key="expired_plan",
                status="pending",
                expires_at=datetime(2020, 1, 1),
            ),
        ]
    )
    await db_session.flush()

    context = await ThreadContextBuilder(db_session).build(
        user_id="user_001",
        thread_id="thread_001",
        turn_id=root_run.id,
    )

    assert context.attachments == [{"id": "attachment_001", "name": "题目.png"}]
    assert context.context_refs == [{"type": "question", "id": "question_001"}]
    assert context.selected_artifact_ids == ["artifact_public"]
    assert context.recent_artifacts[0].summary == "批改结果\n还需复习循环队列"
    assert [item.id for item in context.pending_interactions] == [
        "input_pending",
        "approval_pending",
    ]
    assert context.permission_scope.root_run_id == root_run.id
    assert context.permission_scope.artifact_ids == ["artifact_public"]


@pytest.mark.asyncio
async def test_context_history_can_be_passed_to_pydantic_ai_router(db_session):
    now = datetime(2026, 7, 23, 9, 0)
    await _add_thread(db_session, thread_id="thread_001", user_id="user_001")
    await _add_message(
        db_session,
        message_id="msg_previous",
        thread_id="thread_001",
        user_id="user_001",
        role="user",
        content="先讲循环队列",
        sequence=1,
        created_at=now,
    )
    _, run = await _add_current_turn(db_session, content="再给我一道题")
    context = await ThreadContextBuilder(db_session).build(
        user_id="user_001",
        thread_id="thread_001",
        turn_id=run.id,
    )
    runtime = RouterRuntime(
        TestModel(
            custom_output_args={
                "action": "direct_answer",
                "confidence": 0.9,
                "reason_code": "continue_conversation",
            }
        )
    )

    decision = await runtime.decide(
        context.current_input,
        deps=RouterDeps(
            thread_id=context.thread_id,
            user_id=context.user_id,
            turn_id=context.turn_id,
            token_budget=context.token_budget,
        ),
        message_history=context.to_message_history(),
    )

    assert decision.action == "direct_answer"


@pytest.mark.asyncio
async def test_context_preserves_explicit_artifact_when_budget_is_tight(db_session):
    await _add_thread(db_session, thread_id="thread_001", user_id="user_001")
    _, run = await _add_current_turn(
        db_session,
        content="看这个",
        metadata={"context_refs": [{"type": "artifact", "id": "artifact_explicit"}]},
    )
    db_session.add_all(
        [
            AgentArtifact(
                id="artifact_explicit",
                run_id=run.id,
                artifact_type="feedback",
                content_json={"summary": "必须保留的显式引用产物" * 20},
                created_at=datetime(2026, 7, 22, 9, 0),
            ),
            AgentArtifact(
                id="artifact_recent",
                run_id=run.id,
                artifact_type="message",
                content_json={"summary": "较新的非必要产物"},
                created_at=datetime(2026, 7, 23, 9, 0),
            ),
        ]
    )
    await db_session.flush()

    context = await ThreadContextBuilder(db_session).build(
        user_id="user_001",
        thread_id="thread_001",
        turn_id=run.id,
        token_budget=10,
    )

    assert context.selected_artifact_ids == ["artifact_explicit"]
    assert context.dropped_artifact_ids == ["artifact_recent"]
    assert context.estimated_tokens > context.token_budget
