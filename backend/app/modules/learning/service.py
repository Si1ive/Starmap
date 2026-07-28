"""Project real learning evidence into Ebbinghaus retention trajectories."""

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import KnowledgePoint, Question
from app.modules.agent.models import UserLearningMastery
from app.modules.practice.models import (
    PracticeAnswer,
    PracticeSession,
    PracticeSessionQuestion,
    StudyTimerRecord,
)
from app.modules.learning.models import LearningActivityEvent

RETENTION_REVIEW_THRESHOLD = 0.55
CURVE_DAY_OFFSETS = (0, 1, 2, 4, 7, 14, 30)


@dataclass(frozen=True)
class LearningEvidence:
    keyword: str
    occurred_at: datetime
    quality: float
    correct: bool | None
    source_type: str
    source_id: str
    weight: int = 1


def normalize_keyword(value: str) -> str:
    keyword = re.sub(r"[\s，。；、:：/\\]+", "", str(value or "")).strip().lower()
    return keyword[:40]


def project_ebbinghaus(events: Iterable[LearningEvidence], now: datetime) -> dict:
    ordered = sorted(events, key=lambda item: item.occurred_at)
    if not ordered:
        raise ValueError("至少需要一条学习证据")
    strength_hours = 24.0
    last_at = ordered[0].occurred_at
    first = True
    correct_count = 0
    for event in ordered:
        quality = max(0.0, min(1.0, event.quality))
        repetitions = max(1, min(event.weight, 20))
        for _ in range(repetitions):
            elapsed_hours = max(
                0.0, (event.occurred_at - last_at).total_seconds() / 3600
            )
            retention_before = math.exp(-elapsed_hours / max(strength_hours, 0.1))
            if first:
                strength_hours = 12.0 + 24.0 * quality
                first = False
            elif quality >= 0.7:
                strength_hours = min(
                    24.0 * 180,
                    strength_hours * (1.35 + 0.75 * quality + 0.25 * retention_before),
                )
            else:
                strength_hours = max(6.0, strength_hours * (0.45 + 0.35 * quality))
            last_at = event.occurred_at
        if event.correct is True:
            correct_count += 1
    elapsed_now_hours = max(0.0, (now - last_at).total_seconds() / 3600)
    retention = math.exp(-elapsed_now_hours / strength_hours)
    review_after_hours = -strength_hours * math.log(RETENTION_REVIEW_THRESHOLD)
    next_review_at = last_at + timedelta(hours=review_after_hours)
    return {
        "retention": round(retention * 100, 1),
        "strength_hours": round(strength_hours, 2),
        "last_studied_at": last_at,
        "next_review_at": next_review_at,
        "evidence_count": len(ordered),
        "correct_count": correct_count,
        "curve": [
            {
                "day": day,
                "retention": round(
                    math.exp(-(elapsed_now_hours + day * 24) / strength_hours) * 100,
                    1,
                ),
            }
            for day in CURVE_DAY_OFFSETS
        ],
    }


class LearningProgressService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: object, *, now: datetime | None = None) -> dict:
        now = now or datetime.utcnow()
        activity_events = await self._load_activity_events(user_id)
        activity_source_ids = {item.source_id for item in activity_events}
        evidence = self._activity_evidence(activity_events)
        evidence.extend(await self._load_question_evidence(user_id, activity_source_ids))
        evidence.extend(await self._load_mastery_evidence(user_id))
        answered_questions, correct_questions = await self._question_totals(user_id)
        grouped: dict[str, list[LearningEvidence]] = defaultdict(list)
        for item in evidence:
            grouped[item.keyword].append(item)

        topics = []
        for keyword, items in grouped.items():
            projection = project_ebbinghaus(items, now)
            retention = projection["retention"]
            topics.append(
                {
                    "keyword": keyword,
                    **projection,
                    "last_studied_at": projection["last_studied_at"].isoformat(),
                    "next_review_at": projection["next_review_at"].isoformat(),
                    "status": (
                        "due"
                        if retention < RETENTION_REVIEW_THRESHOLD * 100
                        else "stable"
                    ),
                    "source_types": sorted({item.source_type for item in items}),
                }
            )
        topics.sort(
            key=lambda item: (
                item["status"] != "due",
                item["retention"],
                item["keyword"],
            )
        )

        timers = list(
            (
                await self.db.scalars(
                    select(StudyTimerRecord).where(
                        StudyTimerRecord.user_id == user_id,
                        StudyTimerRecord.status == "completed",
                    )
                )
            ).all()
        )
        submitted_sessions = list(
            (
                await self.db.scalars(
                    select(PracticeSession).where(
                        PracticeSession.user_id == user_id,
                        PracticeSession.status == "submitted",
                    )
                )
            ).all()
        )
        total_seconds = sum(int(item.actual_seconds or 0) for item in timers) + sum(
            min(
                item.duration_seconds,
                max(
                    0,
                    int(
                        (
                            (item.submitted_at or item.started_at) - item.started_at
                        ).total_seconds()
                    ),
                ),
            )
            for item in submitted_sessions
        )
        week = self._weekly_rhythm(timers, submitted_sessions, now)
        return {
            "generated_at": now.isoformat(),
            "summary": {
                "learned_keywords": len(topics),
                "due_keywords": sum(1 for item in topics if item["status"] == "due"),
                "answered_questions": answered_questions,
                "correct_questions": correct_questions,
                "accuracy_rate": (
                    round(correct_questions / answered_questions * 100, 1)
                    if answered_questions
                    else 0
                ),
                "study_seconds": total_seconds,
            },
            "topics": topics,
            "recent_activities": [self._activity_payload(item) for item in activity_events[:20]],
            "week": week,
        }

    async def _load_activity_events(self, user_id: object) -> list[LearningActivityEvent]:
        return list(
            (
                await self.db.scalars(
                    select(LearningActivityEvent)
                    .where(LearningActivityEvent.user_id == user_id)
                    .order_by(LearningActivityEvent.occurred_at.desc(), LearningActivityEvent.id.desc())
                )
            ).all()
        )

    @staticmethod
    def _activity_evidence(events: list[LearningActivityEvent]) -> list[LearningEvidence]:
        evidence: list[LearningEvidence] = []
        for event in events:
            for keyword in event.topic_keywords_json or []:
                normalized = normalize_keyword(keyword)
                if not normalized:
                    continue
                evidence.append(
                    LearningEvidence(
                        keyword=normalized,
                        occurred_at=event.occurred_at,
                        quality=event.quality,
                        correct=event.is_correct,
                        source_type=event.source_type,
                        source_id=event.source_id,
                    )
                )
        return evidence

    @staticmethod
    def _activity_payload(event: LearningActivityEvent) -> dict:
        payload = event.payload_json or {}
        return {
            "id": event.id,
            "event_type": event.event_type,
            "source_type": event.source_type,
            "source_id": event.source_id,
            "topic_keywords": list(event.topic_keywords_json or []),
            "is_correct": event.is_correct,
            "occurred_at": event.occurred_at.isoformat(),
            "session_id": payload.get("session_id"),
            "thread_id": event.thread_id,
            "run_id": event.run_id,
            "title": payload.get("session_title") or payload.get("title"),
        }

    async def _load_question_evidence(
        self,
        user_id: object,
        projected_source_ids: set[str] | None = None,
    ) -> list[LearningEvidence]:
        rows = (
            await self.db.execute(
                select(PracticeAnswer, PracticeSessionQuestion, Question)
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
        evidence = []
        for answer, session_question, question in rows:
            source_id = f"{answer.session_id}:{session_question.item_id}"
            if source_id in (projected_source_ids or set()):
                continue
            snapshot = session_question.snapshot_json or {}
            keywords = self._keywords(
                snapshot.get("topic_terms") or question.topic_terms or [],
                snapshot.get("tags") or question.tags or [],
                [question.source_section_path or ""],
            )
            for keyword in keywords:
                evidence.append(
                    LearningEvidence(
                        keyword=keyword,
                        occurred_at=answer.saved_at,
                        quality=1.0 if answer.is_correct else 0.25,
                        correct=answer.is_correct,
                        source_type="question",
                        source_id=source_id,
                    )
                )
        return evidence

    async def _question_totals(self, user_id: object) -> tuple[int, int]:
        answered, correct = (
            await self.db.execute(
                select(
                    func.count(PracticeAnswer.id),
                    func.sum(case((PracticeAnswer.is_correct.is_(True), 1), else_=0)),
                )
                .join(
                    PracticeSession,
                    PracticeSession.id == PracticeAnswer.session_id,
                )
                .where(
                    PracticeSession.user_id == user_id,
                    PracticeSession.status == "submitted",
                    PracticeAnswer.user_answer != "",
                )
            )
        ).one()
        return int(answered or 0), int(correct or 0)

    async def _load_mastery_evidence(self, user_id: object) -> list[LearningEvidence]:
        rows = (
            await self.db.execute(
                select(UserLearningMastery, KnowledgePoint)
                .join(
                    KnowledgePoint,
                    KnowledgePoint.id == UserLearningMastery.knowledge_point_id,
                )
                .where(
                    UserLearningMastery.user_id == user_id.hex,
                    UserLearningMastery.evidence_count > 0,
                    UserLearningMastery.last_graded_at.is_not(None),
                )
            )
        ).all()
        evidence = []
        for mastery, point in rows:
            keywords = self._keywords(
                point.topic_terms or [],
                point.aliases or [],
                [point.canonical_title or point.title],
            )
            for keyword in keywords:
                evidence.append(
                    LearningEvidence(
                        keyword=keyword,
                        occurred_at=mastery.last_graded_at,
                        quality=max(0.0, min(1.0, float(mastery.mastery_score or 0))),
                        correct=None,
                        source_type="knowledge_point",
                        source_id=point.id,
                        weight=max(1, int(mastery.evidence_count or 1)),
                    )
                )
        return evidence

    @staticmethod
    def _keywords(*groups: Iterable[str]) -> list[str]:
        result = []
        for group in groups:
            for value in group:
                keyword = normalize_keyword(value)
                if 2 <= len(keyword) <= 40 and keyword not in result:
                    result.append(keyword)
                if len(result) >= 6:
                    return result
        return result

    @staticmethod
    def _weekly_rhythm(timers, sessions, now: datetime) -> list[dict]:
        monday = (now - timedelta(days=now.weekday())).date()
        seconds_by_day = defaultdict(int)
        for timer in timers:
            day = (timer.completed_at or timer.started_at).date()
            if monday <= day <= monday + timedelta(days=6):
                seconds_by_day[day] += int(timer.actual_seconds or 0)
        for session in sessions:
            day = (session.submitted_at or session.started_at).date()
            if monday <= day <= monday + timedelta(days=6):
                seconds_by_day[day] += min(
                    session.duration_seconds,
                    max(
                        0,
                        int(
                            (
                                (session.submitted_at or session.started_at)
                                - session.started_at
                            ).total_seconds()
                        ),
                    ),
                )
        return [
            {
                "date": (monday + timedelta(days=offset)).isoformat(),
                "study_seconds": seconds_by_day[monday + timedelta(days=offset)],
            }
            for offset in range(7)
        ]
