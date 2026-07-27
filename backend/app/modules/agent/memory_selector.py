"""Load workflow-neutral memory bundles from persisted snapshots."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    KnowledgePoint,
    KnowledgePointChapterLink,
    Question,
    QuestionKnowledgeLink,
)

from .mastery_decay import calculate_effective_mastery
from .memory_contracts import MemoryFactType, MemoryNeed, MemoryPartition
from .models import (
    AgentMemoryEvent,
    AgentMemoryItem,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentRun,
    UserLearningMastery,
)
from .preference_memory import PreferenceSource, load_preference_bundle
from .time_utils import utc_isoformat, utc_now

_EXCLUDED_EVENT_LIMIT = 10
_EXCLUDED_QUESTION_LIMIT = 50
_WEAK_MASTERY_THRESHOLD = 0.6


class TopicBundle(BaseModel):
    title: str
    entity_type: str
    entity_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    source: str


class PracticeBundle(BaseModel):
    snapshot_id: str | None = None
    standalone_request: str | None = None
    topic: TopicBundle | None = None
    constraints: list[str] = Field(default_factory=list)
    unresolved_constraints: list[str] = Field(default_factory=list)
    difficulty: str | None = None
    knowledge_point_ids: list[str] = Field(default_factory=list)
    chapter_ids: list[str] = Field(default_factory=list)
    chapter_scope_source: Literal["explicit", "knowledge_point"] | None = None
    reference_sources: list[dict[str, Any]] = Field(default_factory=list)
    selected_artifact_ids: list[str] = Field(default_factory=list)
    mastery_signals: list[dict[str, Any]] = Field(default_factory=list)
    excluded_question_ids: list[str] = Field(default_factory=list)


class PlanningTarget(BaseModel):
    title: str
    target: str
    source: Literal["snapshot_topic", "approved_goal", "learning_mastery"]
    entity_type: str | None = None
    entity_id: str | None = None
    source_id: str | None = None
    daily_minutes: int | None = Field(default=None, ge=1, le=1440)
    mastery_score: float | None = Field(default=None, ge=0, le=1)
    evidence_id: str | None = None


class PlanningBundle(BaseModel):
    snapshot_id: str | None = None
    standalone_request: str | None = None
    period: str | None = None
    targets: list[PlanningTarget] = Field(default_factory=list)
    learning_goal_item_ids: list[str] = Field(default_factory=list)
    mastery_signals: list[dict[str, Any]] = Field(default_factory=list)
    preferences: dict[str, str | int | bool] = Field(default_factory=dict)
    preference_sources: list[PreferenceSource] = Field(default_factory=list)


class EvaluationQuestion(BaseModel):
    id: str
    question_type: Literal[
        "choice", "fill", "judge", "short_answer", "design", "analysis"
    ]
    content: str
    options: list[dict[str, Any]] = Field(default_factory=list)
    standard_answer: str
    answer_source: Literal["extracted", "manual", "llm"]
    explanation: str | None = None
    knowledge_point_ids: list[str] = Field(default_factory=list)
    subject_id: str | None = None
    source_artifact_id: str | None = None


class EvaluationBundle(BaseModel):
    snapshot_id: str | None = None
    standalone_request: str | None = None
    raw_input: str | None = None
    user_answer: str | None = None
    question: EvaluationQuestion | None = None
    unresolved_reason: Literal[
        "run_not_found",
        "snapshot_not_found",
        "question_reference_missing",
        "question_reference_ambiguous",
        "question_not_eligible",
        "user_answer_missing",
    ] | None = None


_ANSWER_PREFIX_PATTERN = re.compile(
    r"(?:(?:我的\s*)?(?:答案|作答)\s*(?:是|为|：|:)\s*|我\s*选(?:择)?\s*)(.+)",
    re.IGNORECASE,
)
_ANSWER_SUFFIX_PATTERN = re.compile(
    r"\s*[，,。；;！？!?]?\s*(?:请|帮我|麻烦|对吗|是否正确|正确吗|批改|评分).*$"
)
_CHOICE_ANSWER_PATTERN = re.compile(r"(?:选(?:择)?\s*)?([A-H])\b", re.IGNORECASE)


def _extract_user_answer(raw_input: str, question_type: str) -> str | None:
    """从显式“答案/作答”表达中提取最小答案，不猜测普通请求正文。"""
    normalized_input = raw_input.strip()
    match = _ANSWER_PREFIX_PATTERN.search(normalized_input)
    answer_text = match.group(1).strip() if match else ""
    if question_type == "choice":
        choice_match = _CHOICE_ANSWER_PATTERN.search(answer_text)
        return choice_match.group(1).upper() if choice_match else None
    if question_type == "judge":
        for token in ("不正确", "不对", "错误", "正确", "对", "错", "√", "×", "true", "false"):
            if token.casefold() in answer_text.casefold():
                return token
        return None
    if not answer_text:
        return None
    answer_text = _ANSWER_SUFFIX_PATTERN.sub("", answer_text).strip(" \t\r\n\"'“”‘’")
    return answer_text or None


def _bundle_topic_from_understanding(understanding: dict[str, Any]) -> TopicBundle | None:
    topic_entities = understanding.get("topic_entities") or []
    if not topic_entities:
        return None
    topic = topic_entities[0]
    title = str(topic.get("title") or "").strip()
    entity_type = str(topic.get("entity_type") or "").strip()
    if not title or not entity_type:
        return None
    aliases = [
        str(alias).strip()
        for alias in (topic.get("aliases") or [])
        if str(alias).strip()
    ]
    return TopicBundle(
        title=title,
        entity_type=entity_type,
        entity_id=str(topic.get("entity_id")) if topic.get("entity_id") else None,
        aliases=aliases,
        source=str(topic.get("source") or "snapshot"),
    )


def _bundle_topic(snapshot: AgentMemorySnapshot) -> TopicBundle | None:
    understanding = snapshot.understanding_json or {}
    return _bundle_topic_from_understanding(understanding)


def _bundle_difficulty(constraints: list[str]) -> str | None:
    normalized_constraints = [str(item).strip() for item in constraints if str(item).strip()]
    for constraint in normalized_constraints:
        if constraint.startswith("difficulty:"):
            difficulty = constraint.split(":", 1)[1].strip().lower()
            if difficulty in {"easy", "medium", "hard"}:
                return difficulty
    for constraint in normalized_constraints:
        if "难度适中" in constraint or "适中" in constraint or "中等" in constraint:
            return "medium"
        if "难一点" in constraint or "难一些" in constraint or "难点" in constraint:
            return "hard"
        if "简单点" in constraint or "容易点" in constraint or "基础点" in constraint:
            return "easy"
    return None


def _mastery_signal(
    mastery: UserLearningMastery,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """从不可变统计值派生带策略版本的有效掌握度审计副本。"""
    if mastery.evidence_count <= 0:
        return None
    evidence_at = mastery.last_graded_at
    evidence_time_source = "last_graded_at"
    if evidence_at is None:
        evidence_at = mastery.updated_at
        evidence_time_source = "updated_at"
    if evidence_at is None:
        evidence_at = mastery.created_at
        evidence_time_source = "created_at"
    if evidence_at is None:
        return None
    effective = calculate_effective_mastery(
        mastery.mastery_score,
        evidence_at=evidence_at,
        now=now,
    )
    return {
        "mastery_id": mastery.id,
        "knowledge_point_id": mastery.knowledge_point_id,
        # 兼容既有 Bundle 消费方：mastery_score 现在明确表示有效分数。
        "mastery_score": effective.effective_score,
        "raw_mastery_score": effective.raw_score,
        "effective_mastery_score": effective.effective_score,
        "evidence_count": mastery.evidence_count,
        "last_evidence_id": mastery.last_evidence_id,
        "evidence_at": utc_isoformat(effective.evidence_at),
        "evidence_time_source": evidence_time_source,
        "age_days": effective.age_days,
        "decay_policy_version": effective.policy_version,
    }


async def _load_frozen_mastery_signals(
    db: AsyncSession,
    *,
    snapshot_id: str,
    memory_need: MemoryNeed,
) -> list[dict[str, Any]]:
    items = list(
        (
            await db.execute(
                select(AgentMemorySnapshotItem)
                .where(
                    AgentMemorySnapshotItem.snapshot_id == snapshot_id,
                    AgentMemorySnapshotItem.memory_need == memory_need.value,
                    AgentMemorySnapshotItem.memory_partition
                    == MemoryPartition.LEARNING_MASTERY.value,
                    AgentMemorySnapshotItem.source_kind == "user_learning_mastery",
                    AgentMemorySnapshotItem.selected.is_(True),
                )
                .order_by(AgentMemorySnapshotItem.id)
            )
        ).scalars()
    )
    return [dict(item.payload_json or {}) for item in items]


async def _freeze_mastery_signals(
    db: AsyncSession,
    *,
    snapshot_id: str,
    memory_need: MemoryNeed,
    masteries_by_id: dict[int, UserLearningMastery],
    signals: list[dict[str, Any]],
) -> None:
    # 同一 child Run 理论上只有一个 Worker；仍锁定 snapshot 并在锁内复核，
    # 让租约重领或管理员重放不会追加第二份相同选择。
    locked_snapshot_id = await db.scalar(
        select(AgentMemorySnapshot.id)
        .where(AgentMemorySnapshot.id == snapshot_id)
        .with_for_update()
    )
    if locked_snapshot_id is None:
        return
    if await _load_frozen_mastery_signals(
        db,
        snapshot_id=snapshot_id,
        memory_need=memory_need,
    ):
        return
    for signal in signals:
        mastery_id = signal.get("mastery_id")
        if not isinstance(mastery_id, int) or isinstance(mastery_id, bool):
            continue
        mastery = masteries_by_id.get(mastery_id)
        if mastery is None:
            continue
        db.add(
            AgentMemorySnapshotItem(
                snapshot_id=snapshot_id,
                memory_need=memory_need.value,
                memory_partition=MemoryPartition.LEARNING_MASTERY.value,
                source_kind="user_learning_mastery",
                source_id=str(mastery.id),
                item_key=(
                    f"{memory_need.value}:mastery:{mastery.id}:"
                    f"{mastery.evidence_count}"
                ),
                version=mastery.evidence_count,
                selected=True,
                selection_reason="effective_mastery_below_threshold",
                token_estimate=0,
                payload_json=signal,
            )
        )
    await db.flush()


async def load_planning_bundle(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
    now: datetime | None = None,
) -> PlanningBundle:
    """按当前主题、批准目标和真实掌握度选择最小规划记忆。"""
    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
        )
    )
    if run is None:
        return PlanningBundle()
    effective_now = now or utc_now()

    metadata = run.metadata_json or {}
    snapshot_id = metadata.get("memory_snapshot_id")
    snapshot = None
    if snapshot_id:
        snapshot = await db.scalar(
            select(AgentMemorySnapshot).where(
                AgentMemorySnapshot.id == snapshot_id,
                AgentMemorySnapshot.user_id == user_id,
                AgentMemorySnapshot.thread_id == run.thread_id,
            )
        )

    preference_bundle = await load_preference_bundle(
        db,
        run_id=run_id,
        user_id=user_id,
        memory_need=MemoryNeed.PLANNING_GOAL,
    )

    goal_items = list(
        (
            await db.execute(
                select(AgentMemoryItem)
                .where(
                    AgentMemoryItem.user_id == user_id,
                    AgentMemoryItem.scope == "user",
                    AgentMemoryItem.thread_id.is_(None),
                    AgentMemoryItem.item_type == "learning_goal",
                    AgentMemoryItem.status == "active",
                )
                .order_by(AgentMemoryItem.updated_at.desc(), AgentMemoryItem.id.desc())
                .limit(1)
            )
        ).scalars()
    )
    frozen_mastery_signals = (
        await _load_frozen_mastery_signals(
            db,
            snapshot_id=snapshot.id,
            memory_need=MemoryNeed.PLANNING_GOAL,
        )
        if snapshot is not None
        else []
    )
    weak_candidates: list[dict[str, Any]] = []
    if frozen_mastery_signals:
        weak_candidates = [
            signal
            for signal in frozen_mastery_signals
            if str(signal.get("knowledge_point_title") or "").strip()
        ]
    else:
        mastery_rows = (
            await db.execute(
                select(UserLearningMastery, KnowledgePoint)
                .join(
                    KnowledgePoint,
                    KnowledgePoint.id == UserLearningMastery.knowledge_point_id,
                )
                .where(
                    UserLearningMastery.user_id == user_id,
                    UserLearningMastery.evidence_count > 0,
                    KnowledgePoint.status == "active",
                )
            )
        ).all()
        live_candidates = [
            (
                {
                    **signal,
                    "knowledge_point_title": knowledge_point.title,
                    "knowledge_point_aliases": [
                        str(alias).strip()
                        for alias in (knowledge_point.aliases or [])
                        if str(alias).strip()
                    ],
                },
                mastery,
            )
            for mastery, knowledge_point in mastery_rows
            if (signal := _mastery_signal(mastery, now=effective_now)) is not None
            and signal["effective_mastery_score"] < _WEAK_MASTERY_THRESHOLD
        ]
        live_candidates.sort(
            key=lambda item: (
                item[0]["effective_mastery_score"],
                -item[0]["evidence_count"],
                item[0]["knowledge_point_id"],
            )
        )
        selected_candidates = live_candidates[:10]
        weak_candidates = [signal for signal, _mastery in selected_candidates]
        if snapshot is not None and selected_candidates:
            await _freeze_mastery_signals(
                db,
                snapshot_id=snapshot.id,
                memory_need=MemoryNeed.PLANNING_GOAL,
                masteries_by_id={
                    mastery.id: mastery
                    for _signal, mastery in selected_candidates
                },
                signals=[signal for signal, _mastery in selected_candidates],
            )

    targets: list[PlanningTarget] = []
    seen_titles: set[str] = set()

    def add_target(target: PlanningTarget) -> None:
        key = target.title.strip().casefold()
        if not key or key in seen_titles:
            return
        seen_titles.add(key)
        targets.append(target)

    topic = _bundle_topic(snapshot) if snapshot is not None else None
    if topic is not None:
        add_target(
            PlanningTarget(
                title=topic.title,
                target="围绕当前主题继续巩固",
                source="snapshot_topic",
                entity_type=topic.entity_type,
                entity_id=topic.entity_id,
                source_id=snapshot.id,
            )
        )

    period = None
    for item in goal_items:
        goal_metadata = item.metadata_json or {}
        if period is None:
            normalized_period = str(goal_metadata.get("period") or "").strip()
            period = normalized_period or None
        goals = goal_metadata.get("goals") or []
        if not isinstance(goals, list):
            continue
        for goal in goals:
            if not isinstance(goal, dict):
                continue
            title = str(goal.get("subject") or goal.get("title") or "").strip()
            target_text = str(goal.get("target") or "").strip()
            if not title or not target_text:
                continue
            daily_minutes = goal.get("daily_minutes")
            if (
                not isinstance(daily_minutes, int)
                or isinstance(daily_minutes, bool)
                or not 1 <= daily_minutes <= 1440
            ):
                daily_minutes = None
            add_target(
                PlanningTarget(
                    title=title,
                    target=target_text,
                    source="approved_goal",
                    source_id=item.id,
                    daily_minutes=daily_minutes,
                )
            )

    mastery_signals: list[dict[str, Any]] = []
    for signal in weak_candidates:
        mastery_signals.append(signal)
        add_target(
            PlanningTarget(
                title=signal["knowledge_point_title"],
                target="针对真实薄弱点进行巩固",
                source="learning_mastery",
                entity_type="knowledge_point",
                entity_id=signal["knowledge_point_id"],
                source_id=signal["knowledge_point_id"],
                mastery_score=signal["effective_mastery_score"],
                evidence_id=signal.get("last_evidence_id"),
            )
        )

    return PlanningBundle(
        snapshot_id=snapshot.id if snapshot is not None else None,
        standalone_request=(
            snapshot.standalone_request if snapshot is not None else run.input_message
        ),
        period=period,
        targets=targets,
        learning_goal_item_ids=[item.id for item in goal_items],
        mastery_signals=mastery_signals,
        preferences=preference_bundle.values,
        preference_sources=preference_bundle.selected_sources,
    )


async def load_evaluation_bundle(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
) -> EvaluationBundle:
    """按快照中的唯一题目引用装载可信题面、标准答案与本轮作答。"""
    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
        )
    )
    if run is None:
        return EvaluationBundle(unresolved_reason="run_not_found")

    snapshot_id = (run.metadata_json or {}).get("memory_snapshot_id")
    if not snapshot_id:
        return EvaluationBundle(
            standalone_request=run.input_message,
            unresolved_reason="snapshot_not_found",
        )
    snapshot = await db.scalar(
        select(AgentMemorySnapshot).where(
            AgentMemorySnapshot.id == snapshot_id,
            AgentMemorySnapshot.user_id == user_id,
            AgentMemorySnapshot.thread_id == run.thread_id,
        )
    )
    if snapshot is None:
        return EvaluationBundle(
            standalone_request=run.input_message,
            unresolved_reason="snapshot_not_found",
        )

    understanding = snapshot.understanding_json or {}
    raw_input = str(understanding.get("raw_input") or "").strip()
    question_references: dict[str, dict[str, Any]] = {}
    for reference in understanding.get("reference_sources") or []:
        if not isinstance(reference, dict) or reference.get("type") != "question":
            continue
        question_id = str(reference.get("id") or "").strip()
        if question_id:
            question_references.setdefault(question_id, reference)
    if not question_references:
        return EvaluationBundle(
            snapshot_id=snapshot.id,
            standalone_request=snapshot.standalone_request,
            raw_input=raw_input or None,
            unresolved_reason="question_reference_missing",
        )
    if len(question_references) != 1:
        return EvaluationBundle(
            snapshot_id=snapshot.id,
            standalone_request=snapshot.standalone_request,
            raw_input=raw_input or None,
            unresolved_reason="question_reference_ambiguous",
        )

    question_id, reference = next(iter(question_references.items()))
    question = await db.scalar(
        select(Question).where(
            Question.id == question_id,
            Question.status == "active",
            Question.review_status != "rejected",
            Question.answer_source.in_(("extracted", "manual", "llm")),
        )
    )
    if question is None or not str(question.answer or "").strip():
        return EvaluationBundle(
            snapshot_id=snapshot.id,
            standalone_request=snapshot.standalone_request,
            raw_input=raw_input or None,
            unresolved_reason="question_not_eligible",
        )

    linked_knowledge_point_ids = list(
        (
            await db.execute(
                select(QuestionKnowledgeLink.knowledge_point_id)
                .where(QuestionKnowledgeLink.question_id == question.id)
                .order_by(
                    QuestionKnowledgeLink.relevance.desc(),
                    QuestionKnowledgeLink.knowledge_point_id,
                )
            )
        ).scalars()
    )
    knowledge_point_ids = list(
        dict.fromkeys(
            normalized
            for value in [
                *(question.knowledge_point_ids or []),
                *linked_knowledge_point_ids,
            ]
            if (normalized := str(value).strip())
        )
    )
    user_answer = _extract_user_answer(raw_input, question.type)
    if user_answer is None:
        return EvaluationBundle(
            snapshot_id=snapshot.id,
            standalone_request=snapshot.standalone_request,
            raw_input=raw_input or None,
            unresolved_reason="user_answer_missing",
        )

    source_artifact_id = str(reference.get("artifact_id") or "").strip() or None
    selected_artifact_ids = set(
        (snapshot.selection_metadata_json or {}).get("selected_artifact_ids") or []
    )
    if source_artifact_id not in selected_artifact_ids:
        source_artifact_id = None

    return EvaluationBundle(
        snapshot_id=snapshot.id,
        standalone_request=snapshot.standalone_request,
        raw_input=raw_input,
        user_answer=user_answer,
        question=EvaluationQuestion(
            id=question.id,
            question_type=question.type,
            content=question.content,
            options=list(question.options or []),
            standard_answer=question.answer,
            answer_source=question.answer_source,
            explanation=question.explanation,
            knowledge_point_ids=knowledge_point_ids,
            subject_id=question.subject_id,
            source_artifact_id=source_artifact_id,
        ),
    )


async def _load_excluded_question_ids(db: AsyncSession, *, user_id: str) -> list[str]:
    """按近期 practice 事实事件装载用户的真实排除集，越新的题排越前。"""
    events = (
        await db.execute(
            select(AgentMemoryEvent)
            .where(
                AgentMemoryEvent.user_id == user_id,
                AgentMemoryEvent.fact_type
                == MemoryFactType.PRACTICE_ARTIFACT_CREATED.value,
            )
            .order_by(AgentMemoryEvent.id.desc())
            .limit(_EXCLUDED_EVENT_LIMIT)
        )
    ).scalars()
    excluded: list[str] = []
    seen: set[str] = set()
    for event in events:
        for question_id in (event.payload_json or {}).get("question_ids") or []:
            normalized = str(question_id).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            excluded.append(normalized)
            if len(excluded) >= _EXCLUDED_QUESTION_LIMIT:
                return excluded
    return excluded


async def _load_chapter_ids(
    db: AsyncSession,
    knowledge_point_ids: list[str],
) -> list[str]:
    """从知识点章节关联读取标准章节 ID，主章节和高关联度优先。

    没有已解析知识点时返回空列表，把章节定位交给检索层的大纲扩展。
    """
    if not knowledge_point_ids:
        return []
    links = (
        await db.execute(
            select(KnowledgePointChapterLink)
            .where(
                KnowledgePointChapterLink.knowledge_point_id.in_(knowledge_point_ids)
            )
            .order_by(
                KnowledgePointChapterLink.is_primary.desc(),
                KnowledgePointChapterLink.relevance.desc(),
            )
        )
    ).scalars()
    chapter_ids: list[str] = []
    seen: set[str] = set()
    for link in links:
        if link.canonical_chapter_id in seen:
            continue
        seen.add(link.canonical_chapter_id)
        chapter_ids.append(link.canonical_chapter_id)
    return chapter_ids


async def _resolve_explicit_chapter_ids(
    db: AsyncSession,
    *,
    constraints: list[str],
    knowledge_point_ids: list[str],
) -> tuple[list[str] | None, list[str]]:
    """把显式章节序号解析到唯一学科的一级标准章节。

    返回 ``None`` 表示用户没有显式章节约束；返回空列表则表示存在显式约束但无法安全解析。
    """
    chapter_constraints = [
        constraint
        for constraint in constraints
        if constraint.startswith("chapter_ordinal:")
    ]
    if not chapter_constraints:
        return None, []
    if len(chapter_constraints) != 1 or not knowledge_point_ids:
        return [], chapter_constraints
    try:
        ordinal = int(chapter_constraints[0].split(":", 1)[1])
    except (IndexError, ValueError):
        return [], chapter_constraints
    if ordinal < 1:
        return [], chapter_constraints

    subject_ids = list(
        (
            await db.execute(
                select(KnowledgePoint.subject_id)
                .where(KnowledgePoint.id.in_(knowledge_point_ids))
                .distinct()
            )
        ).scalars()
    )
    if len(subject_ids) != 1:
        return [], chapter_constraints
    chapter_id = await db.scalar(
        select(CanonicalChapter.id)
        .where(
            CanonicalChapter.subject_id == subject_ids[0],
            CanonicalChapter.parent_id.is_(None),
            CanonicalChapter.level == 1,
            CanonicalChapter.status == "active",
        )
        .order_by(CanonicalChapter.sort_order, CanonicalChapter.id)
        .offset(ordinal - 1)
        .limit(1)
    )
    if chapter_id is None:
        return [], chapter_constraints
    return [chapter_id], []


async def _load_unique_weak_topic(
    db: AsyncSession,
    *,
    user_id: str,
    now: datetime,
    snapshot: AgentMemorySnapshot | None = None,
) -> tuple[TopicBundle | None, list[dict[str, Any]]]:
    """按有效掌握度选择唯一薄弱点，并为同一 Snapshot 冻结首次选择。"""
    frozen_signals = (
        await _load_frozen_mastery_signals(
            db,
            snapshot_id=snapshot.id,
            memory_need=MemoryNeed.PRACTICE_GENERATION,
        )
        if snapshot is not None
        else []
    )
    selected: list[tuple[UserLearningMastery | None, dict[str, Any]]] = []
    if frozen_signals:
        selected = [(None, signal) for signal in frozen_signals]
    else:
        mastery_rows = list(
            (
                await db.execute(
                    select(UserLearningMastery).where(
                        UserLearningMastery.user_id == user_id,
                        UserLearningMastery.evidence_count > 0,
                    )
                )
            ).scalars()
        )
        live_candidates = [
            (mastery, signal)
            for mastery in mastery_rows
            if (signal := _mastery_signal(mastery, now=now)) is not None
            and signal["effective_mastery_score"] < _WEAK_MASTERY_THRESHOLD
        ]
        live_candidates.sort(
            key=lambda item: (
                item[1]["effective_mastery_score"],
                -item[1]["evidence_count"],
                item[1]["knowledge_point_id"],
            )
        )
        selected = live_candidates[:2]
    if len(selected) != 1:
        return None, []
    mastery, signal = selected[0]
    if frozen_signals:
        title = str(signal.get("knowledge_point_title") or "").strip()
        aliases = [
            str(alias).strip()
            for alias in signal.get("knowledge_point_aliases") or []
            if str(alias).strip()
        ]
        if not title:
            return None, []
    else:
        knowledge_point = await db.scalar(
            select(KnowledgePoint).where(
                KnowledgePoint.id == signal["knowledge_point_id"],
                KnowledgePoint.status == "active",
            )
        )
        if knowledge_point is None:
            return None, []
        title = knowledge_point.title
        aliases = [
            str(alias).strip()
            for alias in (knowledge_point.aliases or [])
            if str(alias).strip()
        ]
        signal = {
            **signal,
            "knowledge_point_title": title,
            "knowledge_point_aliases": aliases,
        }
        if snapshot is not None and mastery is not None:
            await _freeze_mastery_signals(
                db,
                snapshot_id=snapshot.id,
                memory_need=MemoryNeed.PRACTICE_GENERATION,
                masteries_by_id={mastery.id: mastery},
                signals=[signal],
            )
    topic = TopicBundle(
        title=title,
        entity_type="knowledge_point",
        entity_id=signal["knowledge_point_id"],
        aliases=aliases,
        source="learning_mastery",
    )
    return topic, [signal]


async def load_practice_bundle(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
    now: datetime | None = None,
) -> PracticeBundle:
    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
        )
    )
    if run is None:
        return PracticeBundle()
    effective_now = now or utc_now()

    excluded_question_ids = await _load_excluded_question_ids(db, user_id=user_id)
    metadata = run.metadata_json or {}
    snapshot_id = metadata.get("memory_snapshot_id")
    if not snapshot_id:
        topic, mastery_signals = await _load_unique_weak_topic(
            db,
            user_id=user_id,
            now=effective_now,
        )
        knowledge_point_ids = (
            [topic.entity_id] if topic is not None and topic.entity_id else []
        )
        chapter_ids = await _load_chapter_ids(db, knowledge_point_ids)
        return PracticeBundle(
            topic=topic,
            knowledge_point_ids=knowledge_point_ids,
            chapter_ids=chapter_ids,
            chapter_scope_source="knowledge_point" if chapter_ids else None,
            mastery_signals=mastery_signals,
            selected_artifact_ids=list(
                (metadata.get("context_snapshot") or {}).get("selected_artifact_ids") or []
            ),
            excluded_question_ids=excluded_question_ids,
        )

    snapshot = await db.scalar(
        select(AgentMemorySnapshot).where(
            AgentMemorySnapshot.id == snapshot_id,
            AgentMemorySnapshot.user_id == user_id,
            AgentMemorySnapshot.thread_id == run.thread_id,
        )
    )
    if snapshot is None:
        topic, mastery_signals = await _load_unique_weak_topic(
            db,
            user_id=user_id,
            now=effective_now,
        )
        knowledge_point_ids = (
            [topic.entity_id] if topic is not None and topic.entity_id else []
        )
        chapter_ids = await _load_chapter_ids(db, knowledge_point_ids)
        return PracticeBundle(
            snapshot_id=str(snapshot_id),
            topic=topic,
            knowledge_point_ids=knowledge_point_ids,
            chapter_ids=chapter_ids,
            chapter_scope_source="knowledge_point" if chapter_ids else None,
            mastery_signals=mastery_signals,
            excluded_question_ids=excluded_question_ids,
        )

    snapshot_items = list(
        (
            await db.execute(
                select(AgentMemorySnapshotItem).where(
                    AgentMemorySnapshotItem.snapshot_id == snapshot.id,
                    AgentMemorySnapshotItem.memory_need.in_(
                        (
                            MemoryNeed.TOPIC_FOCUS.value,
                            MemoryNeed.PRACTICE_GENERATION.value,
                        )
                    ),
                    AgentMemorySnapshotItem.selected.is_(True),
                )
            )
        ).scalars()
    )
    understanding = dict(snapshot.understanding_json or {})
    for item in snapshot_items:
        payload = item.payload_json or {}
        if not understanding.get("topic_entities") and payload.get("topic_entities"):
            understanding["topic_entities"] = payload.get("topic_entities")
        if not understanding.get("constraints") and payload.get("constraints"):
            understanding["constraints"] = payload.get("constraints")
        if not understanding.get("reference_sources") and payload.get("reference_sources"):
            understanding["reference_sources"] = payload.get("reference_sources")
    context_snapshot = snapshot.selection_metadata_json or metadata.get("context_snapshot") or {}
    topic = _bundle_topic_from_understanding(understanding)
    mastery_signals: list[dict[str, Any]] = []
    if topic is None:
        # 冲突优先级：快照主题（当前输入/引用/活跃主题）优先，全部缺失才回退唯一薄弱点。
        topic, mastery_signals = await _load_unique_weak_topic(
            db,
            user_id=user_id,
            now=effective_now,
            snapshot=snapshot,
        )
    knowledge_point_ids = (
        [topic.entity_id]
        if topic is not None
        and topic.entity_type == "knowledge_point"
        and topic.entity_id
        else []
    )
    constraints = list(understanding.get("constraints") or [])
    explicit_chapter_ids, unresolved_constraints = (
        await _resolve_explicit_chapter_ids(
            db,
            constraints=constraints,
            knowledge_point_ids=knowledge_point_ids,
        )
    )
    if explicit_chapter_ids is not None:
        chapter_ids = explicit_chapter_ids
        chapter_scope_source = "explicit"
    else:
        chapter_ids = await _load_chapter_ids(db, knowledge_point_ids)
        chapter_scope_source = "knowledge_point" if chapter_ids else None
    return PracticeBundle(
        snapshot_id=snapshot.id,
        standalone_request=snapshot.standalone_request,
        topic=topic,
        constraints=constraints,
        unresolved_constraints=unresolved_constraints,
        difficulty=_bundle_difficulty(constraints),
        knowledge_point_ids=knowledge_point_ids,
        chapter_ids=chapter_ids,
        chapter_scope_source=chapter_scope_source,
        reference_sources=list(understanding.get("reference_sources") or []),
        selected_artifact_ids=list(context_snapshot.get("selected_artifact_ids") or []),
        mastery_signals=mastery_signals,
        excluded_question_ids=_apply_explicit_question_repeat(excluded_question_ids, understanding),
    )


def build_practice_query(
    bundle: PracticeBundle | dict[str, Any] | None,
    fallback_terms: list[str],
) -> str:
    if bundle is None:
        bundle = PracticeBundle()
    if isinstance(bundle, dict):
        bundle = PracticeBundle.model_validate(bundle)
    if bundle.topic is None:
        return " ".join(fallback_terms) if fallback_terms else ""
    terms = [bundle.topic.title, *bundle.topic.aliases]
    unique_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_terms.append(normalized)
    return " ".join(unique_terms) if unique_terms else bundle.topic.title


def build_practice_filters(
    bundle: PracticeBundle | dict[str, Any] | None,
) -> dict[str, Any]:
    if bundle is None:
        bundle = PracticeBundle()
    if isinstance(bundle, dict):
        bundle = PracticeBundle.model_validate(bundle)
    filters: dict[str, Any] = {}
    if bundle.difficulty:
        filters["difficulty"] = bundle.difficulty
    return filters


class ConversationTurn(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str
    sequence: int


class ConversationBundle(BaseModel):
    snapshot_id: str | None = None
    standalone_request: str | None = None
    topic: TopicBundle | None = None
    messages: list[ConversationTurn] = Field(default_factory=list)
    conversation_summary: str | None = None
    conversation_summary_id: str | None = None
    conversation_summary_version: int | None = None
    artifact_summaries: list[str] = Field(default_factory=list)
    reference_sources: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_query: str | None = None

    def to_message_history(self):
        """把 snapshot 选中的可见消息转换为 Pydantic AI 历史。"""
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

        history = []
        for message in self.messages:
            if message.role == "user":
                history.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
            else:
                history.append(ModelResponse(parts=[TextPart(content=message.content)]))
        return history


async def load_conversation_bundle(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
) -> ConversationBundle:
    """严格复现 snapshot 选中的对话连续性、Artifact 摘要与检索焦点。"""
    from .models import (
        AgentArtifact,
        AgentConversationSummary,
        AgentMessage,
        AgentThreadItem,
    )

    run = await db.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
    )
    if run is None:
        return ConversationBundle()
    snapshot_id = (run.metadata_json or {}).get("memory_snapshot_id")
    if not snapshot_id:
        return ConversationBundle(standalone_request=run.input_message)
    snapshot = await db.scalar(
        select(AgentMemorySnapshot).where(
            AgentMemorySnapshot.id == snapshot_id,
            AgentMemorySnapshot.user_id == user_id,
            AgentMemorySnapshot.thread_id == run.thread_id,
        )
    )
    if snapshot is None:
        return ConversationBundle(standalone_request=run.input_message)

    metadata = snapshot.selection_metadata_json or {}
    conversation_summary = None
    conversation_summary_id = metadata.get("conversation_summary_id")
    conversation_summary_version = None
    if conversation_summary_id:
        summary_items = list(
            (
                await db.execute(
                    select(AgentMemorySnapshotItem)
                    .where(
                        AgentMemorySnapshotItem.snapshot_id == snapshot.id,
                        AgentMemorySnapshotItem.memory_need == "conversation_continuity",
                        AgentMemorySnapshotItem.memory_partition == "historical_summaries",
                        AgentMemorySnapshotItem.source_kind == "conversation_summary",
                        AgentMemorySnapshotItem.source_id == conversation_summary_id,
                        AgentMemorySnapshotItem.selected.is_(True),
                    )
                    .limit(2)
                )
            ).scalars()
        )
        summary_item = summary_items[0] if len(summary_items) == 1 else None
        summary_source = await db.scalar(
            select(AgentConversationSummary).where(
                AgentConversationSummary.id == conversation_summary_id,
                AgentConversationSummary.thread_id == run.thread_id,
                AgentConversationSummary.user_id == user_id,
            )
        )
        if summary_item is not None and summary_source is not None:
            payload = summary_item.payload_json or {}
            frozen_text = str(payload.get("summary_text") or "").strip()
            if frozen_text and summary_item.version == summary_source.version:
                conversation_summary = frozen_text
                conversation_summary_version = summary_item.version
    selected_message_ids = list(dict.fromkeys(metadata.get("selected_message_ids") or []))
    message_rows = []
    if selected_message_ids:
        message_rows = (
            await db.execute(
                select(AgentMessage, AgentThreadItem.sequence)
                .join(
                    AgentThreadItem,
                    (AgentThreadItem.ref_id == AgentMessage.id)
                    & (AgentThreadItem.thread_id == AgentMessage.thread_id)
                    & (AgentThreadItem.item_type == "message"),
                )
                .where(
                    AgentMessage.id.in_(selected_message_ids),
                    AgentMessage.thread_id == run.thread_id,
                    AgentMessage.user_id == user_id,
                    AgentMessage.role.in_(("user", "assistant")),
                    AgentMessage.status == "completed",
                    AgentThreadItem.visibility == "visible",
                )
                .order_by(AgentThreadItem.sequence)
            )
        ).all()
    messages = [
        ConversationTurn(
            message_id=message.id,
            role=message.role,
            content=content,
            sequence=sequence,
        )
        for message, sequence in message_rows
        if (content := str(message.content_text or "").strip())
    ]

    selected_artifact_ids = list(dict.fromkeys(metadata.get("selected_artifact_ids") or []))
    artifacts = []
    if selected_artifact_ids:
        artifacts = list(
            (
                await db.execute(
                    select(AgentArtifact)
                    .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
                    .where(
                        AgentArtifact.id.in_(selected_artifact_ids),
                        AgentRun.thread_id == run.thread_id,
                        AgentRun.user_id == user_id,
                        AgentRun.presentation != "silent",
                    )
                    .order_by(AgentArtifact.created_at, AgentArtifact.id)
                )
            ).scalars()
        )
    artifact_summaries = []
    for artifact in artifacts:
        if (artifact.metadata_json or {}).get("visibility") == "hidden":
            continue
        content = artifact.content_json or {}
        summary = str(content.get("summary") or content.get("title") or "").strip()
        if summary:
            artifact_summaries.append(summary[:500])

    understanding = snapshot.understanding_json or {}
    reference_sources = [
        dict(reference)
        for reference in understanding.get("reference_sources") or []
        if isinstance(reference, dict)
    ]
    topic = _bundle_topic_from_understanding(understanding)
    question_ids = list(
        dict.fromkeys(
            str(reference.get("id") or "").strip()
            for reference in reference_sources
            if reference.get("type") == "question" and reference.get("id")
        )
    )
    question_content = None
    if len(question_ids) == 1:
        question_content = await db.scalar(
            select(Question.content).where(
                Question.id == question_ids[0],
                Question.status == "active",
                Question.review_status != "rejected",
            )
        )
    if question_content and str(question_content).strip():
        retrieval_query = str(question_content).strip()[:500]
    elif topic is not None:
        retrieval_query = " ".join(dict.fromkeys([topic.title, *topic.aliases]))
    else:
        retrieval_query = snapshot.standalone_request or run.input_message

    return ConversationBundle(
        snapshot_id=snapshot.id,
        standalone_request=snapshot.standalone_request or run.input_message,
        topic=topic,
        messages=messages,
        conversation_summary=conversation_summary,
        conversation_summary_id=(conversation_summary_id if conversation_summary else None),
        conversation_summary_version=conversation_summary_version,
        artifact_summaries=artifact_summaries,
        reference_sources=reference_sources,
        retrieval_query=str(retrieval_query).strip() if retrieval_query else None,
    )


def _apply_explicit_question_repeat(
    excluded_question_ids: list[str],
    understanding: dict[str, Any],
) -> list[str]:
    """唯一显式题目引用可覆盖本轮排除视图；事实事件本身保持不变。"""
    if "repeat_referenced_question" not in (understanding.get("constraints") or []):
        return excluded_question_ids
    referenced_ids = {
        str(reference.get("id") or "").strip()
        for reference in understanding.get("reference_sources") or []
        if isinstance(reference, dict)
        and reference.get("type") == "question"
        and str(reference.get("id") or "").strip()
    }
    if len(referenced_ids) != 1:
        return excluded_question_ids
    return [
        question_id
        for question_id in excluded_question_ids
        if question_id not in referenced_ids
    ]
