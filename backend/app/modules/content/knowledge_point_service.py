"""Application service for managed knowledge points."""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    EntitySourceLink,
    KnowledgePoint,
    KnowledgePointChapterLink,
    KnowledgeRelation,
    QuestionKnowledgeLink,
)
from app.modules.content.entity_assets import get_entity_assets
from app.modules.content.entity_indexing import rebuild_entity_index
from app.modules.content.entity_serializers import (
    serialize_managed_knowledge_point,
)
from app.modules.retrieval.segment_service import SegmentService


class KnowledgePointService:
    """Manage knowledge points independently from human-review state."""

    INDEX_FIELDS = {
        "subject_id",
        "chapter_id",
        "title",
        "content",
        "difficulty",
        "exam_frequency",
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
        subject_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        difficulty: Optional[str] = None,
        keyword: Optional[str] = None,
        review_status: Optional[str] = None,
        item_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = select(KnowledgePoint).where(
            KnowledgePoint.status != "deleted"
        )
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
            query = query.where(
                KnowledgePoint.review_status == review_status
            )
        if item_status:
            query = query.where(KnowledgePoint.status == item_status)

        total = await self.db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0
        result = await self.db.execute(
            query.order_by(
                KnowledgePoint.created_at.desc(),
                KnowledgePoint.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return {
            "items": [
                serialize_managed_knowledge_point(item, truncate=True)
                for item in result.scalars().all()
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get(self, point_id: str) -> Dict[str, Any]:
        point = await self.db.get(KnowledgePoint, point_id)
        if not point or point.status == "deleted":
            raise HTTPException(status_code=404, detail="知识点不存在")

        data = serialize_managed_knowledge_point(point)
        data["assets"] = await get_entity_assets(
            self.db,
            entity_type="knowledge_point",
            entity_id=point_id,
        )
        return data

    async def update(
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
            return await SegmentService(
                self.db
            ).commit_entity_segment_removal(
                "knowledge_point",
                [point_id],
            )

        await self.db.commit()
        if changed_fields & self.INDEX_FIELDS:
            return await self._rebuild_entity_index(point_id)
        return {"status": "skipped"}

    async def delete(self, point_id: str) -> Dict[str, Any]:
        point = await self.db.get(KnowledgePoint, point_id)
        if not point or point.status == "deleted":
            raise HTTPException(status_code=404, detail="知识点不存在")

        point.status = "deleted"
        await self._delete_dependencies([point_id])
        indexing = await SegmentService(
            self.db
        ).commit_entity_segment_removal(
            "knowledge_point",
            [point_id],
        )
        return {"id": point_id, "indexing": indexing}

    async def batch_delete(self, ids: List[str]) -> Dict[str, Any]:
        unique_ids = list(dict.fromkeys(ids))
        result = await self.db.execute(
            select(KnowledgePoint.id).where(
                KnowledgePoint.id.in_(unique_ids),
                KnowledgePoint.status != "deleted",
            )
        )
        existing_ids = [row[0] for row in result.all()]
        if not existing_ids:
            raise HTTPException(
                status_code=404,
                detail="未找到可删除的知识点",
            )

        await self.db.execute(
            update(KnowledgePoint)
            .where(KnowledgePoint.id.in_(existing_ids))
            .values(status="deleted")
        )
        await self._delete_dependencies(existing_ids)
        indexing = await SegmentService(
            self.db
        ).commit_entity_segment_removal(
            "knowledge_point",
            existing_ids,
        )
        return {
            "deleted_count": len(existing_ids),
            "requested_count": len(unique_ids),
            "indexing": indexing,
        }

    async def _delete_dependencies(self, ids: List[str]) -> None:
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

    async def _rebuild_entity_index(
        self,
        point_id: str,
    ) -> Dict[str, Any]:
        return await rebuild_entity_index(
            self.db,
            "knowledge_point",
            point_id,
        )
