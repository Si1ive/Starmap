"""标准章节的相似召回、已审核关系扩展和交叉引用校验。"""

from typing import Dict, List, Tuple

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.qdrant import qdrant_manager
from app.infrastructure.ai.embedding_service import (
    get_embedding_service_from_settings,
)
from app.models.mysql_models import CanonicalChapter, ChapterRelation
from app.modules.retrieval.chapter_scope_retrieval import expand_chapter_scope

logger = get_logger(__name__)


async def fallback_chapter_similarity(
    db: AsyncSession,
    chapter_id: str,
    top_k: int = 5,
) -> List[Tuple[str, float]]:
    """通过章节 Segment 向量召回跨章相似候选。"""
    chapter = await db.get(CanonicalChapter, chapter_id)
    if not chapter:
        return []

    embedding = await get_embedding_service_from_settings(db)
    query_text = f"{chapter.name} {chapter.enhanced_description or ''}"
    query_vector = await embedding.embed_text(query_text)
    results = qdrant_manager.search(
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="entity_type",
                    match=MatchValue(value="canonical_chapter"),
                )
            ]
        ),
        limit=top_k + 1,
    )

    pairs: List[Tuple[str, float]] = []
    for hit in results:
        payload = hit.get("payload") or {}
        related_chapter_id = payload.get("entity_id")
        score = hit.get("score", 0)
        if not related_chapter_id or related_chapter_id == chapter_id:
            continue
        if score < 0.75:
            continue
        pairs.append((related_chapter_id, score))
    return pairs[:top_k]


async def expand_related_chapters(
    db: AsyncSession,
    chapter_ids: List[str],
    max_results: int = 10,
) -> Dict[str, Dict[str, list]]:
    """
    分别返回章节树范围扩展和已审核语义关系，不混合两类结果。
    """
    result: Dict[str, Dict[str, list]] = {}
    for chapter_id in dict.fromkeys(chapter_ids):
        scope_ids = await expand_chapter_scope(
            db,
            [chapter_id],
            upward_levels=0,
        )
        relations = (
            await db.execute(
                select(ChapterRelation)
                .where(
                    ChapterRelation.source_chapter_id == chapter_id,
                    ChapterRelation.review_status == "approved",
                )
                .order_by(ChapterRelation.confidence.desc())
                .limit(max_results)
            )
        ).scalars().all()

        result[chapter_id] = {
            "scope_expansion": [
                {
                    "chapter_id": related_id,
                    "relation": "sibling_or_ancestor",
                }
                for related_id in scope_ids
                if related_id != chapter_id
            ],
            "semantic_relations": [
                {
                    "chapter_id": relation.target_chapter_id,
                    "source_type": relation.source_type,
                    "relation_type": relation.relation_type,
                    "confidence": float(relation.confidence or 0),
                    "evidence_text": relation.evidence_text,
                }
                for relation in relations
            ],
        }

    return result


async def validate_cross_references(
    db: AsyncSession,
    cross_refs: List[dict],
) -> List[dict]:
    """只保留指向现有启用章节的 LLM 交叉引用。"""
    if not cross_refs:
        return []

    target_ids = [
        target_id
        for ref in cross_refs
        if (target_id := ref.get("target_chapter_id"))
    ]
    existing_ids = (
        await db.execute(
            select(CanonicalChapter.id).where(
                CanonicalChapter.id.in_(target_ids),
                CanonicalChapter.status == "active",
            )
        )
    ).scalars().all()
    existing_set = set(existing_ids)
    valid = [
        ref
        for ref in cross_refs
        if ref.get("target_chapter_id") in existing_set
    ]

    if len(valid) < len(cross_refs):
        invalid_ids = [
            ref.get("target_chapter_id")
            for ref in cross_refs
            if ref.get("target_chapter_id") not in existing_set
        ]
        logger.warning(
            "cross_references 包含无效 chapter_id，已过滤",
            total=len(cross_refs),
            valid=len(valid),
            invalid_ids=invalid_ids,
        )
    return valid
