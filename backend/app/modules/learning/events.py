"""Project trusted product events into learning activity facts."""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import KnowledgePoint
from app.modules.agent.models import AgentArtifact, AgentRun
from app.modules.practice.models import PracticeAnswer, PracticeSession, PracticeSessionQuestion

from .contracts import EvidenceContext, EvidenceOutcome, EvidenceType, LearningEvidence
from .evidence import (
    EvidenceGate,
    build_assessment_evidence,
    finalize_evidence_weight,
)
from .models import LearningActivityEvent
from .service import normalize_keyword


def _keywords(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        keyword = normalize_keyword(str(value or ""))
        if 2 <= len(keyword) <= 40 and keyword not in result:
            result.append(keyword)
        if len(result) >= 6:
            break
    return result


def _valid_user_id(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return False
    return True


async def record_practice_submission(
    db: AsyncSession,
    *,
    session: PracticeSession,
    rows: list[tuple[PracticeSessionQuestion, object, PracticeAnswer | None]],
) -> list[LearningActivityEvent]:
    """Write one idempotent assessment event for every answered session item."""
    created: list[LearningActivityEvent] = []
    for link, _question, answer in rows:
        if answer is None or not answer.user_answer.strip() or answer.is_correct is None:
            continue
        source_id = f"{session.id}:{link.item_id}"
        existing = await db.scalar(
            select(LearningActivityEvent).where(
                LearningActivityEvent.user_id == session.user_id,
                LearningActivityEvent.event_type == "practice_answer_graded",
                LearningActivityEvent.source_id == source_id,
            )
        )
        if existing is not None:
            continue
        snapshot = link.snapshot_json or {}
        keywords = _keywords(
            [
                *(snapshot.get("topic_terms") or []),
                *(snapshot.get("tags") or []),
                snapshot.get("provenance", {}).get("topic"),
            ]
        )
        if not keywords:
            keywords = _keywords([snapshot.get("content")])
        generated_question = (
            (snapshot.get("provenance") or {}).get("source_type")
            == "agent_generated"
            or snapshot.get("answer_source") == "llm"
            and session.source_type == "agent"
        )
        question_id = str(
            link.question_id or snapshot.get("question_id") or link.item_id
        ).strip()
        answer_source = (
            "generated_question"
            if generated_question
            else snapshot.get("answer_source") or "question_bank"
        )
        evidence = build_assessment_evidence(
            source_id=source_id,
            source_type="agent_practice" if session.source_type == "agent" else "question",
            verdict="correct" if answer.is_correct else "incorrect",
            question_id=question_id,
            knowledge_point_ids=list(snapshot.get("knowledge_point_ids") or []),
            answer_source=answer_source,
            assessment_source=(
                "generated_question" if generated_question else "deterministic"
            ),
            hint_levels_used=list(answer.hint_levels_used_json or []),
            answer_exposed=bool(snapshot.get("answer_exposed", False)),
            confidence=1.0,
            model_version=(snapshot.get("model_version") or {}).get("version")
            if isinstance(snapshot.get("model_version"), dict)
            else snapshot.get("model_version")
            or (snapshot.get("provenance") or {}).get("model_version"),
            knowledge_point_coverage=snapshot.get("knowledge_point_coverage"),
        )
        EvidenceGate().validate(
            evidence,
            owner_user_id=session.user_id,
            source_user_id=session.user_id,
            source_run_id=session.agent_run_id,
            expected_question_id=question_id,
            verified_knowledge_point_ids=list(snapshot.get("knowledge_point_ids") or []),
            require_knowledge_point_coverage=False,
        )
        evidence, weight = finalize_evidence_weight(
            evidence,
            question_review_status=snapshot.get("review_status"),
        )
        event = LearningActivityEvent(
            user_id=session.user_id,
            event_type="practice_answer_graded",
            source_type="agent_practice" if session.source_type == "agent" else "question",
            source_id=source_id,
            thread_id=session.agent_thread_id,
            run_id=session.agent_run_id,
            topic_keywords_json=keywords,
            knowledge_point_ids_json=evidence.knowledge_point_ids,
            evidence_type=evidence.evidence_type.value,
            evidence_outcome=evidence.evidence_outcome.value,
            assessment_source=evidence.assessment_source.value
            if evidence.assessment_source
            else None,
            evidence_strength=weight.evidence_strength,
            assessment_confidence=evidence.assessment_confidence,
            model_version=evidence.model_version,
            knowledge_point_coverage_json=evidence.knowledge_point_coverage,
            quality=1.0 if answer.is_correct else 0.25,
            is_correct=answer.is_correct,
            occurred_at=answer.saved_at,
            payload_json={
                "session_id": session.id,
                "session_title": session.title,
                "practice_item_id": link.item_id,
                "question_id": link.question_id,
                "content": snapshot.get("content"),
                "hint_levels_used": list(answer.hint_levels_used_json or []),
                "answer_source": answer_source,
                "learning_evidence": evidence.to_payload(),
                "evidence_weight_policy_version": weight.policy_version,
                "evidence_weight_reasons": list(weight.reasons),
            },
        )
        db.add(event)
        created.append(event)
    await db.flush()
    return created


async def record_explanation_activity(
    db: AsyncSession,
    *,
    run: AgentRun,
    artifact: AgentArtifact,
) -> LearningActivityEvent | None:
    """Record topic exposure without turning discussion into mastery evidence."""
    if not _valid_user_id(run.user_id):
        return None
    existing = await db.scalar(
        select(LearningActivityEvent).where(
            LearningActivityEvent.user_id == run.user_id,
            LearningActivityEvent.event_type == "agent_explanation_completed",
            LearningActivityEvent.source_id == artifact.id,
        )
    )
    if existing is not None:
        return existing
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    snapshot = metadata.get("context_snapshot") if isinstance(metadata.get("context_snapshot"), dict) else {}
    active_topic = snapshot.get("active_topic") if isinstance(snapshot.get("active_topic"), dict) else {}
    keywords = _keywords(
        [active_topic.get("title"), *((active_topic.get("aliases") or []))]
    )
    if not keywords:
        return None
    evidence = LearningEvidence(
        source_id=artifact.id,
        source_type="agent_discussion",
        evidence_type=EvidenceType.EXPOSURE,
        evidence_outcome=EvidenceOutcome.UNKNOWN,
        confidence=0.0,
        evidence_strength=0.0,
        knowledge_point_ids=(
            [active_topic["entity_id"]]
            if active_topic.get("entity_type") == "knowledge_point"
            and active_topic.get("entity_id")
            else []
        ),
        context=EvidenceContext(),
    )
    EvidenceGate().validate(
        evidence,
        owner_user_id=run.user_id,
        source_user_id=run.user_id,
        source_run_id=run.id,
    )
    event = LearningActivityEvent(
        user_id=run.user_id,
        event_type="agent_explanation_completed",
        source_type="agent_discussion",
        source_id=artifact.id,
        thread_id=run.thread_id,
        run_id=run.id,
        topic_keywords_json=keywords,
        knowledge_point_ids_json=(
            [active_topic["entity_id"]]
            if active_topic.get("entity_type") == "knowledge_point" and active_topic.get("entity_id")
            else []
        ),
        evidence_type=evidence.evidence_type.value,
        evidence_outcome=evidence.evidence_outcome.value,
        evidence_strength=0.0,
        assessment_confidence=None,
        knowledge_point_coverage_json=evidence.knowledge_point_coverage,
        quality=0.35,
        is_correct=None,
        occurred_at=artifact.created_at,
        payload_json={
            "artifact_id": artifact.id,
            "title": artifact.content_json.get("title"),
            "learning_evidence": evidence.to_payload(),
            "evidence_weight_policy_version": "evidence-weight-v1",
        },
    )
    db.add(event)
    await db.flush()
    return event


async def record_agent_grade_activity(
    db: AsyncSession,
    *,
    run: AgentRun,
    artifact: AgentArtifact,
    grading: dict,
) -> LearningActivityEvent | None:
    """Project a confirmed Agent Grade into the same assessment event stream."""
    if not _valid_user_id(run.user_id):
        return None
    verdict = str(grading.get("verdict") or "").strip().lower()
    if verdict not in {"correct", "partial", "incorrect"}:
        return None
    source_id = str(grading.get("evidence_id") or artifact.id)
    existing = await db.scalar(
        select(LearningActivityEvent).where(
            LearningActivityEvent.user_id == run.user_id,
            LearningActivityEvent.event_type == "agent_grade_confirmed",
            LearningActivityEvent.source_id == source_id,
        )
    )
    if existing is not None:
        return existing
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    snapshot = metadata.get("context_snapshot") if isinstance(metadata.get("context_snapshot"), dict) else {}
    active_topic = snapshot.get("active_topic") if isinstance(snapshot.get("active_topic"), dict) else {}
    keywords = _keywords([active_topic.get("title"), *((active_topic.get("aliases") or []))])
    knowledge_point_ids = list(grading.get("knowledge_point_ids") or [])
    if not keywords and knowledge_point_ids:
        points = list(
            (
                await db.scalars(
                    select(KnowledgePoint).where(KnowledgePoint.id.in_(knowledge_point_ids))
                )
            ).all()
        )
        keywords = _keywords(
            [value for point in points for value in [point.canonical_title or point.title, *(point.aliases or [])]]
        )
    if not keywords:
        return None
    question_id = str(grading.get("question_id") or "").strip()
    if not question_id:
        return None
    artifact_content = artifact.content_json or {}
    feedback = artifact_content.get("content") if isinstance(artifact_content.get("content"), dict) else {}
    generated_question = (
        str(grading.get("assessment_source") or "").strip().lower()
        == "generated_question"
        or str(question_id).startswith("generated_")
    )
    evidence = build_assessment_evidence(
        source_id=source_id,
        source_type="agent_grade",
        verdict=verdict,
        question_id=question_id,
        knowledge_point_ids=knowledge_point_ids,
        answer_source=(
            "generated_question"
            if generated_question
            else grading.get("answer_source") or "manual"
        ),
        assessment_source=grading.get("assessment_source")
        or ("generated_question" if generated_question else "deterministic"),
        hint_levels_used=list(grading.get("hint_levels_used") or []),
        answer_exposed=bool(grading.get("answer_exposed", False)),
        confidence=grading.get("assessment_confidence", grading.get("confidence", 1.0)),
        model_version=grading.get("model_version"),
        knowledge_point_coverage=grading.get("knowledge_point_coverage"),
        error_tags=grading.get("error_tags") or grading.get("error_types") or [],
        evidence_type=grading.get("evidence_type"),
    )
    EvidenceGate().validate(
        evidence,
        owner_user_id=run.user_id,
        source_user_id=run.user_id,
        source_run_id=run.id,
        expected_question_id=question_id,
        verified_knowledge_point_ids=knowledge_point_ids,
    )
    evidence, weight = finalize_evidence_weight(
        evidence,
        question_review_status=grading.get("question_review_status"),
        suggested_weight=grading.get("suggested_weight"),
    )
    event = LearningActivityEvent(
        user_id=run.user_id,
        event_type="agent_grade_confirmed",
        source_type="agent_grade",
        source_id=source_id,
        thread_id=run.thread_id,
        run_id=run.id,
        topic_keywords_json=keywords,
        knowledge_point_ids_json=evidence.knowledge_point_ids,
        evidence_type=evidence.evidence_type.value,
        evidence_outcome=evidence.evidence_outcome.value,
        assessment_source=evidence.assessment_source.value
        if evidence.assessment_source
        else None,
        evidence_strength=weight.evidence_strength,
        assessment_confidence=evidence.assessment_confidence,
        model_version=evidence.model_version,
        knowledge_point_coverage_json=evidence.knowledge_point_coverage,
        quality=(
            1.0
            if verdict == "correct"
            else 0.5
            if verdict == "partial"
            else 0.25
        ),
        is_correct=True if verdict == "correct" else False if verdict == "incorrect" else None,
        occurred_at=artifact.created_at,
        payload_json={
            "artifact_id": artifact.id,
            "question_id": grading.get("question_id"),
            "content": "；".join(feedback.get("weaknesses") or []) or feedback.get("overall"),
            "source": "Agent 对话内批改",
            "error_types": list(grading.get("error_types") or []),
            "answer_source": (
                "generated_question"
                if generated_question
                else grading.get("answer_source") or "manual"
            ),
            "learning_evidence": evidence.to_payload(),
            "evidence_weight_policy_version": weight.policy_version,
            "evidence_weight_reasons": list(weight.reasons),
        },
    )
    db.add(event)
    await db.flush()
    return event
