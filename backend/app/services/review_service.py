"""
审核服务

统一处理知识点、题目、章节映射、关系的审核操作。
"""

from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from app.models.mysql_models import (
    KnowledgePoint, Question, DocumentSectionMapping, CanonicalChapter,
    KnowledgeRelation, KnowledgePointChapterLink, QuestionChapterLink,
    RetrievalSegment
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id

logger = get_logger(__name__)


class ReviewService:
    """审核服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== 知识点审核 ==========

    async def get_knowledge_points_for_review(
        self,
        subject_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        review_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取待审核的知识点列表"""
        query = select(KnowledgePoint)
        count_query = select(func.count()).select_from(KnowledgePoint)

        conditions = []
        conditions.append(KnowledgePoint.status != "deleted")
        if subject_id:
            conditions.append(KnowledgePoint.subject_id == subject_id)
        if chapter_id:
            conditions.append(
                or_(
                    KnowledgePoint.primary_chapter_id == chapter_id,
                    KnowledgePoint.chapter_id == chapter_id,
                )
            )
        if review_status:
            conditions.append(KnowledgePoint.review_status == review_status)
            if review_status == "pending":
                conditions.append(KnowledgePoint.status == "pending")
            elif review_status == "approved":
                conditions.append(KnowledgePoint.status == "active")

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = await self.db.scalar(count_query) or 0

        query = query.order_by(KnowledgePoint.created_at.desc(), KnowledgePoint.id.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        items = result.scalars().all()

        return {
            "items": [self._knowledge_point_to_dict(kp) for kp in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def review_knowledge_point(
        self,
        knowledge_point_id: str,
        review_status: str,
        review_notes: Optional[str] = None,
        reviewed_by: Optional[str] = None,
        primary_chapter_id: Optional[str] = None,
        topic_terms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """审核知识点"""
        result = await self.db.execute(
            select(KnowledgePoint).where(KnowledgePoint.id == knowledge_point_id)
        )
        kp = result.scalar_one_or_none()

        if not kp:
            raise ValueError(f"知识点不存在: {knowledge_point_id}")

        # 更新章节归属
        if primary_chapter_id and primary_chapter_id != kp.primary_chapter_id:
            canonical_chapter = await self.db.get(CanonicalChapter, primary_chapter_id)
            kp.primary_chapter_id = primary_chapter_id
            if canonical_chapter and canonical_chapter.subject_id:
                kp.subject_id = canonical_chapter.subject_id
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=kp.subject_id,
            )
            if legacy_chapter_id:
                kp.chapter_id = legacy_chapter_id

            # 更新章节关联
            await self._update_chapter_links(
                "knowledge_point", knowledge_point_id, primary_chapter_id
            )

            # 标记需要重建 segment
            await self._mark_segment_rebuild("knowledge_point", knowledge_point_id)

        # 更新主题术语
        if topic_terms is not None:
            kp.topic_terms = topic_terms

        kp.review_status = review_status
        if review_status == "approved":
            kp.status = "active"
        else:
            kp.status = "pending"
        kp.review_notes = review_notes

        await self.db.commit()

        # 审核通过 → 自动富化（LLM 生成摘要/别名/要点）。未配置 enrich_llm 时优雅降级，不阻塞审核。
        enrich_result = None
        chapter_link_result = None
        if review_status == "approved":
            try:
                from app.services.enrichment_service import EnrichmentService
                enrich_result = await EnrichmentService(self.db).enrich_knowledge_point(knowledge_point_id)
            except Exception as e:
                logger.warning("知识点审核后富化失败，不影响审核", knowledge_point_id=knowledge_point_id, error=str(e))

            # 自动关联大纲章节（富化后执行，利用富化生成的 summary 提升匹配准确率）
            try:
                from app.services.chapter_link_service import ChapterLinkService
                chapter_link_result = await ChapterLinkService(self.db).link_knowledge_point_to_chapters(knowledge_point_id)
                logger.info("知识点自动关联章节", knowledge_point_id=knowledge_point_id,
                           linked_count=chapter_link_result.get("linked_count", 0),
                           strategy=chapter_link_result.get("strategy_used"))
            except Exception as e:
                logger.warning("知识点自动关联章节失败，不影响审核", knowledge_point_id=knowledge_point_id, error=str(e))

        logger.info(
            "知识点审核完成",
            knowledge_point_id=knowledge_point_id,
            review_status=review_status,
        )

        return {
            "id": knowledge_point_id,
            "review_status": review_status,
            "enrich": enrich_result,
            "chapter_link": chapter_link_result,
        }

    # ========== 题目审核 ==========

    async def get_questions_for_review(
        self,
        subject_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        exam_scope: Optional[str] = None,
        exam_year: Optional[int] = None,
        question_type: Optional[str] = None,
        review_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取待审核的题目列表"""
        query = select(Question)
        count_query = select(func.count()).select_from(Question)

        conditions = []
        conditions.append(Question.status != "deleted")
        if subject_id:
            conditions.append(Question.subject_id == subject_id)
        if chapter_id:
            conditions.append(
                or_(
                    Question.primary_chapter_id == chapter_id,
                    Question.chapter_id == chapter_id,
                )
            )
        if exam_scope:
            conditions.append(Question.exam_scope == exam_scope)
        if exam_year:
            conditions.append(Question.exam_year == exam_year)
        if question_type:
            conditions.append(Question.type == question_type)
        if review_status:
            conditions.append(Question.review_status == review_status)
            if review_status == "pending":
                conditions.append(Question.status == "pending")
            elif review_status == "approved":
                conditions.append(Question.status == "active")

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = await self.db.scalar(count_query) or 0

        query = query.order_by(Question.created_at.desc(), Question.id.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        items = result.scalars().all()

        return {
            "items": [self._question_to_dict(q) for q in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def review_question(
        self,
        question_id: str,
        review_status: str,
        review_notes: Optional[str] = None,
        reviewed_by: Optional[str] = None,
        primary_chapter_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """审核题目"""
        result = await self.db.execute(
            select(Question).where(Question.id == question_id)
        )
        q = result.scalar_one_or_none()

        if not q:
            raise ValueError(f"题目不存在: {question_id}")

        # 更新章节归属
        if primary_chapter_id and primary_chapter_id != q.primary_chapter_id:
            canonical_chapter = await self.db.get(CanonicalChapter, primary_chapter_id)
            q.primary_chapter_id = primary_chapter_id
            if canonical_chapter and canonical_chapter.subject_id:
                q.subject_id = canonical_chapter.subject_id
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=q.subject_id,
            )
            if legacy_chapter_id:
                q.chapter_id = legacy_chapter_id

            # 更新章节关联
            await self._update_chapter_links(
                "question", question_id, primary_chapter_id
            )

            # 标记需要重建 segment
            await self._mark_segment_rebuild("question", question_id)

        q.review_status = review_status
        if review_status == "approved":
            q.status = "active"
        else:
            q.status = "pending"
        q.review_notes = review_notes

        await self.db.commit()

        # 审核通过 → 自动富化（答案/解析 + 考点回连知识点）。未配置 enrich_llm 时优雅降级。
        enrich_result = None
        chapter_link_result = None
        if review_status == "approved":
            try:
                from app.services.enrichment_service import EnrichmentService
                enrich_result = await EnrichmentService(self.db).enrich_question(question_id)
            except Exception as e:
                logger.warning("题目审核后富化失败，不影响审核", question_id=question_id, error=str(e))

            # 自动关联大纲章节
            try:
                from app.services.chapter_link_service import ChapterLinkService
                chapter_link_result = await ChapterLinkService(self.db).link_question_to_chapters(question_id)
                logger.info("题目自动关联章节", question_id=question_id,
                           linked_count=chapter_link_result.get("linked_count", 0),
                           strategy=chapter_link_result.get("strategy_used"))
            except Exception as e:
                logger.warning("题目自动关联章节失败，不影响审核", question_id=question_id, error=str(e))

        logger.info(
            "题目审核完成",
            question_id=question_id,
            review_status=review_status,
        )

        return {
            "id": question_id,
            "review_status": review_status,
            "enrich": enrich_result,
            "chapter_link": chapter_link_result,
        }

    # ========== 关系审核 ==========

    async def get_relations_for_review(
        self,
        relation_type: Optional[str] = None,
        review_status: Optional[str] = None,
        subject_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取待审核的关系列表"""
        source_kp = aliased(KnowledgePoint)
        target_kp = aliased(KnowledgePoint)
        query = (
            select(
                KnowledgeRelation,
                source_kp.title.label("source_title"),
                target_kp.title.label("target_title"),
            )
            .join(
                source_kp,
                KnowledgeRelation.source_knowledge_id == source_kp.id,
            )
            .join(
                target_kp,
                KnowledgeRelation.target_knowledge_id == target_kp.id,
            )
        )
        count_query = (
            select(func.count())
            .select_from(KnowledgeRelation)
            .join(source_kp, KnowledgeRelation.source_knowledge_id == source_kp.id)
            .join(target_kp, KnowledgeRelation.target_knowledge_id == target_kp.id)
        )

        conditions = []
        if relation_type:
            conditions.append(KnowledgeRelation.relation_type == relation_type)
        if review_status:
            conditions.append(KnowledgeRelation.review_status == review_status)
        if subject_id:
            conditions.append(
                or_(
                    source_kp.subject_id == subject_id,
                    target_kp.subject_id == subject_id,
                )
            )

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = await self.db.scalar(count_query) or 0

        query = query.order_by(KnowledgeRelation.created_at.desc(), KnowledgeRelation.id.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        rows = result.all()

        items = []
        for relation, source_title, target_title in rows:
            items.append({
                "id": relation.id,
                "relation_id": relation.id,
                "relation_type": relation.relation_type,
                "directionality": relation.directionality,
                "source_knowledge_id": relation.source_knowledge_id,
                "source_knowledge_title": source_title,
                "source_title": source_title,
                "target_knowledge_id": relation.target_knowledge_id,
                "target_knowledge_title": target_title,
                "target_title": target_title,
                "evidence_text": relation.evidence_text,
                "evidence_page": relation.evidence_page,
                "confidence": float(relation.confidence) if relation.confidence else None,
                "source_type": relation.source_type,
                "review_status": relation.review_status,
                "review_notes": relation.review_notes,
                "created_at": relation.created_at.isoformat() if relation.created_at else None,
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def review_relation(
        self,
        relation_id: str,
        review_status: str,
        relation_type: Optional[str] = None,
        directionality: Optional[str] = None,
        review_notes: Optional[str] = None,
        reviewed_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """审核关系"""
        result = await self.db.execute(
            select(KnowledgeRelation).where(KnowledgeRelation.id == relation_id)
        )
        relation = result.scalar_one_or_none()

        if not relation:
            raise ValueError(f"关系不存在: {relation_id}")

        # 修改关系类型或方向后自动回到 pending
        if relation_type and relation_type != relation.relation_type:
            relation.relation_type = relation_type
            if review_status != "pending":
                review_status = "pending"  # 强制回到待审

        if directionality and directionality != relation.directionality:
            relation.directionality = directionality
            if review_status != "pending":
                review_status = "pending"  # 强制回到待审

        relation.review_status = review_status
        relation.review_notes = review_notes
        relation.reviewed_by = reviewed_by
        relation.reviewed_at = datetime.utcnow()

        await self.db.commit()

        logger.info(
            "关系审核完成",
            relation_id=relation_id,
            review_status=review_status,
        )

        return {
            "id": relation_id,
            "review_status": review_status,
            "relation_type": relation.relation_type,
        }

    # ========== 统计 ==========

    async def get_review_stats(self, subject_id: Optional[str] = None) -> Dict[str, Any]:
        """获取审核统计"""
        stats = {}

        # 知识点统计
        kp_query = select(
            KnowledgePoint.review_status,
            func.count().label('count')
        ).group_by(KnowledgePoint.review_status)
        if subject_id:
            kp_query = kp_query.where(KnowledgePoint.subject_id == subject_id)

        result = await self.db.execute(kp_query)
        stats['knowledge_points'] = {row[0]: row[1] for row in result.all()}

        # 题目统计
        q_query = select(
            Question.review_status,
            func.count().label('count')
        ).group_by(Question.review_status)
        if subject_id:
            q_query = q_query.where(Question.subject_id == subject_id)

        result = await self.db.execute(q_query)
        stats['questions'] = {row[0]: row[1] for row in result.all()}

        # 关系统计
        r_query = select(
            KnowledgeRelation.review_status,
            func.count().label('count')
        ).group_by(KnowledgeRelation.review_status)
        result = await self.db.execute(r_query)
        stats['relations'] = {row[0]: row[1] for row in result.all()}

        # 映射统计
        m_query = select(
            DocumentSectionMapping.review_status,
            func.count().label('count')
        ).group_by(DocumentSectionMapping.review_status)
        result = await self.db.execute(m_query)
        stats['section_mappings'] = {row[0]: row[1] for row in result.all()}

        return stats

    # ========== 辅助方法 ==========

    async def _update_chapter_links(
        self,
        entity_type: str,
        entity_id: str,
        primary_chapter_id: str,
    ):
        """更新章节关联"""
        if entity_type == "knowledge_point":
            # 删除旧的主章节标记
            result = await self.db.execute(
                select(KnowledgePointChapterLink).where(
                    and_(
                        KnowledgePointChapterLink.knowledge_point_id == entity_id,
                        KnowledgePointChapterLink.is_primary == True,
                    )
                )
            )
            old_link = result.scalar_one_or_none()
            if old_link:
                old_link.is_primary = False

            # 创建或更新新的主章节关联
            result = await self.db.execute(
                select(KnowledgePointChapterLink).where(
                    and_(
                        KnowledgePointChapterLink.knowledge_point_id == entity_id,
                        KnowledgePointChapterLink.canonical_chapter_id == primary_chapter_id,
                    )
                )
            )
            link = result.scalar_one_or_none()
            if link:
                link.is_primary = True
            else:
                link = KnowledgePointChapterLink(
                    knowledge_point_id=entity_id,
                    canonical_chapter_id=primary_chapter_id,
                    is_primary=True,
                )
                self.db.add(link)

        elif entity_type == "question":
            # 类似处理题目
            result = await self.db.execute(
                select(QuestionChapterLink).where(
                    and_(
                        QuestionChapterLink.question_id == entity_id,
                        QuestionChapterLink.is_primary == True,
                    )
                )
            )
            old_link = result.scalar_one_or_none()
            if old_link:
                old_link.is_primary = False

            result = await self.db.execute(
                select(QuestionChapterLink).where(
                    and_(
                        QuestionChapterLink.question_id == entity_id,
                        QuestionChapterLink.canonical_chapter_id == primary_chapter_id,
                    )
                )
            )
            link = result.scalar_one_or_none()
            if link:
                link.is_primary = True
            else:
                link = QuestionChapterLink(
                    question_id=entity_id,
                    canonical_chapter_id=primary_chapter_id,
                    is_primary=True,
                )
                self.db.add(link)

    async def _mark_segment_rebuild(self, entity_type: str, entity_id: str):
        """标记需要重建 segment"""
        result = await self.db.execute(
            select(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == entity_type,
                    RetrievalSegment.entity_id == entity_id,
                )
            )
        )
        segments = result.scalars().all()

        for segment in segments:
            # 标记需要重建（可以删除或设置状态）
            await self.db.delete(segment)

    def _knowledge_point_to_dict(self, kp: KnowledgePoint) -> Dict[str, Any]:
        return {
            "id": kp.id,
            "subject_id": kp.subject_id,
            "chapter_id": kp.chapter_id,
            "primary_chapter_id": kp.primary_chapter_id,
            "source_document_id": kp.source_document_id,
            "title": kp.title,
            "canonical_title": kp.canonical_title,
            "content": kp.content[:500] if kp.content else None,  # 截断
            "difficulty": kp.difficulty,
            "exam_frequency": kp.exam_frequency,
            "topic_terms": kp.topic_terms,
            "aliases": kp.aliases,
            "tags": kp.tags,
            "key_points": kp.key_points,
            "related_point_ids": kp.related_point_ids,
            "review_status": kp.review_status,
            "review_notes": kp.review_notes,
            "status": kp.status,
            "created_at": kp.created_at.isoformat() if kp.created_at else None,
            "updated_at": kp.updated_at.isoformat() if kp.updated_at else None,
        }

    def _question_to_dict(self, q: Question) -> Dict[str, Any]:
        return {
            "id": q.id,
            "subject_id": q.subject_id,
            "chapter_id": q.chapter_id,
            "primary_chapter_id": q.primary_chapter_id,
            "source_document_id": q.source_document_id,
            "type": q.type,
            "content": q.content[:500] if q.content else None,  # 截断
            "options": q.options,
            "answer": q.answer,
            "explanation": q.explanation[:300] if q.explanation else None,
            "difficulty": q.difficulty,
            "source": q.source,
            "exam_scope": q.exam_scope,
            "exam_year": q.exam_year,
            "paper_name": q.paper_name,
            "question_no": q.question_no,
            "topic_terms": q.topic_terms,
            "knowledge_point_ids": q.knowledge_point_ids,
            "review_status": q.review_status,
            "review_notes": q.review_notes,
            "status": q.status,
            "created_at": q.created_at.isoformat() if q.created_at else None,
            "updated_at": q.updated_at.isoformat() if q.updated_at else None,
        }
