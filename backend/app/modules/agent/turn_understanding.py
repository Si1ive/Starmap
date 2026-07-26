"""Deterministic turn understanding and memory snapshot persistence."""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .context_builder import AgentRunContext
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
    if any(hint in raw_input for hint in _PRACTICE_HINTS):
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
    return constraints


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
