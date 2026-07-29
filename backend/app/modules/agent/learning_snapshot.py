"""ConversationTutorAgent 使用的只读 LearningSnapshot 摘要。

这里不把掌握度计算搬进在线路由：掌握度仍由既有 projector 写入，Tutor 只读取当前
Run 已冻结的 mastery signals 和未过期的 Observer diagnostic hypotheses。Observer
hypothesis 首次进入下一轮时复制为 Snapshot item，保证同一 Run 内不会混用 live 状态。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning.models import LearningActivityEvent

from .memory_contracts import MemoryPartition
from .models import AgentMemorySnapshot, AgentMemorySnapshotItem
from .time_utils import utc_now

LEARNING_SNAPSHOT_POLICY_VERSION = "learning-snapshot-v1"
_MAX_MASTERY_SIGNALS = 16
_MAX_DIAGNOSTIC_HYPOTHESES = 16
_HYPOTHESIS_TTL_DAYS = 14


class LearningSnapshotSummary(BaseModel):
    """本轮 Tutor 可消费的、已按 Run 冻结的学习状态摘要。"""

    model_config = ConfigDict(extra="forbid")

    policy_version: str = LEARNING_SNAPSHOT_POLICY_VERSION
    snapshot_id: str | None = None
    state_version: int | None = None
    active_topic: dict[str, Any] | None = None
    mastery_signals: list[dict[str, Any]] = Field(default_factory=list)
    diagnostic_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    source_item_ids: list[int] = Field(default_factory=list)

    @property
    def known_knowledge_point_ids(self) -> tuple[str, ...]:
        """返回服务端已经冻结过的知识点 ID，供 Router 做目标范围校验。"""

        values: list[str] = []
        if isinstance(self.active_topic, dict):
            topic_id = str(self.active_topic.get("entity_id") or "").strip()
            if topic_id and self.active_topic.get("entity_type") == "knowledge_point":
                values.append(topic_id)
        for signal in self.mastery_signals:
            point_id = str(signal.get("knowledge_point_id") or "").strip()
            if point_id:
                values.append(point_id)
        for hypothesis in self.diagnostic_hypotheses:
            point_id = str(hypothesis.get("knowledge_point_id") or "").strip()
            if point_id:
                values.append(point_id)
        return tuple(dict.fromkeys(values))


def _safe_mastery_signal(payload: dict[str, Any]) -> dict[str, Any] | None:
    """只复制掌握度选择器的稳定字段，不把任意 JSON 交给模型。"""

    point_id = str(payload.get("knowledge_point_id") or "").strip()
    if not point_id:
        return None
    signal: dict[str, Any] = {"knowledge_point_id": point_id}
    for key in (
        "knowledge_point_title",
        "knowledge_point_aliases",
        "effective_mastery_score",
        "mastery_score",
        "raw_mastery_score",
        "evidence_count",
        "last_evidence_id",
        "evidence_at",
        "decay_policy_version",
    ):
        if key in payload:
            signal[key] = payload[key]
    return signal


def _parse_expiry(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _safe_hypothesis(
    payload: dict[str, Any], *, now: datetime
) -> dict[str, Any] | None:
    """只复制 Observer 的稳定 hypothesis 字段，并在读时执行 TTL。"""

    expires_at = _parse_expiry(payload.get("expires_at"))
    if expires_at is None or expires_at <= now:
        return None
    source_message_id = str(payload.get("source_message_id") or "").strip()
    signal = str(payload.get("signal") or "").strip()
    if not source_message_id or not signal:
        return None
    return {
        key: payload[key]
        for key in (
            "knowledge_point_id",
            "signal",
            "outcome",
            "error_tags",
            "model_confidence",
            "diagnostic_need",
            "source_message_id",
            "observer_version",
            "source_run_id",
            "expires_at",
        )
        if key in payload
    }


async def _freeze_diagnostic_hypotheses(
    db: AsyncSession,
    *,
    snapshot: AgentMemorySnapshot,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[int]]:
    """把当前有效 Observer hypothesis 复制到本轮 Snapshot，避免在线漂移。"""

    frozen_items = list(
        (
            await db.scalars(
                select(AgentMemorySnapshotItem)
                .where(
                    AgentMemorySnapshotItem.snapshot_id == snapshot.id,
                    AgentMemorySnapshotItem.memory_partition
                    == MemoryPartition.LEARNING_HYPOTHESIS.value,
                    AgentMemorySnapshotItem.selected.is_(True),
                )
                .order_by(AgentMemorySnapshotItem.id)
            )
        ).all()
    )
    if frozen_items:
        hypotheses = [
            safe
            for item in frozen_items
            if (safe := _safe_hypothesis(dict(item.payload_json or {}), now=now))
            is not None
        ]
        return hypotheses[:_MAX_DIAGNOSTIC_HYPOTHESES], [
            item.id for item in frozen_items[:_MAX_DIAGNOSTIC_HYPOTHESES]
        ]

    # 旧测试/迁移数据可能仍使用非 UUID 的兼容用户标识；LearningActivityEvent
    # 的 UUIDBinary 边界不能绑定这类值，明确按“没有 Observer 事实”处理。
    try:
        uuid.UUID(str(snapshot.user_id))
    except (TypeError, ValueError, AttributeError):
        return [], []

    events = list(
        (
            await db.scalars(
                select(LearningActivityEvent)
                .where(
                    LearningActivityEvent.user_id == snapshot.user_id,
                    LearningActivityEvent.event_type == "agent_turn_observed",
                    LearningActivityEvent.occurred_at
                    >= now - timedelta(days=_HYPOTHESIS_TTL_DAYS),
                )
                .order_by(
                    LearningActivityEvent.occurred_at.desc(),
                    LearningActivityEvent.id.desc(),
                )
                .limit(_MAX_DIAGNOSTIC_HYPOTHESES)
            )
        ).all()
    )
    hypotheses: list[dict[str, Any]] = []
    source_item_ids: list[int] = []
    for event in events:
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        for raw in payload.get("diagnostic_hypotheses") or []:
            if not isinstance(raw, dict):
                continue
            safe = _safe_hypothesis(
                {**raw, "source_run_id": payload.get("source_run_id")},
                now=now,
            )
            if safe is None:
                continue
            item = AgentMemorySnapshotItem(
                snapshot_id=snapshot.id,
                memory_need="topic_focus",
                memory_partition=MemoryPartition.LEARNING_HYPOTHESIS.value,
                source_kind="learning_activity_event",
                source_id=str(event.id),
                item_key=f"diagnostic_hypothesis:{event.id}:{len(hypotheses)}",
                version=1,
                selected=True,
                selection_reason="active_observer_hypothesis_within_ttl",
                token_estimate=0,
                payload_json=safe,
            )
            db.add(item)
            await db.flush()
            hypotheses.append(safe)
            source_item_ids.append(item.id)
            if len(hypotheses) >= _MAX_DIAGNOSTIC_HYPOTHESES:
                return hypotheses, source_item_ids
    return hypotheses, source_item_ids


async def load_learning_snapshot_summary(
    db: AsyncSession,
    *,
    snapshot_id: str | None,
    user_id: str,
    thread_id: str,
    active_topic: dict[str, Any] | None = None,
) -> LearningSnapshotSummary:
    """按用户、线程和快照 ID读取只读 LearningSnapshot 摘要。

    找不到快照时返回明确的空摘要而不是读取 live 掌握度；这样 Router 不会在
    同一 Run 内混用冻结上下文和当前数据库状态。查询异常继续向 route 节点传播，
    由 Worker 将该 Run 标记为失败，且不会创建 child Run。
    """

    if not snapshot_id:
        return LearningSnapshotSummary(active_topic=active_topic)

    snapshot = await db.scalar(
        select(AgentMemorySnapshot).where(
            AgentMemorySnapshot.id == snapshot_id,
            AgentMemorySnapshot.user_id == user_id,
            AgentMemorySnapshot.thread_id == thread_id,
        )
    )
    if snapshot is None:
        return LearningSnapshotSummary(
            snapshot_id=snapshot_id,
            active_topic=active_topic,
        )

    items = list(
        (
            await db.execute(
                select(AgentMemorySnapshotItem)
                .where(
                    AgentMemorySnapshotItem.snapshot_id == snapshot.id,
                    AgentMemorySnapshotItem.memory_partition
                    == MemoryPartition.LEARNING_MASTERY.value,
                    AgentMemorySnapshotItem.selected.is_(True),
                )
                .order_by(AgentMemorySnapshotItem.id)
                .limit(_MAX_MASTERY_SIGNALS)
            )
        ).scalars()
    )
    mastery_signals: list[dict[str, Any]] = []
    source_item_ids: list[int] = []
    seen_point_ids: set[str] = set()
    for item in items:
        signal = _safe_mastery_signal(dict(item.payload_json or {}))
        if signal is None or signal["knowledge_point_id"] in seen_point_ids:
            continue
        seen_point_ids.add(signal["knowledge_point_id"])
        mastery_signals.append(signal)
        source_item_ids.append(item.id)

    diagnostic_hypotheses, hypothesis_item_ids = await _freeze_diagnostic_hypotheses(
        db,
        snapshot=snapshot,
        now=utc_now(),
    )

    return LearningSnapshotSummary(
        snapshot_id=snapshot.id,
        state_version=snapshot.state_version,
        active_topic=active_topic,
        mastery_signals=mastery_signals,
        diagnostic_hypotheses=diagnostic_hypotheses,
        source_item_ids=[*source_item_ids, *hypothesis_item_ids],
    )


__all__ = [
    "LEARNING_SNAPSHOT_POLICY_VERSION",
    "LearningSnapshotSummary",
    "load_learning_snapshot_summary",
]
