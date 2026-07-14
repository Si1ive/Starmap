"""Canonical chapter tree management."""

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CanonicalChapter, Subject

logger = get_logger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:32]


class CanonicalChapterService:
    """Manage canonical chapter trees."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def init_chapters(
        self,
        subject_id: str,
        chapters: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Initialize a subject's canonical chapter tree."""
        subject = await self.db.get(Subject, subject_id)
        if not subject:
            raise ValueError(f"学科不存在: {subject_id}")

        created_count = 0
        chapter_ids = {}

        async def create_chapter(
            data: Dict[str, Any],
            parent_id: Optional[str],
            level: int,
        ) -> None:
            nonlocal created_count

            existing = await self.db.execute(
                select(CanonicalChapter).where(
                    and_(
                        CanonicalChapter.subject_id == subject_id,
                        CanonicalChapter.name == data["name"],
                        CanonicalChapter.level == level,
                        CanonicalChapter.parent_id == parent_id,
                    )
                )
            )
            chapter = existing.scalar_one_or_none()

            if not chapter:
                chapter = CanonicalChapter(
                    id=_generate_id(),
                    subject_id=subject_id,
                    parent_id=parent_id,
                    level=level,
                    name=data["name"],
                    code=data.get("code"),
                    aliases=data.get("aliases"),
                    description=data.get("description"),
                    sort_order=data.get("sort_order", created_count),
                )
                self.db.add(chapter)
                created_count += 1
                await self.db.flush()

            chapter_ids[data["name"]] = chapter.id

            for child in data.get("children", []):
                await create_chapter(child, chapter.id, level + 1)

        for index, chapter_data in enumerate(chapters):
            chapter_data.setdefault("sort_order", index)
            await create_chapter(chapter_data, None, 1)

        await self.db.commit()

        logger.info(
            "标准章节初始化完成",
            subject_id=subject_id,
            created_count=created_count,
        )

        return {
            "subject_id": subject_id,
            "created_count": created_count,
            "chapter_ids": chapter_ids,
        }

    async def get_chapters(self, subject_id: str) -> List[Dict[str, Any]]:
        """Return the canonical chapters as a tree."""
        result = await self.db.execute(
            select(CanonicalChapter)
            .where(CanonicalChapter.subject_id == subject_id)
            .order_by(CanonicalChapter.sort_order)
        )
        chapters = result.scalars().all()
        if not chapters:
            return []

        chapter_map = {chapter.id: self._to_dict(chapter) for chapter in chapters}
        root_chapters = []

        for chapter in chapters:
            node = chapter_map[chapter.id]
            if chapter.parent_id and chapter.parent_id in chapter_map:
                parent = chapter_map[chapter.parent_id]
                parent.setdefault("children", []).append(node)
            else:
                root_chapters.append(node)

        return root_chapters

    async def get_chapters_flat(self, subject_id: str) -> List[Dict[str, Any]]:
        """Return the canonical chapters as a flat list."""
        result = await self.db.execute(
            select(CanonicalChapter)
            .where(CanonicalChapter.subject_id == subject_id)
            .order_by(CanonicalChapter.sort_order)
        )
        return [self._to_dict(chapter) for chapter in result.scalars().all()]

    async def search_chapters(
        self,
        subject_id: str,
        keyword: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search canonical chapters by name or code."""
        keyword_pattern = f"%{keyword}%"
        result = await self.db.execute(
            select(CanonicalChapter)
            .where(
                and_(
                    CanonicalChapter.subject_id == subject_id,
                    or_(
                        CanonicalChapter.name.ilike(keyword_pattern),
                        CanonicalChapter.code.ilike(keyword_pattern),
                    ),
                )
            )
            .limit(limit)
        )
        return [self._to_dict(chapter) for chapter in result.scalars().all()]

    def _to_dict(self, chapter: CanonicalChapter) -> Dict[str, Any]:
        return {
            "id": chapter.id,
            "subject_id": chapter.subject_id,
            "parent_id": chapter.parent_id,
            "level": chapter.level,
            "name": chapter.name,
            "code": chapter.code,
            "aliases": chapter.aliases,
            "description": chapter.description,
            "sort_order": chapter.sort_order,
            "status": chapter.status,
            "created_at": chapter.created_at.isoformat() if chapter.created_at else None,
        }
