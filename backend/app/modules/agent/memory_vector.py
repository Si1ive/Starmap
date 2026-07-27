"""Agent 长期记忆的 Embedding、Qdrant 生命周期与可复现召回。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.qdrant import QdrantManager, qdrant_manager
from app.infrastructure.ai.embedding_service import (
    EmbeddingService,
    get_embedding_service_from_settings,
)

from .memory_contracts import MemoryNeed
from .models import (
    AgentConversationSummary,
    AgentMemoryItem,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMemoryUpdateOutbox,
    AgentRun,
)

logger = get_logger(__name__)

MEMORY_VECTOR_COLLECTION = "agent_memory"
MEMORY_ITEM_VECTOR_TASK = "memory_item_vector_upsert"
SUMMARY_VECTOR_TASK = "conversation_summary_vector_upsert"
_VECTOR_NAMESPACE = uuid.UUID("a64f6276-0fd9-4ed8-8d66-772685c2248b")
_PAYLOAD_INDEXES = {
    "user_id": PayloadSchemaType.KEYWORD,
    "thread_id": PayloadSchemaType.KEYWORD,
    "scope": PayloadSchemaType.KEYWORD,
    "memory_partition": PayloadSchemaType.KEYWORD,
    "source_kind": PayloadSchemaType.KEYWORD,
    "source_id": PayloadSchemaType.KEYWORD,
    "source_version": PayloadSchemaType.INTEGER,
    "status": PayloadSchemaType.KEYWORD,
}


def memory_item_vector_task_type(source_version: int) -> str:
    return f"{MEMORY_ITEM_VECTOR_TASK}:{source_version}"


def summary_vector_task_type(source_version: int) -> str:
    return f"{SUMMARY_VECTOR_TASK}:{source_version}"


def is_memory_vector_task(event_type: str) -> bool:
    return event_type.startswith(
        (f"{MEMORY_ITEM_VECTOR_TASK}:", f"{SUMMARY_VECTOR_TASK}:")
    )


@dataclass(frozen=True, slots=True)
class MemoryVectorHit:
    point_id: str
    score: float
    source_kind: str
    source_id: str
    source_version: int
    user_id: str
    thread_id: str | None
    scope: str
    memory_partition: str
    content_text: str


def memory_vector_point_id(
    source_kind: str, source_id: str, source_version: int
) -> str:
    return str(
        uuid.uuid5(
            _VECTOR_NAMESPACE,
            f"{source_kind}:{source_id}:{source_version}",
        )
    )


async def enqueue_memory_vector_task(
    db: AsyncSession,
    *,
    run: AgentRun,
    event_type: str,
    source_kind: str,
    source_id: str,
    source_version: int,
    delete_sources: list[dict[str, Any]] | None = None,
) -> None:
    """按 Run + task type 幂等追加向量任务；payload 只保存来源标识。"""
    existing = await db.scalar(
        select(AgentMemoryUpdateOutbox).where(
            AgentMemoryUpdateOutbox.run_id == run.id,
            AgentMemoryUpdateOutbox.event_type == event_type,
        )
    )
    payload = {
        "task_type": event_type,
        "source_kind": source_kind,
        "source_id": source_id,
        "source_version": source_version,
        "delete_sources": delete_sources or [],
    }
    if existing is not None:
        if existing.payload_json != payload:
            raise ValueError("同一 Run 的向量任务来源版本不一致")
        return
    try:
        async with db.begin_nested():
            db.add(
                AgentMemoryUpdateOutbox(
                    run_id=run.id,
                    thread_id=run.thread_id,
                    user_id=run.user_id,
                    event_type=event_type,
                    status="pending",
                    payload_json=payload,
                )
            )
            await db.flush()
    except IntegrityError:
        logger.info("记忆向量任务并发幂等命中", run_id=run.id, event_type=event_type)


class MemoryVectorLifecycle:
    def __init__(
        self,
        *,
        qdrant: QdrantManager = qdrant_manager,
        embedding_factory=get_embedding_service_from_settings,
    ) -> None:
        self.qdrant = qdrant
        self.embedding_factory = embedding_factory

    def _ensure_collection(self, embedding: EmbeddingService) -> None:
        self.qdrant.ensure_collection(
            MEMORY_VECTOR_COLLECTION,
            vector_size=embedding.dimension,
            distance=Distance.COSINE,
        )
        for field, schema in _PAYLOAD_INDEXES.items():
            try:
                self.qdrant.client.create_payload_index(
                    collection_name=MEMORY_VECTOR_COLLECTION,
                    field_name=field,
                    field_schema=schema,
                )
            except Exception as error:
                logger.debug(
                    "Agent 记忆 payload 索引创建跳过", field=field, error=str(error)
                )

    def _delete_sources(self, sources: list[dict[str, Any]]) -> None:
        point_ids = [
            memory_vector_point_id(
                str(source.get("source_kind") or ""),
                str(source.get("source_id") or ""),
                int(source.get("source_version") or 0),
            )
            for source in sources
            if source.get("source_kind")
            and source.get("source_id")
            and int(source.get("source_version") or 0) > 0
        ]
        if not point_ids:
            return
        collections = self.qdrant.client.get_collections()
        if MEMORY_VECTOR_COLLECTION not in {
            collection.name for collection in collections.collections
        }:
            return
        self.qdrant.client.delete(
            collection_name=MEMORY_VECTOR_COLLECTION,
            points_selector=PointIdsList(points=point_ids),
        )

    def delete_sources(self, sources: list[dict[str, Any]]) -> None:
        """供治理任务复用的幂等删除入口；连接/删除错误继续向 Outbox 传播。"""
        self._delete_sources(sources)

    async def process_outbox(
        self,
        db: AsyncSession,
        outbox: AgentMemoryUpdateOutbox,
    ) -> None:
        payload = outbox.payload_json or {}
        if payload.get("task_type") != outbox.event_type:
            raise ValueError("向量 Outbox task type 不匹配")
        source_kind = str(payload.get("source_kind") or "")
        source_id = str(payload.get("source_id") or "")
        source_version = int(payload.get("source_version") or 0)
        source = await self._load_source(
            db,
            outbox=outbox,
            source_kind=source_kind,
            source_id=source_id,
            source_version=source_version,
        )
        if source is None:
            self._delete_sources(
                [
                    {
                        "source_kind": source_kind,
                        "source_id": source_id,
                        "source_version": source_version,
                    },
                    *(payload.get("delete_sources") or []),
                ]
            )
            return

        embedding = await self.embedding_factory(db)
        vector = await embedding.embed_text(source.content_text)
        if len(vector) != embedding.dimension:
            raise ValueError("记忆向量维度与 Embedding 配置不一致")
        self._ensure_collection(embedding)
        self.qdrant.upsert_points(
            MEMORY_VECTOR_COLLECTION,
            [
                PointStruct(
                    id=source.point_id,
                    vector=vector,
                    payload={
                        "user_id": source.user_id,
                        "thread_id": source.thread_id,
                        "scope": source.scope,
                        "memory_partition": source.memory_partition,
                        "source_kind": source.source_kind,
                        "source_id": source.source_id,
                        "source_version": source.source_version,
                        "status": "active",
                    },
                )
            ],
        )
        self._delete_sources(payload.get("delete_sources") or [])

    async def recall(
        self,
        db: AsyncSession,
        *,
        query: str,
        user_id: str,
        thread_id: str | None,
        memory_partitions: list[str],
        limit: int = 5,
    ) -> list[MemoryVectorHit]:
        normalized_query = query.strip()
        if not normalized_query or not memory_partitions:
            return []
        embedding = await self.embedding_factory(db)
        query_vector = await embedding.embed_text(normalized_query)
        self._ensure_collection(embedding)
        must = [
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
            FieldCondition(key="status", match=MatchValue(value="active")),
            FieldCondition(
                key="memory_partition",
                match=MatchAny(any=memory_partitions),
            ),
        ]
        should = []
        if thread_id:
            should = [
                FieldCondition(key="scope", match=MatchValue(value="user")),
                FieldCondition(key="thread_id", match=MatchValue(value=thread_id)),
            ]
        else:
            must.append(FieldCondition(key="scope", match=MatchValue(value="user")))
        raw_hits = self.qdrant.search(
            MEMORY_VECTOR_COLLECTION,
            query_vector,
            limit=limit,
            query_filter=Filter(must=must, should=should or None),
        )
        hits: list[MemoryVectorHit] = []
        for raw_hit in raw_hits:
            hit = await self._hydrate_hit(
                db,
                raw_hit=raw_hit,
                user_id=user_id,
                thread_id=thread_id,
                allowed_partitions=set(memory_partitions),
            )
            if hit is not None:
                hits.append(hit)
        return hits

    async def recall_for_snapshot(
        self,
        db: AsyncSession,
        *,
        snapshot_id: str,
        memory_need: MemoryNeed,
        query: str,
        user_id: str,
        thread_id: str,
        memory_partitions: list[str],
        limit: int = 5,
    ) -> list[MemoryVectorHit]:
        snapshot = await db.scalar(
            select(AgentMemorySnapshot).where(
                AgentMemorySnapshot.id == snapshot_id,
                AgentMemorySnapshot.user_id == user_id,
                AgentMemorySnapshot.thread_id == thread_id,
            )
        )
        if snapshot is None:
            return []
        frozen = await self._load_frozen_hits(db, snapshot_id, memory_need)
        if frozen:
            return frozen
        recalled = await self.recall(
            db,
            query=query,
            user_id=user_id,
            thread_id=thread_id,
            memory_partitions=memory_partitions,
            limit=limit,
        )
        if not recalled:
            return []
        await db.scalar(
            select(AgentMemorySnapshot.id)
            .where(AgentMemorySnapshot.id == snapshot.id)
            .with_for_update()
        )
        frozen = await self._load_frozen_hits(db, snapshot_id, memory_need)
        if frozen:
            return frozen
        for hit in recalled:
            db.add(
                AgentMemorySnapshotItem(
                    snapshot_id=snapshot.id,
                    memory_need=memory_need.value,
                    memory_partition=hit.memory_partition,
                    source_kind=hit.source_kind,
                    source_id=hit.source_id,
                    item_key=(
                        f"vector:{hit.source_kind}:{hit.source_id}:"
                        f"{hit.source_version}"
                    ),
                    version=hit.source_version,
                    selected=True,
                    selection_reason="semantic_vector_recall",
                    token_estimate=max(1, (len(hit.content_text) + 3) // 4),
                    payload_json={
                        "point_id": hit.point_id,
                        "score": hit.score,
                        "source_kind": hit.source_kind,
                        "source_id": hit.source_id,
                        "source_version": hit.source_version,
                        "user_id": hit.user_id,
                        "thread_id": hit.thread_id,
                        "scope": hit.scope,
                        "memory_partition": hit.memory_partition,
                        "content_text": hit.content_text,
                    },
                )
            )
        await db.flush()
        return recalled

    async def _load_source(
        self,
        db: AsyncSession,
        *,
        outbox: AgentMemoryUpdateOutbox,
        source_kind: str,
        source_id: str,
        source_version: int,
    ) -> MemoryVectorHit | None:
        if source_kind == "conversation_summary":
            summary = await db.scalar(
                select(AgentConversationSummary).where(
                    AgentConversationSummary.id == source_id,
                    AgentConversationSummary.user_id == outbox.user_id,
                    AgentConversationSummary.thread_id == outbox.thread_id,
                    AgentConversationSummary.version == source_version,
                )
            )
            if summary is None or summary.superseded_by_id is not None:
                return None
            return MemoryVectorHit(
                point_id=memory_vector_point_id(source_kind, source_id, source_version),
                score=1.0,
                source_kind=source_kind,
                source_id=source_id,
                source_version=source_version,
                user_id=summary.user_id,
                thread_id=summary.thread_id,
                scope="thread",
                memory_partition="topic_summary",
                content_text=summary.summary_text,
            )
        if source_kind == "memory_item":
            item = await db.scalar(
                select(AgentMemoryItem).where(
                    AgentMemoryItem.id == source_id,
                    AgentMemoryItem.user_id == outbox.user_id,
                    AgentMemoryItem.last_confirmed_run_id == outbox.run_id,
                    AgentMemoryItem.status == "active",
                )
            )
            current_version = (
                int((item.metadata_json or {}).get("source_memory_event_id") or 0)
                if item
                else 0
            )
            if item is None or current_version != source_version:
                return None
            partition = (
                "user_goal"
                if item.item_type == "learning_goal"
                else "thread_topic_state"
            )
            return MemoryVectorHit(
                point_id=memory_vector_point_id(source_kind, source_id, source_version),
                score=1.0,
                source_kind=source_kind,
                source_id=source_id,
                source_version=source_version,
                user_id=item.user_id,
                thread_id=item.thread_id,
                scope=item.scope,
                memory_partition=partition,
                content_text=item.content_text,
            )
        raise ValueError("不支持的记忆向量 source kind")

    async def _hydrate_hit(
        self,
        db: AsyncSession,
        *,
        raw_hit: dict[str, Any],
        user_id: str,
        thread_id: str | None,
        allowed_partitions: set[str],
    ) -> MemoryVectorHit | None:
        payload = raw_hit.get("payload") or {}
        if payload.get("user_id") != user_id or payload.get("status") != "active":
            return None
        scope = str(payload.get("scope") or "")
        payload_thread_id = payload.get("thread_id")
        if scope == "thread" and (not thread_id or payload_thread_id != thread_id):
            return None
        if scope not in {"user", "thread"}:
            return None
        partition = str(payload.get("memory_partition") or "")
        if partition not in allowed_partitions:
            return None
        source_kind = str(payload.get("source_kind") or "")
        source_id = str(payload.get("source_id") or "")
        source_version = int(payload.get("source_version") or 0)
        if source_kind == "memory_item":
            item = await db.scalar(
                select(AgentMemoryItem).where(
                    AgentMemoryItem.id == source_id,
                    AgentMemoryItem.user_id == user_id,
                    AgentMemoryItem.status == "active",
                )
            )
            if item is None:
                return None
            current_version = int(
                (item.metadata_json or {}).get("source_memory_event_id") or 0
            )
            if current_version != source_version:
                return None
            if item.scope == "thread" and item.thread_id != thread_id:
                return None
            return MemoryVectorHit(
                point_id=str(raw_hit.get("id")),
                score=float(raw_hit.get("score") or 0),
                source_kind=source_kind,
                source_id=source_id,
                source_version=source_version,
                user_id=item.user_id,
                thread_id=item.thread_id,
                scope=item.scope,
                memory_partition=partition,
                content_text=item.content_text,
            )
        if source_kind == "conversation_summary":
            summary = await db.scalar(
                select(AgentConversationSummary).where(
                    AgentConversationSummary.id == source_id,
                    AgentConversationSummary.user_id == user_id,
                    AgentConversationSummary.version == source_version,
                    AgentConversationSummary.superseded_by_id.is_(None),
                )
            )
            if summary is None or summary.thread_id != thread_id:
                return None
            return MemoryVectorHit(
                point_id=str(raw_hit.get("id")),
                score=float(raw_hit.get("score") or 0),
                source_kind=source_kind,
                source_id=source_id,
                source_version=source_version,
                user_id=summary.user_id,
                thread_id=summary.thread_id,
                scope="thread",
                memory_partition=partition,
                content_text=summary.summary_text,
            )
        return None

    async def _load_frozen_hits(
        self,
        db: AsyncSession,
        snapshot_id: str,
        memory_need: MemoryNeed,
    ) -> list[MemoryVectorHit]:
        items = list(
            (
                await db.execute(
                    select(AgentMemorySnapshotItem)
                    .where(
                        AgentMemorySnapshotItem.snapshot_id == snapshot_id,
                        AgentMemorySnapshotItem.memory_need == memory_need.value,
                        AgentMemorySnapshotItem.selection_reason
                        == "semantic_vector_recall",
                        AgentMemorySnapshotItem.selected.is_(True),
                    )
                    .order_by(AgentMemorySnapshotItem.id)
                )
            ).scalars()
        )
        hits = []
        for item in items:
            payload = item.payload_json or {}
            content_text = str(payload.get("content_text") or "").strip()
            if not content_text:
                continue
            hits.append(
                MemoryVectorHit(
                    point_id=str(payload.get("point_id") or ""),
                    score=float(payload.get("score") or 0),
                    source_kind=str(payload.get("source_kind") or item.source_kind),
                    source_id=str(payload.get("source_id") or item.source_id),
                    source_version=int(
                        payload.get("source_version") or item.version or 0
                    ),
                    user_id=str(payload.get("user_id") or ""),
                    thread_id=payload.get("thread_id"),
                    scope=str(payload.get("scope") or ""),
                    memory_partition=str(
                        payload.get("memory_partition") or item.memory_partition
                    ),
                    content_text=content_text,
                )
            )
        return hits


memory_vector_lifecycle = MemoryVectorLifecycle()
