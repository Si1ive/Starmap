"""Crawler schedule administration routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.modules.crawler.schedule_service import CrawlerScheduleService

router = APIRouter(prefix="/admin/crawler", tags=["爬虫管理"])


@router.get("/schedules", response_model=ApiResponse)
async def get_crawler_schedules(
    page: int = 1,
    page_size: int = 20,
    is_enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取定时任务列表。"""
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
                    "total_runs": schedule.total_runs,
                    "success_runs": schedule.success_runs,
                    "failed_runs": schedule.failed_runs,
                    "last_run_at": (
                        schedule.last_run_at.isoformat()
                        if schedule.last_run_at
                        else None
                    ),
                    "last_run_status": schedule.last_run_status,
                    "next_run_at": (
                        schedule.next_run_at.isoformat()
                        if schedule.next_run_at
                        else None
                    ),
                    "created_at": (
                        schedule.created_at.isoformat()
                        if schedule.created_at
                        else None
                    ),
                }
                for schedule in schedules
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.post("/schedules", response_model=ApiResponse)
async def create_crawler_schedule(data: dict, db: AsyncSession = Depends(get_db)):
    """创建定时任务。"""
    service = CrawlerScheduleService(db)
    try:
        schedule = await service.create_schedule(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(code=200, message="创建成功", data={"id": schedule.id})


@router.get("/schedules/{schedule_id}", response_model=ApiResponse)
async def get_crawler_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取定时任务详情。"""
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
    schedule_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """更新定时任务。"""
    service = CrawlerScheduleService(db)
    try:
        schedule = await service.update_schedule(schedule_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not schedule:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(code=200, message="更新成功", data={"id": schedule.id})


@router.delete("/schedules/{schedule_id}", response_model=ApiResponse)
async def delete_crawler_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除定时任务。"""
    service = CrawlerScheduleService(db)
    success = await service.delete_schedule(schedule_id)
    if not success:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(code=200, message="删除成功")


@router.post("/schedules/{schedule_id}/toggle", response_model=ApiResponse)
async def toggle_crawler_schedule(
    schedule_id: str,
    enabled: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """启用或禁用定时任务。"""
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
    """获取定时任务执行历史。"""
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
                    "id": run.id,
                    "schedule_id": run.schedule_id,
                    "task_id": run.task_id,
                    "status": run.status,
                    "started_at": (
                        run.started_at.isoformat() if run.started_at else None
                    ),
                    "completed_at": (
                        run.completed_at.isoformat() if run.completed_at else None
                    ),
                    "duration": run.duration,
                    "total_requests": run.total_requests,
                    "success_count": run.success_count,
                    "failed_count": run.failed_count,
                    "error_message": run.error_message,
                }
                for run in runs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )
