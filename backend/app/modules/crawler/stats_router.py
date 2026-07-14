"""Crawler statistics administration routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.modules.crawler.scrapy_task_bridge import ScrapyTaskBridge
from app.modules.crawler.stats_service import CrawlerStatsService

router = APIRouter(prefix="/admin/crawler", tags=["爬虫管理"])


@router.get("/stats/overview", response_model=ApiResponse)
async def get_crawler_overview(db: AsyncSession = Depends(get_db)):
    """获取爬虫总体概览。"""
    service = CrawlerStatsService(db)
    overview = await service.get_overview()
    overview["scrapy_status"] = await _get_scrapy_status(db)
    return ApiResponse(code=200, message="success", data=overview)


@router.get("/stats/sources", response_model=ApiResponse)
async def get_source_comparison(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    """获取各源对比数据。"""
    service = CrawlerStatsService(db)
    comparison = await service.get_source_comparison(days)
    return ApiResponse(code=200, message="success", data=comparison)


@router.get("/stats/trend", response_model=ApiResponse)
async def get_crawler_trend(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """获取爬虫运行趋势。"""
    service = CrawlerStatsService(db)
    trend = await service.get_trend(days)
    return ApiResponse(code=200, message="success", data=trend)


@router.get("/stats/file-types", response_model=ApiResponse)
async def get_file_type_distribution(db: AsyncSession = Depends(get_db)):
    """获取下载文件类型分布。"""
    service = CrawlerStatsService(db)
    distribution = await service.get_file_type_distribution()
    return ApiResponse(code=200, message="success", data=distribution)


@router.get("/stats/suggestions", response_model=ApiResponse)
async def get_crawler_suggestions(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    """获取爬虫运营优化建议。"""
    service = CrawlerStatsService(db)
    suggestions = await service.get_suggestions(days)
    return ApiResponse(code=200, message="success", data=suggestions)


@router.get("/scrapy/status", response_model=ApiResponse)
async def get_scrapy_status(db: AsyncSession = Depends(get_db)):
    """获取 Scrapy 服务连接状态和队列信息。"""
    status = await _get_scrapy_status(db)
    return ApiResponse(code=200, message="success", data=status)


async def _get_scrapy_status(db: AsyncSession) -> dict:
    bridge = ScrapyTaskBridge(db)
    try:
        return await bridge.get_scrapy_status()
    finally:
        await bridge.close()
