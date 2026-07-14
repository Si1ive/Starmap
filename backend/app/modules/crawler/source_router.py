"""Crawler source administration routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.modules.crawler.source_service import CrawlerSourceService

router = APIRouter(prefix="/admin/crawler", tags=["爬虫管理"])


@router.get("/sources", response_model=ApiResponse)
async def get_crawler_sources(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取爬取源列表。"""
    service = CrawlerSourceService(db)
    sources, total = await service.get_sources(
        skip=(page - 1) * page_size,
        limit=page_size,
        status=status,
        source_type=source_type,
    )
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [
                {
                    "id": source.id,
                    "name": source.name,
                    "code": source.code,
                    "type": source.type,
                    "base_url": source.base_url,
                    "status": source.status,
                    "health_status": source.health_status,
                    "request_interval": (
                        float(source.request_interval)
                        if source.request_interval
                        else None
                    ),
                    "daily_limit": source.daily_limit,
                    "concurrent_limit": source.concurrent_limit,
                    "config": source.config,
                    "total_requests": source.total_requests,
                    "total_success": source.total_success,
                    "total_failed": source.total_failed,
                    "avg_response_time": (
                        float(source.avg_response_time)
                        if source.avg_response_time
                        else None
                    ),
                    "last_health_check": (
                        source.last_health_check.isoformat()
                        if source.last_health_check
                        else None
                    ),
                    "created_at": (
                        source.created_at.isoformat() if source.created_at else None
                    ),
                    "updated_at": (
                        source.updated_at.isoformat() if source.updated_at else None
                    ),
                }
                for source in sources
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.post("/sources", response_model=ApiResponse)
async def create_crawler_source(data: dict, db: AsyncSession = Depends(get_db)):
    """创建爬取源。"""
    service = CrawlerSourceService(db)
    try:
        source = await service.create_source(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(code=200, message="创建成功", data={"id": source.id})


@router.post("/sources/defaults", response_model=ApiResponse)
async def initialize_default_sources(db: AsyncSession = Depends(get_db)):
    """初始化默认爬取源。"""
    service = CrawlerSourceService(db)
    sources = await service.ensure_default_sources()
    return ApiResponse(
        code=200,
        message="默认数据源已初始化",
        data={
            "items": [
                {
                    "id": source.id,
                    "name": source.name,
                    "code": source.code,
                    "status": source.status,
                    "health_status": source.health_status,
                }
                for source in sources
            ],
            "total": len(sources),
        },
    )


@router.get("/sources/{source_id}", response_model=ApiResponse)
async def get_crawler_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """获取爬取源详情。"""
    service = CrawlerSourceService(db)
    source = await service.get_source_by_id(source_id)
    if not source:
        return ApiResponse(code=404, message="爬取源不存在")
    return ApiResponse(
        code=200,
        message="success",
        data={
            "id": source.id,
            "name": source.name,
            "code": source.code,
            "type": source.type,
            "base_url": source.base_url,
            "config": source.config,
            "status": source.status,
            "health_status": source.health_status,
            "request_interval": (
                float(source.request_interval) if source.request_interval else None
            ),
            "daily_limit": source.daily_limit,
            "concurrent_limit": source.concurrent_limit,
            "total_requests": source.total_requests,
            "total_success": source.total_success,
            "total_failed": source.total_failed,
            "avg_response_time": (
                float(source.avg_response_time) if source.avg_response_time else None
            ),
            "last_health_check": (
                source.last_health_check.isoformat()
                if source.last_health_check
                else None
            ),
            "created_at": source.created_at.isoformat() if source.created_at else None,
            "updated_at": source.updated_at.isoformat() if source.updated_at else None,
        },
    )


@router.put("/sources/{source_id}", response_model=ApiResponse)
async def update_crawler_source(
    source_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """更新爬取源。"""
    service = CrawlerSourceService(db)
    source = await service.update_source(source_id, data)
    if not source:
        return ApiResponse(code=404, message="爬取源不存在")
    return ApiResponse(code=200, message="更新成功", data={"id": source.id})


@router.delete("/sources/{source_id}", response_model=ApiResponse)
async def delete_crawler_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """删除爬取源。"""
    service = CrawlerSourceService(db)
    success = await service.delete_source(source_id)
    if not success:
        return ApiResponse(code=404, message="爬取源不存在")
    return ApiResponse(code=200, message="删除成功")


@router.post("/sources/{source_id}/health", response_model=ApiResponse)
async def check_source_health(source_id: str, db: AsyncSession = Depends(get_db)):
    """检查爬取源健康状态。"""
    service = CrawlerSourceService(db)
    result = await service.health_check(source_id)
    return ApiResponse(code=200, message="success", data=result)


@router.get("/sources/{source_id}/stats", response_model=ApiResponse)
async def get_source_stats(
    source_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """获取爬取源统计。"""
    service = CrawlerSourceService(db)
    stats = await service.get_source_stats(source_id, days)
    return ApiResponse(code=200, message="success", data=stats)
