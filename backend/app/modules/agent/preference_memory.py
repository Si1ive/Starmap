"""偏好候选生产、用户治理、冲突解析与 Snapshot 冻结。"""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from .memory_contracts import MemoryNeed, MemoryPartition
from .model_runtime.preference_extractor import (
    PreferenceCandidateProposal,
    PreferenceExtractionDeps,
    PreferenceExtractionRuntime,
    preference_extraction_runtime,
)
from .models import (
    AgentMemoryItem,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentPreferenceCandidate,
    AgentRun,
)
from .time_utils import utc_isoformat, utc_now

logger = get_logger(__name__)

PREFERENCE_EXTRACTION_TASK = "preference_candidate_extraction"
_CANDIDATE_NAMESPACE = uuid.UUID("90990686-9903-4576-9c55-d3ddd4dfc485")
_DAILY_MINUTES_PATTERN = re.compile(
    r"(?:我(?:通常|一般)?\s*)?(?:每天|每日)\s*(?:想|希望|计划)?\s*"
    r"(?:学习|复习)?\s*(\d{1,4})\s*分钟"
)
_DETAIL_PATTERN = re.compile(
    r"(?:回答|讲解|解释)(?:时)?(?:请|希望你)?(?:尽量|更)?\s*(简洁|详细|精简|深入)"
)
_EXPLICIT_PAIR_PATTERN = re.compile(
    r"(?:本轮)?偏好\s*[:：]\s*([a-z][a-z0-9_]{1,63})\s*=\s*([^，,；;\n]+)",
    re.IGNORECASE,
)


class PreferenceSource(BaseModel):
    preference_key: str
    value: str | int | bool
    source_priority: Literal[
        "current_turn_explicit",
        "trusted_business_event",
        "model_extracted_candidate",
    ]
    source_kind: str
    source_id: str
    scope: Literal["user", "thread"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    candidate_status: str | None = None
    event_at: str | None = None
    dropped_reason: str | None = None


class PreferenceBundle(BaseModel):
    snapshot_id: str | None = None
    values: dict[str, str | int | bool] = Field(default_factory=dict)
    selected_sources: list[PreferenceSource] = Field(default_factory=list)
    dropped_sources: list[PreferenceSource] = Field(default_factory=list)


def _candidate_id(
    user_id: str,
    source_kind: str,
    source_id: str,
    preference_key: str,
) -> str:
    stable = uuid.uuid5(
        _CANDIDATE_NAMESPACE,
        f"{user_id}:{source_kind}:{source_id}:{preference_key}",
    )
    return f"prefcand_{stable.hex[:20]}"


def _preference_value(payload: dict[str, Any]) -> str | int | bool | None:
    value = payload.get("value")
    if isinstance(value, (str, int, bool)):
        return value
    return None


def extract_explicit_preferences(text: str) -> dict[str, str | int | bool]:
    """只识别明确、结构化的本轮陈述，不用模型猜测当前最高优先级。"""
    normalized = text.strip()
    preferences: dict[str, str | int | bool] = {}
    minutes = _DAILY_MINUTES_PATTERN.search(normalized)
    if minutes:
        value = int(minutes.group(1))
        if 1 <= value <= 1440:
            preferences["daily_study_minutes"] = value
    detail = _DETAIL_PATTERN.search(normalized)
    if detail:
        preferences["response_detail"] = (
            "concise" if detail.group(1) in {"简洁", "精简"} else "detailed"
        )
    for pair in _EXPLICIT_PAIR_PATTERN.finditer(normalized):
        key = pair.group(1).lower()
        raw_value = pair.group(2).strip()
        if raw_value.isdigit():
            value: str | int | bool = int(raw_value)
        elif raw_value.casefold() in {"true", "false"}:
            value = raw_value.casefold() == "true"
        else:
            value = raw_value[:500]
        preferences[key] = value
    return preferences


async def enqueue_preference_candidate_extraction(
    db: AsyncSession,
    run: AgentRun,
) -> None:
    """只为已完成根 conversation Run 的原始用户消息追加候选抽取任务。"""
    if (
        run.status != "completed"
        or run.workflow_name != "conversation"
        or run.parent_run_id is not None
        or not run.trigger_message_id
        or not (run.input_message or "").strip()
    ):
        return
    existing = await db.scalar(
        select(AgentMemoryUpdateOutbox).where(
            AgentMemoryUpdateOutbox.run_id == run.id,
            AgentMemoryUpdateOutbox.event_type == PREFERENCE_EXTRACTION_TASK,
        )
    )
    payload = {
        "task_type": PREFERENCE_EXTRACTION_TASK,
        "source_kind": "message",
        "source_id": run.trigger_message_id,
        "source_version": 1,
    }
    if existing is not None:
        if existing.payload_json != payload:
            raise ValueError("同一 Run 的偏好抽取来源不一致")
        return
    try:
        async with db.begin_nested():
            db.add(
                AgentMemoryUpdateOutbox(
                    run_id=run.id,
                    thread_id=run.thread_id,
                    user_id=run.user_id,
                    event_type=PREFERENCE_EXTRACTION_TASK,
                    status="pending",
                    payload_json=payload,
                )
            )
            await db.flush()
    except IntegrityError:
        logger.info("偏好候选抽取任务并发幂等命中", run_id=run.id)


class PreferenceCandidateProjector:
    def __init__(
        self,
        runtime: PreferenceExtractionRuntime = preference_extraction_runtime,
    ) -> None:
        self.runtime = runtime

    async def process_outbox(
        self,
        db: AsyncSession,
        outbox: AgentMemoryUpdateOutbox,
    ) -> int:
        payload = outbox.payload_json or {}
        if (
            outbox.event_type != PREFERENCE_EXTRACTION_TASK
            or payload.get("task_type") != PREFERENCE_EXTRACTION_TASK
            or payload.get("source_kind") != "message"
            or int(payload.get("source_version") or 0) != 1
        ):
            raise ValueError("偏好候选 Outbox 契约不匹配")
        source_id = str(payload.get("source_id") or "")
        run = await db.scalar(
            select(AgentRun).where(
                AgentRun.id == outbox.run_id,
                AgentRun.user_id == outbox.user_id,
                AgentRun.thread_id == outbox.thread_id,
                AgentRun.workflow_name == "conversation",
                AgentRun.parent_run_id.is_(None),
                AgentRun.status == "completed",
                AgentRun.trigger_message_id == source_id,
            )
        )
        message = await db.scalar(
            select(AgentMessage).where(
                AgentMessage.id == source_id,
                AgentMessage.user_id == outbox.user_id,
                AgentMessage.thread_id == outbox.thread_id,
                AgentMessage.role == "user",
                AgentMessage.status == "completed",
            )
        )
        if run is None or message is None or not (message.content_text or "").strip():
            raise ValueError("偏好候选任务找不到同作用域原始用户消息")
        existing = list(
            (
                await db.execute(
                    select(AgentPreferenceCandidate).where(
                        AgentPreferenceCandidate.user_id == outbox.user_id,
                        AgentPreferenceCandidate.source_kind == "message",
                        AgentPreferenceCandidate.source_id == source_id,
                    )
                )
            ).scalars()
        )
        if existing:
            return len(existing)
        batch = await self.runtime.extract(
            message.content_text,
            deps=PreferenceExtractionDeps(
                user_id=outbox.user_id,
                thread_id=outbox.thread_id,
                run_id=outbox.run_id,
            ),
            db=db,
        )
        for proposal in batch.candidates:
            self._add_candidate(
                db,
                outbox=outbox,
                source_id=source_id,
                proposal=proposal,
                extractor_version=batch.extractor_version,
                model_name=batch.model_name,
                model_config_id=batch.model_config_id,
            )
        await db.flush()
        return len(batch.candidates)

    @staticmethod
    def _add_candidate(
        db: AsyncSession,
        *,
        outbox: AgentMemoryUpdateOutbox,
        source_id: str,
        proposal: PreferenceCandidateProposal,
        extractor_version: str,
        model_name: str,
        model_config_id: str | None,
    ) -> None:
        db.add(
            AgentPreferenceCandidate(
                id=_candidate_id(
                    outbox.user_id,
                    "message",
                    source_id,
                    proposal.preference_key,
                ),
                user_id=outbox.user_id,
                thread_id=outbox.thread_id,
                run_id=outbox.run_id,
                scope=proposal.scope,
                source_kind="message",
                source_id=source_id,
                source_version=1,
                preference_key=proposal.preference_key,
                preference_value_json={"value": proposal.value},
                confidence=proposal.confidence,
                status="pending",
                extractor_version=extractor_version,
                model_name=model_name,
                model_config_id=model_config_id,
            )
        )


async def list_preference_candidates(
    db: AsyncSession,
    *,
    user_id: str,
    status: str | None = None,
    limit: int = 100,
) -> list[AgentPreferenceCandidate]:
    statement = select(AgentPreferenceCandidate).where(
        AgentPreferenceCandidate.user_id == user_id
    )
    if status:
        statement = statement.where(AgentPreferenceCandidate.status == status)
    result = await db.execute(
        statement.order_by(
            AgentPreferenceCandidate.created_at.desc(),
            AgentPreferenceCandidate.id.desc(),
        ).limit(limit)
    )
    return list(result.scalars())


async def decide_preference_candidate(
    db: AsyncSession,
    *,
    candidate_id: str,
    user_id: str,
    decision: Literal["approved", "rejected"],
    reason: str | None = None,
) -> AgentPreferenceCandidate | None:
    candidate = await db.scalar(
        select(AgentPreferenceCandidate).where(
            AgentPreferenceCandidate.id == candidate_id,
            AgentPreferenceCandidate.user_id == user_id,
        )
    )
    if candidate is None:
        return None
    # 同一用户、作用域和 key 的决定必须串行化，避免两个并发批准都物化 active 项。
    sibling_statement = select(AgentPreferenceCandidate.id).where(
        AgentPreferenceCandidate.user_id == candidate.user_id,
        AgentPreferenceCandidate.scope == candidate.scope,
        AgentPreferenceCandidate.preference_key == candidate.preference_key,
    )
    if candidate.scope == "thread":
        sibling_statement = sibling_statement.where(
            AgentPreferenceCandidate.thread_id == candidate.thread_id
        )
    await db.execute(
        sibling_statement.order_by(AgentPreferenceCandidate.id).with_for_update()
    )
    await db.refresh(candidate)
    if candidate.status == decision:
        return candidate
    if candidate.status != "pending":
        return None
    if candidate.scope == "thread" and not candidate.thread_id:
        return None
    candidate.status = decision
    candidate.decided_by = user_id
    candidate.decision_reason = (reason or "").strip()[:255] or None
    candidate.decided_at = utc_now()
    if decision == "approved":
        await _materialize_approved_preference(db, candidate)
    await db.flush()
    return candidate


async def _materialize_approved_preference(
    db: AsyncSession,
    candidate: AgentPreferenceCandidate,
) -> AgentMemoryItem:
    active_items = list(
        (
            await db.execute(
                select(AgentMemoryItem).where(
                    AgentMemoryItem.user_id == candidate.user_id,
                    AgentMemoryItem.scope == candidate.scope,
                    AgentMemoryItem.item_type == "user_preference",
                    AgentMemoryItem.status == "active",
                )
            )
        ).scalars()
    )
    for item in active_items:
        metadata = item.metadata_json or {}
        if metadata.get("preference_key") == candidate.preference_key:
            if candidate.scope == "user" or item.thread_id == candidate.thread_id:
                item.status = "superseded"
    value = _preference_value(candidate.preference_value_json or {})
    if value is None:
        raise ValueError("批准的偏好候选缺少合法结构化值")
    item = AgentMemoryItem(
        id=f"memitem_{uuid.uuid4().hex[:20]}",
        user_id=candidate.user_id,
        thread_id=(candidate.thread_id if candidate.scope == "thread" else None),
        scope=candidate.scope,
        item_type="user_preference",
        item_key=f"preference:{candidate.preference_key}:{candidate.id}",
        status="active",
        content_text=f"{candidate.preference_key}={value}",
        metadata_json={
            "preference_key": candidate.preference_key,
            "preference_value": value,
            "source_candidate_id": candidate.id,
            "source_kind": candidate.source_kind,
            "source_id": candidate.source_id,
            "source_thread_id": candidate.thread_id,
            "confidence": candidate.confidence,
            "approval_status": "approved",
            "decided_at": utc_isoformat(candidate.decided_at),
        },
        last_confirmed_run_id=candidate.run_id,
    )
    db.add(item)
    await db.flush()
    return item


def _candidate_source(candidate: AgentPreferenceCandidate) -> PreferenceSource | None:
    value = _preference_value(candidate.preference_value_json or {})
    if value is None:
        return None
    return PreferenceSource(
        preference_key=candidate.preference_key,
        value=value,
        source_priority=(
            "trusted_business_event"
            if candidate.status in {"approved", "rejected"}
            else "model_extracted_candidate"
        ),
        source_kind="preference_candidate",
        source_id=candidate.id,
        scope=candidate.scope,
        confidence=candidate.confidence,
        candidate_status=candidate.status,
        event_at=utc_isoformat(candidate.decided_at or candidate.created_at),
    )


async def _resolve_preference_sources(
    db: AsyncSession,
    *,
    user_id: str,
    thread_id: str,
    explicit: dict[str, str | int | bool],
    explicit_source_id: str,
) -> tuple[list[PreferenceSource], list[PreferenceSource]]:
    candidates = list(
        (
            await db.execute(
                select(AgentPreferenceCandidate).where(
                    AgentPreferenceCandidate.user_id == user_id,
                    or_(
                        AgentPreferenceCandidate.scope == "user",
                        (
                            (AgentPreferenceCandidate.scope == "thread")
                            & (AgentPreferenceCandidate.thread_id == thread_id)
                        ),
                    ),
                )
            )
        ).scalars()
    )
    by_key: dict[str, list[AgentPreferenceCandidate]] = {}
    for candidate in candidates:
        by_key.setdefault(candidate.preference_key, []).append(candidate)

    selected: list[PreferenceSource] = []
    dropped: list[PreferenceSource] = []
    for key in sorted(set(by_key) | set(explicit)):
        rows = by_key.get(key, [])
        approved = sorted(
            (row for row in rows if row.status == "approved"),
            key=lambda row: (row.decided_at or row.created_at, row.id),
            reverse=True,
        )
        if key in explicit:
            selected.append(
                PreferenceSource(
                    preference_key=key,
                    value=explicit[key],
                    source_priority="current_turn_explicit",
                    source_kind="current_turn",
                    source_id=explicit_source_id,
                    scope="thread",
                )
            )
        elif approved:
            source = _candidate_source(approved[0])
            if source is not None:
                selected.append(source)
        approved_winner_id = approved[0].id if approved else None
        for row in rows:
            source = _candidate_source(row)
            if source is None:
                continue
            if key in explicit and row.status == "approved":
                reason = "overridden_by_current_turn"
            elif row.status == "approved" and row.id != approved_winner_id:
                reason = "superseded_by_business_event"
            elif row.status == "pending":
                reason = "pending_user_approval"
            elif row.status == "rejected":
                reason = "rejected_by_user"
            elif row.status == "invalidated":
                reason = "source_invalidated"
            else:
                continue
            dropped.append(source.model_copy(update={"dropped_reason": reason}))
    return selected, dropped


async def _load_frozen_preference_bundle(
    db: AsyncSession,
    *,
    snapshot_id: str,
    memory_need: MemoryNeed,
) -> PreferenceBundle | None:
    items = list(
        (
            await db.execute(
                select(AgentMemorySnapshotItem)
                .where(
                    AgentMemorySnapshotItem.snapshot_id == snapshot_id,
                    AgentMemorySnapshotItem.memory_need == memory_need.value,
                    AgentMemorySnapshotItem.memory_partition
                    == MemoryPartition.USER_PREFERENCE.value,
                )
                .order_by(AgentMemorySnapshotItem.id)
            )
        ).scalars()
    )
    if not any(item.source_kind == "preference_selection_marker" for item in items):
        return None
    selected = []
    dropped = []
    for item in items:
        if item.source_kind == "preference_selection_marker":
            continue
        try:
            source = PreferenceSource.model_validate(item.payload_json or {})
        except ValueError:
            continue
        (selected if item.selected else dropped).append(source)
    return PreferenceBundle(
        snapshot_id=snapshot_id,
        values={source.preference_key: source.value for source in selected},
        selected_sources=selected,
        dropped_sources=dropped,
    )


async def _freeze_preference_bundle(
    db: AsyncSession,
    *,
    snapshot_id: str,
    memory_need: MemoryNeed,
    selected: list[PreferenceSource],
    dropped: list[PreferenceSource],
) -> PreferenceBundle:
    await db.scalar(
        select(AgentMemorySnapshot.id)
        .where(AgentMemorySnapshot.id == snapshot_id)
        .with_for_update()
    )
    frozen = await _load_frozen_preference_bundle(
        db,
        snapshot_id=snapshot_id,
        memory_need=memory_need,
    )
    if frozen is not None:
        return frozen
    for index, source in enumerate([*selected, *dropped], start=1):
        is_selected = source.dropped_reason is None
        db.add(
            AgentMemorySnapshotItem(
                snapshot_id=snapshot_id,
                memory_need=memory_need.value,
                memory_partition=MemoryPartition.USER_PREFERENCE.value,
                source_kind=source.source_kind,
                source_id=source.source_id,
                item_key=(
                    f"{memory_need.value}:preference:{source.preference_key}:"
                    f"{source.source_id}:{index}"
                ),
                version=1,
                selected=is_selected,
                selection_reason=(
                    source.source_priority if is_selected else "preference_conflict"
                ),
                dropped_reason=source.dropped_reason,
                token_estimate=0,
                payload_json=source.model_dump(mode="json"),
            )
        )
    db.add(
        AgentMemorySnapshotItem(
            snapshot_id=snapshot_id,
            memory_need=memory_need.value,
            memory_partition=MemoryPartition.USER_PREFERENCE.value,
            source_kind="preference_selection_marker",
            source_id=snapshot_id,
            item_key=f"{memory_need.value}:preference:selection_complete",
            version=1,
            selected=False,
            selection_reason="preference_selection_complete",
            token_estimate=0,
            payload_json={
                "selected_count": len(selected),
                "dropped_count": len(dropped),
            },
        )
    )
    await db.flush()
    return PreferenceBundle(
        snapshot_id=snapshot_id,
        values={source.preference_key: source.value for source in selected},
        selected_sources=selected,
        dropped_sources=dropped,
    )


async def load_preference_bundle(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
    memory_need: MemoryNeed = MemoryNeed.PLANNING_GOAL,
) -> PreferenceBundle:
    run = await db.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
    )
    if run is None:
        return PreferenceBundle()
    snapshot_id = (run.metadata_json or {}).get("memory_snapshot_id")
    snapshot = None
    if snapshot_id:
        snapshot = await db.scalar(
            select(AgentMemorySnapshot).where(
                AgentMemorySnapshot.id == snapshot_id,
                AgentMemorySnapshot.user_id == user_id,
                AgentMemorySnapshot.thread_id == run.thread_id,
            )
        )
    if snapshot is not None:
        frozen = await _load_frozen_preference_bundle(
            db,
            snapshot_id=snapshot.id,
            memory_need=memory_need,
        )
        if frozen is not None:
            return frozen
    understanding = snapshot.understanding_json or {} if snapshot is not None else {}
    explicit_text = str(
        understanding.get("raw_input")
        or (snapshot.standalone_request if snapshot is not None else run.input_message)
        or ""
    )
    selected, dropped = await _resolve_preference_sources(
        db,
        user_id=user_id,
        thread_id=run.thread_id,
        explicit=extract_explicit_preferences(explicit_text),
        explicit_source_id=(
            run.trigger_message_id or (snapshot.id if snapshot else run.id)
        ),
    )
    if snapshot is not None:
        return await _freeze_preference_bundle(
            db,
            snapshot_id=snapshot.id,
            memory_need=memory_need,
            selected=selected,
            dropped=dropped,
        )
    return PreferenceBundle(
        values={source.preference_key: source.value for source in selected},
        selected_sources=selected,
        dropped_sources=dropped,
    )


preference_candidate_projector = PreferenceCandidateProjector()
