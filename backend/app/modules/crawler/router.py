"""Crawler administration routes."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.core.logging import get_logger
from app.core.websocket import log_websocket_manager
from app.db import get_db, get_optional_db
from app.models.mysql_models import DownloadedFile
from app.modules.crawler.log_service import CrawlerLogService
from app.modules.crawler.schedule_service import CrawlerScheduleService
from app.modules.crawler.scrapy_bridge import ScrapyBridgeService
from app.modules.crawler.source_service import CrawlerSourceService
from app.modules.crawler.stats_service import CrawlerStatsService
from app.modules.crawler.storage import DOWNLOAD_STORE
from app.modules.operations.security import get_request_admin_id
from app.modules.operations.settings_service import SystemSettingsService

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/crawler", tags=["爬虫管理"])

# ========== 爬虫管理相关 ==========


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


# ========== 爬取源管理 ==========


@router.get("/sources", response_model=ApiResponse)
async def get_crawler_sources(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取爬取源列表"""
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
                    "id": s.id,
                    "name": s.name,
                    "code": s.code,
                    "type": s.type,
                    "base_url": s.base_url,
                    "status": s.status,
                    "health_status": s.health_status,
                    "request_interval": (
                        float(s.request_interval) if s.request_interval else None
                    ),
                    "daily_limit": s.daily_limit,
                    "concurrent_limit": s.concurrent_limit,
                    "config": s.config,
                    "total_requests": s.total_requests,
                    "total_success": s.total_success,
                    "total_failed": s.total_failed,
                    "avg_response_time": (
                        float(s.avg_response_time) if s.avg_response_time else None
                    ),
                    "last_health_check": (
                        s.last_health_check.isoformat() if s.last_health_check else None
                    ),
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
                for s in sources
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.post("/sources", response_model=ApiResponse)
async def create_crawler_source(data: dict, db: AsyncSession = Depends(get_db)):
    """创建爬取源"""
    service = CrawlerSourceService(db)
    try:
        source = await service.create_source(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(code=200, message="创建成功", data={"id": source.id})


@router.post("/sources/defaults", response_model=ApiResponse)
async def initialize_default_sources(db: AsyncSession = Depends(get_db)):
    """初始化默认爬取源"""
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
    """获取爬取源详情"""
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
    source_id: str, data: dict, db: AsyncSession = Depends(get_db)
):
    """更新爬取源"""
    service = CrawlerSourceService(db)
    source = await service.update_source(source_id, data)
    if not source:
        return ApiResponse(code=404, message="爬取源不存在")
    return ApiResponse(code=200, message="更新成功", data={"id": source.id})


@router.delete("/sources/{source_id}", response_model=ApiResponse)
async def delete_crawler_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """删除爬取源"""
    service = CrawlerSourceService(db)
    success = await service.delete_source(source_id)
    if not success:
        return ApiResponse(code=404, message="爬取源不存在")
    return ApiResponse(code=200, message="删除成功")


@router.post("/sources/{source_id}/health", response_model=ApiResponse)
async def check_source_health(source_id: str, db: AsyncSession = Depends(get_db)):
    """爬取源健康检查"""
    service = CrawlerSourceService(db)
    result = await service.health_check(source_id)
    return ApiResponse(code=200, message="success", data=result)


@router.get("/sources/{source_id}/stats", response_model=ApiResponse)
async def get_source_stats(
    source_id: str, days: int = 30, db: AsyncSession = Depends(get_db)
):
    """获取爬取源统计"""
    service = CrawlerSourceService(db)
    stats = await service.get_source_stats(source_id, days)
    return ApiResponse(code=200, message="success", data=stats)


# ========== 统计报表 ==========


@router.get("/stats/overview", response_model=ApiResponse)
async def get_crawler_overview(db: AsyncSession = Depends(get_db)):
    """获取爬虫总体概览"""
    service = CrawlerStatsService(db)
    overview = await service.get_overview()

    # 添加 Scrapy 服务状态
    bridge = ScrapyBridgeService(db)
    scrapy_status = await bridge.get_scrapy_status()
    overview["scrapy_status"] = scrapy_status
    await bridge.close()

    return ApiResponse(code=200, message="success", data=overview)


@router.get("/stats/sources", response_model=ApiResponse)
async def get_source_comparison(days: int = 7, db: AsyncSession = Depends(get_db)):
    """获取各源对比数据"""
    service = CrawlerStatsService(db)
    comparison = await service.get_source_comparison(days)
    return ApiResponse(code=200, message="success", data=comparison)


@router.get("/stats/trend", response_model=ApiResponse)
async def get_crawler_trend(days: int = 30, db: AsyncSession = Depends(get_db)):
    """获取趋势数据"""
    service = CrawlerStatsService(db)
    trend = await service.get_trend(days)
    return ApiResponse(code=200, message="success", data=trend)


@router.get("/stats/file-types", response_model=ApiResponse)
async def get_file_type_distribution(db: AsyncSession = Depends(get_db)):
    """获取文件类型分布"""
    service = CrawlerStatsService(db)
    distribution = await service.get_file_type_distribution()
    return ApiResponse(code=200, message="success", data=distribution)


@router.get("/stats/suggestions", response_model=ApiResponse)
async def get_crawler_suggestions(days: int = 7, db: AsyncSession = Depends(get_db)):
    """获取爬虫运营优化建议"""
    service = CrawlerStatsService(db)
    suggestions = await service.get_suggestions(days)
    return ApiResponse(code=200, message="success", data=suggestions)


@router.get("/scrapy/status", response_model=ApiResponse)
async def get_scrapy_status(db: AsyncSession = Depends(get_db)):
    """
    获取 Scrapy 服务状态

    返回 Scrapy 爬虫服务的连接状态和队列信息。
    """
    bridge = ScrapyBridgeService(db)
    status = await bridge.get_scrapy_status()
    await bridge.close()

    return ApiResponse(code=200, message="success", data=status)


# ========== 定时任务 ==========


@router.get("/schedules", response_model=ApiResponse)
async def get_crawler_schedules(
    page: int = 1,
    page_size: int = 20,
    is_enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取定时任务列表"""
    service = CrawlerScheduleService(db)
    schedules, total = await service.get_schedules(
        skip=(page - 1) * page_size,
        limit=page_size,
        is_enabled=is_enabled,
    )
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "task_type": s.task_type,
                    "source_ids": s.source_ids,
                    "target_config": s.target_config,
                    "cron_expression": s.cron_expression,
                    "timezone": s.timezone,
                    "is_enabled": s.is_enabled,
                    "max_retries": s.max_retries,
                    "retry_interval": s.retry_interval,
                    "concurrent_limit": s.concurrent_limit,
                    "timeout": s.timeout,
                    "total_runs": s.total_runs,
                    "success_runs": s.success_runs,
                    "failed_runs": s.failed_runs,
                    "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                    "last_run_status": s.last_run_status,
                    "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in schedules
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.post("/schedules", response_model=ApiResponse)
async def create_crawler_schedule(data: dict, db: AsyncSession = Depends(get_db)):
    """创建定时任务"""
    service = CrawlerScheduleService(db)
    try:
        schedule = await service.create_schedule(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(code=200, message="创建成功", data={"id": schedule.id})


@router.get("/schedules/{schedule_id}", response_model=ApiResponse)
async def get_crawler_schedule(schedule_id: str, db: AsyncSession = Depends(get_db)):
    """获取定时任务详情"""
    service = CrawlerScheduleService(db)
    schedule = await service.get_schedule_by_id(schedule_id)
    if not schedule:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(
        code=200,
        message="success",
        data={
            "id": schedule.id,
            "name": schedule.name,
            "description": schedule.description,
            "task_type": schedule.task_type,
            "source_ids": schedule.source_ids,
            "target_config": schedule.target_config,
            "cron_expression": schedule.cron_expression,
            "timezone": schedule.timezone,
            "is_enabled": schedule.is_enabled,
            "max_retries": schedule.max_retries,
            "retry_interval": schedule.retry_interval,
            "concurrent_limit": schedule.concurrent_limit,
            "timeout": schedule.timeout,
            "notify_on_success": schedule.notify_on_success,
            "notify_on_failure": schedule.notify_on_failure,
            "total_runs": schedule.total_runs,
            "success_runs": schedule.success_runs,
            "failed_runs": schedule.failed_runs,
            "last_run_at": (
                schedule.last_run_at.isoformat() if schedule.last_run_at else None
            ),
            "last_run_status": schedule.last_run_status,
            "next_run_at": (
                schedule.next_run_at.isoformat() if schedule.next_run_at else None
            ),
            "created_by": schedule.created_by,
            "created_at": (
                schedule.created_at.isoformat() if schedule.created_at else None
            ),
            "updated_at": (
                schedule.updated_at.isoformat() if schedule.updated_at else None
            ),
        },
    )


@router.put("/schedules/{schedule_id}", response_model=ApiResponse)
async def update_crawler_schedule(
    schedule_id: str, data: dict, db: AsyncSession = Depends(get_db)
):
    """更新定时任务"""
    service = CrawlerScheduleService(db)
    try:
        schedule = await service.update_schedule(schedule_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not schedule:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(code=200, message="更新成功", data={"id": schedule.id})


@router.delete("/schedules/{schedule_id}", response_model=ApiResponse)
async def delete_crawler_schedule(schedule_id: str, db: AsyncSession = Depends(get_db)):
    """删除定时任务"""
    service = CrawlerScheduleService(db)
    success = await service.delete_schedule(schedule_id)
    if not success:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(code=200, message="删除成功")


@router.post("/schedules/{schedule_id}/toggle", response_model=ApiResponse)
async def toggle_crawler_schedule(
    schedule_id: str, enabled: bool = True, db: AsyncSession = Depends(get_db)
):
    """启用/禁用定时任务"""
    service = CrawlerScheduleService(db)
    try:
        schedule = await service.toggle_schedule(schedule_id, enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not schedule:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(
        code=200,
        message="success",
        data={"id": schedule.id, "is_enabled": schedule.is_enabled},
    )


@router.get("/schedules/{schedule_id}/runs", response_model=ApiResponse)
async def get_schedule_runs(
    schedule_id: str,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取定时任务执行历史"""
    service = CrawlerScheduleService(db)
    runs, total = await service.get_runs(
        schedule_id=schedule_id,
        skip=(page - 1) * page_size,
        limit=page_size,
        status=status,
    )
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [
                {
                    "id": r.id,
                    "schedule_id": r.schedule_id,
                    "task_id": r.task_id,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": (
                        r.completed_at.isoformat() if r.completed_at else None
                    ),
                    "duration": r.duration,
                    "total_requests": r.total_requests,
                    "success_count": r.success_count,
                    "failed_count": r.failed_count,
                    "error_message": r.error_message,
                }
                for r in runs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


# ========== 日志系统 ==========


@router.get("/logs", response_model=ApiResponse)
async def get_crawler_logs(
    task_id: Optional[str] = None,
    source_id: Optional[str] = None,
    level: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """获取爬虫日志"""
    service = CrawlerLogService(db)
    logs, total = await service.get_logs(
        task_id=task_id,
        source_id=source_id,
        level=level,
        status=status,
        resource_type=resource_type,
        start_time=start_time,
        end_time=end_time,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [
                {
                    "id": log.id,
                    "task_id": log.task_id,
                    "source_id": log.source_id,
                    "level": log.level,
                    "stage": log.stage,
                    "resource_url": log.resource_url,
                    "resource_name": log.resource_name,
                    "resource_type": log.resource_type,
                    "action": log.action,
                    "status": log.status,
                    "duration_ms": log.duration_ms,
                    "message": log.message,
                    "error_type": log.error_type,
                    "error_detail": log.error_detail,
                    "retry_count": log.retry_count,
                    "details": log.details,
                    "created_at": (
                        log.created_at.isoformat() if log.created_at else None
                    ),
                }
                for log in logs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get("/logs/export")
async def export_crawler_logs(
    task_id: Optional[str] = None,
    source_id: Optional[str] = None,
    level: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    file_format: str = Query("csv", alias="format"),
    limit: int = Query(5000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
):
    """导出爬虫日志"""
    normalized_format = file_format.lower()
    if normalized_format not in {"csv", "json"}:
        raise HTTPException(status_code=400, detail="format 仅支持 csv 或 json")

    service = CrawlerLogService(db)
    rows, total = await service.export_logs(
        task_id=task_id,
        source_id=source_id,
        level=level,
        status=status,
        resource_type=resource_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    exported_at = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"crawler_logs_{exported_at}.{normalized_format}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Total-Count": str(total),
        "X-Exported-Count": str(len(rows)),
    }

    if normalized_format == "json":
        return JSONResponse(
            content=jsonable_encoder(
                {
                    "items": rows,
                    "total": total,
                    "exported": len(rows),
                }
            ),
            headers=headers,
        )

    return Response(
        content=service.to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get("/file-logs", response_model=ApiResponse)
async def get_crawler_file_logs(
    task_id: Optional[str] = None,
    repo_name: Optional[str] = None,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """获取文件爬取日志（以文件为单位）"""
    query = select(DownloadedFile)
    count_query = select(func.count()).select_from(DownloadedFile)

    filters = []
    if task_id:
        filters.append(DownloadedFile.task_id == task_id)
    if repo_name:
        filters.append(DownloadedFile.repo_name == repo_name)
    if status:
        filters.append(DownloadedFile.status == status)
    if file_type:
        filters.append(DownloadedFile.file_type == file_type)
    if keyword:
        kw = f"%{keyword}%"
        filters.append(
            or_(
                DownloadedFile.file_name.ilike(kw),
                DownloadedFile.repo_name.ilike(kw),
                DownloadedFile.file_path.ilike(kw),
                DownloadedFile.error_detail.ilike(kw),
            )
        )

    for f in filters:
        query = query.where(f)
        count_query = count_query.where(f)

    total = await db.scalar(count_query) or 0

    # 成功/失败统计（同筛选条件下的全局统计）
    success_query = (
        select(func.count())
        .select_from(DownloadedFile)
        .where(DownloadedFile.status != "failed")
    )
    failed_query = (
        select(func.count())
        .select_from(DownloadedFile)
        .where(DownloadedFile.status == "failed")
    )
    for flt in filters:
        success_query = success_query.where(flt)
        failed_query = failed_query.where(flt)
    success_count = await db.scalar(success_query) or 0
    failed_count = await db.scalar(failed_query) or 0

    query = query.order_by(DownloadedFile.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    files = result.scalars().all()

    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [
                {
                    "id": f.id,
                    "task_id": f.task_id,
                    "repo_name": f.repo_name,
                    "repo_url": f.repo_url,
                    "file_path": f.file_path,
                    "file_name": f.file_name,
                    "file_type": f.file_type,
                    "file_size": f.file_size,
                    "download_url": f.download_url,
                    "local_path": f.local_path,
                    "status": f.status,
                    "error_detail": f.error_detail,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in files
            ],
            "total": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get("/file-logs/repos", response_model=ApiResponse)
async def get_file_log_repos(db: AsyncSession = Depends(get_db)):
    """获取所有仓库名列表（用于筛选）"""
    result = await db.execute(
        select(DownloadedFile.repo_name)
        .where(DownloadedFile.repo_name.isnot(None))
        .distinct()
        .order_by(DownloadedFile.repo_name)
    )
    repos = [row[0] for row in result.all()]
    return ApiResponse(code=200, message="success", data=repos)


@router.get("/logs/analysis", response_model=ApiResponse)
async def get_log_analysis(days: int = 7, db: AsyncSession = Depends(get_db)):
    """获取日志分析"""
    service = CrawlerLogService(db)
    analysis = await service.get_analysis(days)
    return ApiResponse(code=200, message="success", data=analysis)


# ========== WebSocket 实时日志 ==========


@router.websocket("/logs/stream")
async def crawler_logs_stream(
    websocket: WebSocket,
    task_id: Optional[str] = None,
    source_id: Optional[str] = None,
    level: Optional[str] = None,
):
    """
    WebSocket 实时日志推送

    连接后自动接收符合条件的日志消息。
    支持通过 query 参数过滤：task_id, source_id, level
    """
    # 解析过滤条件
    task_ids = {task_id} if task_id else set()
    source_ids = {source_id} if source_id else set()
    levels = {level} if level else set()

    await log_websocket_manager.connect(
        websocket,
        task_ids=task_ids if task_ids else None,
        source_ids=source_ids if source_ids else None,
        levels=levels if levels else None,
    )

    try:
        while True:
            # 等待客户端消息（心跳或控制命令）
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "filter":
                    # 动态更新过滤条件
                    new_task_ids = set(message.get("task_ids", []))
                    new_source_ids = set(message.get("source_ids", []))
                    new_levels = set(message.get("levels", []))
                    log_websocket_manager.update_filters(
                        websocket,
                        task_ids=new_task_ids,
                        source_ids=new_source_ids,
                        levels=new_levels,
                    )
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "filter_updated",
                                "task_ids": list(new_task_ids),
                                "source_ids": list(new_source_ids),
                                "levels": list(new_levels),
                            }
                        )
                    )
            except json.JSONDecodeError:
                logger.warning(f"Invalid WebSocket message: {data}")

    except WebSocketDisconnect:
        await log_websocket_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await log_websocket_manager.disconnect(websocket)


@router.post("/file-logs/retry", response_model=ApiResponse)
async def retry_file_downloads(
    file_ids: List[str],
    db: AsyncSession = Depends(get_db),
):
    """重试下载指定文件"""
    import httpx

    if not file_ids:
        raise HTTPException(status_code=400, detail="请提供至少一个文件ID")
    if len(file_ids) > 50:
        raise HTTPException(status_code=400, detail="单次最多重试50个文件")

    result = await db.execute(
        select(DownloadedFile).where(DownloadedFile.id.in_(file_ids))
    )
    files = result.scalars().all()

    if not files:
        raise HTTPException(status_code=404, detail="未找到指定文件")

    download_store = Path(DOWNLOAD_STORE).resolve()
    success_count = 0
    fail_count = 0
    results = []

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for f in files:
            file_result = {"id": f.id, "file_name": f.file_name}
            try:
                if not f.download_url:
                    raise ValueError("文件无下载链接")

                # 标记为处理中
                await db.execute(
                    update(DownloadedFile)
                    .where(DownloadedFile.id == f.id)
                    .values(status="processing", error_detail=None)
                )
                await db.commit()

                # 下载文件
                resp = await client.get(f.download_url)
                resp.raise_for_status()

                # 确定保存路径（与 Scrapy 爬虫保持一致：DOWNLOAD_STORE/<task_id>/<safe_repo>/<file_path>）
                if f.local_path and Path(f.local_path).resolve().parent.exists():
                    save_path = Path(f.local_path)
                else:
                    safe_repo = (f.repo_name or "unknown").replace("/", "_")
                    task_dir = f.task_id or "manual"
                    repo_file_path = f.file_path or f.file_name
                    save_path = download_store / task_dir / safe_repo / repo_file_path

                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(resp.content)

                # 更新状态
                await db.execute(
                    update(DownloadedFile)
                    .where(DownloadedFile.id == f.id)
                    .values(
                        status="downloaded",
                        file_size=len(resp.content),
                        local_path=str(save_path),
                        error_detail=None,
                    )
                )
                await db.commit()

                file_result["status"] = "downloaded"
                success_count += 1

            except Exception as e:
                error_msg = str(e)[:500]
                try:
                    await db.execute(
                        update(DownloadedFile)
                        .where(DownloadedFile.id == f.id)
                        .values(status="failed", error_detail=error_msg)
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()

                file_result["status"] = "failed"
                file_result["error"] = error_msg
                fail_count += 1

            results.append(file_result)

    return ApiResponse(
        data={
            "total": len(files),
            "success_count": success_count,
            "fail_count": fail_count,
            "results": results,
        }
    )
