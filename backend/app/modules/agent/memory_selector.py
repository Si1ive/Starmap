"""Load workflow-neutral memory bundles from persisted snapshots."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    KnowledgePoint,
    KnowledgePointChapterLink,
)

from .memory_contracts import MemoryFactType, MemoryNeed
from .models import (
    AgentMemoryEvent,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentRun,
    UserLearningMastery,
)

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
) -> tuple[TopicBundle | None, list[dict[str, Any]]]:
    """唯一高优先级薄弱点回退：恰好一个低掌握度知识点时才回退主题，多个则继续澄清。"""
    weak_rows = list(
        (
            await db.execute(
                select(UserLearningMastery)
                .where(
                    UserLearningMastery.user_id == user_id,
                    UserLearningMastery.mastery_score < _WEAK_MASTERY_THRESHOLD,
                    UserLearningMastery.evidence_count > 0,
                )
                .order_by(UserLearningMastery.mastery_score.asc())
                .limit(2)
            )
        ).scalars()
    )
    if len(weak_rows) != 1:
        return None, []
    weak = weak_rows[0]
    knowledge_point = await db.scalar(
        select(KnowledgePoint).where(KnowledgePoint.id == weak.knowledge_point_id)
    )
    if knowledge_point is None:
        return None, []
    topic = TopicBundle(
        title=knowledge_point.title,
        entity_type="knowledge_point",
        entity_id=knowledge_point.id,
        aliases=[
            str(alias).strip()
            for alias in (knowledge_point.aliases or [])
            if str(alias).strip()
        ],
        source="learning_mastery",
    )
    mastery_signals = [
        {
            "knowledge_point_id": weak.knowledge_point_id,
            "mastery_score": weak.mastery_score,
            "evidence_count": weak.evidence_count,
            "last_evidence_id": weak.last_evidence_id,
        }
    ]
    return topic, mastery_signals


async def load_practice_bundle(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
) -> PracticeBundle:
    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
        )
    )
    if run is None:
        return PracticeBundle()

    excluded_question_ids = await _load_excluded_question_ids(db, user_id=user_id)
    metadata = run.metadata_json or {}
    snapshot_id = metadata.get("memory_snapshot_id")
    if not snapshot_id:
        topic, mastery_signals = await _load_unique_weak_topic(db, user_id=user_id)
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
        )
    )
    if snapshot is None:
        topic, mastery_signals = await _load_unique_weak_topic(db, user_id=user_id)
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
        topic, mastery_signals = await _load_unique_weak_topic(db, user_id=user_id)
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
        excluded_question_ids=excluded_question_ids,
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
