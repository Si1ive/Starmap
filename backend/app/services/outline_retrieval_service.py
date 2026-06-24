"""
大纲辅助检索服务

实现设计文档 outline-retrieval-cross-chapter-association-design.md 中定义的核心函数：

Phase 0: expand_query_with_outline()  - 大纲辅助 Query 扩展
Phase 2: expand_chapter_scope()      - 沿考点树向上扩展
Phase 2: retrieve_by_chapters()      - 从考点出发的结构化展开
Phase 2: retrieve_by_question()      - 从题出发（题→考点→委托 retrieve_by_chapters）
Phase 2: fallback_chapter_similarity()  - embedding 兜底（离线构建器用）
Phase 2: expand_related_chapters()      - 在线读取器：scope 在线算 + semantic 读 ChapterRelation 已审核行
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from qdrant_client.models import Filter, FieldCondition, MatchValue

from app.core.logging import get_logger
from app.db.qdrant import qdrant_manager
from app.models.mysql_models import (
    CanonicalChapter,
    ChapterRelation,
    KnowledgePoint,
    KnowledgePointChapterLink,
    Question,
    QuestionChapterLink,
)
from app.services.embedding_service import get_embedding_service_from_settings

logger = get_logger(__name__)


# ========== 数据结构 ==========


@dataclass
class OutlineExpansionResult:
    """Phase 0 大纲扩展结果"""
    expanded_query: str
    subject_ids: List[str] = field(default_factory=list)
    chapter_ids: List[str] = field(default_factory=list)
    matched_chapters: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ScopeChapter:
    """scope_expansion 结果：考点树结构派生（在线计算，不入表）"""
    chapter_id: str
    relation: str = "sibling_or_ancestor"  # sibling / parent / child


@dataclass
class SemanticRelation:
    """semantic_relations 结果：读 ChapterRelation 已审核行"""
    chapter_id: str
    source_type: str  # llm / embedding / manual
    relation_type: str = "similar_to"
    confidence: float = 0.0
    evidence_text: Optional[str] = None


# ========== Phase 0: 大纲辅助 Query 扩展 ==========


async def expand_query_with_outline(
    db: AsyncSession,
    query: str,
    top_k: int = 3,
) -> OutlineExpansionResult:
    """
    用大纲考点扩展用户 query，解决短查询 vs 长文档的语义不对称问题。

    1. query embedding → Qdrant 检索 entity_type="canonical_chapter" 的 segment
    2. 聚合到 chapter_id，取 top-K 考点
    3. 用考点 keywords + enhanced_description 扩写 query
    4. 提取结构化过滤条件 (subject_ids, chapter_ids)
    """
    if not query.strip():
        return OutlineExpansionResult(expanded_query=query)

    embedding = await get_embedding_service_from_settings(db)
    query_vector = await embedding.embed_text(query)

    # Step 1: Qdrant 检索考点 segment（title + content 双路）
    title_hits = qdrant_manager.search(
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
            FieldCondition(key="segment_type", match=MatchValue(value="title")),
        ]),
        limit=top_k * 2,
    )
    content_hits = qdrant_manager.search(
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
            FieldCondition(key="segment_type", match=MatchValue(value="content")),
        ]),
        limit=top_k * 2,
    )

    # Step 2: 合并 title + content 命中，聚合到 chapter_id
    chapter_scores: Dict[str, float] = {}
    for hit in title_hits + content_hits:
        ch_id = hit.payload.get("entity_id")
        if not ch_id:
            continue
        weight = 1.2 if hit.payload.get("segment_type") == "title" else 1.0
        chapter_scores[ch_id] = max(chapter_scores.get(ch_id, 0), hit.score * weight)

    top_chapters = sorted(
        [(cid, s) for cid, s in chapter_scores.items() if s >= 0.7],
        key=lambda x: -x[1],
    )[:top_k]

    if not top_chapters:
        return OutlineExpansionResult(expanded_query=query)

    # Step 3: 从 MySQL 加载考点完整信息
    top_ids = [cid for cid, _ in top_chapters]
    chapters = (await db.execute(
        select(CanonicalChapter).where(CanonicalChapter.id.in_(top_ids))
    )).scalars().all()
    chapter_map = {ch.id: ch for ch in chapters}

    # 构建扩展 query
    query_parts = [query]
    for cid, _score in top_chapters:
        ch = chapter_map.get(cid)
        if not ch:
            continue
        if ch.keywords:
            query_parts.append(" ".join(ch.keywords[:8]))
        if ch.enhanced_description:
            query_parts.append(ch.enhanced_description[:100])

    expanded_query = " ".join(query_parts)

    # Step 4: 提取结构化过滤条件
    subject_ids = list({
        chapter_map[cid].subject_id
        for cid, _ in top_chapters
        if chapter_map.get(cid) and chapter_map[cid].subject_id
    })

    matched_chapters = [
        {
            "chapter_id": cid,
            "name": chapter_map[cid].name if chapter_map.get(cid) else "",
            "outline_code": chapter_map[cid].outline_code if chapter_map.get(cid) else "",
            "score": round(score, 4),
            "keywords": chapter_map[cid].keywords if chapter_map.get(cid) else [],
        }
        for cid, score in top_chapters
        if chapter_map.get(cid)
    ]

    return OutlineExpansionResult(
        expanded_query=expanded_query[:2000],
        subject_ids=subject_ids,
        chapter_ids=top_ids,
        matched_chapters=matched_chapters,
    )


# ========== Phase 2: 考点树展开 ==========


async def expand_chapter_scope(
    db: AsyncSession,
    chapter_ids: List[str],
    upward_levels: int = 1,
) -> List[str]:
    """
    沿考点树向上扩展，返回范围内所有考点 ID。

    1. 收集起点章节的兄弟节点（同 parent_id）
    2. 逐级向上爬：每爬一级，把当前父节点和它的所有子节点加入结果
    """
    result = set(chapter_ids)

    chapters = (await db.execute(
        select(CanonicalChapter).where(
            CanonicalChapter.id.in_(chapter_ids),
            CanonicalChapter.status == "active",
        )
    )).scalars().all()

    if not chapters:
        return list(result)

    # 收集各起点的 parent_id，批量查兄弟
    parent_ids = {ch.parent_id for ch in chapters if ch.parent_id}
    if parent_ids:
        siblings = (await db.execute(
            select(CanonicalChapter.id).where(
                CanonicalChapter.parent_id.in_(parent_ids),
                CanonicalChapter.status == "active",
            )
        )).scalars().all()
        result.update(siblings)
        result.update(parent_ids)

    if upward_levels <= 0:
        return list(result)

    # 逐级向上爬
    current_parents = parent_ids
    visited_parents = set(current_parents)

    for _ in range(upward_levels):
        if not current_parents:
            break

        parents = (await db.execute(
            select(CanonicalChapter).where(
                CanonicalChapter.id.in_(list(current_parents)),
                CanonicalChapter.status == "active",
            )
        )).scalars().all()

        next_parent_ids = set()
        for parent in parents:
            result.add(parent.id)
            if parent.parent_id and parent.parent_id not in visited_parents:
                next_parent_ids.add(parent.parent_id)
                visited_parents.add(parent.parent_id)

        if next_parent_ids:
            cousins = (await db.execute(
                select(CanonicalChapter.id).where(
                    CanonicalChapter.parent_id.in_(list(next_parent_ids)),
                    CanonicalChapter.status == "active",
                )
            )).scalars().all()
            result.update(cousins)

        current_parents = next_parent_ids

    return list(result)


# ========== Phase 2: 题 → 考点 → 相关知识 结构化检索 ==========


async def retrieve_by_chapters(
    db: AsyncSession,
    chapter_ids: List[str],
    expand_to_siblings: bool = True,
    expand_upward_levels: int = 1,
    exclude_question_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从一组考点出发，展开该范围内的题目和知识点（结构化检索，纯 link 表 JOIN）。

    chapter_ids 为「主考点」，可选地沿考点树展开到兄弟/父考点。

    返回:
    {
        "primary_chapters": [...],   # 传入的主考点
        "all_chapters": [...],       # 展开后的全部考点
        "questions_by_chapter": {...},
        "knowledge_points_by_chapter": {...},
    }
    """
    primary_ids = list(chapter_ids)

    # Step 1: 扩展考点范围
    all_chapter_ids = set(primary_ids)
    if expand_to_siblings and primary_ids:
        expanded = await expand_chapter_scope(db, primary_ids, expand_upward_levels)
        all_chapter_ids.update(expanded)

    chapter_id_list = list(all_chapter_ids)

    # Step 2: 批量收集范围内的题目和知识点
    questions = []
    if chapter_id_list:
        conds = [
            QuestionChapterLink.canonical_chapter_id.in_(chapter_id_list),
            Question.review_status == "approved",
        ]
        if exclude_question_id:
            conds.append(Question.id != exclude_question_id)
        questions = (await db.execute(
            select(Question).join(QuestionChapterLink).where(*conds)
        )).scalars().all()

    knowledge_points = []
    if chapter_id_list:
        knowledge_points = (await db.execute(
            select(KnowledgePoint).join(KnowledgePointChapterLink).where(
                KnowledgePointChapterLink.canonical_chapter_id.in_(chapter_id_list),
                KnowledgePoint.review_status == "approved",
            )
        )).scalars().all()

    # Step 3: 加载章节信息
    chapters = []
    if chapter_id_list:
        chapters = (await db.execute(
            select(CanonicalChapter).where(
                CanonicalChapter.id.in_(chapter_id_list),
                CanonicalChapter.status == "active",
            )
        )).scalars().all()

    # 按考点分组
    questions_by_chapter: Dict[str, List[Dict[str, Any]]] = {}
    for q in questions:
        for link in q.chapter_links:
            cid = link.canonical_chapter_id
            if cid not in questions_by_chapter:
                questions_by_chapter[cid] = []
            questions_by_chapter[cid].append({
                "id": q.id,
                "content": (q.content or "")[:200],
                "question_no": getattr(q, "question_no", None),
                "exam_year": getattr(q, "exam_year", None),
            })

    kp_by_chapter: Dict[str, List[Dict[str, Any]]] = {}
    for kp in knowledge_points:
        for link in kp.chapter_links:
            cid = link.canonical_chapter_id
            if cid not in kp_by_chapter:
                kp_by_chapter[cid] = []
            kp_by_chapter[cid].append({
                "id": kp.id,
                "title": kp.title,
                "summary": getattr(kp, "summary", None),
            })

    return {
        "primary_chapters": [
            {"id": ch.id, "name": ch.name, "level": ch.level}
            for ch in chapters if ch.id in primary_ids
        ],
        "all_chapters": [
            {"id": ch.id, "name": ch.name, "level": ch.level, "outline_code": ch.outline_code}
            for ch in chapters
        ],
        "questions_by_chapter": questions_by_chapter,
        "knowledge_points_by_chapter": kp_by_chapter,
    }


async def retrieve_by_question(
    db: AsyncSession,
    question_id: str,
    expand_to_siblings: bool = True,
    expand_upward_levels: int = 1,
) -> Dict[str, Any]:
    """
    从一道题出发：题 → 考点（QuestionChapterLink）→ 委托 retrieve_by_chapters 展开。

    返回结构同 retrieve_by_chapters，主考点为该题直接关联的考点。
    """
    chapter_links = (await db.execute(
        select(QuestionChapterLink).where(
            QuestionChapterLink.question_id == question_id
        )
    )).scalars().all()
    chapter_ids = [link.canonical_chapter_id for link in chapter_links]

    return await retrieve_by_chapters(
        db,
        chapter_ids=chapter_ids,
        expand_to_siblings=expand_to_siblings,
        expand_upward_levels=expand_upward_levels,
        exclude_question_id=question_id,
    )


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
        if hit.payload.get("entity_id") == chapter_id:
            continue
        if hit.score < 0.75:
            continue
        pairs.append((hit.payload["entity_id"], hit.score))
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
