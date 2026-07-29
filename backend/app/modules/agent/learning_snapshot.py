"""ConversationTutorAgent 使用的只读 LearningSnapshot 摘要。

阶段二不新增学习状态表，也不把掌握度计算搬进在线路由。这里仅从当前 Run 已
冻结的 AgentMemorySnapshot 及其 selected learning_mastery items 读取最小摘要，
供 ConversationTutorAgent 选择教学策略；真实掌握度仍由既有 projector 写入。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .memory_contracts import MemoryPartition
from .models import AgentMemorySnapshot, AgentMemorySnapshotItem

LEARNING_SNAPSHOT_POLICY_VERSION = "learning-snapshot-v1"
_MAX_MASTERY_SIGNALS = 16


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

    return LearningSnapshotSummary(
        snapshot_id=snapshot.id,
        state_version=snapshot.state_version,
        active_topic=active_topic,
        mastery_signals=mastery_signals,
        source_item_ids=source_item_ids,
    )


__all__ = [
    "LEARNING_SNAPSHOT_POLICY_VERSION",
    "LearningSnapshotSummary",
    "load_learning_snapshot_summary",
]
