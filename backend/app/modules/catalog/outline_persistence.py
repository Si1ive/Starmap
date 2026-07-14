"""考试大纲元信息和章节树持久化。"""

import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import CanonicalChapter, ExamOutline
from app.modules.retrieval.chapter_relation_retrieval import (
    validate_cross_references,
)


def generate_outline_id() -> str:
    """生成目录域使用的 32 位十六进制 ID。"""
    return uuid.uuid4().hex[:32]


class OutlinePersistence:
    """复用大纲元信息和递归章节树的 upsert 规则。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_outline_meta(
        self,
        name: str,
        year: int,
        version: str,
        description: Optional[str],
        set_default: bool,
        *,
        update_description: bool = True,
    ) -> ExamOutline:
        """按年份和版本 upsert 大纲，并维护默认大纲互斥。"""
        outline = (
            await self.db.execute(
                select(ExamOutline).where(
                    ExamOutline.year == year,
                    ExamOutline.version == version,
                )
            )
        ).scalar_one_or_none()
        if outline:
            outline.name = name
            if update_description:
                outline.description = description or outline.description
            outline.status = "active"
        else:
            outline = ExamOutline(
                id=generate_outline_id(),
                name=name,
                year=year,
                version=version,
                description=description,
                release_date=date.today(),
                effective_date=date.today(),
                status="active",
                is_default=set_default,
            )
            self.db.add(outline)
            await self.db.flush()

        if set_default:
            others = (
                await self.db.execute(
                    select(ExamOutline).where(
                        ExamOutline.id != outline.id,
                        ExamOutline.is_default.is_(True),
                    )
                )
            ).scalars().all()
            for other in others:
                other.is_default = False
            outline.is_default = True
        return outline

    async def upsert_chapters(
        self,
        subject_id: str,
        outline_id: str,
        chapters: List[Dict[str, Any]],
        parent_id: Optional[str] = None,
        level: int = 1,
    ) -> Tuple[int, int]:
        """递归 upsert 章节树，返回新建和更新数量。"""
        created = 0
        updated = 0

        for index, data in enumerate(chapters):
            query = select(CanonicalChapter).where(
                and_(
                    CanonicalChapter.subject_id == subject_id,
                    CanonicalChapter.outline_id == outline_id,
                    CanonicalChapter.name == data["name"],
                    CanonicalChapter.level == level,
                )
            )
            if parent_id:
                query = query.where(CanonicalChapter.parent_id == parent_id)
            else:
                query = query.where(CanonicalChapter.parent_id.is_(None))

            chapter = (await self.db.execute(query)).scalar_one_or_none()
            if chapter:
                chapter.outline_code = (
                    data.get("outline_code") or chapter.outline_code
                )
                chapter.code = data.get("code") or chapter.code
                chapter.aliases = data.get("aliases") or chapter.aliases
                chapter.description = (
                    data.get("description") or chapter.description
                )
                chapter.enhanced_description = (
                    data.get("enhanced_description")
                    or chapter.enhanced_description
                )
                chapter.keywords = data.get("keywords") or chapter.keywords
                if data.get("cross_references"):
                    chapter.cross_references = await validate_cross_references(
                        self.db,
                        data["cross_references"],
                    )
                chapter.sort_order = data.get("sort_order", index)
                chapter.status = "active"
                updated += 1
            else:
                chapter = CanonicalChapter(
                    id=generate_outline_id(),
                    subject_id=subject_id,
                    outline_id=outline_id,
                    parent_id=parent_id,
                    level=level,
                    name=data["name"],
                    code=data.get("code"),
                    outline_code=data.get("outline_code"),
                    aliases=data.get("aliases"),
                    description=data.get("description"),
                    enhanced_description=data.get("enhanced_description"),
                    keywords=data.get("keywords"),
                    cross_references=(
                        data.get("cross_references")
                        if data.get("cross_references")
                        else None
                    ),
                    sort_order=data.get("sort_order", index),
                    status="active",
                )
                self.db.add(chapter)
                created += 1
                await self.db.flush()

            children = data.get("children") or []
            if children:
                child_created, child_updated = await self.upsert_chapters(
                    subject_id=subject_id,
                    outline_id=outline_id,
                    chapters=children,
                    parent_id=chapter.id,
                    level=level + 1,
                )
                created += child_created
                updated += child_updated

        return created, updated
