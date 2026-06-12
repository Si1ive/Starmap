"""
旧章节兼容服务

为仍依赖 `chapters.id` 的旧字段提供兼容映射，
将 `canonical_chapters` 解析到 legacy `chapters`。
"""

from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import CanonicalChapter, Chapter


async def resolve_legacy_chapter_id(
    db: AsyncSession,
    canonical_chapter_id: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> Optional[str]:
    """
    将标准章节 ID 解析为旧 chapters 表中的 chapter_id。

    优先按标准章节及其祖先名称精确匹配，找不到时做一次轻量模糊匹配，
    最后回退到该学科排序最靠前的 legacy chapter。
    """
    resolved_subject_id = subject_id
    candidate_names: List[str] = []

    if canonical_chapter_id:
        current = await db.get(CanonicalChapter, canonical_chapter_id)
        visited = set()
        while current and current.id not in visited:
            visited.add(current.id)
            if current.name:
                candidate_names.append(current.name.strip())
            resolved_subject_id = current.subject_id or resolved_subject_id
            if not current.parent_id:
                break
            current = await db.get(CanonicalChapter, current.parent_id)

    if not resolved_subject_id:
        return None

    result = await db.execute(
        select(Chapter)
        .where(Chapter.subject_id == resolved_subject_id)
        .order_by(Chapter.sort_order, Chapter.id)
    )
    chapters = result.scalars().all()
    if not chapters:
        return None

    by_name = {
        (chapter.name or "").strip().lower(): chapter.id
        for chapter in chapters
        if chapter.name
    }
    for candidate_name in candidate_names:
        matched = by_name.get(candidate_name.lower())
        if matched:
            return matched

    best_id: Optional[str] = None
    best_score = 0.0
    for candidate_name in candidate_names:
        normalized = candidate_name.lower()
        for chapter in chapters:
            chapter_name = (chapter.name or "").strip().lower()
            if not chapter_name:
                continue
            if chapter_name in normalized or normalized in chapter_name:
                score = min(len(chapter_name), len(normalized)) / max(len(chapter_name), len(normalized), 1)
                if score > best_score:
                    best_score = score
                    best_id = chapter.id

    return best_id or chapters[0].id
