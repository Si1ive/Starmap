"""ConversationTutorAgent 使用的只读 LearningSnapshot。

本模块把在线 Tutor 的学习状态读取固定在 ``AgentMemorySnapshot`` 边界内：首次
读取时复制知识点级 mastery、证据来源和 ``WeaknessFinding``，之后只消费快照项，
不因为同一 Run 后续发生的新评分而漂移。掌握度仍由 ``MasteryProjector`` 写入，
这里仅负责读取和冻结。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
import uuid

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning.models import LearningActivityEvent

from .mastery_decay import calculate_effective_mastery
from .memory_contracts import MemoryPartition
from .models import AgentMemorySnapshot, AgentMemorySnapshotItem, UserLearningMastery
from .time_utils import utc_isoformat, utc_now
from .weakness_projector import WeaknessFinding, WeaknessProjector

if TYPE_CHECKING:
    from app.models.mysql_models import KnowledgePoint

LEARNING_SNAPSHOT_POLICY_VERSION = "learning-snapshot-v1"
_MAX_MASTERY_SIGNALS = 16
_MAX_WEAKNESS_FINDINGS = 16
_MAX_EVIDENCE_SOURCES = 8
_MAX_DIAGNOSTIC_HYPOTHESES = 16
_HYPOTHESIS_TTL_DAYS = 14
_LEARNING_STATE_INITIALIZED_KEY = "learning_snapshot_state_initialized"


class LearningSnapshotSummary(BaseModel):
    """本轮 Tutor 可消费的、已按 Run 冻结的学习状态摘要。"""

    model_config = ConfigDict(extra="forbid")

    policy_version: str = LEARNING_SNAPSHOT_POLICY_VERSION
    snapshot_id: str | None = None
    state_version: int | None = None
    active_topic: dict[str, Any] | None = None
    mastery_signals: list[dict[str, Any]] = Field(default_factory=list)
    weakness_findings: list[dict[str, Any]] = Field(default_factory=list)
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
        for finding in self.weakness_findings:
            point_id = str(finding.get("knowledge_point_id") or "").strip()
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
        "correct_count",
        "incorrect_count",
        "last_evidence_id",
        "evidence_at",
        "evidence_time_source",
        "age_days",
        "decay_policy_version",
        "state_model_version",
        "uncertainty",
        "evidence_mass",
        "recommended_review_reason",
    ):
        if key in payload:
            signal[key] = payload[key]
    raw_tags = payload.get("error_tags")
    if isinstance(raw_tags, list):
        signal["error_tags"] = [str(item) for item in raw_tags[:6] if str(item).strip()]
    raw_sources = payload.get("evidence_sources")
    if isinstance(raw_sources, list):
        signal["evidence_sources"] = [
            _safe_evidence_source(item)
            for item in raw_sources[:_MAX_EVIDENCE_SOURCES]
            if isinstance(item, dict)
        ]
    return signal


def _safe_evidence_source(payload: dict[str, Any]) -> dict[str, Any]:
    """复制证据来源最小审计字段，不把活动 payload 原文交给 Tutor。"""

    return {
        key: payload[key]
        for key in (
            "source_id",
            "source_type",
            "evidence_type",
            "evidence_outcome",
            "assessment_source",
            "evidence_strength",
            "confidence",
            "error_tags",
            "occurred_at",
            "answer_exposed",
        )
        if key in payload
    }


def _safe_weakness_finding(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        finding = WeaknessFinding.model_validate(payload)
    except Exception:
        return None
    return finding.model_dump(mode="json")


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
    if not _is_uuid(snapshot.user_id):
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


class LearningSnapshotReader:
    """读取并首次冻结本轮 Tutor 所需的学习状态。"""

    def __init__(self, db: AsyncSession, *, now: datetime | None = None):
        self.db = db
        self.now = now

    async def read(
        self,
        *,
        snapshot_id: str | None,
        user_id: str,
        thread_id: str,
        active_topic: dict[str, Any] | None = None,
    ) -> LearningSnapshotSummary:
        if not snapshot_id:
            return LearningSnapshotSummary(active_topic=active_topic)

        snapshot = await self.db.scalar(
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

        now = self.now or utc_now()
        await self._ensure_learning_state(
            snapshot,
            active_topic=active_topic,
            now=now,
        )

        items = list(
            (
                await self.db.execute(
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
        weakness_items = list(
            (
                await self.db.execute(
                    select(AgentMemorySnapshotItem)
                    .where(
                        AgentMemorySnapshotItem.snapshot_id == snapshot.id,
                        AgentMemorySnapshotItem.memory_partition == "learning_weakness",
                        AgentMemorySnapshotItem.selected.is_(True),
                    )
                    .order_by(AgentMemorySnapshotItem.id)
                    .limit(_MAX_WEAKNESS_FINDINGS)
                )
            ).scalars()
        )
        mastery_signals: list[dict[str, Any]] = []
        weakness_findings: list[dict[str, Any]] = []
        source_item_ids: list[int] = []
        seen_point_ids: set[str] = set()
        for item in items:
            signal = _safe_mastery_signal(dict(item.payload_json or {}))
            if signal is None or signal["knowledge_point_id"] in seen_point_ids:
                continue
            seen_point_ids.add(signal["knowledge_point_id"])
            mastery_signals.append(signal)
            source_item_ids.append(item.id)
        for item in weakness_items:
            finding = _safe_weakness_finding(dict(item.payload_json or {}))
            if finding is None:
                continue
            weakness_findings.append(finding)
            source_item_ids.append(item.id)

        diagnostic_hypotheses, hypothesis_item_ids = (
            await _freeze_diagnostic_hypotheses(
                self.db,
                snapshot=snapshot,
                now=now,
            )
        )
        source_item_ids.extend(hypothesis_item_ids)

        return LearningSnapshotSummary(
            snapshot_id=snapshot.id,
            state_version=snapshot.state_version,
            active_topic=active_topic,
            mastery_signals=mastery_signals,
            weakness_findings=weakness_findings,
            diagnostic_hypotheses=diagnostic_hypotheses,
            source_item_ids=source_item_ids,
        )

    async def _ensure_learning_state(
        self,
        snapshot: AgentMemorySnapshot,
        *,
        active_topic: dict[str, Any] | None,
        now: datetime,
    ) -> None:
        metadata = dict(snapshot.selection_metadata_json or {})
        if metadata.get(_LEARNING_STATE_INITIALIZED_KEY) is True:
            return

        existing_items = list(
            (
                await self.db.execute(
                    select(AgentMemorySnapshotItem)
                    .where(
                        AgentMemorySnapshotItem.snapshot_id == snapshot.id,
                        AgentMemorySnapshotItem.memory_partition.in_(
                            [
                                MemoryPartition.LEARNING_MASTERY.value,
                                "learning_weakness",
                            ]
                        ),
                        AgentMemorySnapshotItem.selected.is_(True),
                    )
                    .order_by(AgentMemorySnapshotItem.id)
                )
            ).scalars()
        )
        if not existing_items:
            masteries, points_by_id = await self._load_mastery_rows(
                snapshot.user_id,
                active_topic=active_topic,
                now=now,
            )
            events = await self._load_learning_events(snapshot.user_id)
            titles = {
                point_id: str(point.title or point_id)
                for point_id, point in points_by_id.items()
            }
            findings = WeaknessProjector().project_events(
                events,
                now=now,
                knowledge_point_titles=titles,
            )
            finding_by_point = {
                finding.knowledge_point_id: finding
                for finding in findings
                if finding.knowledge_point_id
            }
            for mastery, _point, signal in masteries[:_MAX_MASTERY_SIGNALS]:
                finding = finding_by_point.get(mastery.knowledge_point_id)
                signal["recommended_review_reason"] = (
                    finding.recommended_review_reason
                    if finding is not None
                    else _recommended_mastery_reason(signal)
                )
                self.db.add(
                    AgentMemorySnapshotItem(
                        snapshot_id=snapshot.id,
                        memory_need="topic_focus",
                        memory_partition=MemoryPartition.LEARNING_MASTERY.value,
                        source_kind="learning_snapshot_reader",
                        source_id=str(mastery.id),
                        item_key=f"learning_snapshot:mastery:{mastery.id}",
                        version=int(mastery.evidence_count or 0),
                        selected=True,
                        selection_reason="freeze_learning_snapshot_mastery",
                        token_estimate=0,
                        payload_json=signal,
                    )
                )
            for finding in findings[:_MAX_WEAKNESS_FINDINGS]:
                self.db.add(
                    AgentMemorySnapshotItem(
                        snapshot_id=snapshot.id,
                        memory_need="topic_focus",
                        memory_partition="learning_weakness",
                        source_kind="weakness_projector",
                        source_id=finding.finding_id[:64],
                        item_key=f"learning_snapshot:weakness:{finding.finding_id}"[
                            :128
                        ],
                        version=snapshot.state_version,
                        selected=True,
                        selection_reason="freeze_learning_snapshot_weakness",
                        token_estimate=0,
                        payload_json=finding.model_dump(mode="json"),
                    )
                )
            await self.db.flush()
        metadata[_LEARNING_STATE_INITIALIZED_KEY] = True
        metadata["learning_snapshot_policy_version"] = LEARNING_SNAPSHOT_POLICY_VERSION
        snapshot.selection_metadata_json = metadata
        await self.db.flush()

    async def _load_mastery_rows(
        self,
        user_id: str,
        *,
        active_topic: dict[str, Any] | None,
        now: datetime,
    ) -> tuple[
        list[tuple[UserLearningMastery, KnowledgePoint | None, dict[str, Any]]],
        dict[str, KnowledgePoint],
    ]:
        # 延迟导入题库 ORM，避免只运行 Conversation/Observer 的轻量环境在
        # Base.metadata.create_all 时提前注册无关的 users 外键表。
        from app.models.mysql_models import KnowledgePoint

        mastery_rows = list(
            (
                await self.db.scalars(
                    select(UserLearningMastery).where(
                        UserLearningMastery.user_id.in_(_user_id_values(user_id)),
                        UserLearningMastery.evidence_count > 0,
                    )
                )
            ).all()
        )
        point_ids = [row.knowledge_point_id for row in mastery_rows]
        points = (
            list(
                (
                    await self.db.scalars(
                        select(KnowledgePoint).where(KnowledgePoint.id.in_(point_ids))
                    )
                ).all()
            )
            if point_ids
            else []
        )
        points_by_id = {point.id: point for point in points}
        rows = [
            (mastery, points_by_id.get(mastery.knowledge_point_id))
            for mastery in mastery_rows
        ]
        events = await self._load_learning_events(user_id)
        active_point_id = (
            str(active_topic.get("entity_id") or "").strip()
            if isinstance(active_topic, dict)
            and active_topic.get("entity_type") == "knowledge_point"
            else ""
        )
        result = []
        points_by_id = dict(points_by_id)
        for mastery, point in rows:
            if point is not None:
                points_by_id[mastery.knowledge_point_id] = point
            result.append(
                (
                    mastery,
                    point,
                    _build_mastery_signal(
                        mastery,
                        point,
                        events=events,
                        now=now,
                    ),
                )
            )
        result.sort(
            key=lambda item: (
                0 if item[0].knowledge_point_id == active_point_id else 1,
                item[2]["effective_mastery_score"],
                -int(item[0].evidence_count or 0),
                item[0].knowledge_point_id,
            )
        )
        return result, points_by_id

    async def _load_learning_events(self, user_id: str) -> list[LearningActivityEvent]:
        # UUIDBinary 的用户边界拒绝非 UUID 兼容测试标识；这类快照仍可读取
        # mastery，但不会错误地把无法绑定归属的活动事实送进 Tutor。
        if not _is_uuid(user_id):
            return []
        return list(
            (
                await self.db.scalars(
                    select(LearningActivityEvent)
                    .where(LearningActivityEvent.user_id == user_id)
                    .order_by(
                        LearningActivityEvent.occurred_at.desc(),
                        LearningActivityEvent.id.desc(),
                    )
                    .limit(200)
                )
            ).all()
        )


def _build_mastery_signal(
    mastery: UserLearningMastery,
    point: KnowledgePoint | None,
    *,
    events: list[LearningActivityEvent],
    now: datetime,
) -> dict[str, Any]:
    evidence_at = (
        getattr(mastery, "last_evidence_at", None)
        or mastery.last_graded_at
        or mastery.updated_at
        or mastery.created_at
        or now
    )
    effective = calculate_effective_mastery(
        mastery.mastery_score,
        evidence_at=evidence_at,
        now=now,
        state_model_version=(
            getattr(mastery, "state_model_version", None) or "mastery-beta-v1"
        ),
    )
    point_id = mastery.knowledge_point_id
    sources: list[dict[str, Any]] = []
    error_tags: list[str] = []
    for event in events:
        event_points = [str(item) for item in event.knowledge_point_ids_json or []]
        if point_id not in event_points:
            continue
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        try:
            evidence = event.to_learning_evidence()
        except Exception:
            continue
        tags = [
            str(item.value if hasattr(item, "value") else item)
            for item in evidence.error_tags
        ]
        for tag in tags:
            if tag not in error_tags:
                error_tags.append(tag)
        sources.append(
            {
                "source_id": str(evidence.source_id),
                "source_type": evidence.source_type,
                "evidence_type": evidence.evidence_type.value,
                "evidence_outcome": evidence.evidence_outcome.value,
                "assessment_source": (
                    evidence.assessment_source.value
                    if evidence.assessment_source
                    else None
                ),
                "evidence_strength": float(evidence.evidence_strength),
                "confidence": float(evidence.assessment_confidence or 0.0),
                "error_tags": tags,
                "occurred_at": utc_isoformat(event.occurred_at),
                "answer_exposed": bool(
                    payload.get("answer_exposed") or payload.get("answer_revealed")
                ),
            }
        )
        if len(sources) >= _MAX_EVIDENCE_SOURCES:
            break
    return {
        "mastery_id": mastery.id,
        "knowledge_point_id": point_id,
        "knowledge_point_title": point.title if point is not None else point_id,
        "knowledge_point_aliases": (
            [
                str(alias).strip()
                for alias in (point.aliases or [])
                if str(alias).strip()
            ]
            if point is not None
            else []
        ),
        "mastery_score": effective.effective_score,
        "raw_mastery_score": effective.raw_score,
        "effective_mastery_score": effective.effective_score,
        "evidence_count": int(mastery.evidence_count or 0),
        "correct_count": int(mastery.correct_count or 0),
        "incorrect_count": int(mastery.incorrect_count or 0),
        "last_evidence_id": mastery.last_evidence_id,
        "evidence_at": utc_isoformat(effective.evidence_at),
        "evidence_time_source": "last_evidence_at",
        "age_days": effective.age_days,
        "decay_policy_version": effective.policy_version,
        "state_model_version": effective.state_model_version,
        "uncertainty": float(getattr(mastery, "uncertainty", 1.0) or 1.0),
        "evidence_mass": float(
            getattr(mastery, "evidence_mass", mastery.evidence_count) or 0.0
        ),
        "error_tags": error_tags[:6],
        "evidence_sources": sources,
    }


def _recommended_mastery_reason(signal: dict[str, Any]) -> str:
    score = float(signal.get("effective_mastery_score") or 0.0)
    uncertainty = float(signal.get("uncertainty") or 1.0)
    if score < 0.4:
        return "掌握度偏低，先安排一次基础诊断并针对性复习"
    if uncertainty >= 0.7:
        return "证据不足，安排一次独立诊断以降低不确定性"
    if float(signal.get("age_days") or 0.0) > 14:
        return "最近证据已衰减，安排间隔复习验证"
    return "保持当前节奏并安排下一次间隔验证"


def _user_id_values(user_id: str) -> list[str]:
    values = [str(user_id)]
    try:
        parsed = uuid.UUID(str(user_id))
    except (TypeError, ValueError, AttributeError):
        return values
    if parsed.hex not in values:
        values.append(parsed.hex)
    if str(parsed) not in values:
        values.append(str(parsed))
    return values


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return False
    return True


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

    return await LearningSnapshotReader(db).read(
        snapshot_id=snapshot_id,
        user_id=user_id,
        thread_id=thread_id,
        active_topic=active_topic,
    )


__all__ = [
    "LEARNING_SNAPSHOT_POLICY_VERSION",
    "LearningSnapshotReader",
    "LearningSnapshotSummary",
    "load_learning_snapshot_summary",
]
