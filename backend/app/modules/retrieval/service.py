"""
检索模块应用服务。

提供 dense / sparse / hybrid 三种检索模式，支持：
- 章节过滤（chapter_ids）
- 学科过滤（subject_id）
- 来源引用（source citation）
- 知识点关系扩展（prerequisite / similar_to 等）
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.qdrant import qdrant_manager
from app.models.mysql_models import (
    RetrievalSegment, KnowledgePoint, Question,
    KnowledgeRelation,
)
from app.modules.retrieval.outline_service import (
    expand_query_with_outline,
    retrieve_by_chapters,
)
from app.modules.retrieval.search_engine import (
    RetrievalResult,
    RetrievalSearchEngine,
)
from app.infrastructure.ai.embedding_service import (
    get_embedding_service_from_settings,
)

logger = get_logger(__name__)


class RetrievalService:
    """检索服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding = None  # 惰性加载：首次用时从系统设置读 embedding 配置
        self.qdrant = qdrant_manager
        self.search_engine = RetrievalSearchEngine(db)

    async def _ensure_embedding(self):
        if self.embedding is None:
            self.embedding = await get_embedding_service_from_settings(self.db)
        return self.embedding

    async def search_with_outline_expansion(
        self,
        query: str,
        subject_id: Optional[str] = None,
        chapter_ids: Optional[List[str]] = None,
        entity_type: Optional[str] = None,
        mode: str = "hybrid",
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Phase 0 + Phase 1 检索：先用大纲扩展 query，再做内容检索。

        1. Phase 0: query → Qdrant 搜 canonical_chapter → 扩展 query + 提取过滤条件
        2. Phase 1: 用扩展后的 query + 合并后的过滤条件做内容检索

        Returns:
            {
                "results": [...],
                "total": N,
                "outline_expansion": {
                    "expanded_query": "...",
                    "matched_chapters": [...],
                },
            }
        """
        # Phase 0: 大纲扩展
        expansion = await expand_query_with_outline(self.db, query)

        # 合并过滤条件。chapter filter 只取高置信 top-2 命中考点（matched_chapters
        # 已按 score 降序），避免低分考点把候选集扩成混杂主题、引入噪声。
        merged_subject_id = subject_id or (expansion.subject_ids[0] if expansion.subject_ids else None)
        top_expansion_chapter_ids = [
            c["chapter_id"] for c in expansion.matched_chapters[:2] if c.get("chapter_id")
        ]
        merged_chapter_ids = list(set(
            (chapter_ids or []) + top_expansion_chapter_ids
        )) or None

        # Phase 1: dense 用扩展后的 query（解决短查询语义不对称）；
        # sparse 保留原始 query（避免扩展拼入的长描述污染关键词匹配）。
        dense_query = expansion.expanded_query if expansion.matched_chapters else query
        results = await self.search(
            query=dense_query,
            sparse_query=query,
            subject_id=merged_subject_id,
            chapter_ids=merged_chapter_ids,
            entity_type=entity_type,
            mode=mode,
            limit=limit,
            filters=filters,
        )

        return {
            "results": [r.to_dict() for r in results],
            "total": len(results),
            "mode": mode,
            "outline_expansion": {
                "expanded_query": expansion.expanded_query[:200],
                "matched_chapters": expansion.matched_chapters,
                "subject_ids": expansion.subject_ids,
                "chapter_ids": expansion.chapter_ids,
            },
        }

    async def merge_dual_path_recall(
        self,
        expanded_query: str,
        chapter_ids: List[str],
        subject_id: Optional[str] = None,
        limit: int = 20,
        per_chapter_cap: int = 10,
    ) -> Dict[str, Any]:
        """
        双路分层归并（见设计文档 6.4）：

        - 路 A 向量直接命中（第一梯队，带 cosine 分数）：expanded_query → hybrid 检索
        - 路 B 考点结构化展开（第二梯队，无分数，按 link 表 JOIN）：在 chapter_ids
          范围内拉同考点的知识点/题目，补向量没召回的内容

        归并纪律：
        1. 分层不混排——路 A 在前（按分数），路 B 在后（补充上下文）
        2. 路 B 每考点设上限 per_chapter_cap，避免几十条无分数内容淹没精确命中
        3. JOIN 为主——路 B 走 link 表精确 JOIN，不再用关键词重搜
        4. 去重——路 A 已命中的实体不在路 B 重复出现，标注 dual_hit
        """
        # 路 A: 向量直接命中（第一梯队）
        vector_hits = await self.search(
            query=expanded_query,
            subject_id=subject_id,
            chapter_ids=chapter_ids or None,
            entity_type=None,  # knowledge_point + question 都召回
            mode="hybrid",
            limit=limit,
        )
        seen_entity_ids = {h.entity_id for h in vector_hits}

        tier1 = [
            {
                "entity_id": h.entity_id,
                "entity_type": h.entity_type,
                "segment_type": h.segment_type,
                "content_text": h.content_text,
                "score": h.score,
                "chapter_ids": h.chapter_ids,
                "source": "vector",
                "tier": 1,
            }
            for h in sorted(vector_hits, key=lambda x: x.score, reverse=True)
        ]

        # 路 B: 考点结构化展开（第二梯队），不再向上爬树，只取本批考点内容
        tier2: List[Dict[str, Any]] = []
        if chapter_ids:
            scope = await retrieve_by_chapters(
                self.db,
                chapter_ids=chapter_ids,
                expand_to_siblings=False,
            )
            for cid, items in scope.get("knowledge_points_by_chapter", {}).items():
                for item in items[:per_chapter_cap]:
                    if item["id"] in seen_entity_ids:
                        continue
                    seen_entity_ids.add(item["id"])
                    tier2.append({
                        "entity_id": item["id"],
                        "entity_type": "knowledge_point",
                        "content_text": item.get("summary") or item.get("title"),
                        "score": None,
                        "chapter_ids": [cid],
                        "source": "scope_expansion",
                        "tier": 2,
                    })
            for cid, items in scope.get("questions_by_chapter", {}).items():
                for item in items[:per_chapter_cap]:
                    if item["id"] in seen_entity_ids:
                        continue
                    seen_entity_ids.add(item["id"])
                    tier2.append({
                        "entity_id": item["id"],
                        "entity_type": "question",
                        "content_text": item.get("content"),
                        "score": None,
                        "chapter_ids": [cid],
                        "source": "scope_expansion",
                        "tier": 2,
                    })

        merged = (tier1 + tier2)[:limit]
        return {
            "results": merged,
            "total": len(merged),
            "tier1_count": len(tier1),
            "tier2_count": len(tier2),
        }

    async def search(
        self,
        query: str,
        subject_id: Optional[str] = None,
        chapter_ids: Optional[List[str]] = None,
        entity_type: Optional[str] = None,
        mode: str = "hybrid",
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        sparse_query: Optional[str] = None,
    ) -> List[RetrievalResult]:
        """
        统一检索入口

        Args:
            query: 用户查询文本（dense 检索用，可为大纲扩展后的长 query）
            subject_id: 学科过滤
            chapter_ids: 章节过滤（任意匹配）
            entity_type: "knowledge_point" / "question" / None(both)
            mode: "dense" / "sparse" / "hybrid"
            limit: 返回数量
            filters: 结构化过滤，支持 exam_year/exam_scope/difficulty/question_type/answer_source/tags
            sparse_query: sparse 检索专用 query。缺省时复用 query；大纲扩展场景下
                应传入原始 query，避免扩展拼接的长串给关键词 LIKE 引入噪声词

        Returns:
            按相关性排序的检索结果列表
        """
        if not query.strip():
            return []

        sparse_q = sparse_query if (sparse_query and sparse_query.strip()) else query

        # 生成 query embedding（dense 用 query）
        await self._ensure_embedding()
        query_vector = await self.embedding.embed_text(query)

        # 构建 Qdrant 过滤条件
        qdrant_filter = self.search_engine.build_filter(
            subject_id,
            chapter_ids,
            filters,
        )

        # 确定要搜索的 collections
        collections = self.search_engine.get_collections(entity_type)

        all_results: List[RetrievalResult] = []

        for collection in collections:
            # dense 检索
            dense_hits = self.qdrant.search(
                collection_name=collection,
                query_vector=query_vector,
                limit=limit * 2,
                query_filter=qdrant_filter,
            )

            if mode == "dense":
                hits = dense_hits
            elif mode == "sparse":
                hits = await self.search_engine.sparse_search(
                    collection,
                    sparse_q,
                    limit * 2,
                    subject_id=subject_id,
                    chapter_ids=chapter_ids,
                    filters=filters,
                )
            else:
                # hybrid: dense 用 query，sparse 用 sparse_q（原始 query）
                sparse_hits = await self.search_engine.sparse_search(
                    collection,
                    sparse_q,
                    limit * 2,
                    subject_id=subject_id,
                    chapter_ids=chapter_ids,
                    filters=filters,
                )
                hits = self.search_engine.merge_hits(dense_hits, sparse_hits)

            # 从 MySQL 补全完整信息
            results = await self.search_engine.hydrate_results(hits)
            all_results.extend(results)

        # 按 score 排序，截取 top-N
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:limit]

    async def search_with_relations(
        self,
        query: str,
        subject_id: Optional[str] = None,
        chapter_ids: Optional[List[str]] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """
        带关系扩展的检索

        1. 先做 hybrid 检索拿到 top-K 知识点
        2. 查询这些知识点的关系边
        3. 将关系关联的知识点也加入结果（prerequisite 优先）

        Returns:
            {
                "primary_results": [...],
                "related_results": [...],  # 关系扩展
                "relations": [...],        # 关系边信息
            }
        """
        # Step 1: 主检索
        primary = await self.search(
            query=query,
            subject_id=subject_id,
            chapter_ids=chapter_ids,
            entity_type="knowledge_point",
            mode="hybrid",
            limit=limit,
        )

        if not primary:
            return {"primary_results": [], "related_results": [], "relations": []}

        # Step 2: 查询关系
        primary_ids = list({r.entity_id for r in primary})
        relations = await self._get_relations(primary_ids)

        # Step 3: 关系扩展
        related_ids = set()
        relation_details = []
        for rel in relations:
            related_ids.add(rel["related_knowledge_id"])
            relation_details.append(rel)

        # 排除已有的
        related_ids -= set(primary_ids)

        # 查询关联知识点的 segments
        related_results: List[RetrievalResult] = []
        if related_ids:
            result = await self.db.execute(
                select(RetrievalSegment).where(
                    and_(
                        RetrievalSegment.entity_type == "knowledge_point",
                        RetrievalSegment.entity_id.in_(list(related_ids)),
                        RetrievalSegment.segment_type == "content",
                    )
                )
            )
            segments = result.scalars().all()

            for seg in segments:
                related_results.append(RetrievalResult(
                    segment_id=seg.id,
                    entity_type="knowledge_point",
                    entity_id=seg.entity_id,
                    segment_type=seg.segment_type,
                    content_text=seg.content_text,
                    context_text=seg.context_text,
                    score=0.3,  # 关系扩展的默认分数
                    subject_id=seg.subject_id,
                    chapter_ids=seg.chapter_ids or [],
                    source_document_id=seg.document_id,
                ))

        # Step 4: 双向扩展——查到的知识点带出关联题目（QuestionKnowledgeLink）
        linked_questions: List[Dict[str, Any]] = []
        try:
            linked_questions = await self._get_linked_questions(primary_ids, limit=limit)
        except Exception as e:
            logger.warning("知识点关联题目扩展失败，跳过", error=str(e))

        return {
            "primary_results": [r.to_dict() for r in primary],
            "related_results": [r.to_dict() for r in related_results[:limit]],
            "relations": relation_details[:10],
            "linked_questions": linked_questions,
        }

    async def _get_linked_questions(
        self, knowledge_point_ids: List[str], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """根据知识点反查关联题目（QuestionKnowledgeLink），按 relevance 降序。"""
        if not knowledge_point_ids:
            return []
        from app.models.mysql_models import QuestionKnowledgeLink
        rows = (await self.db.execute(
            select(QuestionKnowledgeLink, Question)
            .join(Question, QuestionKnowledgeLink.question_id == Question.id)
            .where(
                QuestionKnowledgeLink.knowledge_point_id.in_(knowledge_point_ids),
                Question.status != "deleted",
            )
            .order_by(QuestionKnowledgeLink.relevance.desc())
            .limit(limit * 3)
        )).all()
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for link, q in rows:
            if q.id in seen:
                continue
            seen.add(q.id)
            out.append({
                "question_id": q.id,
                "content": (q.content or "")[:200],
                "question_no": q.question_no,
                "exam_year": q.exam_year,
                "source": q.source,
                "relevance": float(link.relevance or 0),
                "via_knowledge_point_id": link.knowledge_point_id,
            })
            if len(out) >= limit:
                break
        return out

    async def _get_relations(
        self, knowledge_point_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """查询知识点的关系边"""
        from sqlalchemy import or_

        result = await self.db.execute(
            select(KnowledgeRelation, KnowledgePoint)
            .join(
                KnowledgePoint,
                or_(
                    and_(
                        KnowledgeRelation.target_knowledge_id == KnowledgePoint.id,
                        KnowledgeRelation.source_knowledge_id.in_(knowledge_point_ids),
                    ),
                    and_(
                        KnowledgeRelation.source_knowledge_id == KnowledgePoint.id,
                        KnowledgeRelation.target_knowledge_id.in_(knowledge_point_ids),
                    ),
                ),
            )
            .where(
                KnowledgeRelation.review_status == "approved",
                or_(
                    KnowledgeRelation.source_knowledge_id.in_(knowledge_point_ids),
                    KnowledgeRelation.target_knowledge_id.in_(knowledge_point_ids),
                ),
            )
        )
        rows = result.all()

        relations = []
        for rel, kp in rows:
            if rel.source_knowledge_id in knowledge_point_ids:
                direction = "outgoing"
                related_id = rel.target_knowledge_id
            else:
                direction = "incoming"
                related_id = rel.source_knowledge_id

            relations.append({
                "relation_id": rel.id,
                "relation_type": rel.relation_type,
                "direction": direction,
                "related_knowledge_id": related_id,
                "related_knowledge_title": kp.title,
                "evidence_text": rel.evidence_text,
            })

        return relations


# 依赖注入
async def get_retrieval_service(db: AsyncSession) -> RetrievalService:
    return RetrievalService(db)
