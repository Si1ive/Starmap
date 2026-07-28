"""管理员记忆观测、Snapshot 复现与受约束 source 回查。"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AgentArtifact,
    AgentConversationSummary,
    AgentEvent,
    AgentMemoryItem,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMemoryTrace,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentPreferenceCandidate,
    AgentRun,
    AgentStep,
    AgentThread,
    UserLearningMastery,
)
from .time_utils import utc_isoformat

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "dsn",
    "database_url",
}
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
_CREDENTIAL_URL_PATTERN = re.compile(r"([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@", re.I)
_OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")


def redact_admin_value(value: Any) -> Any:
    """递归清理管理端响应中的凭证型字段，不改变普通业务 token 统计。"""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_KEYS or normalized.endswith("_secret"):
                cleaned[str(key)] = "[REDACTED]"
            else:
                cleaned[str(key)] = redact_admin_value(item)
        return cleaned
    if isinstance(value, list):
        return [redact_admin_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_admin_value(item) for item in value]
    if isinstance(value, str):
        if "Traceback (most recent call last)" in value:
            return "内部异常详情已隐藏"
        redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
        redacted = _CREDENTIAL_URL_PATTERN.sub(r"\1[REDACTED]@", redacted)
        return _OPENAI_KEY_PATTERN.sub("[REDACTED]", redacted)
    return value


def safe_error_summary(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return str(redact_admin_value(value.strip()))[:500]


def _serialize_snapshot_item(item: AgentMemorySnapshotItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "snapshot_id": item.snapshot_id,
        "memory_need": item.memory_need,
        "memory_partition": item.memory_partition,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "item_key": item.item_key,
        "version": item.version,
        "selected": bool(item.selected),
        "selection_reason": item.selection_reason,
        "dropped_reason": item.dropped_reason,
        "token_estimate": item.token_estimate,
        "frozen_payload": redact_admin_value(item.payload_json or {}),
        "source_lookup_supported": item.source_kind
        in {
            "message",
            "current_turn",
            "artifact",
            "conversation_summary",
            "user_learning_mastery",
            "memory_item",
            "preference_candidate",
        },
        "created_at": utc_isoformat(item.created_at),
    }


def _actual_tool_calls(events: list[AgentEvent]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in events:
        if event.event_type != "tool.called":
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        metadata = payload.get("public_metadata")
        actual = metadata if isinstance(metadata, dict) else {}
        calls.append(
            {
                "event_id": event.id,
                "sequence": event.sequence,
                "activity_id": payload.get("activity_id"),
                "attempt_id": payload.get("attempt_id"),
                "tool": actual.get("tool"),
                "query": actual.get("query"),
                "entity_type": actual.get("entity_type"),
                "difficulty": (
                    (actual.get("filters") or {}).get("difficulty")
                    if isinstance(actual.get("filters"), dict)
                    else None
                ),
                "chapter_ids": actual.get("chapter_ids") or [],
                "knowledge_point_ids": actual.get("knowledge_point_ids") or [],
                "exclude_entity_ids": actual.get("exclude_entity_ids") or [],
                "strict_chapter_scope": actual.get("strict_chapter_scope"),
                "filters": redact_admin_value(actual.get("filters") or {}),
                "limit": actual.get("limit"),
                "created_at": utc_isoformat(event.created_at),
            }
        )
    return calls


def _runtime_context_trace(steps: list[AgentStep]) -> list[dict[str, Any]]:
    """用相邻步骤的冻结输入还原运行时上下文变化，不混入长期 Memory。"""
    traces: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        input_data = step.input_data if isinstance(step.input_data, dict) else {}
        before = (
            input_data.get("variables")
            if isinstance(input_data.get("variables"), dict)
            else {}
        )
        next_input = (
            steps[index + 1].input_data
            if index + 1 < len(steps) and isinstance(steps[index + 1].input_data, dict)
            else {}
        )
        after = (
            next_input.get("variables")
            if isinstance(next_input.get("variables"), dict)
            else None
        )
        before_keys = set(before)
        after_keys = set(after or {})
        changed_keys = (
            sorted(
                key
                for key in before_keys | after_keys
                if before.get(key) != (after or {}).get(key)
            )
            if after is not None
            else []
        )
        traces.append(
            {
                "step_id": step.id,
                "node_name": step.node_name,
                "node_type": step.node_type,
                "status": step.status,
                "before": redact_admin_value(before),
                "output": redact_admin_value(step.output_data or {}),
                "next_step_before": (
                    redact_admin_value(after) if after is not None else None
                ),
                "added_keys": sorted(after_keys - before_keys),
                "removed_keys": sorted(before_keys - after_keys),
                "changed_keys": changed_keys,
                "started_at": utc_isoformat(step.started_at),
                "completed_at": utc_isoformat(step.completed_at),
            }
        )
    return traces


async def get_run_memory_observability(
    db: AsyncSession,
    run_id: str,
) -> dict[str, Any]:
    """读取单个 Run 的冻结理解、选择审计、真实工具参数和派生任务。"""
    run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run 不存在")
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    bound_snapshot_id = metadata.get("memory_snapshot_id")
    snapshot = await db.scalar(
        select(AgentMemorySnapshot).where(
            or_(
                AgentMemorySnapshot.run_id == run.id,
                AgentMemorySnapshot.id == bound_snapshot_id,
            ),
            AgentMemorySnapshot.user_id == run.user_id,
            AgentMemorySnapshot.thread_id == run.thread_id,
        )
    )
    items: list[AgentMemorySnapshotItem] = []
    if snapshot is not None:
        items = list(
            (
                await db.execute(
                    select(AgentMemorySnapshotItem)
                    .where(AgentMemorySnapshotItem.snapshot_id == snapshot.id)
                    .order_by(AgentMemorySnapshotItem.id)
                )
            ).scalars()
        )
    events = list(
        (
            await db.execute(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.id)
                .order_by(AgentEvent.sequence)
            )
        ).scalars()
    )
    outbox_rows = list(
        (
            await db.execute(
                select(AgentMemoryUpdateOutbox)
                .where(AgentMemoryUpdateOutbox.run_id == run.id)
                .order_by(AgentMemoryUpdateOutbox.id)
            )
        ).scalars()
    )
    memory_traces = list(
        (
            await db.execute(
                select(AgentMemoryTrace)
                .where(AgentMemoryTrace.run_id == run.id)
                .order_by(AgentMemoryTrace.id)
            )
        ).scalars()
    )
    steps = list(
        (
            await db.execute(
                select(AgentStep)
                .where(AgentStep.run_id == run.id)
                .order_by(AgentStep.started_at, AgentStep.id)
            )
        ).scalars()
    )
    context_audit = metadata.get("context_audit")
    model_calls = metadata.get("model_calls")
    safe_model_calls = (
        redact_admin_value(model_calls) if isinstance(model_calls, list) else []
    )
    selected_tokens = sum(item.token_estimate for item in items if item.selected)
    dropped_tokens = sum(item.token_estimate for item in items if not item.selected)
    return {
        "run": {
            "id": run.id,
            "thread_id": run.thread_id,
            "user_id": run.user_id,
            "workflow_key": run.workflow_key or run.workflow_name,
            "status": run.status,
            "raw_input": run.input_message,
        },
        "turn_understanding": redact_admin_value(
            (snapshot.understanding_json if snapshot else None)
            or metadata.get("turn_understanding")
            or {}
        ),
        "snapshot": (
            {
                "id": snapshot.id,
                "state_version": snapshot.state_version,
                "standalone_request": snapshot.standalone_request,
                "selection_metadata": redact_admin_value(
                    snapshot.selection_metadata_json or {}
                ),
                "memory_needs": sorted({item.memory_need for item in items}),
                "created_at": utc_isoformat(snapshot.created_at),
            }
            if snapshot
            else None
        ),
        "items": [_serialize_snapshot_item(item) for item in items],
        "token_budget": {
            "configured": (
                context_audit.get("token_budget")
                if isinstance(context_audit, dict)
                else None
            ),
            "context_estimated": (
                context_audit.get("estimated_tokens")
                if isinstance(context_audit, dict)
                else None
            ),
            "selected_items": selected_tokens,
            "dropped_items": dropped_tokens,
        },
        "model": {
            "config_id": metadata.get("model_config_id"),
            "name": metadata.get("model_name"),
            "provider": metadata.get("model_provider"),
            "model_call_count": run.model_call_count,
            "max_model_calls": run.max_model_calls,
            "final_model_call_id": (
                safe_model_calls[-1].get("id") if safe_model_calls else None
            ),
            "calls": safe_model_calls,
        },
        "tool_calls": _actual_tool_calls(events),
        "runtime_context_trace": _runtime_context_trace(steps),
        "memory_outbox": [
            {
                "id": row.id,
                "event_type": row.event_type,
                "task_key": row.task_key,
                "status": row.status,
                "retry_count": row.retry_count,
                "safe_error_summary": safe_error_summary(row.last_error_message),
                "scheduled_at": utc_isoformat(row.scheduled_at),
                "processed_at": utc_isoformat(row.processed_at),
                "created_at": utc_isoformat(row.created_at),
            }
            for row in outbox_rows
        ],
        "memory_trace": [
            {
                "id": trace.id,
                "event_id": trace.event_id,
                "event_sequence": trace.event_sequence,
                "event_type": trace.event_type,
                "changed": bool(trace.changed),
                "before": redact_admin_value(trace.before_json or {}),
                "after": redact_admin_value(trace.after_json or {}),
                "created_at": utc_isoformat(trace.created_at),
            }
            for trace in memory_traces
        ],
    }


_CONVERSATION_MEMORY_SECTIONS = (
    "thread_state",
    "snapshot",
    "memory_events",
    "memory_items",
    "mastery",
    "summaries",
)


def _conversation_memory_state(value: Any) -> dict[str, Any]:
    """只保留管理员要比较的记忆域，排除 Outbox 等运维状态。"""
    source = value if isinstance(value, dict) else {}
    return {
        section: redact_admin_value(source.get(section))
        for section in _CONVERSATION_MEMORY_SECTIONS
    }


def _changed_memory_sections(
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[str]:
    return [
        section
        for section in _CONVERSATION_MEMORY_SECTIONS
        if before.get(section) != after.get(section)
    ]


def _section_token_total(section: str, value: Any) -> int:
    """Count selected frozen Snapshot tokens without guessing tokens for other domains."""
    if section != "snapshot" or not isinstance(value, dict):
        return 0
    items = value.get("items")
    if not isinstance(items, list):
        return 0
    return sum(
        int(item.get("token_estimate") or 0)
        for item in items
        if isinstance(item, dict) and item.get("selected") is True
    )


def _conversation_section_states(
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[dict[str, Any]]:
    states = []
    for section in _CONVERSATION_MEMORY_SECTIONS:
        before_tokens = _section_token_total(section, before.get(section))
        after_tokens = _section_token_total(section, after.get(section))
        states.append(
            {
                "key": section,
                "changed": before.get(section) != after.get(section),
                "before": before.get(section),
                "after": after.get(section),
                "token_before": before_tokens,
                "token_after": after_tokens,
                "token_delta": after_tokens - before_tokens,
            }
        )
    return states


async def get_conversation_memory_observability(
    db: AsyncSession,
    thread_id: str,
) -> dict[str, Any]:
    """按会话轮次投影连续记忆状态，避免把事件采样误判为“无变化”。"""
    thread = await db.scalar(select(AgentThread).where(AgentThread.id == thread_id))
    if thread is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    runs = list(
        (
            await db.execute(
                select(AgentRun)
                .where(
                    AgentRun.thread_id == thread.id,
                    AgentRun.user_id == thread.user_id,
                )
                .order_by(AgentRun.created_at, AgentRun.id)
            )
        ).scalars()
    )
    root_runs = [run for run in runs if run.parent_run_id is None]
    run_to_root = {
        run.id: (run.root_run_id or run.parent_run_id or run.id) for run in runs
    }
    traces = list(
        (
            await db.execute(
                select(AgentMemoryTrace)
                .where(
                    AgentMemoryTrace.thread_id == thread.id,
                    AgentMemoryTrace.user_id == thread.user_id,
                )
                .order_by(AgentMemoryTrace.created_at, AgentMemoryTrace.id)
            )
        ).scalars()
    )
    traces_by_root: dict[str, list[AgentMemoryTrace]] = {
        run.id: [] for run in root_runs
    }
    for trace in traces:
        root_id = run_to_root.get(trace.run_id)
        if root_id in traces_by_root:
            traces_by_root[root_id].append(trace)

    turns: list[dict[str, Any]] = []
    previous_state = _conversation_memory_state({})
    for turn_number, root_run in enumerate(root_runs, start=1):
        turn_traces = traces_by_root.get(root_run.id, [])
        if turn_traces:
            # 第一轮从空状态开始，确保首次建立 Snapshot/线程状态可见；后续轮次
            # 以前一轮最终状态为基线，捕获发生在相邻事件采样之间的真实变化。
            final_state = _conversation_memory_state(turn_traces[-1].after_json)
            changed_sections = _changed_memory_sections(previous_state, final_state)
            observed_at = utc_isoformat(turn_traces[-1].created_at)
        else:
            final_state = previous_state
            changed_sections = []
            observed_at = utc_isoformat(root_run.completed_at or root_run.updated_at)
        turns.append(
            {
                "turn_number": turn_number,
                "root_run_id": root_run.id,
                "input_message": root_run.input_message,
                "status": root_run.status,
                "changed": bool(changed_sections),
                "changed_sections": changed_sections,
                "sections": _conversation_section_states(
                    previous_state,
                    final_state,
                ),
                "before": previous_state,
                "after": final_state,
                "token_totals": {
                    "before": sum(
                        _section_token_total(section, previous_state.get(section))
                        for section in _CONVERSATION_MEMORY_SECTIONS
                    ),
                    "after": sum(
                        _section_token_total(section, final_state.get(section))
                        for section in _CONVERSATION_MEMORY_SECTIONS
                    ),
                },
                "trace_count": len(turn_traces),
                "observed_at": observed_at,
            }
        )
        turns[-1]["token_totals"]["delta"] = (
            turns[-1]["token_totals"]["after"] - turns[-1]["token_totals"]["before"]
        )
        previous_state = final_state

    return {
        "thread": {
            "id": thread.id,
            "user_id": thread.user_id,
            "title": thread.title,
            "status": thread.status,
        },
        "turns": turns,
        "changed_turn_count": sum(1 for turn in turns if turn["changed"]),
    }


async def replay_run_memory_snapshot(
    db: AsyncSession,
    run_id: str,
) -> dict[str, Any]:
    """按原顺序只读重组旧 Snapshot；不调用模型、工具或当前记忆选择器。"""
    payload = await get_run_memory_observability(db, run_id)
    snapshot = payload["snapshot"]
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Run Snapshot 不存在")
    return {
        "mode": "frozen_snapshot_read_only",
        "run": payload["run"],
        "turn_understanding": payload["turn_understanding"],
        "snapshot": snapshot,
        "ordered_items": payload["items"],
        "token_budget": payload["token_budget"],
        "model": payload["model"],
        "actual_tool_calls": payload["tool_calls"],
    }


async def get_snapshot_item_source(
    db: AsyncSession,
    *,
    run_id: str,
    item_id: int,
) -> dict[str, Any]:
    """经 Run/Snapshot 绑定回查 source；缺失、越权与版本漂移统一安全 404。"""
    row = (
        await db.execute(
            select(AgentMemorySnapshotItem, AgentMemorySnapshot, AgentRun)
            .join(
                AgentMemorySnapshot,
                AgentMemorySnapshot.id == AgentMemorySnapshotItem.snapshot_id,
            )
            .join(AgentRun, AgentRun.id == AgentMemorySnapshot.run_id)
            .where(
                AgentRun.id == run_id,
                AgentMemorySnapshotItem.id == item_id,
                AgentMemorySnapshot.user_id == AgentRun.user_id,
                AgentMemorySnapshot.thread_id == AgentRun.thread_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="记忆来源不存在")
    item, snapshot, run = row
    current, current_version, superseded = await _load_current_source(
        db,
        item=item,
        user_id=run.user_id,
        thread_id=run.thread_id,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="记忆来源不存在")
    if (
        item.version is not None
        and current_version is not None
        and item.version != current_version
    ):
        raise HTTPException(status_code=404, detail="记忆来源不存在")
    return {
        "run_id": run.id,
        "snapshot_id": snapshot.id,
        "item_id": item.id,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "frozen_version": item.version,
        "current_version": current_version,
        "superseded": superseded,
        "frozen_copy": redact_admin_value(item.payload_json or {}),
        "current_source": redact_admin_value(current),
    }


async def _load_current_source(
    db: AsyncSession,
    *,
    item: AgentMemorySnapshotItem,
    user_id: str,
    thread_id: str,
) -> tuple[dict[str, Any] | None, int | None, bool]:
    source_id = item.source_id
    if not source_id:
        return None, None, False
    if item.source_kind in {"message", "current_turn"}:
        source = await db.scalar(
            select(AgentMessage).where(
                AgentMessage.id == source_id,
                AgentMessage.user_id == user_id,
                AgentMessage.thread_id == thread_id,
            )
        )
        if source is None:
            return None, None, False
        return (
            {
                "role": source.role,
                "status": source.status,
                "content_text": source.content_text,
                "content_blocks": source.content_blocks_json or [],
            },
            None,
            False,
        )
    if item.source_kind == "artifact":
        source = await db.scalar(
            select(AgentArtifact)
            .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
            .where(
                AgentArtifact.id == source_id,
                AgentRun.user_id == user_id,
                AgentRun.thread_id == thread_id,
            )
        )
        if source is None:
            return None, None, False
        return (
            {
                "artifact_type": source.artifact_type,
                "content": source.content_json,
                "metadata": source.metadata_json or {},
            },
            None,
            False,
        )
    if item.source_kind == "conversation_summary":
        source = await db.scalar(
            select(AgentConversationSummary).where(
                AgentConversationSummary.id == source_id,
                AgentConversationSummary.user_id == user_id,
                AgentConversationSummary.thread_id == thread_id,
            )
        )
        if source is None:
            return None, None, False
        return (
            {
                "summary_text": source.summary_text,
                "start_sequence": source.start_sequence,
                "end_sequence": source.end_sequence,
                "source_message_ids": source.source_message_ids_json or [],
                "superseded_by_id": source.superseded_by_id,
            },
            source.version,
            source.superseded_by_id is not None,
        )
    if item.source_kind == "user_learning_mastery":
        try:
            mastery_id = int(source_id)
        except ValueError:
            return None, None, False
        source = await db.scalar(
            select(UserLearningMastery).where(
                UserLearningMastery.id == mastery_id,
                UserLearningMastery.user_id == user_id,
            )
        )
        if source is None:
            return None, None, False
        return (
            {
                "knowledge_point_id": source.knowledge_point_id,
                "mastery_score": source.mastery_score,
                "evidence_count": source.evidence_count,
                "correct_count": source.correct_count,
                "incorrect_count": source.incorrect_count,
                "last_evidence_id": source.last_evidence_id,
                "last_graded_at": utc_isoformat(source.last_graded_at),
            },
            source.evidence_count,
            False,
        )
    if item.source_kind == "memory_item":
        source = await db.scalar(
            select(AgentMemoryItem).where(
                AgentMemoryItem.id == source_id,
                AgentMemoryItem.user_id == user_id,
            )
        )
        if source is None or (
            source.scope == "thread" and source.thread_id != thread_id
        ):
            return None, None, False
        version = int((source.metadata_json or {}).get("source_memory_event_id") or 0)
        return (
            {
                "scope": source.scope,
                "item_type": source.item_type,
                "item_key": source.item_key,
                "status": source.status,
                "content_text": source.content_text,
                "metadata": source.metadata_json or {},
            },
            version,
            source.status != "active",
        )
    if item.source_kind == "preference_candidate":
        source = await db.scalar(
            select(AgentPreferenceCandidate).where(
                AgentPreferenceCandidate.id == source_id,
                AgentPreferenceCandidate.user_id == user_id,
            )
        )
        if source is None or (
            source.scope == "thread" and source.thread_id != thread_id
        ):
            return None, None, False
        return (
            {
                "scope": source.scope,
                "preference_key": source.preference_key,
                "preference_value": source.preference_value_json,
                "confidence": source.confidence,
                "status": source.status,
                "source_kind": source.source_kind,
                "source_id": source.source_id,
            },
            1,
            source.status in {"invalidated", "rejected"},
        )
    return None, None, False
