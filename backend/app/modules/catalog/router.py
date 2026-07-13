"""Admin routes for the subject and chapter catalog."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import Chapter, Subject

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
