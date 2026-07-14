"""学科、章节与标准大纲目录管理路由。"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import Chapter, Subject
from app.modules.catalog.canonical_chapter_service import CanonicalChapterService

router = APIRouter(prefix="/admin", tags=["学科与章节"])


@router.get("/subjects", response_model=ApiResponse)
async def get_subjects(db: AsyncSession = Depends(get_db)):
    """Return active subjects in display order."""
    result = await db.execute(
        select(Subject).where(Subject.status == "active").order_by(Subject.sort_order)
    )
    subjects = result.scalars().all()
    return ApiResponse(
        data={
            "items": [
                {
                    "id": subject.id,
                    "name": subject.name,
                    "code": subject.code,
                    "description": subject.description,
                    "icon": subject.icon,
                    "sort_order": subject.sort_order,
                }
                for subject in subjects
            ],
            "total": len(subjects),
        }
    )


@router.get("/subjects/{subject_id}/chapters", response_model=ApiResponse)
async def get_chapters(subject_id: str, db: AsyncSession = Depends(get_db)):
    """Return active chapters for a subject in display order."""
    result = await db.execute(
        select(Chapter)
        .where(Chapter.subject_id == subject_id, Chapter.status == "active")
        .order_by(Chapter.sort_order)
    )
    chapters = result.scalars().all()
    return ApiResponse(
        data={
            "items": [
                {
                    "id": chapter.id,
                    "name": chapter.name,
                    "description": chapter.description,
                    "sort_order": chapter.sort_order,
                }
                for chapter in chapters
            ],
            "total": len(chapters),
        }
    )


@router.post("/canonical-chapters/init", response_model=ApiResponse)
async def init_canonical_chapters(
    subject_id: str = Query(..., description="学科ID"),
    chapters: List[dict] = [],
    db: AsyncSession = Depends(get_db),
):
    """初始化学科的标准章节体系。"""
    try:
        result = await CanonicalChapterService(db).init_chapters(
            subject_id,
            chapters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get("/canonical-chapters", response_model=ApiResponse)
async def get_canonical_chapters(
    subject_id: str = Query(..., description="学科ID"),
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
):
    """获取学科的标准章节。"""
    service = CanonicalChapterService(db)
    if tree:
        result = await service.get_chapters(subject_id)
    else:
        result = await service.get_chapters_flat(subject_id)
    return ApiResponse(data=result)
