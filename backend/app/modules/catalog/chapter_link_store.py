"""知识点与题目的标准章节关联持久化。"""

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    KnowledgePointChapterLink,
    QuestionChapterLink,
)


class ChapterLinkStore:
    """Create or update automatic chapter links for corpus entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_links(
        self,
        entity: Any,
        entity_type: str,
        results: List[Dict[str, Any]],
        strategy_used: str,
    ) -> Dict[str, Any]:
        """Persist chapter candidates and assemble the public result."""
        primary = None
        related = []

        for result in results:
            chapter_id = result["chapter_id"]
            chapter = await self.db.get(CanonicalChapter, chapter_id)
            if not chapter or chapter.status != "active":
                continue

            if entity_type == "knowledge_point":
                await self._save_knowledge_point_link(
                    entity.id,
                    chapter_id,
                    result,
                )
            else:
                await self._save_question_link(
                    entity.id,
                    chapter_id,
                    result,
                )

            chapter_info = {
                "id": chapter.id,
                "name": chapter.name,
                "outline_code": chapter.outline_code,
                "level": chapter.level,
                "relevance": result["relevance"],
                "source": result["source"],
            }
            if result.get("is_primary"):
                primary = chapter_info
            else:
                related.append(chapter_info)

        await self.db.commit()

        return {
            "linked_count": len(results),
            "primary_chapter": primary,
            "related_chapters": related,
            "strategy_used": strategy_used,
        }

    async def _save_knowledge_point_link(
        self,
        knowledge_point_id: str,
        chapter_id: str,
        result: Dict[str, Any],
    ) -> None:
        existing_link = (
            await self.db.execute(
                select(KnowledgePointChapterLink).where(
                    KnowledgePointChapterLink.knowledge_point_id
                    == knowledge_point_id,
                    KnowledgePointChapterLink.canonical_chapter_id
                    == chapter_id,
                )
            )
        ).scalar_one_or_none()
        if existing_link:
            self._update_link(existing_link, result)
            return

        self.db.add(
            KnowledgePointChapterLink(
                knowledge_point_id=knowledge_point_id,
                canonical_chapter_id=chapter_id,
                is_primary=result.get("is_primary", False),
                relevance=result["relevance"],
                source=result["source"],
                created_by="system",
            )
        )

    async def _save_question_link(
        self,
        question_id: str,
        chapter_id: str,
        result: Dict[str, Any],
    ) -> None:
        existing_link = (
            await self.db.execute(
                select(QuestionChapterLink).where(
                    QuestionChapterLink.question_id == question_id,
                    QuestionChapterLink.canonical_chapter_id == chapter_id,
                )
            )
        ).scalar_one_or_none()
        if existing_link:
            self._update_link(existing_link, result)
            return

        self.db.add(
            QuestionChapterLink(
                question_id=question_id,
                canonical_chapter_id=chapter_id,
                is_primary=result.get("is_primary", False),
                relevance=result["relevance"],
                source=result["source"],
                created_by="system",
            )
        )

    @staticmethod
    def _update_link(link: Any, result: Dict[str, Any]) -> None:
        link.relevance = result["relevance"]
        link.source = result["source"]
        link.is_primary = result.get("is_primary", False)
