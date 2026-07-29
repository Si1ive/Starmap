"""Project user-owned wrong answers into explainable weakness clusters."""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import Question
from app.modules.agent.weakness_projector import WeaknessProjector
from app.modules.agent.time_utils import utc_now
from app.modules.learning.service import normalize_keyword
from app.modules.learning.models import LearningActivityEvent
from app.modules.practice.models import (
    PracticeAnswer,
    PracticeSession,
    PracticeSessionQuestion,
)


def _snapshot_keywords(snapshot: dict, question: Question) -> list[str]:
    values = [
        *(snapshot.get("topic_terms") or question.topic_terms or []),
        *(snapshot.get("tags") or question.tags or []),
    ]
    result = []
    for value in values:
        keyword = normalize_keyword(str(value))
        if len(keyword) >= 2 and keyword not in result:
            result.append(keyword)
        if len(result) >= 4:
            break
    if not result:
        fallback = normalize_keyword(question.source_section_path or "未标注考点")
        if len(fallback) >= 2:
            result.append(fallback)
    return result


def project_weakness_rows(rows: list[tuple], now: datetime) -> dict:
    return project_weakness_evidence(_weakness_evidence_from_rows(rows), now)


def _weakness_evidence_from_rows(rows: list[tuple]) -> list[dict]:
    evidence_records = []
    for answer, session, link, question in rows:
        if not answer.user_answer or answer.is_correct is None:
            continue
        snapshot = link.snapshot_json or {}
        evidence = {
            "source_type": "question",
            "source_id": f"{session.id}:{link.item_id}",
            "session_id": session.id,
            "session_title": session.title,
            "question_id": question.id,
            "question_no": snapshot.get("question_no"),
            "content": snapshot.get("content") or question.content,
            "source": snapshot.get("source") or question.source,
            "is_correct": bool(answer.is_correct),
            "occurred_at": answer.saved_at,
            "hint_levels_used": list(answer.hint_levels_used_json or []),
            "thread_id": session.agent_thread_id,
            "run_id": session.agent_run_id,
            "keywords": _snapshot_keywords(snapshot, question),
        }
        evidence_records.append(evidence)
    return evidence_records


def project_weakness_events(events: list[LearningActivityEvent], now: datetime) -> dict:
    return project_weakness_evidence(_weakness_evidence_from_events(events), now)


def _weakness_evidence_from_events(events: list[LearningActivityEvent]) -> list[dict]:
    evidence_records = []
    for event in events:
        if event.is_correct is None:
            continue
        payload = event.payload_json or {}
        evidence_records.append(
            {
                "source_type": event.source_type,
                "source_id": event.source_id,
                "session_id": payload.get("session_id"),
                "session_title": payload.get("session_title") or "Agent 对话练习",
                "question_id": payload.get("question_id")
                or payload.get("practice_item_id"),
                "question_no": None,
                "content": payload.get("content") or "Agent 已完成一次确定性批改",
                "source": payload.get("source")
                or ("Agent 练习" if event.thread_id else "练习记录"),
                "is_correct": bool(event.is_correct),
                "occurred_at": event.occurred_at,
                "hint_levels_used": list(payload.get("hint_levels_used") or []),
                "thread_id": event.thread_id,
                "run_id": event.run_id,
                "diagnostic_context": payload.get("diagnostic_context"),
                "keywords": [
                    keyword
                    for value in event.topic_keywords_json or []
                    if (keyword := normalize_keyword(value))
                ],
            }
        )
    return evidence_records


def project_weakness_evidence(evidence_records: list[dict], now: datetime) -> dict:
    grouped = defaultdict(list)
    wrong_timeline = []
    for evidence in evidence_records:
        for keyword in evidence.pop("keywords", []):
            grouped[keyword].append(evidence)
        if not evidence["is_correct"]:
            wrong_timeline.append(evidence)

    clusters = []
    for keyword, evidence in grouped.items():
        ordered = sorted(evidence, key=lambda item: item["occurred_at"])
        wrong = [item for item in ordered if not item["is_correct"]]
        if not wrong:
            continue
        last_wrong = wrong[-1]
        verified_after = any(
            item["is_correct"] and item["occurred_at"] > last_wrong["occurred_at"]
            for item in ordered
        )
        review_at = last_wrong["occurred_at"] + timedelta(
            days=1 if len(wrong) == 1 else 2
        )
        clusters.append(
            {
                "keyword": keyword,
                "wrong_count": len(wrong),
                "attempt_count": len(ordered),
                "last_wrong_at": last_wrong["occurred_at"].isoformat(),
                "next_review_at": review_at.isoformat(),
                "status": (
                    "awaiting_interval_verification"
                    if verified_after
                    else "due" if review_at <= now else "scheduled"
                ),
                "representative": {
                    key: value
                    for key, value in last_wrong.items()
                    if key != "occurred_at"
                },
                "recent_evidence": [
                    {
                        **{
                            key: value
                            for key, value in item.items()
                            if key != "occurred_at"
                        },
                        "occurred_at": item["occurred_at"].isoformat(),
                    }
                    for item in reversed(ordered[-5:])
                ],
            }
        )
    status_order = {"due": 0, "scheduled": 1, "awaiting_interval_verification": 2}
    clusters.sort(
        key=lambda item: (
            status_order[item["status"]],
            -item["wrong_count"],
            item["next_review_at"],
        )
    )
    wrong_timeline.sort(key=lambda item: item["occurred_at"], reverse=True)
    return {
        "generated_at": now.isoformat(),
        "summary": {
            "cluster_count": len(clusters),
            "wrong_answer_count": len(wrong_timeline),
            "due_count": sum(item["status"] == "due" for item in clusters),
        },
        "clusters": clusters,
        "timeline": [
            {
                **{key: value for key, value in item.items() if key != "occurred_at"},
                "occurred_at": item["occurred_at"].isoformat(),
            }
            for item in wrong_timeline[:20]
        ],
    }


class WeaknessService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: object, *, now: datetime | None = None) -> dict:
        effective_now = now or utc_now()
        events = list(
            (
                await self.db.scalars(
                    select(LearningActivityEvent)
                    .where(
                        LearningActivityEvent.user_id == user_id,
                    )
                    .order_by(LearningActivityEvent.occurred_at)
                )
            ).all()
        )
        projected_source_ids = {event.source_id for event in events}
        rows = (
            await self.db.execute(
                select(
                    PracticeAnswer,
                    PracticeSession,
                    PracticeSessionQuestion,
                    Question,
                )
                .join(PracticeSession, PracticeSession.id == PracticeAnswer.session_id)
                .join(
                    PracticeSessionQuestion,
                    (PracticeSessionQuestion.session_id == PracticeAnswer.session_id)
                    & (
                        PracticeSessionQuestion.question_id
                        == PracticeAnswer.question_id
                    ),
                )
                .join(Question, Question.id == PracticeAnswer.question_id)
                .where(
                    PracticeSession.user_id == user_id,
                    PracticeSession.status == "submitted",
                    PracticeAnswer.user_answer != "",
                )
            )
        ).all()
        legacy_rows = [
            row
            for row in rows
            if f"{row[1].id}:{row[2].item_id}" not in projected_source_ids
        ]
        # Re-project the merged evidence so a later correct result can verify an
        # earlier error even when the two facts came from different surfaces.
        records = [
            *_weakness_evidence_from_events(events),
            *_weakness_evidence_from_rows(legacy_rows),
        ]
        deduplicated = {
            (item["source_type"], item["source_id"]): item for item in records
        }
        projected = project_weakness_evidence(
            list(deduplicated.values()), effective_now
        )
        findings = WeaknessProjector().project(
            [*events, *_weakness_evidence_from_rows(legacy_rows)],
            now=effective_now,
        )
        projected["findings"] = [
            finding.model_dump(mode="json") for finding in findings
        ]
        projected["summary"].update(
            {
                "finding_count": len(findings),
                "confirmed_finding_count": sum(
                    finding.status == "confirmed" for finding in findings
                ),
                "diagnostic_finding_count": sum(
                    finding.status == "needs_diagnostic" for finding in findings
                ),
            }
        )
        return projected
