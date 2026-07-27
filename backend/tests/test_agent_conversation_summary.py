"""历史对话增量摘要的区间、版本和异步失败隔离测试。"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.conversation_summary import (
    CONVERSATION_SUMMARY_TASK,
    ConversationSummaryMaintainer,
    enqueue_conversation_summary_maintenance,
)
from app.modules.agent.memory_outbox import MemoryOutboxConsumer, MemoryOutboxStore
from app.modules.agent.models import (
    AgentConversationSummary,
    AgentMemoryEvent,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentRun,
    AgentThread,
    AgentThreadItem,
)


SUMMARY_TABLES = [
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentThreadItem.__table__,
    AgentMemoryEvent.__table__,
    AgentMemoryUpdateOutbox.__table__,
    AgentConversationSummary.__table__,
]


class SummaryRuntimeStub:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    async def summarize(self, *, previous_summary, messages, deps, db=None):
        self.calls.append(
            {
                "previous_summary": previous_summary,
                "messages": list(messages),
                "deps": deps,
            }
        )
        if self.fail:
            raise RuntimeError("summary model unavailable")
        current = " / ".join(message.content for message in messages)
        return f"{previous_summary} | {current}" if previous_summary else current


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=SUMMARY_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_thread_and_run(
    db_session,
    *,
    thread_id: str = "thread_summary_001",
    user_id: str = "user_001",
    run_id: str = "run_summary_001",
):
    thread = AgentThread(
        id=thread_id,
        user_id=user_id,
        title="摘要测试",
        status="active",
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id=user_id,
        workflow_name="conversation",
        workflow_key="conversation",
        workflow_version="v1",
        status="completed",
        input_message="继续",
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    return thread, run


async def _add_message(
    db_session,
    *,
    thread_id: str,
    user_id: str,
    message_id: str,
    sequence: int,
    role: str,
    content: str,
    status: str = "completed",
    visibility: str = "visible",
):
    message = AgentMessage(
        id=message_id,
        thread_id=thread_id,
        user_id=user_id,
        role=role,
        status=status,
        content_text=content,
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        AgentThreadItem(
            id=f"item_{message_id}",
            thread_id=thread_id,
            sequence=sequence,
            item_type="message",
            ref_id=message.id,
            visibility=visibility,
        )
    )
    await db_session.flush()


async def _add_turns(
    db_session,
    *,
    thread_id: str,
    user_id: str,
    start_turn: int,
    end_turn: int,
):
    for turn in range(start_turn, end_turn + 1):
        await _add_message(
            db_session,
            thread_id=thread_id,
            user_id=user_id,
            message_id=f"msg_u_{thread_id[-3:]}_{turn:02d}",
            sequence=turn * 10,
            role="user",
            content=f"用户第 {turn} 轮",
        )
        await _add_message(
            db_session,
            thread_id=thread_id,
            user_id=user_id,
            message_id=f"msg_a_{thread_id[-3:]}_{turn:02d}",
            sequence=turn * 10 + 1,
            role="assistant",
            content=f"助手第 {turn} 轮",
        )


@pytest.mark.asyncio
async def test_summary_selects_only_old_visible_completed_conversation_range(db_session):
    thread, run = await _create_thread_and_run(db_session)
    await _add_turns(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        start_turn=1,
        end_turn=14,
    )
    await _add_message(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        message_id="msg_hidden_001",
        sequence=12,
        role="assistant",
        content="隐藏消息不得进入摘要",
        visibility="hidden",
    )
    await _add_message(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        message_id="msg_failed_001",
        sequence=13,
        role="assistant",
        content="失败消息不得进入摘要",
        status="failed",
    )
    await _add_message(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        message_id="msg_system_001",
        sequence=14,
        role="system",
        content="系统消息不得进入摘要",
    )
    runtime = SummaryRuntimeStub()
    maintainer = ConversationSummaryMaintainer(runtime=runtime)

    summary = await maintainer.maintain(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        trigger_run_id=run.id,
    )

    assert summary is not None
    assert summary.start_sequence == 10
    assert summary.end_sequence == 21
    assert summary.version == 1
    assert summary.source_message_ids_json == [
        "msg_u_001_01",
        "msg_a_001_01",
        "msg_u_001_02",
        "msg_a_001_02",
    ]
    assert [message.id for message in runtime.calls[0]["messages"]] == (
        summary.source_message_ids_json
    )
    assert "用户第 3 轮" not in summary.summary_text
    assert "隐藏消息" not in summary.summary_text


@pytest.mark.asyncio
async def test_summary_replay_is_idempotent_and_new_range_supersedes_old_version(
    db_session,
):
    thread, run = await _create_thread_and_run(db_session)
    await _add_turns(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        start_turn=1,
        end_turn=13,
    )
    runtime = SummaryRuntimeStub()
    maintainer = ConversationSummaryMaintainer(runtime=runtime)

    first = await maintainer.maintain(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        trigger_run_id=run.id,
    )
    replay = await maintainer.maintain(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        trigger_run_id=run.id,
    )
    assert first is not None
    assert replay is None
    assert len(runtime.calls) == 1

    await _add_turns(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        start_turn=14,
        end_turn=15,
    )
    second = await maintainer.maintain(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        trigger_run_id=run.id,
    )

    assert second is not None
    await db_session.refresh(first)
    assert first.superseded_by_id == second.id
    assert second.version == 2
    assert second.start_sequence == first.start_sequence == 10
    assert second.end_sequence == 31
    assert second.source_message_ids_json == [
        "msg_u_001_01",
        "msg_a_001_01",
        "msg_u_001_02",
        "msg_a_001_02",
        "msg_u_001_03",
        "msg_a_001_03",
    ]
    assert runtime.calls[1]["previous_summary"] == first.summary_text
    active = list(
        (
            await db_session.execute(
                select(AgentConversationSummary).where(
                    AgentConversationSummary.superseded_by_id.is_(None)
                )
            )
        ).scalars()
    )
    assert [item.id for item in active] == [second.id]


@pytest.mark.asyncio
async def test_summary_retries_when_active_version_changes_during_model_call(db_session):
    thread, run = await _create_thread_and_run(db_session)
    await _add_turns(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        start_turn=1,
        end_turn=13,
    )

    class ConcurrentSummaryRuntime:
        async def summarize(self, *, previous_summary, messages, deps, db=None):
            db.add(
                AgentConversationSummary(
                    id="convsum_concurrent_001",
                    thread_id=deps.thread_id,
                    user_id=deps.user_id,
                    start_sequence=messages[0].sequence,
                    end_sequence=messages[-1].sequence,
                    summary_text="另一 Worker 已生成摘要",
                    source_message_ids_json=[message.id for message in messages],
                    version=1,
                )
            )
            await db.flush()
            return "当前 Worker 的过期结果"

    with pytest.raises(RuntimeError, match="活跃版本已变化"):
        await ConversationSummaryMaintainer(
            runtime=ConcurrentSummaryRuntime()
        ).maintain(
            db_session,
            thread_id=thread.id,
            user_id=thread.user_id,
            trigger_run_id=run.id,
        )

    summaries = list(
        (await db_session.execute(select(AgentConversationSummary))).scalars()
    )
    assert [summary.id for summary in summaries] == ["convsum_concurrent_001"]


@pytest.mark.asyncio
async def test_summary_scope_does_not_read_another_user_or_thread(db_session):
    target_thread, target_run = await _create_thread_and_run(db_session)
    other_thread, _ = await _create_thread_and_run(
        db_session,
        thread_id="thread_summary_002",
        user_id="user_002",
        run_id="run_summary_002",
    )
    await _add_turns(
        db_session,
        thread_id=target_thread.id,
        user_id=target_thread.user_id,
        start_turn=1,
        end_turn=13,
    )
    await _add_turns(
        db_session,
        thread_id=other_thread.id,
        user_id=other_thread.user_id,
        start_turn=1,
        end_turn=13,
    )
    runtime = SummaryRuntimeStub()

    summary = await ConversationSummaryMaintainer(runtime=runtime).maintain(
        db_session,
        thread_id=target_thread.id,
        user_id=target_thread.user_id,
        trigger_run_id=target_run.id,
    )

    assert summary is not None
    assert summary.user_id == target_thread.user_id
    assert all("002" not in message.id for message in runtime.calls[0]["messages"])
    other_summary = await db_session.scalar(
        select(AgentConversationSummary).where(
            AgentConversationSummary.thread_id == other_thread.id
        )
    )
    assert other_summary is None


@pytest.mark.asyncio
async def test_summary_outbox_is_idempotent_and_failure_keeps_run_completed(db_session):
    thread, run = await _create_thread_and_run(db_session)
    await _add_turns(
        db_session,
        thread_id=thread.id,
        user_id=thread.user_id,
        start_turn=1,
        end_turn=13,
    )
    await enqueue_conversation_summary_maintenance(db_session, run)
    await enqueue_conversation_summary_maintenance(db_session, run)
    tasks = list(
        (
            await db_session.execute(
                select(AgentMemoryUpdateOutbox).where(
                    AgentMemoryUpdateOutbox.event_type == CONVERSATION_SUMMARY_TASK
                )
            )
        ).scalars()
    )
    assert len(tasks) == 1

    store = MemoryOutboxStore()
    assert await store.claim(db_session, tasks[0].id, "memory_worker_1") is True
    consumer = MemoryOutboxConsumer(
        store=store,
        summary_maintainer=ConversationSummaryMaintainer(
            runtime=SummaryRuntimeStub(fail=True)
        ),
        retry_delay_seconds=45,
    )
    assert await consumer.process_claimed(
        db_session,
        tasks[0].id,
        "memory_worker_1",
    ) is False

    await db_session.refresh(run)
    await db_session.refresh(tasks[0])
    assert run.status == "completed"
    assert tasks[0].status == "pending"
    assert tasks[0].retry_count == 1
    assert await db_session.scalar(select(AgentConversationSummary)) is None
