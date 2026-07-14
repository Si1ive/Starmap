"""Application service for managed questions."""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    EntitySourceLink,
    KnowledgePoint,
    Question,
    QuestionChapterLink,
    QuestionKnowledgeLink,
)
from app.modules.content.chapter_assignment import (
    PrimaryChapterAssignmentService,
)
from app.modules.content.entity_assets import get_entity_assets
from app.modules.content.entity_indexing import rebuild_entity_index
from app.modules.content.entity_serializers import serialize_managed_question
from app.modules.retrieval.segment_service import SegmentService

_UNSET = object()


class QuestionService:
    """Manage questions independently from human-review state."""

    INDEX_FIELDS = {
        "subject_id",
        "chapter_id",
        "primary_chapter_id",
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

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        question_id: Optional[str] = None,
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
        if question_id:
            query = query.where(Question.id == question_id)
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
            query.order_by(
                Question.created_at.desc(),
                Question.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return {
            "items": [
                serialize_managed_question(item, truncate=True)
                for item in result.scalars().all()
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get(self, question_id: str) -> Dict[str, Any]:
        question = await self.db.get(Question, question_id)
        if not question or question.status == "deleted":
            raise HTTPException(status_code=404, detail="题目不存在")

        data = serialize_managed_question(question)
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
                    QuestionKnowledgeLink.knowledge_point_id
                    == KnowledgePoint.id,
                )
                .where(
                    QuestionKnowledgeLink.question_id == question_id
                )
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

    async def update(
        self,
        question_id: str,
        changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        question = await self.db.get(Question, question_id)
        if not question or question.status == "deleted":
            raise HTTPException(status_code=404, detail="题目不存在")

        changes = dict(changes)
        primary_chapter_id = changes.pop("primary_chapter_id", _UNSET)
        changed_fields = {
            field
            for field, value in changes.items()
            if getattr(question, field) != value
        }
        for field, value in changes.items():
            setattr(question, field, value)

        assignment_fields_changed = bool(
            changed_fields & {"subject_id", "chapter_id"}
        )
        assignment_target = primary_chapter_id
        if (
            assignment_target is _UNSET
            and assignment_fields_changed
            and question.primary_chapter_id
        ):
            assignment_target = question.primary_chapter_id

        if assignment_target is not _UNSET and (
            assignment_target != question.primary_chapter_id
            or assignment_fields_changed
        ):
            assignment_service = PrimaryChapterAssignmentService(self.db)
            try:
                if assignment_target is None:
                    await assignment_service.clear_question(question)
                else:
                    await assignment_service.assign_question(
                        question,
                        assignment_target,
                    )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=str(exc),
                ) from exc
            changed_fields.update({
                "primary_chapter_id",
                "subject_id",
                "chapter_id",
            })

        if question.status != "active":
            return await SegmentService(
                self.db
            ).commit_entity_segment_removal(
                "question",
                [question_id],
            )

        await self.db.commit()
        if changed_fields & self.INDEX_FIELDS:
            return await self._rebuild_entity_index(question_id)
        return {"status": "skipped"}

    async def delete(self, question_id: str) -> Dict[str, Any]:
        question = await self.db.get(Question, question_id)
        if not question or question.status == "deleted":
            raise HTTPException(status_code=404, detail="题目不存在")

        question.status = "deleted"
        await self._delete_dependencies([question_id])
        indexing = await SegmentService(
            self.db
        ).commit_entity_segment_removal(
            "question",
            [question_id],
        )
        return {"id": question_id, "indexing": indexing}

    async def batch_delete(self, ids: List[str]) -> Dict[str, Any]:
        unique_ids = list(dict.fromkeys(ids))
        result = await self.db.execute(
            select(Question.id).where(
                Question.id.in_(unique_ids),
                Question.status != "deleted",
            )
        )
        existing_ids = [row[0] for row in result.all()]
        if not existing_ids:
            raise HTTPException(
                status_code=404,
                detail="未找到可删除的题目",
            )

        await self.db.execute(
            update(Question)
            .where(Question.id.in_(existing_ids))
            .values(status="deleted")
        )
        await self._delete_dependencies(existing_ids)
        indexing = await SegmentService(
            self.db
        ).commit_entity_segment_removal(
            "question",
            existing_ids,
        )
        return {
            "deleted_count": len(existing_ids),
            "requested_count": len(unique_ids),
            "indexing": indexing,
        }

    async def _delete_dependencies(self, ids: List[str]) -> None:
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
        question_id: str,
    ) -> Dict[str, Any]:
        return await rebuild_entity_index(
            self.db,
            "question",
            question_id,
        )
