"""LearningObserver 的幂等调度、受控输入快照与活动事实投影。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import KnowledgePoint
from app.modules.learning.contracts import (
    EvidenceContext,
    EvidenceOutcome,
    EvidenceType,
    LearningEvidence,
)
from app.modules.learning.evidence import EvidenceGate
from app.modules.learning.models import LearningActivityEvent

from .model_runtime.observer import (
    OBSERVER_VERSION,
    TurnObservationOutput,
)
from .models import AgentArtifact, AgentMessage, AgentRun
from .service import AgentService
from .state_machine import RunStatus
from .time_utils import utc_isoformat, utc_now

OBSERVER_HYPOTHESIS_TTL_DAYS = 14
_MAX_CONTEXT_MESSAGES = 8
_MAX_ARTIFACT_SUMMARIES = 8
_TEXT_LIMIT = 2000


def _text(value: object, limit: int = _TEXT_LIMIT) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized[:limit]


def _candidate_ids(metadata: dict[str, Any]) -> list[str]:
    values: list[str] = []
    understanding = metadata.get("turn_understanding")
    if isinstance(understanding, dict):
        for topic in understanding.get("topic_entities") or []:
            if (
                not isinstance(topic, dict)
                or topic.get("entity_type") != "knowledge_point"
            ):
                continue
            point_id = _text(topic.get("entity_id"), 64)
            if point_id:
                values.append(point_id)
    snapshot = metadata.get("learning_snapshot")
    if isinstance(snapshot, dict):
        active_topic = snapshot.get("active_topic")
        if (
            isinstance(active_topic, dict)
            and active_topic.get("entity_type") == "knowledge_point"
        ):
            point_id = _text(active_topic.get("entity_id"), 64)
            if point_id:
                values.append(point_id)
        for signal in snapshot.get("mastery_signals") or []:
            if isinstance(signal, dict):
                point_id = _text(signal.get("knowledge_point_id"), 64)
                if point_id:
                    values.append(point_id)
    return list(dict.fromkeys(values))[:32]


async def schedule_learning_observation(
    db: AsyncSession,
    *,
    source_run: AgentRun,
) -> AgentRun | None:
    """只为 completed 根 conversation 幂等创建 silent Observer child Run。"""

    if (
        source_run.status != RunStatus.COMPLETED.value
        or source_run.workflow_name != "conversation"
        or source_run.parent_run_id is not None
        or source_run.root_run_id not in {None, source_run.id}
        or not source_run.trigger_message_id
    ):
        return None
    metadata = (
        source_run.metadata_json if isinstance(source_run.metadata_json, dict) else {}
    )
    observer_metadata: dict[str, Any] = {
        "source_run_id": source_run.id,
        "source_message_id": source_run.trigger_message_id,
        "observer_version": OBSERVER_VERSION,
    }
    if metadata.get("model_config_id"):
        observer_metadata["model_config_id"] = metadata["model_config_id"]
    observer_run = await AgentService(db).create_run(
        user_id=source_run.user_id,
        thread_id=source_run.thread_id,
        workflow_name="learning_observation",
        input_message="观察已完成的用户对话轮次",
        client_idempotency_key=f"observe:{source_run.id}:{OBSERVER_VERSION}",
        workflow_key="learning_observation",
        workflow_version="v1",
        trigger_message_id=source_run.trigger_message_id,
        parent_run_id=source_run.id,
        root_run_id=source_run.id,
        presentation="silent",
        public_title=None,
        metadata_json=observer_metadata,
    )
    observer_run.max_model_calls = 1
    return observer_run


def _artifact_summary(artifact: AgentArtifact) -> dict[str, Any]:
    content = artifact.content_json if isinstance(artifact.content_json, dict) else {}
    raw_content = content.get("content")
    if isinstance(raw_content, dict):
        summary = raw_content.get("overall") or raw_content.get("summary")
    else:
        summary = raw_content
    return {
        "artifact_id": artifact.id,
        "run_id": artifact.run_id,
        "artifact_type": artifact.artifact_type,
        "title": _text(content.get("title"), 200),
        "summary": _text(summary or content.get("summary"), 600),
        "assistant_context_only": True,
    }


async def build_observer_input_snapshot(
    db: AsyncSession,
    *,
    observer_run: AgentRun,
) -> dict[str, Any]:
    """按来源用户、线程和 root Run 构建最小 Observer 输入，拒绝越权引用。"""

    metadata = (
        observer_run.metadata_json
        if isinstance(observer_run.metadata_json, dict)
        else {}
    )
    source_run_id = _text(metadata.get("source_run_id"), 32)
    source_message_id = _text(metadata.get("source_message_id"), 32)
    source_run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == source_run_id,
            AgentRun.user_id == observer_run.user_id,
            AgentRun.thread_id == observer_run.thread_id,
            AgentRun.workflow_name == "conversation",
            AgentRun.parent_run_id.is_(None),
            AgentRun.status == "completed",
        )
    )
    if source_run is None or source_run.trigger_message_id != source_message_id:
        raise ValueError(
            "LearningObserver 来源 conversation Run 不存在或不属于当前用户"
        )
    source_message = await db.scalar(
        select(AgentMessage).where(
            AgentMessage.id == source_message_id,
            AgentMessage.user_id == observer_run.user_id,
            AgentMessage.thread_id == observer_run.thread_id,
            AgentMessage.role == "user",
            AgentMessage.status == "completed",
        )
    )
    if source_message is None or not _text(source_message.content_text):
        raise ValueError("LearningObserver 来源用户消息不存在或不可观察")

    source_metadata = (
        source_run.metadata_json if isinstance(source_run.metadata_json, dict) else {}
    )
    selected_message_ids = list(
        (source_metadata.get("context_audit") or {}).get("selected_message_ids") or []
    )[:_MAX_CONTEXT_MESSAGES]
    messages: list[AgentMessage] = []
    if selected_message_ids:
        messages = list(
            (
                await db.scalars(
                    select(AgentMessage)
                    .where(
                        AgentMessage.id.in_(selected_message_ids),
                        AgentMessage.user_id == observer_run.user_id,
                        AgentMessage.thread_id == observer_run.thread_id,
                        AgentMessage.role.in_(("user", "assistant")),
                        AgentMessage.status == "completed",
                    )
                    .order_by(AgentMessage.created_at, AgentMessage.id)
                )
            ).all()
        )

    artifacts = list(
        (
            await db.scalars(
                select(AgentArtifact)
                .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
                .where(
                    AgentRun.user_id == observer_run.user_id,
                    AgentRun.thread_id == observer_run.thread_id,
                    or_(
                        AgentRun.id == source_run.id,
                        AgentRun.root_run_id == source_run.id,
                    ),
                    AgentRun.presentation != "silent",
                    AgentRun.status == "completed",
                )
                .order_by(AgentArtifact.created_at.desc(), AgentArtifact.id.desc())
                .limit(_MAX_ARTIFACT_SUMMARIES)
            )
        ).all()
    )

    requested_ids = _candidate_ids(source_metadata)
    point_rows = []
    if requested_ids:
        point_rows = list(
            (
                await db.scalars(
                    select(KnowledgePoint).where(KnowledgePoint.id.in_(requested_ids))
                )
            ).all()
        )
    points_by_id = {str(point.id): point for point in point_rows}
    candidates = [
        {
            "knowledge_point_id": point_id,
            "title": _text(
                points_by_id[point_id].canonical_title or points_by_id[point_id].title,
                200,
            ),
            "aliases": [
                _text(alias, 100)
                for alias in (points_by_id[point_id].aliases or [])[:6]
                if _text(alias, 100)
            ],
        }
        for point_id in requested_ids
        if point_id in points_by_id
    ]
    return {
        "policy_version": "learning-observer-input-v1",
        "source_run_id": source_run.id,
        "source_message": {
            "id": source_message.id,
            "role": "user",
            "content": _text(source_message.content_text),
        },
        "conversation_snapshot": [
            {
                "message_id": message.id,
                "role": message.role,
                "content": _text(message.content_text),
            }
            for message in messages
        ],
        "active_topic": (source_metadata.get("learning_snapshot") or {}).get(
            "active_topic"
        ),
        "artifact_summaries": [
            _artifact_summary(artifact) for artifact in reversed(artifacts)
        ],
        "knowledge_point_candidates": candidates,
        "assistant_content_policy": (
            "助手内容只用于 exposure/answer-leakage 上下文，不是用户作答"
        ),
    }


def _diagnostic_hypotheses(
    output: TurnObservationOutput,
    *,
    expires_at,
) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    for observation in output.observations:
        is_hypothesis = observation.diagnostic_need or observation.signal in {
            "confusion",
            "misconception_hypothesis",
            "retrieval_gap_hypothesis",
            "procedure_gap_hypothesis",
            "transfer_gap_hypothesis",
            "careless_error_hypothesis",
            "open_response_candidate",
        }
        if not is_hypothesis:
            continue
        hypotheses.append(
            {
                **observation.model_dump(mode="json"),
                "expires_at": utc_isoformat(expires_at),
            }
        )
    return hypotheses


async def record_turn_observation(
    db: AsyncSession,
    *,
    observer_run: AgentRun,
    input_snapshot: dict[str, Any],
    output: TurnObservationOutput,
) -> LearningActivityEvent:
    """经 EvidenceGate 写一条幂等 observation；该函数从不调用 mastery projector。"""

    metadata = (
        observer_run.metadata_json
        if isinstance(observer_run.metadata_json, dict)
        else {}
    )
    source_run_id = str(metadata.get("source_run_id") or "").strip()
    source_message_id = str(metadata.get("source_message_id") or "").strip()
    source_id = f"{source_run_id}:{OBSERVER_VERSION}"
    existing = await db.scalar(
        select(LearningActivityEvent).where(
            LearningActivityEvent.user_id == observer_run.user_id,
            LearningActivityEvent.event_type == "agent_turn_observed",
            LearningActivityEvent.source_id == source_id,
        )
    )
    if existing is not None:
        return existing

    useful = [
        item for item in output.observations if item.signal != "no_learning_signal"
    ]
    knowledge_point_ids = list(
        dict.fromkeys(
            item.knowledge_point_id
            for item in useful
            if item.knowledge_point_id is not None
        )
    )
    error_tags = list(dict.fromkeys(tag for item in useful for tag in item.error_tags))
    exposure_only = bool(useful) and all(
        item.signal == "topic_exposure" for item in useful
    )
    has_exposure = any(item.signal == "topic_exposure" for item in useful)
    coverage = (
        {point_id: 1.0 / len(knowledge_point_ids) for point_id in knowledge_point_ids}
        if knowledge_point_ids
        else {}
    )
    evidence = LearningEvidence(
        source_id=source_id,
        source_type="agent_observer",
        evidence_type=(
            EvidenceType.EXPOSURE if exposure_only else EvidenceType.OBSERVATION
        ),
        evidence_outcome=EvidenceOutcome.UNKNOWN,
        confidence=max((item.model_confidence for item in useful), default=0.0),
        assessment_confidence=max(
            (item.model_confidence for item in useful), default=0.0
        ),
        evidence_strength=0.0,
        model_version=OBSERVER_VERSION,
        knowledge_point_ids=knowledge_point_ids,
        knowledge_point_coverage=coverage,
        error_tags=error_tags,
        context=EvidenceContext(),
    )
    EvidenceGate().validate(
        evidence,
        owner_user_id=observer_run.user_id,
        source_user_id=observer_run.user_id,
        source_run_id=source_run_id,
        verified_knowledge_point_ids=knowledge_point_ids,
        require_knowledge_point_coverage=False,
    )
    now = utc_now()
    expires_at = now + timedelta(days=OBSERVER_HYPOTHESIS_TTL_DAYS)
    hypotheses = _diagnostic_hypotheses(output, expires_at=expires_at)
    candidate_titles = {
        item.get("knowledge_point_id"): item.get("title")
        for item in input_snapshot.get("knowledge_point_candidates") or []
        if isinstance(item, dict)
    }
    keywords = (
        list(
            dict.fromkeys(
                _text(candidate_titles.get(point_id), 40)
                for point_id in knowledge_point_ids
                if _text(candidate_titles.get(point_id), 40)
            )
        )[:6]
        if has_exposure
        else []
    )
    event = LearningActivityEvent(
        user_id=observer_run.user_id,
        event_type="agent_turn_observed",
        source_type="agent_observer",
        source_id=source_id,
        thread_id=observer_run.thread_id,
        run_id=observer_run.id,
        topic_keywords_json=keywords,
        knowledge_point_ids_json=knowledge_point_ids,
        evidence_type=evidence.evidence_type.value,
        evidence_outcome=evidence.evidence_outcome.value,
        assessment_source=None,
        evidence_strength=0.0,
        assessment_confidence=evidence.assessment_confidence,
        model_version=OBSERVER_VERSION,
        knowledge_point_coverage_json=evidence.knowledge_point_coverage,
        # 只有真实 topic exposure 进入用户保持率轨迹；纯 hypothesis 仍会出现在
        # 最近活动和下一轮策略中，但不能冒充一次学习保持率证据。
        quality=0.35 if has_exposure else 0.0,
        is_correct=None,
        occurred_at=now,
        payload_json={
            "source_run_id": source_run_id,
            "observer_run_id": observer_run.id,
            "source_message_id": source_message_id,
            "observer_version": OBSERVER_VERSION,
            "observations": [
                item.model_dump(mode="json") for item in output.observations
            ],
            "diagnostic_hypotheses": hypotheses,
            "hypothesis_expires_at": utc_isoformat(expires_at),
            "public_activity_summary": output.public_activity_summary,
            "learning_evidence": evidence.to_payload(),
            "assistant_content_policy": input_snapshot.get("assistant_content_policy"),
        },
    )
    db.add(event)
    await db.flush()
    return event


__all__ = [
    "OBSERVER_HYPOTHESIS_TTL_DAYS",
    "build_observer_input_snapshot",
    "record_turn_observation",
    "schedule_learning_observation",
]
