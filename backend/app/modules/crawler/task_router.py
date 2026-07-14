"""Crawler task administration routes."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.db.mysql import mysql_client
from app.modules.crawler.task_service import CrawlerTaskService

router = APIRouter(prefix="/admin/crawler", tags=["爬虫管理"])


@router.get("/tasks", response_model=ApiResponse)
async def get_crawler_tasks(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    source_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取爬虫任务列表。"""
    service = CrawlerTaskService(db)
    skip = (page - 1) * page_size
    tasks, total = await service.get_tasks(
        skip=skip,
        limit=page_size,
        status=status,
        task_type=task_type,
        source_id=source_id,
    )

    items = []
    for task in tasks:
        items.append(
            {
                "id": task.id,
                "name": task.name,
                "task_type": task.task_type,
                "source": task.source,
                "source_id": task.source_id,
                "target_count": task.target_count,
                "completed_count": task.completed_count,
                "success_count": task.success_count,
                "failed_count": task.failed_count,
                "success_rate": (
                    round(task.success_count / task.completed_count * 100, 1)
                    if task.completed_count
                    else 0
                ),
                "progress": float(task.progress) if task.progress else 0,
                "status": task.status,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": (
                    task.completed_at.isoformat() if task.completed_at else None
                ),
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "error_message": getattr(task, "error_message", None),
            }
        )

    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        },
    )


@router.post("/tasks", response_model=ApiResponse)
async def create_crawler_task(data: dict, db: AsyncSession = Depends(get_db)):
    """创建爬虫任务，并可选择立即执行。"""
    service = CrawlerTaskService(db)
    config = data.get("config", {})
    source_ids = data.get("source_ids") or config.get("source_ids") or []
    target_config = {
        **config,
        "source_ids": source_ids,
    }

    try:
        task = await service.create_task(
            name=data.get("name", "手动任务"),
            task_type=data.get("task_type", "targeted"),
            source_ids=source_ids,
            target_config=target_config,
            created_by=data.get("created_by"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if data.get("execute_now", False):
        asyncio.create_task(_execute_task(task.id))

    return ApiResponse(
        code=200,
        message="任务已创建",
        data={
            "id": task.id,
            "name": task.name,
            "task_type": task.task_type,
            "source": task.source,
            "source_id": task.source_id,
            "target_count": task.target_count,
            "completed_count": task.completed_count,
            "success_count": task.success_count,
            "failed_count": task.failed_count,
            "success_rate": 0,
            "progress": float(task.progress) if task.progress else 0,
            "status": task.status,
            "config": task.config,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": (
                task.completed_at.isoformat() if task.completed_at else None
            ),
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "error_message": task.error_message,
        },
    )


@router.post("/tasks/{task_id}/start", response_model=ApiResponse)
async def start_crawler_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """启动爬虫任务。"""
    service = CrawlerTaskService(db)
    task = await service.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务已在运行中")

    asyncio.create_task(_execute_task(task_id))

    return ApiResponse(
        code=200,
        message="任务已启动",
        data={
            "id": task.id,
            "status": "running",
        },
    )


@router.post("/tasks/{task_id}/stop", response_model=ApiResponse)
async def stop_crawler_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """停止爬虫任务。"""
    service = CrawlerTaskService(db)
    task = await service.stop_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return ApiResponse(
        code=200,
        message="任务已停止",
        data={
            "id": task.id,
            "status": task.status,
            "completed_at": (
                task.completed_at.isoformat() if task.completed_at else None
            ),
        },
    )


@router.delete("/tasks/{task_id}", response_model=ApiResponse)
async def delete_crawler_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """删除爬虫任务。"""
    service = CrawlerTaskService(db)
    try:
        success = await service.delete_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")

    return ApiResponse(code=200, message="任务已删除", data={"id": task_id})


async def _execute_task(task_id: str) -> None:
    """Use an independent database session for background task execution."""
    async with mysql_client.session() as session:
        service = CrawlerTaskService(session)
        await service.execute_task(task_id)
