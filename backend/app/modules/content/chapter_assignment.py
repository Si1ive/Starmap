"""Primary canonical-chapter assignment for managed content."""

from typing import Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    KnowledgePoint,
    KnowledgePointChapterLink,
    Question,
    QuestionChapterLink,
)
from app.modules.catalog.chapter_compat import resolve_legacy_chapter_id


class PrimaryChapterAssignmentService:
    """Keep canonical and legacy chapter assignments aligned."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def assign_question(
        self,
        question: Question,
        primary_chapter_id: str,
    ) -> None:
        chapter = await self._get_active_chapter(primary_chapter_id)
        question.primary_chapter_id = chapter.id
        question.subject_id = chapter.subject_id
        question.chapter_id = await resolve_legacy_chapter_id(
            self.db,
            canonical_chapter_id=chapter.id,
            subject_id=chapter.subject_id,
        )
        await self._sync_question_link(question.id, chapter.id)

    async def assign_knowledge_point(
        self,
        point: KnowledgePoint,
        primary_chapter_id: str,
    ) -> None:
        chapter = await self._get_active_chapter(primary_chapter_id)
        point.primary_chapter_id = chapter.id
        point.subject_id = chapter.subject_id
        legacy_chapter_id = await resolve_legacy_chapter_id(
            self.db,
            canonical_chapter_id=chapter.id,
            subject_id=chapter.subject_id,
        )
        if legacy_chapter_id:
            point.chapter_id = legacy_chapter_id
        await self._sync_knowledge_link(point.id, chapter.id)

    async def clear_question(self, question: Question) -> None:
        question.primary_chapter_id = None
        await self._clear_primary_links(QuestionChapterLink, question.id)

    async def _get_active_chapter(self, chapter_id: str) -> CanonicalChapter:
        chapter = await self.db.get(CanonicalChapter, chapter_id)
        if not chapter or chapter.status != "active":
            raise ValueError("所选大纲考点不存在或已停用")
        return chapter

    async def _sync_question_link(
        self,
        question_id: str,
        chapter_id: str,
    ) -> None:
        await self._clear_primary_links(QuestionChapterLink, question_id)
        result = await self.db.execute(
            select(QuestionChapterLink).where(
                QuestionChapterLink.question_id == question_id,
                QuestionChapterLink.canonical_chapter_id == chapter_id,
            )
        )
        link = result.scalar_one_or_none()
        if link:
            link.is_primary = True
            link.source = "manual"
            link.created_by = "admin"
            return

        self.db.add(
            QuestionChapterLink(
                question_id=question_id,
                canonical_chapter_id=chapter_id,
                is_primary=True,
                source="manual",
                created_by="admin",
            )
        )

    async def _sync_knowledge_link(
        self,
        point_id: str,
        chapter_id: str,
    ) -> None:
        await self._clear_primary_links(KnowledgePointChapterLink, point_id)
        result = await self.db.execute(
            select(KnowledgePointChapterLink).where(
                KnowledgePointChapterLink.knowledge_point_id == point_id,
                KnowledgePointChapterLink.canonical_chapter_id == chapter_id,
            )
        )
        link = result.scalar_one_or_none()
        if link:
            link.is_primary = True
            link.source = "manual"
            link.created_by = "admin"
            return

        self.db.add(
            KnowledgePointChapterLink(
                knowledge_point_id=point_id,
                canonical_chapter_id=chapter_id,
                is_primary=True,
                source="manual",
                created_by="admin",
            )
        )

    async def _clear_primary_links(
        self,
        link_model: Union[
            type[QuestionChapterLink],
            type[KnowledgePointChapterLink],
        ],
        entity_id: str,
    ) -> None:
        entity_column = (
            link_model.question_id
            if link_model is QuestionChapterLink
            else link_model.knowledge_point_id
        )
        result = await self.db.execute(
            select(link_model).where(
                entity_column == entity_id,
                link_model.is_primary.is_(True),
            )
        )
        for link in result.scalars().all():
            link.is_primary = False
