"""
语料 ↔ 大纲章节关联服务

当知识点/题目审核通过后，自动建立与大纲章节的关联。

匹配策略（4层）:
1. 直接读取: entity.primary_chapter_id（已有关联）
2. 文档映射: DocumentSectionMapping（规则匹配）
3. 向量检索: canonical_chapter segments（语义匹配）
4. LLM 推理: 低分候选让 LLM 选择（可选）
"""

import uuid
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    KnowledgePoint, Question, CanonicalChapter,
    KnowledgePointChapterLink, QuestionChapterLink,
    EntitySourceLink, DocumentBlock, DocumentSection, DocumentSectionMapping
)

logger = get_logger(__name__)


def _gen_id() -> str:
    return uuid.uuid4().hex[:32]


class ChapterLinkService:
    """语料 ↔ 大纲章节关联服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== 公共接口 ==========

    async def link_knowledge_point_to_chapters(self, kp_id: str) -> Dict[str, Any]:
        """
        为知识点匹配大纲章节

        返回:
        {
            "linked_count": N,
            "primary_chapter": {...},
            "related_chapters": [...],
            "strategy_used": "existing / document_mapping / vector_search"
        }
        """
        kp = await self.db.get(KnowledgePoint, kp_id)
        if not kp:
            raise ValueError(f"知识点不存在: {kp_id}")

        return await self._link_entity_to_chapters(kp, "knowledge_point")

    async def link_question_to_chapters(self, question_id: str) -> Dict[str, Any]:
        """为题目匹配大纲章节"""
        question = await self.db.get(Question, question_id)
        if not question:
            raise ValueError(f"题目不存在: {question_id}")

        return await self._link_entity_to_chapters(question, "question")

    async def batch_link_document(self, document_id: str) -> Dict[str, Any]:
        """
        批量处理一个文档下的所有已审核实体

        返回:
        {
            "knowledge_points": {"linked": N, "failed": M},
            "questions": {"linked": N, "failed": M}
        }
        """
        # 查询该文档下的所有已审核知识点
        kps = (await self.db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.source_document_id == document_id,
                KnowledgePoint.review_status == "approved"
            )
        )).scalars().all()

        # 查询该文档下的所有已审核题目
        questions = (await self.db.execute(
            select(Question).where(
                Question.source_document_id == document_id,
                Question.review_status == "approved"
            )
        )).scalars().all()

        kp_linked = 0
        kp_failed = 0
        for kp in kps:
            try:
                result = await self.link_knowledge_point_to_chapters(kp.id)
                if result["linked_count"] > 0:
                    kp_linked += 1
                else:
                    kp_failed += 1
            except Exception as e:
                logger.error("批量关联知识点失败", kp_id=kp.id, error=str(e))
                kp_failed += 1

        q_linked = 0
        q_failed = 0
        for q in questions:
            try:
                result = await self.link_question_to_chapters(q.id)
                if result["linked_count"] > 0:
                    q_linked += 1
                else:
                    q_failed += 1
            except Exception as e:
                logger.error("批量关联题目失败", question_id=q.id, error=str(e))
                q_failed += 1

        return {
            "knowledge_points": {"linked": kp_linked, "failed": kp_failed},
            "questions": {"linked": q_linked, "failed": q_failed}
        }

    # ========== 核心匹配逻辑 ==========

    async def _link_entity_to_chapters(
        self, entity, entity_type: str
    ) -> Dict[str, Any]:
        """
        综合 3 层策略匹配章节

        策略优先级:
        1. existing: 直接读取 primary_chapter_id
        2. document_mapping: 通过文档section映射
        3. vector_search: 向量检索

        返回格式见 link_knowledge_point_to_chapters 文档
        """
        results = []
        strategy_used = None

        # 策略 1: 直接读取
        if entity.primary_chapter_id:
            # 检查该章节是否仍然存在
            chapter = await self.db.get(CanonicalChapter, entity.primary_chapter_id)
            if chapter and chapter.status == "active":
                results = [{
                    "chapter_id": entity.primary_chapter_id,
                    "relevance": 1.0,
                    "source": "existing",
                    "is_primary": True
                }]
                strategy_used = "existing"
                logger.info("使用已有关联", entity_id=entity.id, entity_type=entity_type)

        # 策略 2: 文档映射
        if not results and entity.source_document_id:
            mapping_result = await self._match_by_document_mapping(entity, entity_type)
            if mapping_result:
                results = [mapping_result]
                strategy_used = "document_mapping"
                logger.info("文档映射匹配成功", entity_id=entity.id,
                           chapter_id=mapping_result["chapter_id"])

        # 策略 3: 向量检索
        if not results:
            vector_results = await self._match_by_vector_search(entity, entity_type)
            if vector_results:
                results = vector_results
                strategy_used = "vector_search"
                logger.info("向量检索匹配成功", entity_id=entity.id,
                           count=len(vector_results))

        # 没有任何匹配
        if not results:
            logger.warning("无法匹配章节", entity_id=entity.id, entity_type=entity_type)
            return {
                "linked_count": 0,
                "primary_chapter": None,
                "related_chapters": [],
                "strategy_used": "none"
            }

        # 写入关联表
        return await self._save_links(entity, entity_type, results, strategy_used)

    # ========== 策略 2: 文档映射 ==========

    async def _match_by_document_mapping(
        self, entity, entity_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        通过文档section映射查找章节

        流程:
        1. entity → EntitySourceLink → 第一个 block
        2. block.page_no → DocumentSection (该页所在的section)
        3. DocumentSection → DocumentSectionMapping (approved)
        4. 返回 canonical_chapter_id
        """
        # 1. 查询实体的第一个来源 block
        source_link_query = select(EntitySourceLink).where(
            EntitySourceLink.entity_type == entity_type,
            EntitySourceLink.entity_id == entity.id
        ).order_by(EntitySourceLink.id).limit(1)

        source_link = (await self.db.execute(source_link_query)).scalar_one_or_none()
        if not source_link or not source_link.block_ids:
            return None

        first_block_id = source_link.block_ids[0]
        block = await self.db.get(DocumentBlock, first_block_id)
        if not block:
            return None

        # 2. 查询该页所在的 DocumentSection（取最深层级的）
        section_query = select(DocumentSection).where(
            DocumentSection.document_id == entity.source_document_id,
            DocumentSection.page_start <= block.page_no,
            DocumentSection.page_end >= block.page_no
        ).order_by(DocumentSection.level.desc())  # 优先取最深层级

        section = (await self.db.execute(section_query)).scalar_one_or_none()
        if not section:
            return None

        # 3. 查询该 section 的 approved 映射
        mapping_query = select(DocumentSectionMapping).where(
            DocumentSectionMapping.document_section_id == section.id,
            DocumentSectionMapping.review_status == "approved"
        ).order_by(DocumentSectionMapping.confidence.desc())

        mapping = (await self.db.execute(mapping_query)).scalar_one_or_none()
        if not mapping:
            return None

        return {
            "chapter_id": mapping.canonical_chapter_id,
            "relevance": float(mapping.confidence),
            "source": "document_mapping",
            "is_primary": True,
            "mapping_type": mapping.mapping_type
        }

    # ========== 策略 3: 向量检索 ==========

    async def _match_by_vector_search(
        self, entity, entity_type: str
    ) -> List[Dict[str, Any]]:
        """
        用实体内容在 canonical_chapter segments 中检索

        返回: 最多 top-3 相关章节
        """
        from app.services.embedding_service import get_embedding_service_from_settings
        from app.db.qdrant import qdrant_manager
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        # 1. 构造查询文本
        if entity_type == "knowledge_point":
            query_text = f"{entity.title}\n{(entity.content or '')[:500]}"
        else:  # question
            options_text = "\n".join([
                f"{opt.get('key', '')}. {opt.get('text', '')}"
                for opt in (entity.options or [])[:4]
            ])
            query_text = f"{entity.content[:300]}\n{options_text[:200]}"

        if not query_text.strip():
            return []

        # 2. 生成 embedding
        try:
            embedding_service = await get_embedding_service_from_settings(self.db)
            query_vector = await embedding_service.embed_text(query_text)
        except Exception as e:
            logger.error("生成 embedding 失败", error=str(e))
            return []

        # 3. Qdrant 检索
        try:
            results = qdrant_manager.search(
                collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
                query_vector=query_vector,
                query_filter=Filter(must=[
                    FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
                    FieldCondition(key="subject_id", match=MatchValue(value=entity.subject_id)),
                ]),
                limit=10  # 多取一些，后续聚合
            )
        except Exception as e:
            logger.error("Qdrant 检索失败", error=str(e))
            return []

        # 4. 聚合到 chapter_id（一个章节可能有多个 segment）
        chapter_scores = {}
        for hit in results:
            chapter_id = hit.payload.get("entity_id")
            if not chapter_id:
                continue
            # 取该章节所有 segment 的最高分
            chapter_scores[chapter_id] = max(
                chapter_scores.get(chapter_id, 0),
                hit.score
            )

        # 5. 过滤 + 排序
        candidates = [
            {
                "chapter_id": cid,
                "relevance": score,
                "source": "vector_search",
                "is_primary": (i == 0 and score >= 0.85),  # 最高分且 >= 0.85 → 主章节
            }
            for i, (cid, score) in enumerate(
                sorted(chapter_scores.items(), key=lambda x: -x[1])
            )
            if score >= 0.75  # 阈值过滤
        ]

        return candidates[:3]  # 最多 3 个

    # ========== 保存关联 ==========

    async def _save_links(
        self, entity, entity_type: str, results: List[Dict[str, Any]], strategy_used: str
    ) -> Dict[str, Any]:
        """
        写入关联表并返回结果

        处理去重: 如果关联已存在，更新 relevance/source
        """
        primary = None
        related = []

        for res in results:
            chapter_id = res["chapter_id"]

            # 检查章节是否存在
            chapter = await self.db.get(CanonicalChapter, chapter_id)
            if not chapter or chapter.status != "active":
                continue

            # 检查是否已有关联
            if entity_type == "knowledge_point":
                existing_link = (await self.db.execute(
                    select(KnowledgePointChapterLink).where(
                        KnowledgePointChapterLink.knowledge_point_id == entity.id,
                        KnowledgePointChapterLink.canonical_chapter_id == chapter_id
                    )
                )).scalar_one_or_none()

                if existing_link:
                    # 更新已有关联
                    existing_link.relevance = res["relevance"]
                    existing_link.source = res["source"]
                    existing_link.is_primary = res.get("is_primary", False)
                else:
                    # 创建新关联
                    link = KnowledgePointChapterLink(
                        knowledge_point_id=entity.id,
                        canonical_chapter_id=chapter_id,
                        is_primary=res.get("is_primary", False),
                        relevance=res["relevance"],
                        source=res["source"],
                        created_by="system"
                    )
                    self.db.add(link)
            else:  # question
                existing_link = (await self.db.execute(
                    select(QuestionChapterLink).where(
                        QuestionChapterLink.question_id == entity.id,
                        QuestionChapterLink.canonical_chapter_id == chapter_id
                    )
                )).scalar_one_or_none()

                if existing_link:
                    existing_link.relevance = res["relevance"]
                    existing_link.source = res["source"]
                    existing_link.is_primary = res.get("is_primary", False)
                else:
                    link = QuestionChapterLink(
                        question_id=entity.id,
                        canonical_chapter_id=chapter_id,
                        is_primary=res.get("is_primary", False),
                        relevance=res["relevance"],
                        source=res["source"],
                        created_by="system"
                    )
                    self.db.add(link)

            # 构造返回信息
            chapter_info = {
                "id": chapter.id,
                "name": chapter.name,
                "outline_code": chapter.outline_code,
                "level": chapter.level,
                "relevance": res["relevance"],
                "source": res["source"]
            }

            if res.get("is_primary"):
                primary = chapter_info
            else:
                related.append(chapter_info)

        await self.db.commit()

        return {
            "linked_count": len(results),
            "primary_chapter": primary,
            "related_chapters": related,
            "strategy_used": strategy_used
        }
