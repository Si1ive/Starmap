"""考试大纲管理端只读查询。"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    ExamOutline,
    ExamOutlineSubject,
    Subject,
)


async def list_outlines(session: AsyncSession) -> List[Dict[str, Any]]:
    """按年份和版本返回考试大纲摘要。"""
    rows = (
        await session.execute(
            select(ExamOutline).order_by(
                ExamOutline.year.desc(),
                ExamOutline.version,
            )
        )
    ).scalars().all()
    return [
        {
            "id": outline.id,
            "name": outline.name,
            "year": outline.year,
            "version": outline.version,
            "description": outline.description,
            "status": outline.status,
            "is_default": bool(outline.is_default),
            "release_date": (
                outline.release_date.isoformat()
                if outline.release_date
                else None
            ),
            "effective_date": (
                outline.effective_date.isoformat()
                if outline.effective_date
                else None
            ),
            "created_at": (
                outline.created_at.isoformat()
                if outline.created_at
                else None
            ),
        }
        for outline in rows
    ]


async def get_outline_chapters(
    session: AsyncSession,
    outline_id: str,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """返回大纲章节树，可按科目过滤。"""
    query = (
        select(CanonicalChapter)
        .where(CanonicalChapter.outline_id == outline_id)
        .order_by(CanonicalChapter.level, CanonicalChapter.sort_order)
    )
    if subject_id:
        query = query.where(CanonicalChapter.subject_id == subject_id)
    rows = (await session.execute(query)).scalars().all()

    chapters_by_id = {
        row.id: {
            "id": row.id,
            "name": row.name,
            "code": row.code,
            "outline_code": row.outline_code,
            "level": row.level,
            "parent_id": row.parent_id,
            "subject_id": row.subject_id,
            "sort_order": row.sort_order,
            "description": row.description,
            "enhanced_description": row.enhanced_description,
            "keywords": row.keywords,
            "exam_guidance": row.exam_guidance,
            "children": [],
        }
        for row in rows
    }

    roots: List[Dict[str, Any]] = []
    for chapter in chapters_by_id.values():
        parent_id = chapter["parent_id"]
        if parent_id and parent_id in chapters_by_id:
            chapters_by_id[parent_id]["children"].append(chapter)
        else:
            roots.append(chapter)
    return roots


async def get_outline_subjects(
    session: AsyncSession,
    outline_id: str,
) -> List[Dict[str, Any]]:
    """返回大纲下各科目的考察目标和复习指导生成状态。"""
    rows = (
        await session.execute(
            select(ExamOutlineSubject, Subject)
            .join(Subject, Subject.id == ExamOutlineSubject.subject_id)
            .where(ExamOutlineSubject.outline_id == outline_id)
            .order_by(Subject.sort_order)
        )
    ).all()
    return [
        {
            "subject_id": link.subject_id,
            "subject_name": subject.name,
            "subject_code": subject.code,
            "exam_objective": link.exam_objective,
            "guidance_status": link.guidance_status,
            "chapter_count": link.chapter_count,
        }
        for link, subject in rows
    ]
