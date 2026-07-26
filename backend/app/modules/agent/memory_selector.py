"""Load workflow-neutral memory bundles from persisted snapshots."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .memory_contracts import MemoryNeed
from .models import AgentMemorySnapshot, AgentMemorySnapshotItem, AgentRun


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

    metadata = run.metadata_json or {}
    snapshot_id = metadata.get("memory_snapshot_id")
    if not snapshot_id:
        return PracticeBundle(
            selected_artifact_ids=list(
                (metadata.get("context_snapshot") or {}).get("selected_artifact_ids") or []
            )
        )

    snapshot = await db.scalar(
        select(AgentMemorySnapshot).where(
            AgentMemorySnapshot.id == snapshot_id,
            AgentMemorySnapshot.user_id == user_id,
        )
    )
    if snapshot is None:
        return PracticeBundle(snapshot_id=str(snapshot_id))

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
    return PracticeBundle(
        snapshot_id=snapshot.id,
        standalone_request=snapshot.standalone_request,
        topic=_bundle_topic_from_understanding(understanding),
        constraints=list(understanding.get("constraints") or []),
        reference_sources=list(understanding.get("reference_sources") or []),
        selected_artifact_ids=list(context_snapshot.get("selected_artifact_ids") or []),
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
