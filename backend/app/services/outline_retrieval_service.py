"""
大纲辅助检索服务

实现设计文档 outline-retrieval-cross-chapter-association-design.md 中定义的核心函数：

Phase 0: expand_query_with_outline()  - 大纲辅助 Query 扩展
Phase 2: expand_chapter_scope()      - 沿考点树向上扩展
Phase 2: retrieve_by_exam_point()    - 从题出发的结构化展开
Phase 2: find_cross_chapter_relations() - 知识点关系图桥接
Phase 2: fallback_chapter_similarity()  - embedding 兜底
Phase 2: expand_related_chapters()      - 跨章关联编排（层叠降级）
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from qdrant_client.models import Filter, FieldCondition, MatchValue

from app.core.logging import get_logger
from app.db.qdrant import qdrant_manager
from app.models.mysql_models import (
    CanonicalChapter,
    KnowledgePoint,
    KnowledgePointChapterLink,
    KnowledgeRelation,
    Question,
    QuestionChapterLink,
    RetrievalSegment,
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
class RelationHop:
    """关系图中的一跳"""
    from_kp: str
    to_kp: str
    relation_type: str
    confidence: float


@dataclass
class CrossChapterRelation:
    """跨章关联结果"""
    target_chapter_id: str
    score: float
    via_knowledge_point_id: str = ""
    path: List[RelationHop] = field(default_factory=list)


@dataclass
class RelatedChapter:
    """跨章关联编排结果"""
    chapter_id: str
    source: str  # sibling / llm_cross_reference / knowledge_bridge / embedding_fallback
    score: float
    relation_type: str = "similar_to"
    reason: Optional[str] = None


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


async def retrieve_by_exam_point(
    db: AsyncSession,
    question_id: str,
    expand_to_siblings: bool = True,
    expand_upward_levels: int = 1,
) -> Dict[str, Any]:
    """
    从一道题出发，围绕考点展开所有相关知识。

    返回:
    {
        "question": {...},
        "primary_chapters": [...],
        "all_chapters": [...],
        "questions_by_chapter": {...},
        "knowledge_points_by_chapter": {...},
    }
    """
    # Step 1: 题目 → 考点
    chapter_links = (await db.execute(
        select(QuestionChapterLink).where(
            QuestionChapterLink.question_id == question_id
        )
    )).scalars().all()
    chapter_ids = [link.canonical_chapter_id for link in chapter_links]

    # Step 2: 扩展考点范围
    all_chapter_ids = set(chapter_ids)
    if expand_to_siblings and chapter_ids:
        expanded = await expand_chapter_scope(db, chapter_ids, expand_upward_levels)
        all_chapter_ids.update(expanded)

    chapter_id_list = list(all_chapter_ids)

    # Step 3: 批量收集范围内的题目和知识点
    questions = []
    if chapter_id_list:
        questions = (await db.execute(
            select(Question).join(QuestionChapterLink).where(
                QuestionChapterLink.canonical_chapter_id.in_(chapter_id_list),
                Question.id != question_id,
                Question.review_status == "approved",
            )
        )).scalars().all()

    knowledge_points = []
    if chapter_id_list:
        knowledge_points = (await db.execute(
            select(KnowledgePoint).join(KnowledgePointChapterLink).where(
                KnowledgePointChapterLink.canonical_chapter_id.in_(chapter_id_list),
                KnowledgePoint.review_status == "approved",
            )
        )).scalars().all()

    # Step 4: 加载章节信息
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
            for ch in chapters if ch.id in chapter_ids
        ],
        "all_chapters": [
            {"id": ch.id, "name": ch.name, "level": ch.level, "outline_code": ch.outline_code}
            for ch in chapters
        ],
        "questions_by_chapter": questions_by_chapter,
        "knowledge_points_by_chapter": kp_by_chapter,
    }


# ========== Phase 2: 跨章关联 ==========


async def find_cross_chapter_relations(
    db: AsyncSession,
    chapter_id: str,
    max_depth: int = 2,
    min_confidence: float = 0.7,
) -> List[CrossChapterRelation]:
    """
    通过知识点关系图找到与指定考点关联的其他考点（Layer 2）。

    1. 考点 → KnowledgePointChapterLink → 该考点下的所有知识点（起点 S）
    2. 从 S 出发，沿 KnowledgeRelation 边做 BFS（max_depth 跳）
    3. 到达的知识点集合 T → KnowledgePointChapterLink → 关联的考点 C
    4. 排除原考点，按关系路径强度排序
    """
    # Step 1: 考点 → 知识点
    kp_links = (await db.execute(
        select(KnowledgePointChapterLink).where(
            KnowledgePointChapterLink.canonical_chapter_id == chapter_id
        )
    )).scalars().all()
    start_kp_ids = {link.knowledge_point_id for link in kp_links}

    if not start_kp_ids:
        return []

    # Step 2: BFS 逐层批量查询
    visited: Dict[str, float] = {kp_id: 1.0 for kp_id in start_kp_ids}
    paths: Dict[str, List[RelationHop]] = {}
    frontier = list(start_kp_ids)

    for _depth in range(max_depth):
        if not frontier:
            break

        rows = (await db.execute(
            select(KnowledgeRelation).where(
                or_(
                    KnowledgeRelation.source_knowledge_id.in_(frontier),
                    KnowledgeRelation.target_knowledge_id.in_(frontier),
                ),
                KnowledgeRelation.review_status == "approved",
                KnowledgeRelation.confidence >= min_confidence,
            )
        )).scalars().all()

        next_frontier = []
        for rel in rows:
            if rel.source_knowledge_id in frontier:
                from_kp = rel.source_knowledge_id
                neighbor = rel.target_knowledge_id
            else:
                from_kp = rel.target_knowledge_id
                neighbor = rel.source_knowledge_id

            if neighbor in start_kp_ids:
                continue

            edge_confidence = float(rel.confidence or 0.5)
            cumulative = visited[from_kp] * edge_confidence

            if neighbor not in visited or cumulative > visited[neighbor]:
                visited[neighbor] = cumulative
                paths[neighbor] = paths.get(from_kp, []) + [RelationHop(
                    from_kp=from_kp,
                    to_kp=neighbor,
                    relation_type=rel.relation_type,
                    confidence=edge_confidence,
                )]
                if neighbor not in next_frontier:
                    next_frontier.append(neighbor)

        frontier = next_frontier

    # Step 3: 到达的知识点 → 考点
    reached_kp_ids = set(visited.keys()) - start_kp_ids
    if not reached_kp_ids:
        return []

    chapter_links = (await db.execute(
        select(KnowledgePointChapterLink).where(
            KnowledgePointChapterLink.knowledge_point_id.in_(list(reached_kp_ids)),
            KnowledgePointChapterLink.canonical_chapter_id != chapter_id,
        )
    )).scalars().all()

    # Step 4: 聚合到考点
    chapter_scores: Dict[str, CrossChapterRelation] = {}
    for link in chapter_links:
        score = visited.get(link.knowledge_point_id, 0)
        if link.canonical_chapter_id not in chapter_scores or \
           score > chapter_scores[link.canonical_chapter_id].score:
            chapter_scores[link.canonical_chapter_id] = CrossChapterRelation(
                target_chapter_id=link.canonical_chapter_id,
                score=score,
                via_knowledge_point_id=link.knowledge_point_id,
                path=paths.get(link.knowledge_point_id, []),
            )

    return sorted(chapter_scores.values(), key=lambda r: r.score, reverse=True)


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
) -> Dict[str, List[RelatedChapter]]:
    """
    跨章关联编排（层叠降级策略）。

    对每个 chapter_id:
    1. Layer 1: 同 parent_id 兄弟考点 → 零误判，优先
    2. Layer 3: cross_references → LLM 精确标注
    3. Layer 2: find_cross_chapter_relations() → 知识点桥接
    4. Layer 4: fallback_chapter_similarity() → embedding 兜底

    去重：同一 target_chapter_id 只保留最高优先级来源的结果。
    """
    result: Dict[str, Dict[str, RelatedChapter]] = {
        cid: {} for cid in chapter_ids
    }

    for chapter_id in chapter_ids:
        chapter = await db.get(CanonicalChapter, chapter_id)
        if not chapter:
            continue
        seen = result[chapter_id]

        # Layer 1: 结构化关联（同章兄弟）
        if chapter.parent_id:
            siblings = (await db.execute(
                select(CanonicalChapter).where(
                    CanonicalChapter.parent_id == chapter.parent_id,
                    CanonicalChapter.id != chapter_id,
                    CanonicalChapter.status == "active",
                )
            )).scalars().all()
            for sib in siblings:
                if sib.id not in seen:
                    seen[sib.id] = RelatedChapter(
                        chapter_id=sib.id,
                        source="sibling",
                        score=1.0,
                        relation_type="similar_to",
                    )

        # Layer 3: LLM 显式标注
        cross_refs = getattr(chapter, "cross_references", None)
        if cross_refs:
            for ref in cross_refs:
                target_id = ref.get("target_chapter_id")
                if target_id and target_id not in seen:
                    seen[target_id] = RelatedChapter(
                        chapter_id=target_id,
                        source="llm_cross_reference",
                        score=0.9,
                        relation_type=ref.get("relation_type", "similar_to"),
                        reason=ref.get("reason"),
                    )

        # Layer 2: 知识点关系图桥接
        try:
            bridged = await find_cross_chapter_relations(db, chapter_id)
            for br in bridged:
                if br.target_chapter_id not in seen:
                    seen[br.target_chapter_id] = RelatedChapter(
                        chapter_id=br.target_chapter_id,
                        source="knowledge_bridge",
                        score=br.score,
                        relation_type=br.path[-1].relation_type if br.path else "similar_to",
                    )
        except Exception as e:
            logger.warning("关系图桥接失败，跳过", chapter_id=chapter_id, error=str(e))

        # Layer 4: embedding 兜底（仅冷启动）
        if len(seen) == 0:
            try:
                sims = await fallback_chapter_similarity(db, chapter_id, top_k=3)
                for target_id, score in sims:
                    if target_id not in seen:
                        seen[target_id] = RelatedChapter(
                            chapter_id=target_id,
                            source="embedding_fallback",
                            score=score,
                            relation_type="similar_to",
                        )
            except Exception as e:
                logger.warning("embedding 兜底失败", chapter_id=chapter_id, error=str(e))

    return {
        cid: sorted(entries.values(), key=lambda r: r.score, reverse=True)[:max_results]
        for cid, entries in result.items()
    }


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
