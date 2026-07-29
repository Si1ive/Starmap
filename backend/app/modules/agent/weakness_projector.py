"""把学习活动事实投影为可解释、只读的知识薄弱点发现。

``WeaknessProjector`` 只消费已经落库的活动/评分事实，不提供任何数据库写入
方法。它和 ``MasteryProjector`` 的边界不同：这里产出的是下一步教学策略使用的
派生 finding，而不是权威掌握度状态。尤其是 exposure、observation 和诊断假设
只能产出 ``needs_diagnostic``，不能被升级为 confirmed weakness。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.modules.learning.contracts import (
    EvidenceOutcome,
    EvidenceType,
    LearningEvidence,
)

from .time_utils import utc_isoformat, utc_now

WEAKNESS_PROJECTOR_VERSION = "weakness-projector-v1"
_WEAKNESS_DECAY_DAYS = 45.0
_MAX_EVIDENCE_SOURCES = 8


class WeaknessFinding(BaseModel):
    """Tutor/学习进度可消费的单个薄弱点发现。"""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    projector_version: str = WEAKNESS_PROJECTOR_VERSION
    knowledge_point_id: str | None = None
    keyword: str | None = None
    title: str | None = None
    status: Literal[
        "confirmed",
        "needs_diagnostic",
        "awaiting_interval_verification",
    ]
    reason_code: str
    recommended_review_reason: str
    severity: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    wrong_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    error_tags: list[str] = Field(default_factory=list, max_length=6)
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    evidence_sources: list[dict[str, Any]] = Field(
        default_factory=list, max_length=_MAX_EVIDENCE_SOURCES
    )
    source_types: list[str] = Field(default_factory=list, max_length=8)
    last_wrong_at: str | None = None
    last_evidence_at: str | None = None
    next_review_at: str | None = None
    hypothesis_expires_at: str | None = None


@dataclass(frozen=True)
class _FindingEvidence:
    key: str
    knowledge_point_id: str | None
    keyword: str | None
    source_id: str
    source_type: str
    evidence_type: str
    outcome: str
    strength: float
    confidence: float
    occurred_at: datetime
    error_tags: tuple[str, ...]
    assessment_source: str | None
    diagnostic_need: bool
    hypothesis_expires_at: datetime | None
    coverage: float


class WeaknessProjector:
    """按 verdict、错误标签、迁移和时间衰减生成薄弱点 finding。"""

    def project(
        self,
        records: Iterable[object],
        *,
        now: datetime | None = None,
        knowledge_point_titles: Mapping[str, str] | None = None,
    ) -> list[WeaknessFinding]:
        """投影活动事实。

        ``records`` 可以是 ``LearningActivityEvent``、``LearningEvidence`` 或旧版
        薄弱点字典。解析失败的历史记录会被跳过；当前调用不吞数据库异常，因为
        查询和权限校验应由上层服务负责。
        """

        effective_now = _naive_utc(now or utc_now())
        grouped: dict[str, list[_FindingEvidence]] = defaultdict(list)
        for record in records:
            for item in _normalize_record(record, now=effective_now):
                grouped[item.key].append(item)

        titles = knowledge_point_titles or {}
        findings: list[WeaknessFinding] = []
        for key, evidence in grouped.items():
            finding = self._project_group(
                key,
                evidence,
                now=effective_now,
                title=titles.get(evidence[0].knowledge_point_id or ""),
            )
            if finding is not None:
                findings.append(finding)
        findings.sort(
            key=lambda item: (
                item.status == "needs_diagnostic",
                -item.severity,
                item.next_review_at or "9999-12-31T23:59:59Z",
                item.finding_id,
            )
        )
        return findings

    def project_events(
        self,
        events: Iterable[object],
        *,
        now: datetime | None = None,
        knowledge_point_titles: Mapping[str, str] | None = None,
    ) -> list[WeaknessFinding]:
        """显式的事件入口，供 SnapshotReader 和学习进度服务调用。"""

        return self.project(
            events,
            now=now,
            knowledge_point_titles=knowledge_point_titles,
        )

    @staticmethod
    def _project_group(
        key: str,
        evidence: list[_FindingEvidence],
        *,
        now: datetime,
        title: str | None,
    ) -> WeaknessFinding | None:
        ordered = sorted(evidence, key=lambda item: item.occurred_at)
        wrong = [
            item for item in ordered if item.outcome == EvidenceOutcome.INCORRECT.value
        ]
        positive = [
            item
            for item in ordered
            if item.outcome
            in {
                EvidenceOutcome.CORRECT.value,
                EvidenceOutcome.PARTIAL.value,
            }
        ]
        unknown = [
            item
            for item in ordered
            if item.outcome
            in {
                EvidenceOutcome.UNKNOWN.value,
                EvidenceOutcome.UNGRADABLE.value,
            }
            or item.evidence_type
            in {
                EvidenceType.EXPOSURE.value,
                EvidenceType.OBSERVATION.value,
                EvidenceType.SELF_REPORT.value,
            }
        ]
        if not wrong and not unknown:
            # 只有正确/partial 证据时不凭空制造薄弱点。
            return None

        last_wrong = wrong[-1] if wrong else None
        last_positive = positive[-1] if positive else None
        last_evidence = ordered[-1]
        error_tags = _ordered_unique(
            tag for item in ordered for tag in item.error_tags
        )[:6]
        source_types = _ordered_unique(item.source_type for item in ordered)[:8]
        evidence_ids = _ordered_unique(item.source_id for item in ordered)[:32]
        evidence_sources = [
            {
                "source_id": item.source_id,
                "source_type": item.source_type,
                "evidence_type": item.evidence_type,
                "evidence_outcome": item.outcome,
                "assessment_source": item.assessment_source,
                "evidence_strength": round(item.strength, 4),
                "coverage": round(item.coverage, 4),
                "confidence": round(item.confidence, 4),
                "error_tags": list(item.error_tags),
                "occurred_at": utc_isoformat(item.occurred_at),
            }
            for item in reversed(ordered[-_MAX_EVIDENCE_SOURCES:])
        ]

        if last_wrong is None:
            diagnostic = any(item.diagnostic_need for item in unknown) or bool(unknown)
            if not diagnostic:
                return None
            status = "needs_diagnostic"
            reason_code = "diagnostic_needed"
            severity = 0.2 if any(item.diagnostic_need for item in unknown) else 0.1
            confidence = max((item.confidence for item in unknown), default=0.0)
            recommended = "只有主题暴露或困惑假设，先做一道独立诊断题"
            next_review = last_evidence.occurred_at + timedelta(days=1)
        else:
            elapsed_days = max(
                0.0, (now - _naive_utc(last_wrong.occurred_at)).total_seconds() / 86400
            )
            time_decay = math.exp(-elapsed_days / _WEAKNESS_DECAY_DAYS)
            negative_mass = sum(
                max(0.0, item.strength) * max(0.01, item.coverage) for item in wrong
            )
            positive_mass = sum(
                max(0.0, item.strength) * max(0.01, item.coverage) for item in positive
            )
            base_severity = negative_mass / max(negative_mass + positive_mass, 1.0)
            if len(wrong) > 1:
                base_severity = min(1.0, base_severity + 0.15)
            severity = max(0.05, min(1.0, base_severity * time_decay))
            confidence = min(
                1.0,
                max(
                    item.confidence
                    * max(0.01, item.strength)
                    * max(0.01, item.coverage)
                    for item in wrong
                ),
            )
            verified_after = any(
                item.occurred_at > last_wrong.occurred_at for item in positive
            )
            status = "awaiting_interval_verification" if verified_after else "confirmed"
            reason_code = _reason_code(error_tags, ordered)
            recommended = _review_reason(reason_code, status, severity)
            review_days = 2 if len(wrong) > 1 else 1
            if "transfer_gap" in error_tags:
                review_days = max(review_days, 3)
            anchor = (
                last_positive.occurred_at
                if verified_after and last_positive
                else last_wrong.occurred_at
            )
            next_review = anchor + timedelta(days=review_days)

        hypothesis_expiries = [
            item.hypothesis_expires_at
            for item in unknown
            if item.hypothesis_expires_at is not None
            and item.hypothesis_expires_at > now
        ]
        point_id = evidence[0].knowledge_point_id
        keyword = evidence[0].keyword
        finding_id = (
            f"weakness:{point_id or keyword or key}:"
            f"{last_wrong.source_id if last_wrong else evidence_ids[-1]}"
        )
        return WeaknessFinding(
            finding_id=finding_id[:255],
            knowledge_point_id=point_id,
            keyword=keyword,
            title=title or keyword or point_id,
            status=status,
            reason_code=reason_code,
            recommended_review_reason=recommended,
            severity=round(severity, 4),
            confidence=round(confidence, 4),
            wrong_count=len(wrong),
            positive_count=len(positive),
            attempt_count=len(ordered),
            error_tags=error_tags,
            evidence_ids=evidence_ids,
            evidence_sources=evidence_sources,
            source_types=source_types,
            last_wrong_at=utc_isoformat(last_wrong.occurred_at) if last_wrong else None,
            last_evidence_at=utc_isoformat(last_evidence.occurred_at),
            next_review_at=utc_isoformat(next_review),
            hypothesis_expires_at=(
                utc_isoformat(min(hypothesis_expiries)) if hypothesis_expiries else None
            ),
        )


def project_weakness_findings(
    records: Iterable[object],
    *,
    now: datetime | None = None,
    knowledge_point_titles: Mapping[str, str] | None = None,
) -> list[WeaknessFinding]:
    """函数式兼容入口，方便学习 API 和测试直接使用。"""

    return WeaknessProjector().project(
        records,
        now=now,
        knowledge_point_titles=knowledge_point_titles,
    )


def _normalize_record(
    record: object,
    *,
    now: datetime,
) -> list[_FindingEvidence]:
    if isinstance(record, LearningEvidence):
        return _from_evidence(record, record, now=now)

    if hasattr(record, "to_learning_evidence"):
        try:
            evidence = record.to_learning_evidence()
        except Exception:
            evidence = None
        if evidence is not None:
            return _from_evidence(evidence, record, now=now)
        return _from_mapping(record, now=now)

    return _from_mapping(record, now=now)


def _from_evidence(
    evidence: LearningEvidence,
    source: object,
    *,
    now: datetime,
) -> list[_FindingEvidence]:
    occurred_at = _naive_utc(getattr(source, "occurred_at", None) or now)
    payload = getattr(source, "payload_json", {}) or {}
    if not isinstance(payload, Mapping):
        payload = {}
    tags = _string_values(evidence.error_tags)
    tags.extend(_string_values(payload.get("error_tags") or payload.get("error_types")))
    diagnostic_need = bool(payload.get("diagnostic_need")) or bool(
        payload.get("diagnostic_hypotheses")
    )
    expires_at = _parse_datetime(payload.get("hypothesis_expires_at"))
    if expires_at is None:
        hypotheses = payload.get("diagnostic_hypotheses") or []
        parsed = [
            _parse_datetime(item.get("expires_at"))
            for item in hypotheses
            if isinstance(item, Mapping)
        ]
        expires_at = next((item for item in parsed if item is not None), None)
    target_ids = _string_values(
        getattr(source, "knowledge_point_ids_json", None)
        or evidence.knowledge_point_ids
    )
    keywords = _string_values(getattr(source, "topic_keywords_json", None))
    if not target_ids and not keywords:
        keywords = ["未标注考点"]
    coverage = evidence.knowledge_point_coverage
    return _expand_targets(
        target_ids=target_ids,
        keywords=keywords,
        source_id=str(evidence.source_id),
        source_type=evidence.source_type,
        evidence_type=evidence.evidence_type.value,
        outcome=evidence.evidence_outcome.value,
        strength=(
            float(evidence.evidence_strength)
            if evidence.evidence_strength > 0
            else (
                1.0
                if evidence.evidence_outcome
                in {
                    EvidenceOutcome.CORRECT,
                    EvidenceOutcome.PARTIAL,
                    EvidenceOutcome.INCORRECT,
                }
                else 0.0
            )
        ),
        confidence=float(evidence.assessment_confidence or evidence.confidence or 0.0),
        occurred_at=occurred_at,
        error_tags=tags,
        assessment_source=(
            evidence.assessment_source.value if evidence.assessment_source else None
        ),
        diagnostic_need=diagnostic_need,
        hypothesis_expires_at=expires_at,
        coverage=coverage,
    )


def _from_mapping(record: object, *, now: datetime) -> list[_FindingEvidence]:
    data: Mapping[str, Any]
    if isinstance(record, Mapping):
        data = record
    else:
        data = {
            key: getattr(record, key, None)
            for key in (
                "source_id",
                "source_type",
                "evidence_type",
                "evidence_outcome",
                "outcome",
                "is_correct",
                "knowledge_point_ids_json",
                "knowledge_point_ids",
                "topic_keywords_json",
                "keywords",
                "error_tags",
                "error_types",
                "evidence_strength",
                "assessment_confidence",
                "occurred_at",
                "assessment_source",
                "diagnostic_need",
                "hypothesis_expires_at",
                "payload_json",
            )
        }
    payload = data.get("payload_json")
    if not isinstance(payload, Mapping):
        payload = {}
    outcome = str(
        data.get("evidence_outcome")
        or data.get("outcome")
        or _outcome_from_bool(data.get("is_correct"))
    ).lower()
    if "." in outcome:
        outcome = outcome.rsplit(".", 1)[-1]
    evidence_type = str(data.get("evidence_type") or "observation").lower()
    if "." in evidence_type:
        evidence_type = evidence_type.rsplit(".", 1)[-1]
    source_id = str(data.get("source_id") or "").strip()
    if not source_id:
        return []
    target_ids = _string_values(
        data.get("knowledge_point_ids")
        or data.get("knowledge_point_ids_json")
        or payload.get("knowledge_point_ids")
    )
    keywords = _string_values(
        data.get("keywords")
        or data.get("topic_keywords")
        or data.get("topic_keywords_json")
        or payload.get("topic_keywords")
    )
    if not target_ids and not keywords:
        keywords = ["未标注考点"]
    tags = _string_values(
        data.get("error_tags")
        or data.get("error_types")
        or payload.get("error_tags")
        or payload.get("error_types")
    )
    raw_strength = data.get("evidence_strength")
    try:
        strength = float(raw_strength) if raw_strength is not None else None
    except (TypeError, ValueError):
        strength = None
    if strength is None:
        strength = (
            1.0
            if outcome
            in {
                EvidenceOutcome.CORRECT.value,
                EvidenceOutcome.PARTIAL.value,
                EvidenceOutcome.INCORRECT.value,
            }
            else 0.0
        )
    raw_confidence = data.get("assessment_confidence")
    try:
        confidence = float(raw_confidence) if raw_confidence is not None else 1.0
    except (TypeError, ValueError):
        confidence = 1.0
    return _expand_targets(
        target_ids=target_ids,
        keywords=keywords,
        source_id=source_id,
        source_type=str(data.get("source_type") or "learning_activity"),
        evidence_type=evidence_type,
        outcome=outcome,
        strength=max(0.0, min(1.0, strength)),
        confidence=max(0.0, min(1.0, confidence)),
        occurred_at=_naive_utc(_parse_datetime(data.get("occurred_at")) or now),
        error_tags=tags,
        assessment_source=_enum_text(data.get("assessment_source")),
        diagnostic_need=bool(
            data.get("diagnostic_need")
            or payload.get("diagnostic_need")
            or payload.get("diagnostic_hypotheses")
        ),
        hypothesis_expires_at=(
            _parse_datetime(data.get("hypothesis_expires_at"))
            or _parse_datetime(payload.get("hypothesis_expires_at"))
        ),
        coverage=data.get("knowledge_point_coverage")
        or data.get("knowledge_point_coverage_json")
        or payload.get("knowledge_point_coverage")
        or {},
    )


def _expand_targets(
    *,
    target_ids: list[str],
    keywords: list[str],
    source_id: str,
    source_type: str,
    evidence_type: str,
    outcome: str,
    strength: float,
    confidence: float,
    occurred_at: datetime,
    error_tags: Iterable[str],
    assessment_source: str | None,
    diagnostic_need: bool,
    hypothesis_expires_at: datetime | None,
    coverage: object,
) -> list[_FindingEvidence]:
    normalized_coverage = coverage if isinstance(coverage, Mapping) else {}
    targets: list[tuple[str | None, str | None, float]] = []
    if target_ids:
        for point_id in target_ids:
            raw_coverage = normalized_coverage.get(point_id, 1.0 / len(target_ids))
            try:
                point_coverage = float(raw_coverage)
            except (TypeError, ValueError):
                point_coverage = 1.0 / len(target_ids)
            targets.append((point_id, None, max(0.01, min(1.0, point_coverage))))
    else:
        for keyword in keywords:
            targets.append((None, keyword, 1.0))
    result = []
    for point_id, keyword, point_coverage in targets:
        key = f"kp:{point_id}" if point_id else f"keyword:{keyword}"
        result.append(
            _FindingEvidence(
                key=key,
                knowledge_point_id=point_id,
                keyword=keyword,
                source_id=source_id,
                source_type=source_type,
                evidence_type=evidence_type,
                outcome=outcome,
                strength=max(0.0, min(1.0, strength)),
                confidence=max(0.0, min(1.0, confidence)),
                occurred_at=_naive_utc(occurred_at),
                error_tags=tuple(_ordered_unique(error_tags)),
                assessment_source=assessment_source,
                diagnostic_need=diagnostic_need,
                hypothesis_expires_at=(
                    _naive_utc(hypothesis_expires_at)
                    if hypothesis_expires_at is not None
                    else None
                ),
                coverage=point_coverage,
            )
        )
    return result


def _reason_code(tags: list[str], evidence: list[_FindingEvidence]) -> str:
    for tag in (
        "misconception",
        "transfer_gap",
        "procedure_gap",
        "retrieval_gap",
        "concept_gap",
        "careless_error",
    ):
        if tag in tags:
            return tag
    if any(item.evidence_type == EvidenceType.TRANSFER.value for item in evidence):
        return "transfer_gap"
    return "incorrect_verdict"


def _review_reason(reason_code: str, status: str, severity: float) -> str:
    if status == "awaiting_interval_verification":
        return "已有一次后续正确，安排间隔或变式验证，保留历史错误"
    if reason_code == "misconception":
        return "先澄清概念误解，再通过变式题验证"
    if reason_code == "transfer_gap":
        return "安排变式迁移题，确认能否把规则用于新情境"
    if reason_code == "retrieval_gap":
        return "先做不看资料的回忆，再安排短间隔复习"
    if reason_code == "procedure_gap":
        return "拆解操作步骤并安排一次独立重做"
    if severity < 0.2:
        return "历史错误证据已衰减，安排一次间隔复习验证"
    return "针对错误知识点复习后重新作答"


def _outcome_from_bool(value: object) -> str:
    if value is True:
        return EvidenceOutcome.CORRECT.value
    if value is False:
        return EvidenceOutcome.INCORRECT.value
    return EvidenceOutcome.UNKNOWN.value


def _string_values(values: object) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    if not isinstance(values, Iterable):
        values = [values]
    result: list[str] = []
    for value in values:
        if hasattr(value, "value"):
            value = value.value
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _enum_text(value: object) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value)).strip() or None


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _naive_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _naive_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


__all__ = [
    "WEAKNESS_PROJECTOR_VERSION",
    "WeaknessFinding",
    "WeaknessProjector",
    "project_weakness_findings",
]
