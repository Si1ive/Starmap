"""Crawler runtime configuration routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db, get_optional_db
from app.modules.operations.security import get_request_admin_id
from app.modules.operations.settings_service import SystemSettingsService

router = APIRouter(prefix="/admin/crawler", tags=["爬虫管理"])


@router.get("/config", response_model=ApiResponse)
async def get_crawler_config(
    db: Optional[AsyncSession] = Depends(get_optional_db),
):
    """获取下一次爬虫任务将使用的运行配置。"""
    config = await SystemSettingsService(db).get_crawler_runtime_config()
    return ApiResponse(code=200, message="success", data=config)


@router.put("/config", response_model=ApiResponse)
async def update_crawler_config(
    data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新爬虫运行配置，并记录操作审计。"""
    try:
        config = await SystemSettingsService(db).update_crawler_settings(
            data,
            user_id=get_request_admin_id(request),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ApiResponse(code=200, message="配置已保存", data=config)
