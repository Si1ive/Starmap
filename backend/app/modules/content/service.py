"""Application service for question and knowledge-point management."""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    EntitySourceLink,
    KnowledgePoint,
    KnowledgePointChapterLink,
    KnowledgeRelation,
    Question,
    QuestionChapterLink,
    QuestionKnowledgeLink,
)
from app.modules.content.entity_assets import get_entity_assets
from app.modules.retrieval.segment_service import SegmentService

logger = get_logger(__name__)


class ContentService:
    """Manage content independently from its human-review state."""

    KNOWLEDGE_INDEX_FIELDS = {
        "subject_id",
        "chapter_id",
        "title",
        "content",
        "difficulty",
        "exam_frequency",
        "tags",
        "status",
    }
    QUESTION_INDEX_FIELDS = {
        "subject_id",
        "chapter_id",
        "type",
        "content",
        "options",
        "explanation",
        "difficulty",
        "source",
        "exam_year",
        "tags",
        "status",
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_knowledge_points(
        self,
        *,
        page: int,
        page_size: int,
        subject_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        difficulty: Optional[str] = None,
        keyword: Optional[str] = None,
        review_status: Optional[str] = None,
        item_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = select(KnowledgePoint).where(KnowledgePoint.status != "deleted")
        if subject_id:
            query = query.where(KnowledgePoint.subject_id == subject_id)
        if chapter_id:
            query = query.where(
                or_(
                    KnowledgePoint.primary_chapter_id == chapter_id,
                    KnowledgePoint.chapter_id == chapter_id,
                )
            )
        if difficulty:
            query = query.where(KnowledgePoint.difficulty == difficulty)
        if keyword:
            query = query.where(
                or_(
                    KnowledgePoint.title.contains(keyword),
                    KnowledgePoint.content.contains(keyword),
                )
            )
        if review_status:
            query = query.where(KnowledgePoint.review_status == review_status)
        if item_status:
            query = query.where(KnowledgePoint.status == item_status)

        total = await self.db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0
        result = await self.db.execute(
            query.order_by(KnowledgePoint.created_at.desc(), KnowledgePoint.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = result.scalars().all()
        return {
            "items": [self._knowledge_point_to_dict(item, truncate=True) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_knowledge_point(self, point_id: str) -> Dict[str, Any]:
        point = await self.db.get(KnowledgePoint, point_id)
        if not point or point.status == "deleted":
            raise HTTPException(status_code=404, detail="知识点不存在")

        data = self._knowledge_point_to_dict(point)
        data["assets"] = await get_entity_assets(
            self.db,
            entity_type="knowledge_point",
            entity_id=point_id,
        )
        return data

    async def update_knowledge_point(
        self,
        point_id: str,
        changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        point = await self.db.get(KnowledgePoint, point_id)
        if not point or point.status == "deleted":
            raise HTTPException(status_code=404, detail="知识点不存在")

        changed_fields = {
            field
            for field, value in changes.items()
            if getattr(point, field) != value
        }
        for field, value in changes.items():
            setattr(point, field, value)

        if point.status != "active":
            return await SegmentService(self.db).commit_entity_segment_removal(
                "knowledge_point",
                [point_id],
            )

        await self.db.commit()
        if changed_fields & self.KNOWLEDGE_INDEX_FIELDS:
            return await self._rebuild_entity_index("knowledge_point", point_id)
        return {"status": "skipped"}

    async def delete_knowledge_point(self, point_id: str) -> Dict[str, Any]:
        point = await self.db.get(KnowledgePoint, point_id)
        if not point or point.status == "deleted":
            raise HTTPException(status_code=404, detail="知识点不存在")

        point.status = "deleted"
        await self._delete_knowledge_dependencies([point_id])
        indexing = await SegmentService(self.db).commit_entity_segment_removal(
            "knowledge_point",
            [point_id],
        )
        return {"id": point_id, "indexing": indexing}

    async def batch_delete_knowledge_points(self, ids: List[str]) -> Dict[str, Any]:
        unique_ids = list(dict.fromkeys(ids))
        result = await self.db.execute(
            select(KnowledgePoint.id).where(
                KnowledgePoint.id.in_(unique_ids),
                KnowledgePoint.status != "deleted",
            )
        )
        existing_ids = [row[0] for row in result.all()]
        if not existing_ids:
            raise HTTPException(status_code=404, detail="未找到可删除的知识点")

        await self.db.execute(
            update(KnowledgePoint)
            .where(KnowledgePoint.id.in_(existing_ids))
            .values(status="deleted")
        )
        await self._delete_knowledge_dependencies(existing_ids)
        indexing = await SegmentService(self.db).commit_entity_segment_removal(
            "knowledge_point",
            existing_ids,
        )
        return {
            "deleted_count": len(existing_ids),
            "requested_count": len(unique_ids),
            "indexing": indexing,
        }

    async def list_questions(
        self,
        *,
        page: int,
        page_size: int,
        subject_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        question_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        exam_scope: Optional[str] = None,
        exam_year: Optional[int] = None,
        keyword: Optional[str] = None,
        review_status: Optional[str] = None,
        item_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = select(Question).where(Question.status != "deleted")
        if subject_id:
            query = query.where(Question.subject_id == subject_id)
        if chapter_id:
            query = query.where(
                or_(
                    Question.primary_chapter_id == chapter_id,
                    Question.chapter_id == chapter_id,
                )
            )
        if question_type:
            query = query.where(Question.type == question_type)
        if difficulty:
            query = query.where(Question.difficulty == difficulty)
        if exam_scope:
            query = query.where(Question.exam_scope == exam_scope)
        if exam_year is not None:
            query = query.where(Question.exam_year == exam_year)
        if keyword:
            query = query.where(Question.content.contains(keyword))
        if review_status:
            query = query.where(Question.review_status == review_status)
        if item_status:
            query = query.where(Question.status == item_status)

        total = await self.db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0
        result = await self.db.execute(
            query.order_by(Question.created_at.desc(), Question.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = result.scalars().all()
        return {
            "items": [self._question_to_dict(item, truncate=True) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_question(self, question_id: str) -> Dict[str, Any]:
        question = await self.db.get(Question, question_id)
        if not question or question.status == "deleted":
            raise HTTPException(status_code=404, detail="题目不存在")

        data = self._question_to_dict(question)
        data["assets"] = await get_entity_assets(
            self.db,
            entity_type="question",
            entity_id=question_id,
        )
        rows = (
            await self.db.execute(
                select(
                    KnowledgePoint.id,
                    KnowledgePoint.title,
                    QuestionKnowledgeLink.relevance,
                )
                .join(
                    QuestionKnowledgeLink,
                    QuestionKnowledgeLink.knowledge_point_id == KnowledgePoint.id,
                )
                .where(QuestionKnowledgeLink.question_id == question_id)
                .order_by(QuestionKnowledgeLink.relevance.desc())
            )
        ).all()
        data["knowledge_points"] = [
            {
                "id": row[0],
                "title": row[1],
                "relevance": float(row[2] or 0),
            }
            for row in rows
        ]
        return data

    async def update_question(
        self,
        question_id: str,
        changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        question = await self.db.get(Question, question_id)
        if not question or question.status == "deleted":
            raise HTTPException(status_code=404, detail="题目不存在")

        changed_fields = {
            field
            for field, value in changes.items()
            if getattr(question, field) != value
        }
        for field, value in changes.items():
            setattr(question, field, value)

        if question.status != "active":
            return await SegmentService(self.db).commit_entity_segment_removal(
                "question",
                [question_id],
            )

        await self.db.commit()
        if changed_fields & self.QUESTION_INDEX_FIELDS:
            return await self._rebuild_entity_index("question", question_id)
        return {"status": "skipped"}

    async def delete_question(self, question_id: str) -> Dict[str, Any]:
        question = await self.db.get(Question, question_id)
        if not question or question.status == "deleted":
            raise HTTPException(status_code=404, detail="题目不存在")

        question.status = "deleted"
        await self._delete_question_dependencies([question_id])
        indexing = await SegmentService(self.db).commit_entity_segment_removal(
            "question",
            [question_id],
        )
        return {"id": question_id, "indexing": indexing}

    async def batch_delete_questions(self, ids: List[str]) -> Dict[str, Any]:
        unique_ids = list(dict.fromkeys(ids))
        result = await self.db.execute(
            select(Question.id).where(
                Question.id.in_(unique_ids),
                Question.status != "deleted",
            )
        )
        existing_ids = [row[0] for row in result.all()]
        if not existing_ids:
            raise HTTPException(status_code=404, detail="未找到可删除的题目")

        await self.db.execute(
            update(Question)
            .where(Question.id.in_(existing_ids))
            .values(status="deleted")
        )
        await self._delete_question_dependencies(existing_ids)
        indexing = await SegmentService(self.db).commit_entity_segment_removal(
            "question",
            existing_ids,
        )
        return {
            "deleted_count": len(existing_ids),
            "requested_count": len(unique_ids),
            "indexing": indexing,
        }

    async def _delete_knowledge_dependencies(self, ids: List[str]) -> None:
        await self.db.execute(
            delete(KnowledgePointChapterLink).where(
                KnowledgePointChapterLink.knowledge_point_id.in_(ids)
            )
        )
        await self.db.execute(
            delete(QuestionKnowledgeLink).where(
                QuestionKnowledgeLink.knowledge_point_id.in_(ids)
            )
        )
        await self.db.execute(
            delete(KnowledgeRelation).where(
                or_(
                    KnowledgeRelation.source_knowledge_id.in_(ids),
                    KnowledgeRelation.target_knowledge_id.in_(ids),
                )
            )
        )
        await self.db.execute(
            delete(EntitySourceLink).where(
                EntitySourceLink.entity_type == "knowledge_point",
                EntitySourceLink.entity_id.in_(ids),
            )
        )

    async def _delete_question_dependencies(self, ids: List[str]) -> None:
        await self.db.execute(
            delete(QuestionChapterLink).where(
                QuestionChapterLink.question_id.in_(ids)
            )
        )
        await self.db.execute(
            delete(QuestionKnowledgeLink).where(
                QuestionKnowledgeLink.question_id.in_(ids)
            )
        )
        await self.db.execute(
            delete(EntitySourceLink).where(
                EntitySourceLink.entity_type == "question",
                EntitySourceLink.entity_id.in_(ids),
            )
        )

    async def _rebuild_entity_index(
        self,
        entity_type: str,
        entity_id: str,
    ) -> Dict[str, Any]:
        try:
            result = await SegmentService(self.db).rebuild_entity_segments(
                entity_type,
                entity_id,
            )
        except Exception as exc:
            await self.db.rollback()
            logger.exception(
                "内容编辑后的索引重建失败",
                entity_type=entity_type,
                entity_id=entity_id,
                error=str(exc),
            )
            return {
                "status": "failed",
                "error": str(exc)[:500],
            }

        status = "warning" if result.get("cleanup_warning") else "success"
        return {"status": status, **result}

    @staticmethod
    def _knowledge_point_to_dict(
        point: KnowledgePoint,
        *,
        truncate: bool = False,
    ) -> Dict[str, Any]:
        content = point.content or ""
        return {
            "id": point.id,
            "chapter_id": point.chapter_id,
            "subject_id": point.subject_id,
            "primary_chapter_id": point.primary_chapter_id,
            "source_document_id": point.source_document_id,
            "source_section_path": point.source_section_path,
            "title": point.title,
            "canonical_title": point.canonical_title,
            "content": content[:200] if truncate else content,
            "difficulty": point.difficulty,
            "exam_frequency": point.exam_frequency,
            "topic_terms": point.topic_terms,
            "aliases": point.aliases,
            "tags": point.tags,
            "key_points": point.key_points,
            "related_point_ids": point.related_point_ids,
            "summary": point.summary,
            "source": point.source,
            "source_page": point.source_page,
            "review_status": point.review_status,
            "review_notes": point.review_notes,
            "reviewed_by": point.reviewed_by,
            "reviewed_at": point.reviewed_at.isoformat() if point.reviewed_at else None,
            "status": point.status,
            "created_at": point.created_at.isoformat() if point.created_at else None,
            "updated_at": point.updated_at.isoformat() if point.updated_at else None,
        }

    @staticmethod
    def _question_to_dict(
        question: Question,
        *,
        truncate: bool = False,
    ) -> Dict[str, Any]:
        content = question.content or ""
        explanation = question.explanation or ""
        return {
            "id": question.id,
            "subject_id": question.subject_id,
            "chapter_id": question.chapter_id,
            "primary_chapter_id": question.primary_chapter_id,
            "source_document_id": question.source_document_id,
            "source_section_path": question.source_section_path,
            "type": question.type,
            "content": content[:200] if truncate else content,
            "options": question.options,
            "answer": question.answer,
            "explanation": explanation[:300] if truncate else explanation,
            "answer_source": question.answer_source,
            "explanation_source": question.explanation_source,
            "enrich_status": question.enrich_status,
            "difficulty": question.difficulty,
            "source": question.source,
            "exam_scope": question.exam_scope,
            "exam_year": question.exam_year,
            "paper_name": question.paper_name,
            "question_no": question.question_no,
            "topic_terms": question.topic_terms,
            "knowledge_point_ids": question.knowledge_point_ids,
            "tags": question.tags,
            "extraction_meta": question.extraction_meta,
            "review_status": question.review_status,
            "review_notes": question.review_notes,
            "reviewed_by": question.reviewed_by,
            "reviewed_at": question.reviewed_at.isoformat() if question.reviewed_at else None,
            "status": question.status,
            "created_at": question.created_at.isoformat() if question.created_at else None,
            "updated_at": question.updated_at.isoformat() if question.updated_at else None,
        }
