"""Project trusted product events into learning activity facts."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import AgentArtifact, AgentRun
from app.modules.practice.models import PracticeAnswer, PracticeSession, PracticeSessionQuestion

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
        event = LearningActivityEvent(
            user_id=session.user_id,
            event_type="practice_answer_graded",
            source_type="agent_practice" if session.source_type == "agent" else "question",
            source_id=source_id,
            thread_id=session.agent_thread_id,
            run_id=session.agent_run_id,
            topic_keywords_json=keywords,
            knowledge_point_ids_json=list(snapshot.get("knowledge_point_ids") or []),
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
        quality=0.35,
        is_correct=None,
        occurred_at=artifact.created_at,
        payload_json={"artifact_id": artifact.id, "title": artifact.content_json.get("title")},
    )
    db.add(event)
    await db.flush()
    return event
