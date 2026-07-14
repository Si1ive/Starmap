"""考试大纲及其关联数据的维护服务。"""

from typing import Any, Dict, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    ExamOutline,
    ExamOutlineSubject,
)


class OutlineMaintenanceService:
    """集中处理大纲删除等写操作。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def delete_outline(
        self,
        outline_id: str,
    ) -> Optional[Dict[str, Any]]:
        outline = await self.db.get(ExamOutline, outline_id)
        if not outline:
            return None

        chapters_count = (
            await self.db.scalar(
                select(func.count())
                .select_from(CanonicalChapter)
                .where(CanonicalChapter.outline_id == outline_id)
            )
            or 0
        )

        # 章节的映射、实体关联和章节关系由数据库外键级联清理。
        await self.db.execute(
            delete(CanonicalChapter).where(
                CanonicalChapter.outline_id == outline_id
            )
        )
        await self.db.execute(
            delete(ExamOutlineSubject).where(
                ExamOutlineSubject.outline_id == outline_id
            )
        )
        await self.db.delete(outline)
        await self.db.commit()

        return {
            "outline_id": outline_id,
            "outline_name": outline.name,
            "deleted_chapters": chapters_count,
            "message": "大纲已删除",
        }
