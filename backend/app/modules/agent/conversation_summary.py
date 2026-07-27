"""按连续消息区间增量生成线程历史摘要。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from .model_runtime.conversation_summary import (
    ConversationSummaryDeps,
    ConversationSummaryMessage,
    ConversationSummaryRuntime,
    conversation_summary_runtime,
)
from .models import (
    AgentConversationSummary,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentRun,
    AgentThread,
    AgentThreadItem,
)

logger = get_logger(__name__)

CONVERSATION_SUMMARY_TASK = "conversation_summary_maintenance"


class ConversationSummaryScopeError(ValueError):
    """摘要任务中的 Run、用户和线程作用域不一致。"""


async def enqueue_conversation_summary_maintenance(
    db: AsyncSession,
    run: AgentRun,
) -> None:
    """在成功 Run 事务内幂等写入摘要维护任务。"""
    if run.status != "completed":
        raise ValueError("只有已完成 Run 可以触发对话摘要维护")
    existing = await db.scalar(
        select(AgentMemoryUpdateOutbox.id).where(
            AgentMemoryUpdateOutbox.run_id == run.id,
            AgentMemoryUpdateOutbox.event_type == CONVERSATION_SUMMARY_TASK,
        )
    )
    if existing is not None:
        return
    try:
        async with db.begin_nested():
            db.add(
                AgentMemoryUpdateOutbox(
                    run_id=run.id,
                    thread_id=run.thread_id,
                    user_id=run.user_id,
                    event_type=CONVERSATION_SUMMARY_TASK,
                    status="pending",
                    payload_json={
                        "task_type": CONVERSATION_SUMMARY_TASK,
                        "trigger_run_id": run.id,
                    },
                )
            )
            await db.flush()
    except IntegrityError:
        logger.info("对话摘要维护任务并发幂等命中", run_id=run.id)


class ConversationSummaryMaintainer:
    """保留近期原始轮次，并把更旧消息滚动合并为版本化摘要。"""

    def __init__(
        self,
        *,
        runtime: ConversationSummaryRuntime = conversation_summary_runtime,
        raw_turns: int = 12,
        max_new_messages: int = 24,
    ) -> None:
        if not 6 <= raw_turns <= 12:
            raise ValueError("raw_turns 必须在 6 到 12 之间")
        if max_new_messages < 2:
            raise ValueError("max_new_messages 必须至少为 2")
        self.runtime = runtime
        self.raw_turns = raw_turns
        self.max_new_messages = max_new_messages

    async def maintain(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        user_id: str,
        trigger_run_id: str,
    ) -> AgentConversationSummary | None:
        """只处理上个活跃摘要之后、近期原始窗口之前的一批消息。"""
        thread = await db.scalar(
            select(AgentThread).where(
                AgentThread.id == thread_id,
                AgentThread.user_id == user_id,
                AgentThread.status.in_(("active", "archived")),
            )
        )
        trigger_run = await db.scalar(
            select(AgentRun).where(
                AgentRun.id == trigger_run_id,
                AgentRun.thread_id == thread_id,
                AgentRun.user_id == user_id,
                AgentRun.status == "completed",
            )
        )
        if thread is None or trigger_run is None:
            raise ConversationSummaryScopeError("对话摘要任务作用域不匹配")

        raw_window_start = await self._load_raw_window_start(
            db,
            thread_id=thread_id,
            user_id=user_id,
        )
        if raw_window_start is None:
            return None

        previous = await self._load_active_summary(
            db,
            thread_id=thread_id,
            user_id=user_id,
        )
        after_sequence = previous.end_sequence if previous else -1
        if after_sequence >= raw_window_start:
            return None

        messages = await self._load_new_messages(
            db,
            thread_id=thread_id,
            user_id=user_id,
            after_sequence=after_sequence,
            before_sequence=raw_window_start,
        )
        if len(messages) < 2:
            return None

        summary_text = await self.runtime.summarize(
            previous_summary=previous.summary_text if previous else None,
            messages=messages,
            deps=ConversationSummaryDeps(
                thread_id=thread_id,
                user_id=user_id,
                trigger_run_id=trigger_run_id,
            ),
            db=db,
        )
        locked_thread = await db.scalar(
            select(AgentThread)
            .where(
                AgentThread.id == thread_id,
                AgentThread.user_id == user_id,
                AgentThread.status.in_(("active", "archived")),
            )
            .with_for_update()
        )
        if locked_thread is None:
            raise ConversationSummaryScopeError("摘要生成期间线程作用域已失效")
        current_active = await self._load_active_summary(
            db,
            thread_id=thread_id,
            user_id=user_id,
            for_update=True,
        )
        if (current_active.id if current_active else None) != (
            previous.id if previous else None
        ):
            raise RuntimeError("摘要生成期间活跃版本已变化")
        previous_source_ids = (
            [
                source_id
                for source_id in (previous.source_message_ids_json or [])
                if isinstance(source_id, str)
            ]
            if previous
            else []
        )
        source_message_ids = list(
            dict.fromkeys(previous_source_ids + [message.id for message in messages])
        )
        summary = AgentConversationSummary(
            id=f"convsum_{uuid.uuid4().hex[:20]}",
            thread_id=thread_id,
            user_id=user_id,
            start_sequence=(previous.start_sequence if previous else messages[0].sequence),
            end_sequence=messages[-1].sequence,
            summary_text=summary_text,
            source_message_ids_json=source_message_ids,
            version=(previous.version + 1 if previous else 1),
        )
        db.add(summary)
        await db.flush()
        if previous:
            previous.superseded_by_id = summary.id
            await db.flush()
        logger.info(
            "线程历史对话摘要已更新",
            thread_id=thread_id,
            summary_id=summary.id,
            version=summary.version,
            start_sequence=summary.start_sequence,
            end_sequence=summary.end_sequence,
            new_message_count=len(messages),
        )
        return summary

    async def _load_active_summary(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        user_id: str,
        for_update: bool = False,
    ) -> AgentConversationSummary | None:
        statement = (
            select(AgentConversationSummary)
            .where(
                AgentConversationSummary.thread_id == thread_id,
                AgentConversationSummary.user_id == user_id,
                AgentConversationSummary.superseded_by_id.is_(None),
            )
            .order_by(AgentConversationSummary.end_sequence.desc())
            .limit(2)
        )
        if for_update:
            statement = statement.with_for_update()
        summaries = list((await db.execute(statement)).scalars())
        if len(summaries) > 1:
            raise ValueError("同一线程存在多条活跃对话摘要")
        return summaries[0] if summaries else None

    async def _load_raw_window_start(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        user_id: str,
    ) -> int | None:
        """返回最近 N 个用户轮次中最早一轮的序号；不足 N+1 轮不摘要。"""
        result = await db.execute(
            select(AgentThreadItem.sequence)
            .join(
                AgentMessage,
                (AgentMessage.id == AgentThreadItem.ref_id)
                & (AgentMessage.thread_id == AgentThreadItem.thread_id),
            )
            .where(
                AgentThreadItem.thread_id == thread_id,
                AgentThreadItem.item_type == "message",
                AgentThreadItem.visibility == "visible",
                AgentMessage.user_id == user_id,
                AgentMessage.role == "user",
                AgentMessage.status == "completed",
                AgentMessage.content_text.is_not(None),
                func.length(func.trim(AgentMessage.content_text)) > 0,
            )
            .order_by(AgentThreadItem.sequence.desc())
            .limit(self.raw_turns + 1)
        )
        sequences = [int(sequence) for sequence in result.scalars()]
        if len(sequences) <= self.raw_turns:
            return None
        return sequences[self.raw_turns - 1]

    async def _load_new_messages(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        user_id: str,
        after_sequence: int,
        before_sequence: int,
    ) -> list[ConversationSummaryMessage]:
        result = await db.execute(
            select(AgentMessage, AgentThreadItem.sequence)
            .join(
                AgentThreadItem,
                (AgentThreadItem.ref_id == AgentMessage.id)
                & (AgentThreadItem.thread_id == AgentMessage.thread_id)
                & (AgentThreadItem.item_type == "message"),
            )
            .where(
                AgentMessage.thread_id == thread_id,
                AgentMessage.user_id == user_id,
                AgentMessage.role.in_(("user", "assistant")),
                AgentMessage.status == "completed",
                AgentThreadItem.visibility == "visible",
                AgentThreadItem.sequence > after_sequence,
                AgentThreadItem.sequence < before_sequence,
            )
            .order_by(AgentThreadItem.sequence.asc())
            .limit(self.max_new_messages * 2)
        )
        messages: list[ConversationSummaryMessage] = []
        for message, sequence in result.all():
            content = (message.content_text or "").strip()
            if not content:
                continue
            messages.append(
                ConversationSummaryMessage(
                    id=message.id,
                    role=message.role,
                    sequence=int(sequence),
                    content=content,
                )
            )
            if len(messages) >= self.max_new_messages:
                break
        return messages


conversation_summary_maintainer = ConversationSummaryMaintainer()
