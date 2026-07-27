"""记录 Agent 关键边界前后的记忆状态，供管理员只读排障。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AgentConversationSummary,
    AgentMemoryEvent,
    AgentMemoryItem,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMemoryTrace,
    AgentMemoryUpdateOutbox,
    AgentRun,
    AgentThreadMemoryState,
    UserLearningMastery,
)
from .time_utils import utc_isoformat


# message.delta 只改变流式正文，不改变上下文记忆；跳过它可以避免长回答产生
# 大量完全相同的快照，同时保留每个有诊断意义的 Agent 事件边界。
TRACEABLE_AGENT_EVENT_TYPES = frozenset(
    {
        "run.created",
        "run.status_changed",
        "run.completed",
        "run.failed",
        "error",
        "step.started",
        "step.completed",
        "step.failed",
        "tool.called",
        "tool.result",
        "message.started",
        "message.completed",
        "message.failed",
        "artifact.rendered",
    }
)

_MAX_STRING_LENGTH = 4000
_MAX_LIST_LENGTH = 50


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    """限制观测副本大小，同时保持内容足够定位上下文问题。"""
    if depth > 5:
        return "[nested value truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, datetime):
        return utc_isoformat(value)
    if isinstance(value, str):
        if len(value) <= _MAX_STRING_LENGTH:
            return value
        return f"{value[:_MAX_STRING_LENGTH]}...[truncated, total {len(value)}]"
    if isinstance(value, dict):
        result = {
            str(key): _bounded_value(item, depth=depth + 1)
            for key, item in list(value.items())[:_MAX_LIST_LENGTH]
        }
        if len(value) > _MAX_LIST_LENGTH:
            result["_truncated_items"] = len(value) - _MAX_LIST_LENGTH
        return result
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        result = [
            _bounded_value(item, depth=depth + 1)
            for item in values[:_MAX_LIST_LENGTH]
        ]
        if len(values) > _MAX_LIST_LENGTH:
            result.append(f"[...{len(values) - _MAX_LIST_LENGTH} items truncated]")
        return result
    return str(value)


def _memory_state_payload(state: AgentThreadMemoryState | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "id": state.id,
        "version": state.version,
        "active_topic": _bounded_value(state.active_topic_json or {}),
        "topic_stack": _bounded_value(state.topic_stack_json or []),
        "active_task": _bounded_value(state.active_task_json or {}),
        "referents": _bounded_value(state.referents_json or []),
        "latest_understanding_run_id": state.latest_understanding_run_id,
        "updated_at": utc_isoformat(state.updated_at),
    }


def _snapshot_payload(
    snapshot: AgentMemorySnapshot | None,
    items: list[AgentMemorySnapshotItem],
) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "id": snapshot.id,
        "state_version": snapshot.state_version,
        "standalone_request": snapshot.standalone_request,
        "understanding": _bounded_value(snapshot.understanding_json or {}),
        "selection_metadata": _bounded_value(snapshot.selection_metadata_json or {}),
        "items": [
            {
                "id": item.id,
                "memory_need": item.memory_need,
                "memory_partition": item.memory_partition,
                "source_kind": item.source_kind,
                "source_id": item.source_id,
                "version": item.version,
                "selected": bool(item.selected),
                "selection_reason": item.selection_reason,
                "dropped_reason": item.dropped_reason,
                "token_estimate": item.token_estimate,
                "payload": _bounded_value(item.payload_json or {}),
            }
            for item in items
        ],
        "created_at": utc_isoformat(snapshot.created_at),
    }


async def capture_memory_state(
    db: AsyncSession,
    *,
    run_id: str,
) -> dict[str, Any]:
    """读取某个 Run 当前可见的分层记忆状态，不执行选择或投影。"""
    run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id))
    if run is None:
        return {}

    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    bound_snapshot_id = metadata.get("memory_snapshot_id")
    state = await db.scalar(
        select(AgentThreadMemoryState).where(
            AgentThreadMemoryState.thread_id == run.thread_id,
            AgentThreadMemoryState.user_id == run.user_id,
        )
    )
    snapshot = await db.scalar(
        select(AgentMemorySnapshot)
        .where(
            AgentMemorySnapshot.user_id == run.user_id,
            AgentMemorySnapshot.thread_id == run.thread_id,
            or_(
                AgentMemorySnapshot.run_id == run.id,
                AgentMemorySnapshot.id == bound_snapshot_id,
            ),
        )
        .order_by(AgentMemorySnapshot.created_at.desc())
        .limit(1)
    )
    snapshot_items: list[AgentMemorySnapshotItem] = []
    if snapshot is not None:
        snapshot_items = list(
            (
                await db.execute(
                    select(AgentMemorySnapshotItem)
                    .where(AgentMemorySnapshotItem.snapshot_id == snapshot.id)
                    .order_by(AgentMemorySnapshotItem.id)
                )
            ).scalars()
        )

    memory_events = list(
        (
            await db.execute(
                select(AgentMemoryEvent)
                .where(
                    AgentMemoryEvent.user_id == run.user_id,
                    AgentMemoryEvent.thread_id == run.thread_id,
                )
                .order_by(AgentMemoryEvent.id.desc())
                .limit(_MAX_LIST_LENGTH)
            )
        ).scalars()
    )
    memory_items = list(
        (
            await db.execute(
                select(AgentMemoryItem)
                .where(
                    AgentMemoryItem.user_id == run.user_id,
                    or_(
                        AgentMemoryItem.thread_id == run.thread_id,
                        AgentMemoryItem.scope == "user",
                    ),
                )
                .order_by(AgentMemoryItem.updated_at.desc(), AgentMemoryItem.id.desc())
                .limit(_MAX_LIST_LENGTH)
            )
        ).scalars()
    )
    masteries = list(
        (
            await db.execute(
                select(UserLearningMastery)
                .where(UserLearningMastery.user_id == run.user_id)
                .order_by(UserLearningMastery.updated_at.desc(), UserLearningMastery.id.desc())
                .limit(_MAX_LIST_LENGTH)
            )
        ).scalars()
    )
    summaries = list(
        (
            await db.execute(
                select(AgentConversationSummary)
                .where(
                    AgentConversationSummary.thread_id == run.thread_id,
                    AgentConversationSummary.user_id == run.user_id,
                )
                .order_by(AgentConversationSummary.version.desc())
                .limit(_MAX_LIST_LENGTH)
            )
        ).scalars()
    )
    outbox_rows = list(
        (
            await db.execute(
                select(AgentMemoryUpdateOutbox)
                .where(AgentMemoryUpdateOutbox.thread_id == run.thread_id)
                .order_by(AgentMemoryUpdateOutbox.id.desc())
                .limit(_MAX_LIST_LENGTH)
            )
        ).scalars()
    )

    return {
        "thread_state": _memory_state_payload(state),
        "snapshot": _snapshot_payload(snapshot, snapshot_items),
        "memory_events": [
            {
                "id": event.id,
                "run_id": event.run_id,
                "memory_scope": event.memory_scope,
                "source_kind": event.source_kind,
                "fact_type": event.fact_type,
                "payload": _bounded_value(event.payload_json or {}),
                "created_at": utc_isoformat(event.created_at),
            }
            for event in reversed(memory_events)
        ],
        "memory_items": [
            {
                "id": item.id,
                "scope": item.scope,
                "item_type": item.item_type,
                "item_key": item.item_key,
                "status": item.status,
                "content_text": _bounded_value(item.content_text),
                "metadata": _bounded_value(item.metadata_json or {}),
                "source_snapshot_id": item.source_snapshot_id,
                "last_confirmed_run_id": item.last_confirmed_run_id,
                "updated_at": utc_isoformat(item.updated_at),
            }
            for item in reversed(memory_items)
        ],
        "mastery": [
            {
                "id": mastery.id,
                "knowledge_point_id": mastery.knowledge_point_id,
                "mastery_score": mastery.mastery_score,
                "evidence_count": mastery.evidence_count,
                "correct_count": mastery.correct_count,
                "incorrect_count": mastery.incorrect_count,
                "last_evidence_id": mastery.last_evidence_id,
                "last_graded_at": utc_isoformat(mastery.last_graded_at),
            }
            for mastery in reversed(masteries)
        ],
        "summaries": [
            {
                "id": summary.id,
                "version": summary.version,
                "start_sequence": summary.start_sequence,
                "end_sequence": summary.end_sequence,
                "summary_text": _bounded_value(summary.summary_text),
                "superseded_by_id": summary.superseded_by_id,
                "created_at": utc_isoformat(summary.created_at),
            }
            for summary in reversed(summaries)
        ],
        "outbox": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "event_type": row.event_type,
                "task_key": row.task_key,
                "status": row.status,
                "retry_count": row.retry_count,
                "scheduled_at": utc_isoformat(row.scheduled_at),
                "processed_at": utc_isoformat(row.processed_at),
            }
            for row in reversed(outbox_rows)
        ],
    }


async def record_memory_trace(
    db: AsyncSession,
    *,
    run: AgentRun,
    event_type: str,
    before: dict[str, Any],
    after: dict[str, Any],
    event_id: int | None = None,
    event_sequence: int | None = None,
) -> AgentMemoryTrace:
    """在当前事务中追加一条不可变的前后状态记录。"""
    trace = AgentMemoryTrace(
        run_id=run.id,
        thread_id=run.thread_id,
        user_id=run.user_id,
        event_id=event_id,
        event_sequence=event_sequence,
        event_type=event_type,
        changed=before != after,
        before_json=before,
        after_json=after,
    )
    db.add(trace)
    await db.flush()
    return trace
