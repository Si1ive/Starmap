"""
题目、知识点与关系审核服务

统一处理知识点、题目、章节映射、关系的审核操作。
"""

from datetime import UTC, datetime
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from app.models.mysql_models import (
    DocumentSectionMapping,
    KnowledgePoint,
    KnowledgeRelation,
    Question,
)
from app.modules.content.chapter_assignment import (
    PrimaryChapterAssignmentService,
)
from app.modules.content.entity_indexing import rebuild_entity_index
from app.modules.content.entity_serializers import (
    serialize_review_knowledge_point,
    serialize_review_question,
)

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

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = await self.db.scalar(count_query) or 0

        query = query.order_by(KnowledgePoint.created_at.desc(), KnowledgePoint.id.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        items = result.scalars().all()

        return {
            "items": [serialize_review_knowledge_point(kp) for kp in items],
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

        should_rebuild_index = False

        # 更新章节归属
        if primary_chapter_id and primary_chapter_id != kp.primary_chapter_id:
            should_rebuild_index = True
            await PrimaryChapterAssignmentService(
                self.db
            ).assign_knowledge_point(
                kp,
                primary_chapter_id,
            )

        # 更新主题术语
        if topic_terms is not None:
            should_rebuild_index = should_rebuild_index or topic_terms != (kp.topic_terms or [])
            kp.topic_terms = topic_terms

        kp.review_status = review_status
        kp.review_notes = review_notes
        kp.reviewed_by = reviewed_by
        kp.reviewed_at = datetime.now(UTC).replace(tzinfo=None)

        await self.db.commit()
        indexing = (
            await self._rebuild_entity_index("knowledge_point", knowledge_point_id)
            if should_rebuild_index
            else {"status": "skipped"}
        )

        logger.info(
            "知识点审核完成",
            knowledge_point_id=knowledge_point_id,
            review_status=review_status,
            indexing_status=indexing["status"],
        )

        return {
            "id": knowledge_point_id,
            "review_status": review_status,
            "status": kp.status,
            "reviewed_at": kp.reviewed_at.isoformat(),
            "indexing": indexing,
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

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = await self.db.scalar(count_query) or 0

        query = query.order_by(Question.created_at.desc(), Question.id.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        items = result.scalars().all()

        return {
            "items": [serialize_review_question(q) for q in items],
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

        should_rebuild_index = False

        # 更新章节归属
        if primary_chapter_id and primary_chapter_id != q.primary_chapter_id:
            should_rebuild_index = True
            await PrimaryChapterAssignmentService(self.db).assign_question(
                q,
                primary_chapter_id,
            )

        q.review_status = review_status
        q.review_notes = review_notes
        q.reviewed_by = reviewed_by
        q.reviewed_at = datetime.now(UTC).replace(tzinfo=None)

        await self.db.commit()
        indexing = (
            await self._rebuild_entity_index("question", question_id)
            if should_rebuild_index
            else {"status": "skipped"}
        )

        logger.info(
            "题目审核完成",
            question_id=question_id,
            review_status=review_status,
            indexing_status=indexing["status"],
        )

        return {
            "id": question_id,
            "review_status": review_status,
            "status": q.status,
            "reviewed_at": q.reviewed_at.isoformat(),
            "indexing": indexing,
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

    async def _rebuild_entity_index(
        self,
        entity_type: str,
        entity_id: str,
    ) -> Dict[str, Any]:
        """审核已落库后增量重建索引，失败不回滚人工审核。"""
        return await rebuild_entity_index(
            self.db,
            entity_type,
            entity_id,
        )
