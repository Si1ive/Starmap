"""
大纲辅助检索服务

实现设计文档 outline-retrieval-cross-chapter-association-design.md 中定义的核心函数：

Phase 2: fallback_chapter_similarity()  - embedding 兜底（离线构建器用）
Phase 2: expand_related_chapters()      - 在线读取器：scope 在线算 + semantic 读 ChapterRelation 已审核行

Phase 0 查询扩展已迁移到 outline_query_expansion.py。
章节范围召回已迁移到 chapter_scope_retrieval.py。
"""

from typing import Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from qdrant_client.models import Filter, FieldCondition, MatchValue

from app.core.logging import get_logger
from app.db.qdrant import qdrant_manager
from app.models.mysql_models import (
    CanonicalChapter,
    ChapterRelation,
)
from app.infrastructure.ai.embedding_service import (
    get_embedding_service_from_settings,
)
from app.modules.retrieval.chapter_scope_retrieval import expand_chapter_scope

logger = get_logger(__name__)


# ========== Phase 2: 跨章关联 ==========


async def fallback_chapter_similarity(
    db: AsyncSession,
    chapter_id: str,
    top_k: int = 5,
) -> List[Tuple[str, float]]:
    """
    冷启动兜底（Layer 4）：直接用章节 segment 的 embedding 计算相似度。
    """
    chapter = await db.get(CanonicalChapter, chapter_id)
    if not chapter:
        return []

    embedding = await get_embedding_service_from_settings(db)
    query_text = f"{chapter.name} {chapter.enhanced_description or ''}"
    query_vector = await embedding.embed_text(query_text)

    results = qdrant_manager.search(
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
        ]),
        limit=top_k + 1,
    )

    pairs = []
    for hit in results:
        payload = hit.get("payload") or {}
        if payload.get("entity_id") == chapter_id:
            continue
        if hit.get("score", 0) < 0.75:
            continue
        pairs.append((payload["entity_id"], hit.get("score", 0)))
    return pairs[:top_k]


async def expand_related_chapters(
    db: AsyncSession,
    chapter_ids: List[str],
    max_results: int = 10,
) -> Dict[str, Dict[str, list]]:
    """
    在线读取器：每个 chapter_id 返回两类关联，互不混排（见设计文档 6.3 阶段 B）。

    - scope_expansion:    在线由 parent_id 计算的结构派生（兄弟/父/子），不入表、不审核
    - semantic_relations: 只读 ChapterRelation 已审核行（review_status="approved"）

    检索路径不再在线推导语义关联——审核员对 ChapterRelation 的 approve/reject
    直接决定这里返回什么，从而修复 v1.2 审核与检索脱节的问题。

    返回: {
        chapter_id: {
            "scope_expansion":    [{chapter_id, relation}],
            "semantic_relations": [{chapter_id, source_type, relation_type,
                                     confidence, evidence_text}],
        }
    }
    """
    out: Dict[str, Dict[str, list]] = {}

    for chapter_id in chapter_ids:
        # 路 1: scope_expansion —— 在线计算，不读表（upward_levels=0 只取兄弟+父）
        scope_ids = await expand_chapter_scope(db, [chapter_id], upward_levels=0)

        # 路 2: semantic_relations —— 只读 ChapterRelation 已审核行
        rows = (await db.execute(
            select(ChapterRelation).where(
                ChapterRelation.source_chapter_id == chapter_id,
                ChapterRelation.review_status == "approved",
            ).order_by(ChapterRelation.confidence.desc()).limit(max_results)
        )).scalars().all()

        out[chapter_id] = {
            "scope_expansion": [
                {"chapter_id": cid, "relation": "sibling_or_ancestor"}
                for cid in scope_ids if cid != chapter_id
            ],
            "semantic_relations": [
                {
                    "chapter_id": r.target_chapter_id,
                    "source_type": r.source_type,
                    "relation_type": r.relation_type,
                    "confidence": float(r.confidence or 0),
                    "evidence_text": r.evidence_text,
                }
                for r in rows
            ],
        }

    return out


# ========== cross_references 校验 ==========


async def validate_cross_references(
    db: AsyncSession,
    cross_refs: List[dict],
) -> List[dict]:
    """校验 LLM 输出的 cross_references：确保 target_chapter_id 真实存在。"""
    if not cross_refs:
        return []

    target_ids = [ref["target_chapter_id"] for ref in cross_refs]
    existing = (await db.execute(
        select(CanonicalChapter.id).where(
            CanonicalChapter.id.in_(target_ids),
            CanonicalChapter.status == "active",
        )
    )).scalars().all()
    existing_set = set(existing)

    valid = [ref for ref in cross_refs if ref["target_chapter_id"] in existing_set]
    if len(valid) < len(cross_refs):
        logger.warning(
            "cross_references 包含无效 chapter_id，已过滤",
            total=len(cross_refs), valid=len(valid),
            invalid_ids=[ref["target_chapter_id"] for ref in cross_refs
                         if ref["target_chapter_id"] not in existing_set],
        )
    return valid
