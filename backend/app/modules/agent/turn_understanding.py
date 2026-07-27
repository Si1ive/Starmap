"""Deterministic turn understanding and memory snapshot persistence."""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import Question

from .context_builder import AgentRunContext
from .model_runtime.referent import ReferentCandidate, ReferentResolution
from .memory_projection import project_topic_confirmed_fact
from .models import (
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentRun,
    AgentThreadMemoryState,
)

_PRACTICE_HINTS = ("出道题", "出一道题", "出一道", "来道题", "练习", "题目")
_EXPLAIN_HINTS = ("讲一下", "讲解", "解释", "说明")
_EASY_HINTS = ("简单点", "简单一点", "容易点", "基础点", "基础一些")
_MEDIUM_HINTS = ("难度适中", "适中", "中等")
_HARD_HINTS = ("难一点", "难一些", "难点", "提高点", "提升点")
_QUESTION_REFERENT_HINTS = (
    "上一道",
    "上道题",
    "刚才那道",
    "上次那题",
    "这道题",
    "这个题",
    "这题",
)
_BARE_REFERENT_HINTS = ("这个", "那个")
_CHAPTER_ORDINAL_PATTERN = re.compile(
    r"第\s*([0-9]{1,2}|[一二三四五六七八九十两]{1,3})\s*章"
)
_CHINESE_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


class TopicEntity(BaseModel):
    entity_type: str
    entity_id: str | None = None
    title: str
    source: str
    aliases: list[str] = Field(default_factory=list)


class TurnUnderstanding(BaseModel):
    raw_input: str
    standalone_request: str
    intent_hint: str | None = None
    topic_entities: list[TopicEntity] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    reference_sources: list[dict[str, Any]] = Field(default_factory=list)
    reference_resolution: dict[str, Any] | None = None


def _topic_from_context_ref(ref: dict[str, Any]) -> TopicEntity | None:
    ref_type = str(ref.get("type") or "").strip()
    if ref_type not in {"knowledge_point", "question", "topic"}:
        return None
    title = str(ref.get("title") or ref.get("name") or ref.get("label") or "").strip()
    if not title:
        return None
    return TopicEntity(
        entity_type=ref_type,
        entity_id=str(ref.get("id")) if ref.get("id") else None,
        title=title,
        source="context_ref",
        aliases=[
            str(alias).strip()
            for alias in (ref.get("aliases") or [])
            if str(alias).strip()
        ],
    )


def _topic_from_memory(active_topic: dict[str, Any] | None) -> TopicEntity | None:
    if not active_topic:
        return None
    title = str(active_topic.get("title") or "").strip()
    entity_type = str(active_topic.get("entity_type") or active_topic.get("type") or "").strip()
    if not title or not entity_type:
        return None
    entity_id = active_topic.get("entity_id") or active_topic.get("id")
    return TopicEntity(
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        title=title,
        source="thread_memory",
        aliases=[
            str(alias).strip()
            for alias in (active_topic.get("aliases") or [])
            if str(alias).strip()
        ],
    )


def _derive_standalone_request(raw_input: str, topic: TopicEntity | None) -> tuple[str, str | None]:
    if topic is None:
        return raw_input, None
    if any(hint in raw_input for hint in _PRACTICE_HINTS) or requests_question_repeat(raw_input):
        return f"给用户出一道关于{topic.title}的练习题", "practice_generation"
    if any(hint in raw_input for hint in _EXPLAIN_HINTS):
        return f"给用户讲解{topic.title}", "topic_explanation"
    return raw_input, None


def _parse_chapter_ordinal(value: str) -> int | None:
    if value.isdigit():
        ordinal = int(value)
    elif "十" in value:
        tens_text, ones_text = value.split("十", 1)
        tens = _CHINESE_DIGITS.get(tens_text, 1) if tens_text else 1
        ones = _CHINESE_DIGITS.get(ones_text, 0) if ones_text else 0
        ordinal = tens * 10 + ones
    else:
        ordinal = _CHINESE_DIGITS.get(value, 0)
    return ordinal if 1 <= ordinal <= 99 else None


def _derive_constraints(raw_input: str) -> list[str]:
    constraints: list[str] = []
    if any(hint in raw_input for hint in _MEDIUM_HINTS):
        constraints.append("difficulty:medium")
    elif any(hint in raw_input for hint in _HARD_HINTS):
        constraints.append("difficulty:hard")
    elif any(hint in raw_input for hint in _EASY_HINTS):
        constraints.append("difficulty:easy")
    chapter_match = _CHAPTER_ORDINAL_PATTERN.search(raw_input)
    if chapter_match:
        ordinal = _parse_chapter_ordinal(chapter_match.group(1))
        if ordinal is not None:
            constraints.append(f"chapter_ordinal:{ordinal}")
    return [*constraints, *(["repeat_referenced_question"] if requests_question_repeat(raw_input) else [])]


def _resolve_question_artifact_reference(
    agent_context: AgentRunContext,
    raw_input: str,
) -> dict[str, Any] | None:
    """从最新练习产物确定性解析题目指代；歧义时不猜测也不回退。"""
    if not any(hint in raw_input for hint in _QUESTION_REFERENT_HINTS) and not requests_question_repeat(raw_input):
        return None
    if any(
        ref.get("type") == "question" and ref.get("id")
        for ref in agent_context.context_refs
    ):
        return None

    for artifact in reversed(agent_context.recent_artifacts):
        if artifact.artifact_type != "practice":
            continue
        question_references = [
            reference
            for reference in artifact.reference_entities
            if reference.get("type") == "question"
            and isinstance(reference.get("id"), str)
            and reference["id"].strip()
        ]
        unique_references = {
            reference["id"].strip(): reference for reference in question_references
        }
        if len(unique_references) != 1:
            return None
        return next(iter(unique_references.values())).copy()
    return None


def build_ambiguous_referent_candidates(
    agent_context: AgentRunContext,
    understanding: TurnUnderstanding,
) -> list[ReferentCandidate]:
    """只为确定性阶段未解决的指代构造服务端候选白名单。"""
    raw_input = understanding.raw_input
    has_question_hint = any(
        hint in raw_input for hint in _QUESTION_REFERENT_HINTS
    )
    has_resolved_question = any(
        reference.get("type") == "question" and reference.get("id")
        for reference in understanding.reference_sources
    )
    has_bare_hint = any(hint in raw_input for hint in _BARE_REFERENT_HINTS)
    if has_question_hint and has_resolved_question:
        return []
    if has_bare_hint and any(
        reference.get("id") for reference in agent_context.context_refs
    ):
        return []
    if not has_question_hint and not has_bare_hint:
        return []

    latest_artifact = next(
        (
            artifact
            for artifact in reversed(agent_context.recent_artifacts)
            if artifact.artifact_type == "practice"
        ),
        None,
    )
    candidates = []
    if latest_artifact is not None:
        candidates = [
            ReferentCandidate(
                candidate_key=f"question:{reference['id'].strip()}",
                entity_type="question",
                entity_id=reference["id"].strip(),
                source="artifact",
                artifact_id=latest_artifact.id,
            )
            for reference in latest_artifact.reference_entities
            if reference.get("type") == "question"
            and isinstance(reference.get("id"), str)
            and reference["id"].strip()
        ]
    if has_question_hint:
        return candidates if len(candidates) > 1 else []

    if latest_artifact is not None:
        candidates.append(
            ReferentCandidate(
                candidate_key=f"artifact:{latest_artifact.id}",
                entity_type="artifact",
                entity_id=latest_artifact.id,
                source="artifact",
                artifact_id=latest_artifact.id,
                label=latest_artifact.summary,
            )
        )
    if agent_context.active_topic:
        entity_id = agent_context.active_topic.get(
            "entity_id"
        ) or agent_context.active_topic.get("id")
        entity_type = agent_context.active_topic.get(
            "entity_type"
        ) or agent_context.active_topic.get("type")
        if entity_id and entity_type:
            candidates.append(
                ReferentCandidate(
                    candidate_key=f"{entity_type}:{entity_id}",
                    entity_type=str(entity_type),
                    entity_id=str(entity_id),
                    source="thread_memory",
                    label=agent_context.active_topic.get("title"),
                )
            )
    return candidates


async def hydrate_referent_candidate_labels(
    db: AsyncSession,
    candidates: list[ReferentCandidate],
) -> list[ReferentCandidate]:
    """用 active 题面水合 question 候选，并丢弃失效或缺失实体。"""
    question_ids = [
        candidate.entity_id
        for candidate in candidates
        if candidate.entity_type == "question"
    ]
    question_content: dict[str, str] = {}
    if question_ids:
        rows = (
            await db.execute(
                select(Question.id, Question.content).where(
                    Question.id.in_(question_ids),
                    Question.status == "active",
                )
            )
        ).all()
        question_content = {
            question_id: content.strip()[:500]
            for question_id, content in rows
            if isinstance(content, str) and content.strip()
        }

    hydrated: list[ReferentCandidate] = []
    for candidate in candidates:
        if candidate.entity_type != "question":
            hydrated.append(candidate)
            continue
        label = question_content.get(candidate.entity_id)
        if label:
            hydrated.append(candidate.model_copy(update={"label": label}))
    return hydrated


def apply_referent_resolution(
    understanding: TurnUnderstanding,
    *,
    candidates: list[ReferentCandidate],
    resolution: ReferentResolution,
) -> TurnUnderstanding:
    """把通过运行时白名单校验的模型选择转换为快照引用。"""
    resolution_audit = {
        "status": resolution.status,
        "candidate_key": resolution.candidate_key,
        "confidence": resolution.confidence,
        "reason_code": resolution.reason_code,
        "candidate_keys": [candidate.candidate_key for candidate in candidates],
    }
    if resolution.status != "resolved" or not resolution.candidate_key:
        return understanding.model_copy(
            update={"reference_resolution": resolution_audit}
        )
    candidate = next(
        (
            item
            for item in candidates
            if item.candidate_key == resolution.candidate_key
        ),
        None,
    )
    if candidate is None:
        raise ValueError("指代消解结果不属于当前候选")
    reference = candidate.to_reference_source()
    reference.update(
        {
            "resolution_source": "model",
            "resolution_reason_code": resolution.reason_code,
        }
    )
    return understanding.model_copy(
        update={
            "reference_sources": [*understanding.reference_sources, reference],
            "reference_resolution": resolution_audit,
        }
    )


def build_turn_understanding(agent_context: AgentRunContext) -> TurnUnderstanding:
    raw_input = agent_context.current_input.strip()
    topic_entities = [
        topic
        for topic in (
            *(_topic_from_context_ref(ref) for ref in agent_context.context_refs),
            _topic_from_memory(agent_context.active_topic),
        )
        if topic is not None
    ]
    deduped_topics: list[TopicEntity] = []
    seen_topics: set[tuple[str, str | None, str]] = set()
    for topic in topic_entities:
        key = (topic.entity_type, topic.entity_id, topic.title)
        if key in seen_topics:
            continue
        seen_topics.add(key)
        deduped_topics.append(topic)
    standalone_request, intent_hint = _derive_standalone_request(
        raw_input,
        deduped_topics[0] if deduped_topics else None,
    )
    constraints = _derive_constraints(raw_input)
    reference_sources = [
        {
            "type": str(ref.get("type") or ""),
            "id": ref.get("id"),
            "title": ref.get("title") or ref.get("name") or ref.get("label"),
        }
        for ref in agent_context.context_refs
    ]
    if agent_context.active_topic:
        reference_sources.append(
            {
                "type": str(
                    agent_context.active_topic.get("entity_type")
                    or agent_context.active_topic.get("type")
                    or "topic"
                ),
                "id": agent_context.active_topic.get("entity_id")
                or agent_context.active_topic.get("id"),
                "title": agent_context.active_topic.get("title"),
                "source": "thread_memory",
            }
        )
    artifact_reference = _resolve_question_artifact_reference(agent_context, raw_input)
    if artifact_reference is not None:
        reference_sources.append(artifact_reference)
    return TurnUnderstanding(
        raw_input=raw_input,
        standalone_request=standalone_request,
        intent_hint=intent_hint,
        topic_entities=deduped_topics,
        constraints=constraints,
        reference_sources=reference_sources,
    )


async def ensure_turn_memory_snapshot(
    db: AsyncSession,
    *,
    run: AgentRun,
    agent_context: AgentRunContext,
    understanding: TurnUnderstanding,
) -> AgentMemorySnapshot:
    existing = await db.scalar(
        select(AgentMemorySnapshot).where(AgentMemorySnapshot.run_id == run.id)
    )
    if existing is not None:
        if understanding.topic_entities:
            await project_topic_confirmed_fact(
                db,
                run,
                snapshot_id=existing.id,
                state_version=existing.state_version,
                source_message_id=agent_context.current_message_id,
                topic=understanding.topic_entities[0].model_dump(mode="json"),
            )
        return existing

    state = await db.scalar(
        select(AgentThreadMemoryState).where(
            AgentThreadMemoryState.thread_id == run.thread_id,
            AgentThreadMemoryState.user_id == run.user_id,
        )
    )
    if state is None:
        state = AgentThreadMemoryState(
            thread_id=run.thread_id,
            user_id=run.user_id,
            version=1,
        )
        db.add(state)
    else:
        state.version += 1
    if understanding.topic_entities:
        state.active_topic_json = understanding.topic_entities[0].model_dump(mode="json")
    state.latest_understanding_run_id = run.id
    await db.flush()

    snapshot = AgentMemorySnapshot(
        id=f"memsnap_{uuid.uuid4().hex[:20]}",
        run_id=run.id,
        thread_id=run.thread_id,
        user_id=run.user_id,
        state_version=state.version,
        standalone_request=understanding.standalone_request,
        understanding_json=understanding.model_dump(mode="json"),
        selection_metadata_json={
            "selected_message_ids": agent_context.selected_message_ids,
            "selected_artifact_ids": agent_context.selected_artifact_ids,
            "conversation_summary_id": (
                (agent_context.conversation_summary_source or {}).get("id")
            ),
            "pending_interaction_ids": [
                item.id for item in agent_context.pending_interactions
            ],
        },
    )
    db.add(snapshot)
    await db.flush()

    snapshot_item = AgentMemorySnapshotItem(
        snapshot_id=snapshot.id,
        memory_need="topic_focus",
        memory_partition="current_turn_understanding",
        source_kind="message",
        source_id=agent_context.current_message_id,
        item_key=agent_context.current_message_id,
        version=state.version,
        selected=True,
        selection_reason="current_turn_understanding",
        token_estimate=max(1, (len(understanding.standalone_request) + 3) // 4),
        payload_json=understanding.model_dump(mode="json"),
    )
    db.add(snapshot_item)
    summary_source = agent_context.conversation_summary_source or {}
    if agent_context.conversation_summary and summary_source.get("id"):
        db.add(
            AgentMemorySnapshotItem(
                snapshot_id=snapshot.id,
                memory_need="conversation_continuity",
                memory_partition="historical_summaries",
                source_kind="conversation_summary",
                source_id=summary_source["id"],
                item_key=summary_source["id"],
                version=summary_source.get("version"),
                selected=True,
                selection_reason="active_summary_before_recent_history",
                token_estimate=int(summary_source.get("token_estimate") or 0),
                payload_json={
                    "summary_text": agent_context.conversation_summary,
                    "start_sequence": summary_source.get("start_sequence"),
                    "end_sequence": summary_source.get("end_sequence"),
                    "source_message_ids": summary_source.get("source_message_ids") or [],
                },
            )
        )
    await db.flush()
    if understanding.topic_entities:
        await project_topic_confirmed_fact(
            db,
            run,
            snapshot_id=snapshot.id,
            state_version=snapshot.state_version,
            source_message_id=agent_context.current_message_id,
            topic=understanding.topic_entities[0].model_dump(mode="json"),
        )
    return snapshot


def requests_question_repeat(raw_input: str) -> bool:
    """识别明确重出已有题目的当前轮意图，并排除常见否定表达。"""
    normalized = "".join(raw_input.split())
    repeat_hints = ("再出", "重新出", "重复出", "再来", "再做", "重做")
    reference_hints = (
        *_QUESTION_REFERENT_HINTS,
        "上次那道题",
        "刚才那题",
        "刚才那道题",
    )
    if any(
        prefix + repeat_hint in normalized
        for prefix in ("不要", "别", "不想", "无需")
        for repeat_hint in repeat_hints
    ):
        return False
    return any(hint in normalized for hint in repeat_hints) and any(
        hint in normalized for hint in reference_hints
    )
