"""Authenticated learning progress projection API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.modules.identity.dependencies import require_current_session
from app.modules.identity.session import AuthenticatedSession
from app.modules.learning.service import LearningProgressService
from app.modules.learning.weaknesses import WeaknessService

router = APIRouter(prefix="/app/learning", tags=["用户学习进度"])


@router.get("/progress", response_model=ApiResponse)
async def get_learning_progress(
    current: AuthenticatedSession = Depends(require_current_session),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await LearningProgressService(db).get(current.user.id))


@router.get("/weaknesses", response_model=ApiResponse)
async def get_learning_weaknesses(
    current: AuthenticatedSession = Depends(require_current_session),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await WeaknessService(db).get(current.user.id))
