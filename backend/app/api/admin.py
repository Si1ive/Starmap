"""
后台管理 API 路由。

当前提供认证、看板、爬虫、对话、监控、系统设置等后台接口。
"""

import json
import os
import asyncio
import uuid
import hashlib
import base64
from pathlib import Path
from typing import Optional, List, Any, Literal, Dict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, get_request_id
from app.core.websocket import log_websocket_manager
from app.db import get_db, get_optional_db
from app.services.source_service import CrawlerSourceService
from app.services.stats_service import CrawlerStatsService
from app.services.schedule_service import CrawlerScheduleService
from app.services.log_service import CrawlerLogService
from app.models.mysql_models import DownloadedFile, CorpusFile, ParseRun, Document

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["后台管理"])

SECRET_KEEP_MASK = "__KEEP_EXISTING__"


# ========== 认证相关 ==========

class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=1, max_length=100, description="密码")


class AdminUserResponse(BaseModel):
    """管理员用户信息"""
    id: str
    username: str
    nickname: str
    avatar: Optional[str] = None
    role: str
    permissions: List[str]


class LoginResponse(BaseModel):
    """登录响应"""
    token: str
    user: AdminUserResponse


class ApiResponse(BaseModel):
    """通用 API 响应"""
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None
    request_id: str = Field(default_factory=get_request_id)


class BatchIdsRequest(BaseModel):
    """批量 ID 请求"""
    ids: List[str] = Field(..., min_length=1, max_length=500, description="待处理 ID 列表")


# 模拟管理员数据（开发调试用）
MOCK_ADMIN_USERS = {
    "admin": {
        "id": "admin_001",
        "username": "admin",
        "nickname": "超级管理员",
        "avatar": None,
        "role": "super",
        "permissions": [
            "person:view", "person:edit", "person:delete",
            "work:view", "work:edit",
            "crawler:view", "crawler:control", "crawler:manage",
            "conversation:view",
            "monitor:view",
            "settings:manage",
            "user:manage"
        ],
        "password": "admin123"
    },
    "operator": {
        "id": "admin_002",
        "username": "operator",
        "nickname": "运营人员",
        "avatar": None,
        "role": "operator",
        "permissions": [
            "person:view",
            "work:view",
            "crawler:view",
            "conversation:view",
            "monitor:view"
        ],
        "password": "operator123"
    }
}


@router.post("/auth/login", response_model=ApiResponse)
async def login(request: LoginRequest):
    """
    管理员登录
    
    验证用户名密码，返回 JWT Token 和用户信息。
    """
    user = MOCK_ADMIN_USERS.get(request.username)
    
    if not user or user["password"] != request.password:
        return ApiResponse(
            code=401,
            message="用户名或密码错误",
            data=None
        )
    
    # 生成模拟 Token
    token = f"mock_jwt_token_{user['id']}"
    
    return ApiResponse(
        code=200,
        message="登录成功",
        data={
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "nickname": user["nickname"],
                "avatar": user["avatar"],
                "role": user["role"],
                "permissions": user["permissions"]
            }
        }
    )


@router.post("/auth/logout", response_model=ApiResponse)
async def logout():
    """
    管理员登出
    
    清除当前用户的登录状态。
    """
    return ApiResponse(code=200, message="登出成功")


@router.get("/auth/me", response_model=ApiResponse)
async def get_current_user():
    """
    获取当前管理员信息
    
    根据请求头中的 Token 返回当前登录用户信息。
    """
    # 返回默认管理员信息（开发调试）
    user = MOCK_ADMIN_USERS["admin"]
    return ApiResponse(
        code=200,
        message="success",
        data={
            "id": user["id"],
            "username": user["username"],
            "nickname": user["nickname"],
            "avatar": user["avatar"],
            "role": user["role"],
            "permissions": user["permissions"]
        }
    )


# ========== 看板相关 ==========

class DashboardStats(BaseModel):
    """看板统计数据"""
    subject_count: int
    chapter_count: int
    knowledge_point_count: int
    question_count: int
    today_chat_count: int


@router.get("/dashboard/stats", response_model=ApiResponse)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """获取看板统计数据（408考研平台）"""
    from app.models.mysql_models import Subject, Chapter, KnowledgePoint, Question, ChatSession
    from sqlalchemy import func
    from datetime import datetime as _dt, time as _time

    subject_count = await db.scalar(
        select(func.count()).select_from(Subject).where(Subject.status == "active")
    ) or 0

    chapter_count = await db.scalar(
        select(func.count()).select_from(Chapter).where(Chapter.status == "active")
    ) or 0

    knowledge_point_count = await db.scalar(
        select(func.count()).select_from(KnowledgePoint).where(KnowledgePoint.status != "deleted")
    ) or 0

    question_count = await db.scalar(
        select(func.count()).select_from(Question).where(Question.status != "deleted")
    ) or 0

    today_start = _dt.combine(_dt.utcnow().date(), _time.min)
    today_chat_count = await db.scalar(
        select(func.count()).select_from(ChatSession).where(ChatSession.created_at >= today_start)
    ) or 0

    return ApiResponse(
        code=200,
        message="success",
        data={
            "subject_count": subject_count,
            "chapter_count": chapter_count,
            "knowledge_point_count": knowledge_point_count,
            "question_count": question_count,
            "today_chat_count": today_chat_count,
        }
    )


@router.get("/dashboard/charts", response_model=ApiResponse)
async def get_dashboard_charts(db: AsyncSession = Depends(get_db)):
    """获取看板图表数据（408考研平台）"""
    from app.models.mysql_models import Subject, KnowledgePoint, Question
    from sqlalchemy import func

    # 各学科知识点分布
    subject_rows = await db.execute(
        select(Subject.name, func.count(KnowledgePoint.id))
        .outerjoin(KnowledgePoint, Subject.id == KnowledgePoint.subject_id)
        .where(Subject.status == "active")
        .group_by(Subject.id, Subject.name)
        .order_by(Subject.sort_order)
    )
    subject_distribution = [
        {"name": row[0], "value": row[1] or 0}
        for row in subject_rows
    ]

    # 知识点难度分布
    difficulty_rows = await db.execute(
        select(KnowledgePoint.difficulty, func.count())
        .where(KnowledgePoint.status != "deleted")
        .group_by(KnowledgePoint.difficulty)
    )
    difficulty_name_map = {"easy": "简单", "medium": "中等", "hard": "困难"}
    difficulty_distribution = [
        {"name": difficulty_name_map.get(d, d), "value": c}
        for d, c in difficulty_rows
    ]

    # 题目类型分布
    type_rows = await db.execute(
        select(Question.type, func.count())
        .where(Question.status != "deleted")
        .group_by(Question.type)
    )
    type_name_map = {
        "choice": "选择题",
        "fill": "填空题",
        "judge": "判断题",
        "short_answer": "简答题",
        "design": "设计题",
        "analysis": "分析题"
    }
    question_type_distribution = [
        {"name": type_name_map.get(t, t), "value": c}
        for t, c in type_rows
    ]

    return ApiResponse(
        code=200,
        message="success",
        data={
            "subject_distribution": subject_distribution,
            "difficulty_distribution": difficulty_distribution,
            "question_type_distribution": question_type_distribution
        }
    )


# ========== 爬虫管理相关 ==========

@router.get("/crawler/tasks", response_model=ApiResponse)
async def get_crawler_tasks(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    source_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    获取爬虫任务列表
    """
    from app.services.task_service import CrawlerTaskService
    
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
        items.append({
            "id": task.id,
            "name": task.name,
            "task_type": task.task_type,
            "source": task.source,
            "source_id": task.source_id,
            "target_count": task.target_count,
            "completed_count": task.completed_count,
            "success_count": task.success_count,
            "failed_count": task.failed_count,
            "success_rate": round(task.success_count / task.completed_count * 100, 1) if task.completed_count else 0,
            "progress": float(task.progress) if task.progress else 0,
            "status": task.status,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "error_message": getattr(task, 'error_message', None),
        })
    
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total else 0
        }
    )


@router.post("/crawler/tasks", response_model=ApiResponse)
async def create_crawler_task(
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    创建爬虫任务
    
    支持创建不同类型的爬虫任务，配置爬虫引擎参数。
    
    请求示例:
    ```json
    {
        "name": "爬取周杰伦信息",
        "task_type": "targeted",
        "source_ids": ["source_001"],
        "config": {
            "spider_type": "person",
            "source": "baike",
            "keywords": ["周杰伦"],
            "concurrent_limit": 3,
            "delay": 1.0,
            "timeout": 30
        },
        "execute_now": true
    }
    ```
    """
    from app.services.task_service import CrawlerTaskService
    
    service = CrawlerTaskService(db)
    
    # 构建任务配置
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    
    # 如果请求立即执行
    if data.get("execute_now", False):
        async def _run_task_in_background(task_id: str):
            from app.db.mysql import mysql_client
            async with mysql_client.session() as session:
                bg_service = CrawlerTaskService(session)
                await bg_service.execute_task(task_id)

        asyncio.create_task(_run_task_in_background(task.id))
    
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
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "error_message": task.error_message,
        }
    )


@router.post("/crawler/tasks/{task_id}/start", response_model=ApiResponse)
async def start_crawler_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """启动爬虫任务"""
    from app.services.task_service import CrawlerTaskService
    
    service = CrawlerTaskService(db)
    task = await service.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务已在运行中")
    
    # 使用独立的会话在后台执行任务，避免与请求上下文会话冲突
    async def _run_task_in_background(task_id: str):
        from app.db.mysql import mysql_client
        async with mysql_client.session() as session:
            bg_service = CrawlerTaskService(session)
            await bg_service.execute_task(task_id)
    
    # 注意：不要 await，让任务在后台运行
    asyncio.ensure_future(_run_task_in_background(task_id))
    
    return ApiResponse(
        code=200,
        message="任务已启动",
        data={
            "id": task.id,
            "status": "running",
        }
    )


@router.post("/crawler/tasks/{task_id}/stop", response_model=ApiResponse)
async def stop_crawler_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """停止爬虫任务"""
    from app.services.task_service import CrawlerTaskService
    
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
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }
    )


@router.delete("/crawler/tasks/{task_id}", response_model=ApiResponse)
async def delete_crawler_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """删除爬虫任务"""
    from app.services.task_service import CrawlerTaskService

    service = CrawlerTaskService(db)
    try:
        success = await service.delete_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")

    return ApiResponse(code=200, message="任务已删除", data={"id": task_id})


# ========== 爬取源管理 ==========

@router.get("/crawler/sources", response_model=ApiResponse)
async def get_crawler_sources(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
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
            "items": [{
                "id": s.id,
                "name": s.name,
                "code": s.code,
                "type": s.type,
                "base_url": s.base_url,
                "status": s.status,
                "health_status": s.health_status,
                "request_interval": float(s.request_interval) if s.request_interval else None,
                "daily_limit": s.daily_limit,
                "concurrent_limit": s.concurrent_limit,
                "config": s.config,
                "total_requests": s.total_requests,
                "total_success": s.total_success,
                "total_failed": s.total_failed,
                "avg_response_time": float(s.avg_response_time) if s.avg_response_time else None,
                "last_health_check": s.last_health_check.isoformat() if s.last_health_check else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            } for s in sources],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/crawler/sources", response_model=ApiResponse)
async def create_crawler_source(
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """创建爬取源"""
    service = CrawlerSourceService(db)
    try:
        source = await service.create_source(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(code=200, message="创建成功", data={"id": source.id})


@router.post("/crawler/sources/defaults", response_model=ApiResponse)
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


@router.get("/crawler/sources/{source_id}", response_model=ApiResponse)
async def get_crawler_source(
    source_id: str,
    db: AsyncSession = Depends(get_db)
):
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
            "request_interval": float(source.request_interval) if source.request_interval else None,
            "daily_limit": source.daily_limit,
            "concurrent_limit": source.concurrent_limit,
            "total_requests": source.total_requests,
            "total_success": source.total_success,
            "total_failed": source.total_failed,
            "avg_response_time": float(source.avg_response_time) if source.avg_response_time else None,
            "last_health_check": source.last_health_check.isoformat() if source.last_health_check else None,
            "created_at": source.created_at.isoformat() if source.created_at else None,
            "updated_at": source.updated_at.isoformat() if source.updated_at else None,
        }
    )


@router.put("/crawler/sources/{source_id}", response_model=ApiResponse)
async def update_crawler_source(
    source_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """更新爬取源"""
    service = CrawlerSourceService(db)
    source = await service.update_source(source_id, data)
    if not source:
        return ApiResponse(code=404, message="爬取源不存在")
    return ApiResponse(code=200, message="更新成功", data={"id": source.id})


@router.delete("/crawler/sources/{source_id}", response_model=ApiResponse)
async def delete_crawler_source(
    source_id: str,
    db: AsyncSession = Depends(get_db)
):
    """删除爬取源"""
    service = CrawlerSourceService(db)
    success = await service.delete_source(source_id)
    if not success:
        return ApiResponse(code=404, message="爬取源不存在")
    return ApiResponse(code=200, message="删除成功")


@router.post("/crawler/sources/{source_id}/health", response_model=ApiResponse)
async def check_source_health(
    source_id: str,
    db: AsyncSession = Depends(get_db)
):
    """爬取源健康检查"""
    service = CrawlerSourceService(db)
    result = await service.health_check(source_id)
    return ApiResponse(code=200, message="success", data=result)


@router.get("/crawler/sources/{source_id}/stats", response_model=ApiResponse)
async def get_source_stats(
    source_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """获取爬取源统计"""
    service = CrawlerSourceService(db)
    stats = await service.get_source_stats(source_id, days)
    return ApiResponse(code=200, message="success", data=stats)


# ========== 统计报表 ==========

@router.get("/crawler/stats/overview", response_model=ApiResponse)
async def get_crawler_overview(db: AsyncSession = Depends(get_db)):
    """获取爬虫总体概览"""
    service = CrawlerStatsService(db)
    overview = await service.get_overview()
    
    # 添加 Scrapy 服务状态
    from app.services.scrapy_bridge import ScrapyBridgeService
    bridge = ScrapyBridgeService(db)
    scrapy_status = await bridge.get_scrapy_status()
    overview["scrapy_status"] = scrapy_status
    await bridge.close()
    
    return ApiResponse(code=200, message="success", data=overview)


@router.get("/crawler/stats/sources", response_model=ApiResponse)
async def get_source_comparison(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """获取各源对比数据"""
    service = CrawlerStatsService(db)
    comparison = await service.get_source_comparison(days)
    return ApiResponse(code=200, message="success", data=comparison)


@router.get("/crawler/stats/trend", response_model=ApiResponse)
async def get_crawler_trend(
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """获取趋势数据"""
    service = CrawlerStatsService(db)
    trend = await service.get_trend(days)
    return ApiResponse(code=200, message="success", data=trend)


@router.get("/crawler/stats/file-types", response_model=ApiResponse)
async def get_file_type_distribution(db: AsyncSession = Depends(get_db)):
    """获取文件类型分布"""
    service = CrawlerStatsService(db)
    distribution = await service.get_file_type_distribution()
    return ApiResponse(code=200, message="success", data=distribution)


@router.get("/crawler/stats/suggestions", response_model=ApiResponse)
async def get_crawler_suggestions(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """获取爬虫运营优化建议"""
    service = CrawlerStatsService(db)
    suggestions = await service.get_suggestions(days)
    return ApiResponse(code=200, message="success", data=suggestions)


@router.get("/crawler/scrapy/status", response_model=ApiResponse)
async def get_scrapy_status(db: AsyncSession = Depends(get_db)):
    """
    获取 Scrapy 服务状态
    
    返回 Scrapy 爬虫服务的连接状态和队列信息。
    """
    from app.services.scrapy_bridge import ScrapyBridgeService
    bridge = ScrapyBridgeService(db)
    status = await bridge.get_scrapy_status()
    await bridge.close()
    
    return ApiResponse(
        code=200,
        message="success",
        data=status
    )


# ========== 定时任务 ==========

@router.get("/crawler/schedules", response_model=ApiResponse)
async def get_crawler_schedules(
    page: int = 1,
    page_size: int = 20,
    is_enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
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
            "items": [{
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
            } for s in schedules],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/crawler/schedules", response_model=ApiResponse)
async def create_crawler_schedule(
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """创建定时任务"""
    service = CrawlerScheduleService(db)
    schedule = await service.create_schedule(data)
    return ApiResponse(code=200, message="创建成功", data={"id": schedule.id})


@router.get("/crawler/schedules/{schedule_id}", response_model=ApiResponse)
async def get_crawler_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db)
):
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
            "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            "last_run_status": schedule.last_run_status,
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            "created_by": schedule.created_by,
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
            "updated_at": schedule.updated_at.isoformat() if schedule.updated_at else None,
        }
    )


@router.put("/crawler/schedules/{schedule_id}", response_model=ApiResponse)
async def update_crawler_schedule(
    schedule_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """更新定时任务"""
    service = CrawlerScheduleService(db)
    schedule = await service.update_schedule(schedule_id, data)
    if not schedule:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(code=200, message="更新成功", data={"id": schedule.id})


@router.delete("/crawler/schedules/{schedule_id}", response_model=ApiResponse)
async def delete_crawler_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db)
):
    """删除定时任务"""
    service = CrawlerScheduleService(db)
    success = await service.delete_schedule(schedule_id)
    if not success:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(code=200, message="删除成功")


@router.post("/crawler/schedules/{schedule_id}/toggle", response_model=ApiResponse)
async def toggle_crawler_schedule(
    schedule_id: str,
    enabled: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """启用/禁用定时任务"""
    service = CrawlerScheduleService(db)
    schedule = await service.toggle_schedule(schedule_id, enabled)
    if not schedule:
        return ApiResponse(code=404, message="定时任务不存在")
    return ApiResponse(
        code=200,
        message="success",
        data={"id": schedule.id, "is_enabled": schedule.is_enabled}
    )


@router.get("/crawler/schedules/{schedule_id}/runs", response_model=ApiResponse)
async def get_schedule_runs(
    schedule_id: str,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
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
            "items": [{
                "id": r.id,
                "schedule_id": r.schedule_id,
                "task_id": r.task_id,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration": r.duration,
                "total_requests": r.total_requests,
                "success_count": r.success_count,
                "failed_count": r.failed_count,
                "error_message": r.error_message,
            } for r in runs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


# ========== 日志系统 ==========

@router.get("/crawler/logs", response_model=ApiResponse)
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
    db: AsyncSession = Depends(get_db)
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
            "items": [{
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
                "created_at": log.created_at.isoformat() if log.created_at else None,
            } for log in logs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/crawler/logs/export")
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
    db: AsyncSession = Depends(get_db)
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
            content=jsonable_encoder({
                "items": rows,
                "total": total,
                "exported": len(rows),
            }),
            headers=headers,
        )

    return Response(
        content=service.to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get("/crawler/file-logs", response_model=ApiResponse)
async def get_crawler_file_logs(
    task_id: Optional[str] = None,
    repo_name: Optional[str] = None,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db)
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
    success_query = select(func.count()).select_from(DownloadedFile).where(DownloadedFile.status != "failed")
    failed_query = select(func.count()).select_from(DownloadedFile).where(DownloadedFile.status == "failed")
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
            "items": [{
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
            } for f in files],
            "total": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/crawler/file-logs/repos", response_model=ApiResponse)
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


@router.get("/crawler/logs/analysis", response_model=ApiResponse)
async def get_log_analysis(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """获取日志分析"""
    service = CrawlerLogService(db)
    analysis = await service.get_analysis(days)
    return ApiResponse(code=200, message="success", data=analysis)


# ========== WebSocket 实时日志 ==========

@router.websocket("/crawler/logs/stream")
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
                    await websocket.send_text(json.dumps({
                        "type": "filter_updated",
                        "task_ids": list(new_task_ids),
                        "source_ids": list(new_source_ids),
                        "levels": list(new_levels),
                    }))
            except json.JSONDecodeError:
                logger.warning(f"Invalid WebSocket message: {data}")

    except WebSocketDisconnect:
        await log_websocket_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await log_websocket_manager.disconnect(websocket)


# ========== 对话管理相关 ==========

@router.get("/conversations", response_model=ApiResponse)
async def get_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    分页查询对话会话列表。
    支持按首条消息/标题模糊搜索。
    """
    from app.models.mysql_models import ChatSession
    from sqlalchemy import select, func, or_

    query = select(ChatSession).order_by(ChatSession.updated_at.desc())
    count_query = select(func.count(ChatSession.id))

    if q:
        like = f"%{q}%"
        cond = or_(ChatSession.title.like(like), ChatSession.first_message.like(like))
        query = query.where(cond)
        count_query = count_query.where(cond)

    total = (await db.execute(count_query)).scalar_one() or 0
    rows = (await db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    items = [
        {
            "id": s.id,
            "title": s.title,
            "first_message": s.first_message,
            "last_message": s.last_message,
            "message_count": int(s.message_count or 0),
            "has_knowledge": bool(s.has_knowledge),
            "created_at": (s.created_at.isoformat() + "Z") if s.created_at else None,
            "updated_at": (s.updated_at.isoformat() + "Z") if s.updated_at else None,
        }
        for s in rows
    ]

    return ApiResponse(data={
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "total_pages": (int(total) + page_size - 1) // page_size if total else 0,
    })


# ========== 系统监控相关 ==========

@router.get("/monitor/api", response_model=ApiResponse)
async def get_api_monitor(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    """API 性能监控数据：聚合 api_call_stats，返回延迟分布/接口排行/慢接口"""
    from app.services.monitor_service import get_api_stats_overview
    metrics = await get_api_stats_overview(db, hours=hours)
    return ApiResponse(data=metrics)


@router.get("/monitor/database", response_model=ApiResponse)
async def get_database_monitor():
    """数据库连接状态：MySQL / Redis / Qdrant 探活"""
    from app.services.monitor_service import get_database_status_extended
    return ApiResponse(data=await get_database_status_extended())


@router.get("/monitor/errors", response_model=ApiResponse)
async def get_error_logs(
    level: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = None,
    logger_name: Optional[str] = None,
    request_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """服务日志查询。默认返回 ERROR 级别，支持按级别 / logger / 关键字 / 时间过滤。"""
    from app.services.monitor_service import query_service_logs
    from datetime import datetime as _dt

    def _parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    result = await query_service_logs(
        session=db,
        page=page,
        page_size=page_size,
        level=level or "ERROR",
        logger_name=logger_name,
        keyword=keyword,
        request_id=request_id,
        start_time=_parse_dt(start_time),
        end_time=_parse_dt(end_time),
    )
    return ApiResponse(data=result)


@router.get("/monitor/logs", response_model=ApiResponse)
async def get_service_logs(
    level: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    keyword: Optional[str] = None,
    logger_name: Optional[str] = None,
    request_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """服务日志全量查询（含 INFO / DEBUG / WARNING / ERROR）"""
    from app.services.monitor_service import query_service_logs
    from datetime import datetime as _dt

    def _parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    result = await query_service_logs(
        session=db,
        page=page,
        page_size=page_size,
        level=level,
        logger_name=logger_name,
        keyword=keyword,
        request_id=request_id,
        start_time=_parse_dt(start_time),
        end_time=_parse_dt(end_time),
    )
    return ApiResponse(data=result)


@router.get("/monitor/logs/stats", response_model=ApiResponse)
async def get_service_logs_stats(
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    from app.services.monitor_service import get_service_log_stats
    return ApiResponse(data=await get_service_log_stats(db, hours=hours))


@router.delete("/monitor/logs", response_model=ApiResponse)
async def delete_service_logs_endpoint(
    older_than_days: Optional[int] = Query(None, ge=0, description="删除 N 天前的日志"),
    level: Optional[str] = Query(None, description="可选限定级别"),
    db: AsyncSession = Depends(get_db),
):
    from app.services.monitor_service import delete_service_logs
    deleted = await delete_service_logs(db, older_than_days=older_than_days, level=level)
    return ApiResponse(data={"deleted": deleted})


@router.post("/monitor/logs/archive", response_model=ApiResponse)
async def archive_service_logs_endpoint(
    older_than_days: int = Query(30, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
):
    """把 N 天前的服务日志导出到 .ndjson.gz 后清库"""
    from app.services.monitor_service import archive_service_logs
    return ApiResponse(data=await archive_service_logs(db, older_than_days=older_than_days))


@router.get("/monitor/system", response_model=ApiResponse)
async def get_system_metrics(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    """系统资源（CPU/内存/磁盘）：最新值 + 时序"""
    from app.services.monitor_service import get_system_metrics_latest, get_system_metrics_series
    latest = await get_system_metrics_latest(db)
    series = await get_system_metrics_series(db, hours=hours)
    return ApiResponse(data={"latest": latest, "series": series, "window_hours": hours})


# ========== 系统配置相关 ==========

@router.get("/settings", response_model=ApiResponse)
async def get_settings(db: Optional[AsyncSession] = Depends(get_optional_db)):
    """
    获取系统配置
    
    返回当前系统配置，优先读取数据库持久化内容。
    """
    from app.services.document_parsers import get_supported_parser_names, inspect_parser_health
    from app.services.system_settings_service import SystemSettingsService, LLM_CONFIG_KEYS

    runtime_settings = await SystemSettingsService(db).load()
    # 对所有 LLM 配置块统一脱敏 api_key
    masked_llm: Dict[str, Any] = {}
    for key in LLM_CONFIG_KEYS:
        block = dict(runtime_settings.get(key, {}) or {})
        if block.get("api_key"):
            block["api_key"] = SECRET_KEEP_MASK
        masked_llm[key] = block

    active_parser = runtime_settings["pdf_parser"]["active_parser"]
    parser_runtime_config = runtime_settings["pdf_parser"]
    available_parsers = []
    for parser_name in get_supported_parser_names():
        parser_status = inspect_parser_health(parser_name, parser_runtime_config)
        parser_status["is_active"] = parser_name == active_parser
        available_parsers.append(parser_status)
    active_runtime_status = next(
        (item for item in available_parsers if item["is_active"]),
        None,
    )

    return ApiResponse(
        code=200,
        message="success",
        data={
            "llm": masked_llm["llm"],
            "pdf_structure_llm": masked_llm["pdf_structure_llm"],
            "outline_llm": masked_llm["outline_llm"],
            "embedding": masked_llm["embedding"],
            "doc_meta_llm": masked_llm["doc_meta_llm"],
            "enrich_llm": masked_llm["enrich_llm"],
            "pdf_parser": {
                "active_parser": active_parser,
                "service_mode": runtime_settings["pdf_parser"]["service_mode"],
                "service_switch_notes": runtime_settings["pdf_parser"]["service_switch_notes"],
                "deployment_target": runtime_settings["pdf_parser"]["deployment_target"],
                "local_service_endpoint": runtime_settings["pdf_parser"]["local_service_endpoint"],
                "remote_service_endpoint": runtime_settings["pdf_parser"]["remote_service_endpoint"],
                "request_timeout_seconds": runtime_settings["pdf_parser"]["request_timeout_seconds"],
                "processing_window_size": runtime_settings["pdf_parser"]["processing_window_size"],
                "active_runtime_status": active_runtime_status,
                "available_parsers": available_parsers,
            }
        }
    )


@router.get("/settings/pdf-parser/history", response_model=ApiResponse)
async def get_pdf_parser_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取 PDF 解析器切换历史"""
    from app.models.mysql_models import AuditLog

    query = (
        select(AuditLog)
        .where(
            AuditLog.action == "pdf_parser_switch",
            AuditLog.resource_type == "system_config",
            AuditLog.resource_id == "pdf_parser",
        )
        .order_by(AuditLog.created_at.desc())
    )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.scalars().all()

    items = [
        {
            "id": row.id,
            "old_parser": row.old_values.get("active_parser") if row.old_values else None,
            "new_parser": row.new_values.get("active_parser") if row.new_values else None,
            "old_target": row.old_values.get("deployment_target") if row.old_values else None,
            "new_target": row.new_values.get("deployment_target") if row.new_values else None,
            "switch_notes": (row.new_values or {}).get("switch_notes", ""),
            "user_id": row.user_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]

    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


def _build_llm_client(kind: str, config: dict):
    """按配置块 kind 构造对应客户端。embedding 返回 EmbeddingService，其余返回 BaseLLMClient 子类。"""
    from app.services.llm_client import (
        ChatLLMClient, PDFStructureLLMClient, OutlineLLMClient, DocMetaLLMClient,
        EnrichLLMClient,
    )
    if kind == "llm":
        return ChatLLMClient(config)
    if kind == "pdf_structure_llm":
        return PDFStructureLLMClient(config)
    if kind == "outline_llm":
        return OutlineLLMClient(config)
    if kind == "doc_meta_llm":
        return DocMetaLLMClient(config)
    if kind == "enrich_llm":
        return EnrichLLMClient(config)
    if kind == "embedding":
        from app.services.embedding_service import EmbeddingService
        return EmbeddingService(config)
    raise HTTPException(status_code=400, detail=f"未知的 LLM 配置块: {kind}")


@router.get("/settings/llm/{kind}/status", response_model=ApiResponse)
async def get_llm_status(kind: str, db: AsyncSession = Depends(get_db)):
    """获取指定 LLM 配置块状态，不发起外部请求。kind ∈ llm/pdf_structure_llm/outline_llm/embedding。"""
    from app.services.system_settings_service import SystemSettingsService, LLM_CONFIG_KEYS

    if kind not in LLM_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail=f"未知的 LLM 配置块: {kind}")

    runtime_settings = await SystemSettingsService(db).load()
    config = runtime_settings.get(kind, {}) or {}

    if kind == "embedding":
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService(config)
        is_local = svc.provider == "local_bge_m3"
        has_key = bool(svc.api_key)
        issues = []
        if not bool(config.get("enabled")):
            issues.append("未启用向量化配置")
        if not svc.model:
            issues.append("未配置模型")
        if not is_local and not has_key:
            issues.append("未配置 API Key，且 OPENAI_API_KEY 环境变量为空")
        is_available = bool(config.get("enabled")) and bool(svc.model and (is_local or has_key))
        return ApiResponse(data={
            "enabled": bool(config.get("enabled")),
            "provider": svc.provider,
            "model": svc.model,
            "base_url": svc.base_url if not is_local else "(本地模型)",
            "dimension": svc.dimension,
            "has_api_key": has_key,
            "uses_env_api_key": not is_local and has_key and not bool(config.get("api_key")),
            "is_available": is_available,
            "issues": issues,
        })

    client = _build_llm_client(kind, config if isinstance(config, dict) else {})
    issues = []
    if not client.enabled:
        issues.append("未启用该 LLM")
    if client.provider != "openai_compatible":
        issues.append("当前仅支持 OpenAI 兼容接口")
    if not client.model:
        issues.append("未配置模型")
    if not client.api_key:
        issues.append("未配置 API Key，且 OPENAI_API_KEY 环境变量为空")

    return ApiResponse(data={
        "enabled": client.enabled,
        "provider": client.provider,
        "model": client.model,
        "base_url": client.base_url,
        "has_api_key": bool(client.api_key),
        "uses_env_api_key": bool(client.api_key) and not bool((config or {}).get("api_key")),
        "is_available": client.is_available,
        "issues": issues,
    })


@router.post("/settings/llm/{kind}/test", response_model=ApiResponse)
async def test_llm(
    kind: str,
    data: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
):
    """按当前表单或已保存配置测试指定 LLM 配置块的连通性。"""
    from app.services.system_settings_service import SystemSettingsService, LLM_CONFIG_KEYS

    if kind not in LLM_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail=f"未知的 LLM 配置块: {kind}")

    runtime_service = SystemSettingsService(db)
    current_settings = await runtime_service.load()
    current_config = current_settings.get(kind, {})
    payload = dict(data or {})
    if payload.get("api_key") == SECRET_KEEP_MASK:
        payload["api_key"] = current_config.get("api_key", "")
    merged_config = dict(current_config if isinstance(current_config, dict) else {})
    merged_config.update(payload)

    if kind == "embedding":
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService(merged_config)
        is_local = svc.provider == "local_bge_m3"
        if not is_local and not (svc.model and svc.api_key):
            return ApiResponse(code=400, message="向量化配置不可用", data={
                "success": False, "model": svc.model, "has_api_key": bool(svc.api_key),
                "error": "请确认模型和 API Key 已配置（或设置 OPENAI_API_KEY 环境变量）。",
            })
        if not svc.model:
            return ApiResponse(code=400, message="向量化配置不可用", data={
                "success": False, "model": svc.model,
                "error": "请配置模型名称。",
            })
        try:
            vec = await svc.embed_text("连通性测试")
        except Exception as e:
            return ApiResponse(code=502, message="向量化测试失败", data={
                "success": False, "model": svc.model, "base_url": svc.base_url or "(本地模型)",
                "error": str(e)[:500],
            })
        return ApiResponse(data={
            "success": True, "model": svc.model, "base_url": svc.base_url or "(本地模型)",
            "dimension": len(vec), "configured_dimension": svc.dimension,
            "dimension_match": len(vec) == svc.dimension,
        })

    client = _build_llm_client(kind, merged_config)
    if not client.is_available:
        return ApiResponse(code=400, message="LLM 配置不可用", data={
            "success": False, "enabled": client.enabled, "provider": client.provider,
            "model": client.model, "has_api_key": bool(client.api_key),
            "error": "请确认已启用、模型和 API Key 已配置，且服务类型为 OpenAI 兼容接口。",
        })

    try:
        reply = await client.chat("请只回复：LLM_OK", purpose="配置连通性测试")
    except Exception as e:
        return ApiResponse(code=502, message="LLM 测试失败", data={
            "success": False, "provider": client.provider, "model": client.model,
            "base_url": client.base_url, "error": str(e)[:500],
        })

    return ApiResponse(data={
        "success": True, "provider": client.provider, "model": client.model,
        "base_url": client.base_url, "reply": reply[:200],
    })


@router.put("/settings", response_model=ApiResponse)
async def update_settings(
    data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    更新系统配置
    
    所有顶级 section 统一落库；PDF 解析器切换额外记录审计日志。
    """
    from app.services.system_settings_service import SystemSettingsService, LLM_CONFIG_KEYS

    runtime_service = SystemSettingsService(db)
    auth_header = request.headers.get("Authorization", "")
    user_id: Optional[str] = None
    if auth_header.startswith("Bearer mock_jwt_token_"):
        user_id = auth_header.replace("Bearer mock_jwt_token_", "", 1)

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    current_settings = await runtime_service.load()
    payload = dict(data or {})
    # 所有 LLM 配置块：api_key 为脱敏占位符时回填已保存的真实值
    for key in LLM_CONFIG_KEYS:
        section = payload.get(key)
        if isinstance(section, dict) and section.get("api_key") == SECRET_KEEP_MASK:
            section["api_key"] = current_settings.get(key, {}).get("api_key", "")
    parser_section = payload.pop("pdf_parser", None) if isinstance(payload.get("pdf_parser"), dict) else None
    saved_runtime = await runtime_service.save_partial(payload) if payload else current_settings

    if parser_section is not None:
        try:
            saved_runtime = await runtime_service.update_pdf_parser(
                parser_name=parser_section.get("active_parser", current_settings["pdf_parser"]["active_parser"]),
                deployment_target=parser_section.get(
                    "deployment_target",
                    current_settings["pdf_parser"]["deployment_target"],
                ),
                local_service_endpoint=parser_section.get(
                    "local_service_endpoint",
                    current_settings["pdf_parser"]["local_service_endpoint"],
                ),
                remote_service_endpoint=parser_section.get(
                    "remote_service_endpoint",
                    current_settings["pdf_parser"]["remote_service_endpoint"],
                ),
                request_timeout_seconds=parser_section.get(
                    "request_timeout_seconds",
                    current_settings["pdf_parser"]["request_timeout_seconds"],
                ),
                processing_window_size=parser_section.get(
                    "processing_window_size",
                    current_settings["pdf_parser"]["processing_window_size"],
                ),
                switch_notes=parser_section.get("service_switch_notes", ""),
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    response_runtime = dict(saved_runtime)
    # 所有 LLM 配置块：响应里脱敏 api_key
    for key in LLM_CONFIG_KEYS:
        block = dict(response_runtime.get(key, {}) or {})
        if block.get("api_key"):
            block["api_key"] = SECRET_KEEP_MASK
            response_runtime[key] = block

    return ApiResponse(code=200, message="保存成功", data=response_runtime)




# ========== 对话详情相关 ==========

@router.get("/conversations/{conversation_id}", response_model=ApiResponse)
async def get_conversation_detail(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取对话详情：会话基本信息 + 完整消息列表。
    """
    from app.models.mysql_models import ChatSession, ChatMessageRecord
    from sqlalchemy import select

    chat_session = (await db.execute(
        select(ChatSession).where(ChatSession.id == conversation_id)
    )).scalar_one_or_none()
    if not chat_session:
        raise HTTPException(status_code=404, detail="会话不存在")

    msgs = (await db.execute(
        select(ChatMessageRecord)
        .where(ChatMessageRecord.session_id == conversation_id)
        .order_by(ChatMessageRecord.id)
    )).scalars().all()

    return ApiResponse(data={
        "id": chat_session.id,
        "title": chat_session.title,
        "first_message": chat_session.first_message,
        "last_message": chat_session.last_message,
        "message_count": int(chat_session.message_count or 0),
        "has_knowledge": bool(chat_session.has_knowledge),
        "metadata_json": chat_session.metadata_json,
        "created_at": (chat_session.created_at.isoformat() + "Z") if chat_session.created_at else None,
        "updated_at": (chat_session.updated_at.isoformat() + "Z") if chat_session.updated_at else None,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "llm_call_id": m.llm_call_id,
                "timestamp": (m.created_at.isoformat() + "Z") if m.created_at else None,
            }
            for m in msgs
        ],
    })


@router.delete("/conversations/{conversation_id}", response_model=ApiResponse)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除会话及其所有消息。"""
    from app.models.mysql_models import ChatSession
    from sqlalchemy import delete as sa_delete

    result = await db.execute(sa_delete(ChatSession).where(ChatSession.id == conversation_id))
    await db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ApiResponse(data={"deleted": int(result.rowcount or 0)})

# ========== P1: 用户管理相关 ==========



class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=6)
    role: str = Field(default="operator")
    permissions: List[str] = Field(default_factory=list)
    is_active: bool = Field(default=True)


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None


@router.get("/users", response_model=ApiResponse)
async def get_users(db: AsyncSession = Depends(get_db)):
    """获取用户列表"""
    from app.models.mysql_models import AdminUser

    result = await db.execute(select(AdminUser).order_by(AdminUser.created_at.desc()))
    users = result.scalars().all()

    return ApiResponse(
        code=200,
        message="success",
        data={"users": [_admin_user_to_dict(user) for user in users]}
    )


@router.post("/users", response_model=ApiResponse)
async def create_user(
    req: CreateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建用户"""
    from app.models.mysql_models import AdminUser

    existing = await db.scalar(
        select(AdminUser).where(
            or_(AdminUser.username == req.username, AdminUser.email == req.email)
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

    user = AdminUser(
        id=uuid.uuid4().hex[:32],
        username=req.username,
        email=req.email,
        password_hash=_hash_admin_password(req.password),
        role=req.role,
        permissions=req.permissions,
        is_active=req.is_active,
    )
    db.add(user)
    await _add_admin_audit_log(
        db,
        request,
        action="admin_user_create",
        resource_id=user.id,
        new_values=_admin_user_to_dict(user),
    )
    await db.commit()

    return ApiResponse(code=200, message="创建成功", data={"user": _admin_user_to_dict(user)})


@router.put("/users/{user_id}", response_model=ApiResponse)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新用户"""
    from app.models.mysql_models import AdminUser

    user = await db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    old_values = _admin_user_to_dict(user)

    if req.email is not None and req.email != user.email:
        existing = await db.scalar(
            select(AdminUser).where(AdminUser.email == req.email, AdminUser.id != user_id)
        )
        if existing:
            raise HTTPException(status_code=400, detail="邮箱已存在")
        user.email = req.email
    if req.role is not None:
        user.role = req.role
    if req.permissions is not None:
        user.permissions = req.permissions
    if req.is_active is not None:
        user.is_active = req.is_active

    await _add_admin_audit_log(
        db,
        request,
        action="admin_user_update",
        resource_id=user.id,
        old_values=old_values,
        new_values=_admin_user_to_dict(user),
    )
    await db.commit()
    await db.refresh(user)

    return ApiResponse(code=200, message="更新成功", data={"user": _admin_user_to_dict(user)})


@router.delete("/users/{user_id}", response_model=ApiResponse)
async def delete_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """删除用户"""
    from app.models.mysql_models import AdminUser

    user = await db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="默认管理员不能删除")

    old_values = _admin_user_to_dict(user)
    await db.delete(user)
    await _add_admin_audit_log(
        db,
        request,
        action="admin_user_delete",
        resource_id=user_id,
        old_values=old_values,
    )
    await db.commit()

    return ApiResponse(code=200, message="删除成功")


def _admin_user_to_dict(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "permissions": user.permissions or [],
        "is_active": bool(user.is_active),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def _add_admin_audit_log(
    db: AsyncSession,
    request: Request,
    action: str,
    resource_id: str,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
) -> None:
    from app.models.mysql_models import AuditLog

    auth_header = request.headers.get("Authorization", "")
    user_id: Optional[str] = None
    if auth_header.startswith("Bearer mock_jwt_token_"):
        user_id = auth_header.replace("Bearer mock_jwt_token_", "", 1)

    db.add(AuditLog(
        user_id=user_id,
        action=action,
        resource_type="admin_user",
        resource_id=resource_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    ))


def _hash_admin_password(password: str) -> str:
    """生成稳定的管理员密码哈希；当前用户管理不改变现有 mock 登录链路。"""
    iterations = 260_000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


# ========== 学科管理 ==========

@router.get("/subjects", response_model=ApiResponse)
async def get_subjects(db: AsyncSession = Depends(get_db)):
    """获取学科列表"""
    from app.models.mysql_models import Subject
    result = await db.execute(
        select(Subject).where(Subject.status == "active").order_by(Subject.sort_order)
    )
    subjects = result.scalars().all()
    return ApiResponse(data={
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "code": s.code,
                "description": s.description,
                "icon": s.icon,
                "sort_order": s.sort_order
            }
            for s in subjects
        ],
        "total": len(subjects)
    })


@router.get("/subjects/{subject_id}/chapters", response_model=ApiResponse)
async def get_chapters(subject_id: str, db: AsyncSession = Depends(get_db)):
    """获取学科下的章节列表"""
    from app.models.mysql_models import Chapter
    result = await db.execute(
        select(Chapter)
        .where(Chapter.subject_id == subject_id, Chapter.status == "active")
        .order_by(Chapter.sort_order)
    )
    chapters = result.scalars().all()
    return ApiResponse(data={
        "items": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "sort_order": c.sort_order
            }
            for c in chapters
        ],
        "total": len(chapters)
    })


# ========== 知识点管理 ==========

@router.get("/knowledge/points", response_model=ApiResponse)
async def get_knowledge_points(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    subject_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    difficulty: Optional[str] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取知识点列表"""
    from app.models.mysql_models import KnowledgePoint

    query = select(KnowledgePoint).where(KnowledgePoint.status != "deleted")

    if subject_id:
        query = query.where(KnowledgePoint.subject_id == subject_id)
    if chapter_id:
        query = query.where(KnowledgePoint.chapter_id == chapter_id)
    if difficulty:
        query = query.where(KnowledgePoint.difficulty == difficulty)
    if keyword:
        query = query.where(KnowledgePoint.title.contains(keyword))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Paginate
    query = query.order_by(KnowledgePoint.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    points = result.scalars().all()

    return ApiResponse(data={
        "items": [
            {
                "id": p.id,
                "chapter_id": p.chapter_id,
                "subject_id": p.subject_id,
                "title": p.title,
                "content": p.content[:200] if p.content else "",
                "difficulty": p.difficulty,
                "exam_frequency": p.exam_frequency,
                "tags": p.tags,
                "source": p.source,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None
            }
            for p in points
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    })


@router.get("/knowledge/points/{point_id}", response_model=ApiResponse)
async def get_knowledge_point_detail(point_id: str, db: AsyncSession = Depends(get_db)):
    """获取知识点详情（含关联资产）"""
    from app.models.mysql_models import KnowledgePoint
    from app.services.entity_asset_service import get_entity_assets
    result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.id == point_id)
    )
    point = result.scalar_one_or_none()
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")

    assets = await get_entity_assets(db, entity_type="knowledge_point", entity_id=point_id)

    return ApiResponse(data={
        "id": point.id,
        "chapter_id": point.chapter_id,
        "subject_id": point.subject_id,
        "title": point.title,
        "content": point.content,
        "difficulty": point.difficulty,
        "exam_frequency": point.exam_frequency,
        "tags": point.tags,
        "key_points": point.key_points,
        "related_point_ids": point.related_point_ids,
        "source": point.source,
        "source_page": point.source_page,
        "status": point.status,
        "assets": assets,
        "created_at": point.created_at.isoformat() if point.created_at else None,
        "updated_at": point.updated_at.isoformat() if point.updated_at else None
    })


class UpdateKnowledgePointRequest(BaseModel):
    """更新知识点请求"""
    title: Optional[str] = None
    content: Optional[str] = None
    difficulty: Optional[str] = None
    exam_frequency: Optional[str] = None
    tags: Optional[List[str]] = None
    key_points: Optional[List[str]] = None
    status: Optional[str] = None


@router.put("/knowledge/points/{point_id}", response_model=ApiResponse)
async def update_knowledge_point(
    point_id: str,
    req: UpdateKnowledgePointRequest,
    db: AsyncSession = Depends(get_db)
):
    """更新知识点"""
    from app.models.mysql_models import KnowledgePoint
    result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.id == point_id)
    )
    point = result.scalar_one_or_none()
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")

    if req.title is not None:
        point.title = req.title
    if req.content is not None:
        point.content = req.content
    if req.difficulty is not None:
        point.difficulty = req.difficulty
    if req.exam_frequency is not None:
        point.exam_frequency = req.exam_frequency
    if req.tags is not None:
        point.tags = req.tags
    if req.key_points is not None:
        point.key_points = req.key_points
    if req.status is not None:
        point.status = req.status

    await db.commit()
    return ApiResponse(message="更新成功")


@router.delete("/knowledge/points/{point_id}", response_model=ApiResponse)
async def delete_knowledge_point(
    point_id: str,
    db: AsyncSession = Depends(get_db)
):
    """删除单个知识点（软删除，并清理关联边）"""
    from app.models.mysql_models import (
        KnowledgePoint, RetrievalSegment, KnowledgePointChapterLink,
        QuestionKnowledgeLink, KnowledgeRelation, EntitySourceLink
    )

    point = await db.get(KnowledgePoint, point_id)
    if not point or point.status == "deleted":
        raise HTTPException(status_code=404, detail="知识点不存在")

    point.status = "deleted"
    point.review_status = "rejected"

    await db.execute(
        delete(RetrievalSegment).where(
            RetrievalSegment.entity_type == "knowledge_point",
            RetrievalSegment.entity_id == point_id,
        )
    )
    await db.execute(
        delete(KnowledgePointChapterLink).where(
            KnowledgePointChapterLink.knowledge_point_id == point_id
        )
    )
    await db.execute(
        delete(QuestionKnowledgeLink).where(
            QuestionKnowledgeLink.knowledge_point_id == point_id
        )
    )
    await db.execute(
        delete(KnowledgeRelation).where(
            or_(
                KnowledgeRelation.source_knowledge_id == point_id,
                KnowledgeRelation.target_knowledge_id == point_id,
            )
        )
    )
    await db.execute(
        delete(EntitySourceLink).where(
            EntitySourceLink.entity_type == "knowledge_point",
            EntitySourceLink.entity_id == point_id,
        )
    )
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": point_id})


@router.post("/knowledge/points/batch-delete", response_model=ApiResponse)
async def batch_delete_knowledge_points(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db)
):
    """批量删除知识点（软删除）"""
    from app.models.mysql_models import (
        KnowledgePoint, RetrievalSegment, KnowledgePointChapterLink,
        QuestionKnowledgeLink, KnowledgeRelation, EntitySourceLink
    )

    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(KnowledgePoint.id).where(
            KnowledgePoint.id.in_(unique_ids),
            KnowledgePoint.status != "deleted",
        )
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的知识点")

    await db.execute(
        update(KnowledgePoint)
        .where(KnowledgePoint.id.in_(existing_ids))
        .values(status="deleted", review_status="rejected")
    )
    await db.execute(
        delete(RetrievalSegment).where(
            RetrievalSegment.entity_type == "knowledge_point",
            RetrievalSegment.entity_id.in_(existing_ids),
        )
    )
    await db.execute(
        delete(KnowledgePointChapterLink).where(
            KnowledgePointChapterLink.knowledge_point_id.in_(existing_ids)
        )
    )
    await db.execute(
        delete(QuestionKnowledgeLink).where(
            QuestionKnowledgeLink.knowledge_point_id.in_(existing_ids)
        )
    )
    await db.execute(
        delete(KnowledgeRelation).where(
            or_(
                KnowledgeRelation.source_knowledge_id.in_(existing_ids),
                KnowledgeRelation.target_knowledge_id.in_(existing_ids),
            )
        )
    )
    await db.execute(
        delete(EntitySourceLink).where(
            EntitySourceLink.entity_type == "knowledge_point",
            EntitySourceLink.entity_id.in_(existing_ids),
        )
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={"deleted_count": len(existing_ids), "requested_count": len(unique_ids)}
    )


# ========== 题目管理 ==========

@router.get("/questions", response_model=ApiResponse)
async def get_questions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    subject_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    type: Optional[str] = None,
    difficulty: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取题目列表"""
    from app.models.mysql_models import Question

    query = select(Question).where(Question.status != "deleted")

    if subject_id:
        query = query.where(Question.subject_id == subject_id)
    if chapter_id:
        query = query.where(Question.chapter_id == chapter_id)
    if type:
        query = query.where(Question.type == type)
    if difficulty:
        query = query.where(Question.difficulty == difficulty)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Paginate
    query = query.order_by(Question.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    questions = result.scalars().all()

    return ApiResponse(data={
        "items": [
            {
                "id": q.id,
                "subject_id": q.subject_id,
                "chapter_id": q.chapter_id,
                "type": q.type,
                "content": q.content[:200] if q.content else "",
                "difficulty": q.difficulty,
                "source": q.source,
                "exam_year": q.exam_year,
                "status": q.status,
                "created_at": q.created_at.isoformat() if q.created_at else None
            }
            for q in questions
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    })


@router.get("/questions/{question_id}", response_model=ApiResponse)
async def get_question_detail(question_id: str, db: AsyncSession = Depends(get_db)):
    """获取题目详情（含关联资产）"""
    from app.models.mysql_models import Question
    from app.services.entity_asset_service import get_entity_assets
    result = await db.execute(
        select(Question).where(Question.id == question_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    assets = await get_entity_assets(db, entity_type="question", entity_id=question_id)

    # 所考知识点（含名称），供"查题反查知识点"展示
    from app.models.mysql_models import QuestionKnowledgeLink, KnowledgePoint
    kp_rows = (await db.execute(
        select(KnowledgePoint.id, KnowledgePoint.title, QuestionKnowledgeLink.relevance)
        .join(QuestionKnowledgeLink, QuestionKnowledgeLink.knowledge_point_id == KnowledgePoint.id)
        .where(QuestionKnowledgeLink.question_id == question_id)
        .order_by(QuestionKnowledgeLink.relevance.desc())
    )).all()
    knowledge_points = [
        {"id": r[0], "title": r[1], "relevance": float(r[2] or 0)} for r in kp_rows
    ]

    return ApiResponse(data={
        "id": question.id,
        "subject_id": question.subject_id,
        "chapter_id": question.chapter_id,
        "type": question.type,
        "content": question.content,
        "options": question.options,
        "answer": question.answer,
        "explanation": question.explanation,
        "answer_source": question.answer_source,
        "explanation_source": question.explanation_source,
        "enrich_status": question.enrich_status,
        "difficulty": question.difficulty,
        "source": question.source,
        "exam_year": question.exam_year,
        "exam_scope": question.exam_scope,
        "paper_name": question.paper_name,
        "knowledge_point_ids": question.knowledge_point_ids,
        "knowledge_points": knowledge_points,
        "tags": question.tags,
        "status": question.status,
        "assets": assets,
        "created_at": question.created_at.isoformat() if question.created_at else None,
        "updated_at": question.updated_at.isoformat() if question.updated_at else None
    })


class UpdateQuestionRequest(BaseModel):
    """更新题目请求"""
    content: Optional[str] = None
    options: Optional[List[dict]] = None
    answer: Optional[str] = None
    explanation: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None


@router.put("/questions/{question_id}", response_model=ApiResponse)
async def update_question(
    question_id: str,
    req: UpdateQuestionRequest,
    db: AsyncSession = Depends(get_db)
):
    """更新题目"""
    from app.models.mysql_models import Question
    result = await db.execute(
        select(Question).where(Question.id == question_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    if req.content is not None:
        question.content = req.content
    if req.options is not None:
        question.options = req.options
    if req.answer is not None:
        question.answer = req.answer
    if req.explanation is not None:
        question.explanation = req.explanation
    if req.difficulty is not None:
        question.difficulty = req.difficulty
    if req.tags is not None:
        question.tags = req.tags
    if req.status is not None:
        question.status = req.status

    await db.commit()
    return ApiResponse(message="更新成功")


@router.delete("/questions/{question_id}", response_model=ApiResponse)
async def delete_question(
    question_id: str,
    db: AsyncSession = Depends(get_db)
):
    """删除单个题目（软删除，并清理关联边）"""
    from app.models.mysql_models import (
        Question, RetrievalSegment, QuestionChapterLink,
        QuestionKnowledgeLink, EntitySourceLink
    )

    question = await db.get(Question, question_id)
    if not question or question.status == "deleted":
        raise HTTPException(status_code=404, detail="题目不存在")

    question.status = "deleted"
    question.review_status = "rejected"

    await db.execute(
        delete(RetrievalSegment).where(
            RetrievalSegment.entity_type == "question",
            RetrievalSegment.entity_id == question_id,
        )
    )
    await db.execute(
        delete(QuestionChapterLink).where(
            QuestionChapterLink.question_id == question_id
        )
    )
    await db.execute(
        delete(QuestionKnowledgeLink).where(
            QuestionKnowledgeLink.question_id == question_id
        )
    )
    await db.execute(
        delete(EntitySourceLink).where(
            EntitySourceLink.entity_type == "question",
            EntitySourceLink.entity_id == question_id,
        )
    )
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": question_id})


@router.post("/questions/batch-delete", response_model=ApiResponse)
async def batch_delete_questions(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db)
):
    """批量删除题目（软删除）"""
    from app.models.mysql_models import (
        Question, RetrievalSegment, QuestionChapterLink,
        QuestionKnowledgeLink, EntitySourceLink
    )

    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(Question.id).where(
            Question.id.in_(unique_ids),
            Question.status != "deleted",
        )
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的题目")

    await db.execute(
        update(Question)
        .where(Question.id.in_(existing_ids))
        .values(status="deleted", review_status="rejected")
    )
    await db.execute(
        delete(RetrievalSegment).where(
            RetrievalSegment.entity_type == "question",
            RetrievalSegment.entity_id.in_(existing_ids),
        )
    )
    await db.execute(
        delete(QuestionChapterLink).where(
            QuestionChapterLink.question_id.in_(existing_ids)
        )
    )
    await db.execute(
        delete(QuestionKnowledgeLink).where(
            QuestionKnowledgeLink.question_id.in_(existing_ids)
        )
    )
    await db.execute(
        delete(EntitySourceLink).where(
            EntitySourceLink.entity_type == "question",
            EntitySourceLink.entity_id.in_(existing_ids),
        )
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={"deleted_count": len(existing_ids), "requested_count": len(unique_ids)}
    )


# ========== PDF入库 ==========

class IngestPdfRequest(BaseModel):
    """PDF入库请求"""
    pdf_path: str = Field(..., description="PDF文件路径")
    subject_id: str = Field(..., description="学科ID")
    chapter_id: str = Field(..., description="章节ID")
    source: Optional[str] = Field(default=None, description="来源说明，如 王道2025/数据结构")


@router.post("/knowledge/ingest", response_model=ApiResponse)
async def ingest_pdf(
    req: IngestPdfRequest,
    db: AsyncSession = Depends(get_db)
):
    """触发PDF入库任务"""
    import uuid
    from app.models.mysql_models import CrawlTask, Subject, Chapter

    # Validate subject exists
    subject = await db.scalar(
        select(Subject).where(Subject.id == req.subject_id)
    )
    if not subject:
        raise HTTPException(status_code=404, detail="学科不存在")

    # Validate chapter exists
    chapter = await db.scalar(
        select(Chapter).where(Chapter.id == req.chapter_id, Chapter.subject_id == req.subject_id)
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在或不属于该学科")

    # Create crawl task
    task_id = f"kp_{uuid.uuid4().hex[:12]}"
    task = CrawlTask(
        id=task_id,
        name=f"PDF入库: {subject.name} - {chapter.name}",
        task_type="targeted",
        source="pdf",
        status="pending",
        config={
            "spider_type": "knowledge",
            "pdf_path": req.pdf_path,
            "subject_id": req.subject_id,
            "chapter_id": req.chapter_id,
            "source": req.source or f"{subject.name}/{chapter.name}",
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Publish to Scrapy queue
    from app.services.scrapy_bridge import ScrapyBridgeService
    bridge = ScrapyBridgeService(db)
    published = await bridge.publish_task(task)
    await bridge.close()

    if not published:
        raise HTTPException(status_code=500, detail="任务发布失败")

    return ApiResponse(
        message="PDF入库任务已创建",
        data={"task_id": task_id}
    )


@router.get("/knowledge/ingest/tasks", response_model=ApiResponse)
async def get_ingest_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """获取PDF入库任务列表"""
    from app.models.mysql_models import CrawlTask

    query = select(CrawlTask).where(
        CrawlTask.source == "pdf"
    ).order_by(CrawlTask.created_at.desc())

    total = await db.scalar(
        select(func.count()).select_from(query.subquery())
    )

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tasks = result.scalars().all()

    return ApiResponse(data={
        "items": [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "progress": float(t.progress) if t.progress else 0,
                "success_count": t.success_count,
                "failed_count": t.failed_count,
                "config": t.config,
                "error_message": t.error_message,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    })


# ========== 已下载文件 ==========

DOWNLOAD_STORE = os.getenv("DOWNLOAD_STORE", str(Path(__file__).parent.parent.parent / "downloads"))


@router.get("/files/downloaded", response_model=ApiResponse)
async def get_downloaded_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    file_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """获取已下载文件列表"""
    from app.models.mysql_models import DownloadedFile

    query = select(DownloadedFile)

    if file_type:
        query = query.where(DownloadedFile.file_type == file_type)
    if status:
        query = query.where(DownloadedFile.status == status)
    if task_id:
        query = query.where(DownloadedFile.task_id == task_id)
    if keyword:
        like_pattern = f"%{keyword}%"
        query = query.where(
            (DownloadedFile.file_name.like(like_pattern)) |
            (DownloadedFile.repo_name.like(like_pattern))
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = query.order_by(DownloadedFile.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    files = result.scalars().all()

    return ApiResponse(data={
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
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in files
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/files/downloaded/{file_id}", response_model=ApiResponse)
async def get_downloaded_file_detail(
    file_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取已下载文件详情"""
    from app.models.mysql_models import DownloadedFile

    result = await db.execute(
        select(DownloadedFile).where(DownloadedFile.id == file_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")

    return ApiResponse(data={
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
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
    })


@router.get("/files/downloaded/{file_id}/preview")
async def preview_downloaded_file(
    file_id: str,
    db: AsyncSession = Depends(get_db)
):
    """预览/下载已下载的文件"""
    from app.models.mysql_models import DownloadedFile

    result = await db.execute(
        select(DownloadedFile).where(DownloadedFile.id == file_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")

    if not f.local_path:
        raise HTTPException(status_code=404, detail="文件路径不存在")

    local_path = Path(f.local_path).resolve()
    download_store = Path(DOWNLOAD_STORE).resolve()

    # 路径安全校验：确保文件在下载目录内
    if not str(local_path).startswith(str(download_store)):
        raise HTTPException(status_code=403, detail="文件路径不允许访问")

    if not local_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在于磁盘")

    media_type = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "ppt": "application/vnd.ms-powerpoint",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }.get(f.file_type or "", "application/octet-stream")

    return FileResponse(
        path=str(local_path),
        media_type=media_type,
        filename=f.file_name,
    )


@router.post("/crawler/file-logs/retry", response_model=ApiResponse)
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

    from app.models.mysql_models import DownloadedFile

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

    return ApiResponse(data={
        "total": len(files),
        "success_count": success_count,
        "fail_count": fail_count,
        "results": results,
    })


# ========== 语料库管理 ==========


class ScanRequest(BaseModel):
    """目录扫描请求"""
    root_path: str = Field(..., description="扫描根目录")
    file_types: Optional[List[str]] = Field(default=None, description="文件类型列表，如 pdf/docx/pptx")
    batch_label: Optional[str] = Field(default=None, description="批次标签")


@router.post("/corpus/files/scan", response_model=ApiResponse)
async def scan_corpus_files(
    req: ScanRequest,
    db: AsyncSession = Depends(get_db),
):
    """扫描目录并注册语料文件"""
    from app.services.corpus_service import CorpusService

    service = CorpusService(db)
    try:
        result = service.scan_and_register(
            root_path=req.root_path,
            file_types=req.file_types,
            batch_label=req.batch_label,
        )
        # scan_and_register 是 async，需要 await
        result = await result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(data=result)


class RegisterFileRequest(BaseModel):
    """单文件注册请求"""
    file_path: str = Field(..., description="文件绝对路径")
    batch_label: Optional[str] = Field(default=None, description="批次标签")


@router.post("/corpus/files/register", response_model=ApiResponse)
async def register_corpus_file(
    req: RegisterFileRequest,
    db: AsyncSession = Depends(get_db),
):
    """注册单个文件到语料库（如已存在则返回已有记录）"""
    from app.services.corpus_service import CorpusService

    service = CorpusService(db)
    try:
        result = await service.register_single_file(
            file_path=req.file_path,
            batch_label=req.batch_label,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(data=result)


class RegisterByDownloadRequest(BaseModel):
    """通过已下载文件ID注册"""
    downloaded_file_id: str = Field(..., description="已下载文件ID")
    batch_label: Optional[str] = Field(default=None, description="批次标签")


@router.post("/corpus/files/register-by-download", response_model=ApiResponse)
async def register_corpus_file_by_download(
    req: RegisterByDownloadRequest,
    db: AsyncSession = Depends(get_db),
):
    """通过已下载文件ID注册到语料库"""
    from app.models.mysql_models import DownloadedFile
    from app.services.corpus_service import CorpusService

    result = await db.execute(
        select(DownloadedFile).where(DownloadedFile.id == req.downloaded_file_id)
    )
    downloaded = result.scalar_one_or_none()
    if not downloaded:
        raise HTTPException(status_code=404, detail="已下载文件不存在")
    if not downloaded.local_path:
        raise HTTPException(status_code=400, detail="该文件未下载到本地，local_path 为空")

    service = CorpusService(db)
    try:
        reg_result = await service.register_single_file(
            file_path=downloaded.local_path,
            batch_label=req.batch_label or downloaded.task_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(data=reg_result)


@router.post("/corpus/files/upload", response_model=ApiResponse)
async def upload_corpus_files(
    files: List[UploadFile] = File(...),
    batch_label: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    上传文件到语料库

    支持批量上传 PDF/DOCX/PPTX 文件
    """
    from app.services.corpus_service import CorpusService, SUPPORTED_EXTENSIONS

    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")

    if len(files) > 50:
        raise HTTPException(status_code=400, detail="单次最多上传50个文件")

    # 创建上传目录
    upload_dir = Path(__file__).parent.parent.parent / "uploads"
    upload_dir.mkdir(exist_ok=True)

    batch = batch_label or f"upload-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    success_items = []
    failed_items = []
    skipped_items = []

    service = CorpusService(db)

    for file in files:
        file_result = {"file_name": file.filename}

        try:
            # 验证文件名
            if not file.filename:
                raise ValueError("文件名为空")

            # 验证文件类型
            ext = Path(file.filename).suffix.lstrip(".").lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise ValueError(f"不支持的文件类型: {ext}，仅支持 {', '.join(SUPPORTED_EXTENSIONS)}")

            # 保存文件到临时路径（带时间戳避免冲突）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            safe_filename = f"{timestamp}_{file.filename}"
            file_path = upload_dir / safe_filename

            # 写入文件
            content = await file.read()
            file_path.write_bytes(content)

            # 注册到语料库
            result = await service.register_single_file(
                file_path=str(file_path),
                batch_label=batch,
            )

            file_result.update({
                "status": "success" if result["is_new"] else "skipped",
                "corpus_file_id": result["corpus_file_id"],
                "is_new": result["is_new"],
            })

            if result["is_new"]:
                success_items.append(file_result)
            else:
                skipped_items.append(file_result)

        except Exception as e:
            file_result["status"] = "failed"
            file_result["error"] = str(e)[:200]
            failed_items.append(file_result)
            logger.warning("文件上传失败", filename=file.filename, error=str(e))

    return ApiResponse(data={
        "batch_label": batch,
        "total": len(files),
        "success_count": len(success_items),
        "skipped_count": len(skipped_items),
        "failed_count": len(failed_items),
        "success_items": success_items,
        "skipped_items": skipped_items,
        "failed_items": failed_items,
    })


@router.get("/corpus/files", response_model=ApiResponse)
async def list_corpus_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    file_ext: Optional[str] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """语料文件列表"""
    from app.services.corpus_service import CorpusService

    service = CorpusService(db)
    result = await service.get_corpus_files(
        page=page,
        page_size=page_size,
        status=status,
        source_type=source_type,
        file_ext=file_ext,
        keyword=keyword,
    )
    return ApiResponse(data=result)


@router.get("/corpus/documents/{document_id}", response_model=ApiResponse)
async def get_document_detail(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """文档详情（含 pages、blocks、assets）"""
    from app.services.document_parse_service import DocumentParseService

    service = DocumentParseService(db)
    result = await service.get_document_detail(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="文档不存在")

    return ApiResponse(data=result)


@router.get("/corpus/files/{file_id}", response_model=ApiResponse)
async def get_corpus_file_detail(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """语料文件详情"""
    from app.services.corpus_service import CorpusService

    service = CorpusService(db)
    result = await service.get_corpus_file_detail(file_id)
    if not result:
        raise HTTPException(status_code=404, detail="语料文件不存在")

    # 同时返回解析记录
    from app.services.document_parse_service import DocumentParseService
    parse_service = DocumentParseService(db)
    parse_runs = await parse_service.get_parse_runs(file_id)
    result["parse_runs"] = parse_runs

    return ApiResponse(data=result)


class ParseCorpusFileRequest(BaseModel):
    """单文件解析请求"""
    parser_name: Optional[Literal["docling", "mineru"]] = Field(
        default=None,
        description="仅用于开发期临时覆盖；正式运行应通过系统设置切换单活解析器",
    )
    parse_mode: Literal["primary", "fallback", "retry", "manual_fix"] = Field(
        default="primary",
        description="解析执行标记，用于区分主解析、重试、人工修复等运行语义",
    )


@router.post("/corpus/files/{file_id}/parse", response_model=ApiResponse)
async def parse_corpus_file(
    file_id: str,
    req: Optional[ParseCorpusFileRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """触发文档解析（异步派发，立即返回 run_id）"""
    from app.services.document_parse_service import DocumentParseService
    from app.services.document_parsers import ParserUnavailableError
    from app.models.mysql_models import CorpusFile, ParseRun
    import asyncio

    # 先检查文件存在
    corpus_file = await db.get(CorpusFile, file_id)
    if not corpus_file:
        raise HTTPException(status_code=404, detail="语料文件不存在")

    # 立即创建 ParseRun 记录（status=running）
    service = DocumentParseService(db)
    parse_req = req or ParseCorpusFileRequest()

    try:
        # 获取解析器信息并创建 run 记录
        parser = await service._get_parser(parse_req.parser_name)
        run_id = service._generate_id()
        parse_run = ParseRun(
            id=run_id,
            corpus_file_id=file_id,
            parser_name=parser.name,
            parser_version=parser.version,
            parse_mode=parse_req.parse_mode or "primary",
            status="running",
            current_stage="parsing",
            stage_detail="准备开始解析...",
        )
        db.add(parse_run)
        await db.commit()
    except ParserUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建解析任务失败: {str(e)[:200]}")

    # 后台异步执行解析（参考 crawler 的模式）
    async def _run_parse_in_background(run_id: str, file_id: str, parser_name: Optional[str], parse_mode: Optional[str]):
        from app.db.mysql import mysql_client
        async with mysql_client.session() as bg_session:
            bg_service = DocumentParseService(bg_session)
            try:
                await bg_service.parse_document_with_run_id(
                    run_id=run_id,
                    corpus_file_id=file_id,
                    parser_name=parser_name,
                    parse_mode=parse_mode,
                )
            except Exception as e:
                logger.error("后台解析任务失败", run_id=run_id, error=str(e))

    asyncio.ensure_future(_run_parse_in_background(
        run_id, file_id, parse_req.parser_name, parse_req.parse_mode
    ))

    return ApiResponse(message="解析任务已启动", data={
        "run_id": run_id,
        "status": "running",
        "corpus_file_id": file_id,
    })


async def _delete_corpus_files_by_ids(
    db: AsyncSession,
    file_ids: List[str],
) -> List[CorpusFile]:
    unique_ids = list(dict.fromkeys(file_ids))
    result = await db.execute(select(CorpusFile).where(CorpusFile.id.in_(unique_ids)))
    corpus_files = result.scalars().all()
    existing_ids = [item.id for item in corpus_files]
    if not existing_ids:
        return []

    await db.execute(delete(ParseRun).where(ParseRun.corpus_file_id.in_(existing_ids)))
    await db.execute(delete(Document).where(Document.corpus_file_id.in_(existing_ids)))
    await db.execute(delete(CorpusFile).where(CorpusFile.id.in_(existing_ids)))
    return corpus_files


@router.delete("/corpus/files/{file_id}", response_model=ApiResponse)
async def delete_corpus_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除语料文件记录"""
    corpus_files = await _delete_corpus_files_by_ids(db, [file_id])
    if not corpus_files:
        raise HTTPException(status_code=404, detail="语料文件不存在")

    await db.commit()
    corpus_file = corpus_files[0]

    return ApiResponse(message="删除成功", data={"file_id": file_id, "file_name": corpus_file.file_name})


@router.post("/corpus/files/batch-delete", response_model=ApiResponse)
async def batch_delete_corpus_files(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除语料文件记录"""
    corpus_files = await _delete_corpus_files_by_ids(db, req.ids)
    if not corpus_files:
        raise HTTPException(status_code=404, detail="未找到可删除的语料文件")

    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={
            "deleted_count": len(corpus_files),
            "requested_count": len(set(req.ids)),
            "items": [{"file_id": item.id, "file_name": item.file_name} for item in corpus_files],
        },
    )


@router.get("/corpus/parse-runs", response_model=ApiResponse)
async def list_parse_runs(
    corpus_file_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """解析任务列表"""
    from sqlalchemy import and_
    from app.models.mysql_models import ParseRun

    query = select(ParseRun)
    count_query = select(func.count()).select_from(ParseRun)

    conditions = []
    if corpus_file_id:
        conditions.append(ParseRun.corpus_file_id == corpus_file_id)
    if status:
        conditions.append(ParseRun.status == status)

    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total = await db.scalar(count_query) or 0
    query = query.order_by(ParseRun.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    runs = result.scalars().all()

    items = [
        {
            "id": r.id,
            "corpus_file_id": r.corpus_file_id,
            "parser_name": r.parser_name,
            "parser_version": r.parser_version,
            "parse_mode": r.parse_mode,
            "status": r.status,
            "page_count": r.page_count,
            "block_count": r.block_count,
            "asset_count": r.asset_count,
            "confidence": float(r.confidence) if r.confidence else None,
            "error_detail": r.error_detail,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in runs
    ]

    return ApiResponse(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/corpus/parse-runs/{run_id}", response_model=ApiResponse)
async def get_parse_run_detail(run_id: str, db: AsyncSession = Depends(get_db)):
    """获取解析任务详情（用于进度轮询）"""
    from app.models.mysql_models import ParseRun, Document

    run = await db.get(ParseRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 计算进度：如果有 total_pages，用 current_page/total_pages；否则返回不确定状态
    progress = 0
    if run.total_pages and run.total_pages > 0 and run.current_page:
        progress = round((run.current_page / run.total_pages) * 100, 1)

    # 查询关联的 document_id（解析成功后供后续流水线使用）
    document_id = None
    doc = (await db.execute(
        select(Document).where(Document.corpus_file_id == run.corpus_file_id)
    )).scalar_one_or_none()
    if doc:
        document_id = doc.id

    return ApiResponse(data={
        "id": run.id,
        "corpus_file_id": run.corpus_file_id,
        "document_id": document_id,
        "parser_name": run.parser_name,
        "parser_version": run.parser_version,
        "parse_mode": run.parse_mode,
        "status": run.status,
        "current_stage": run.current_stage,
        "current_page": run.current_page,
        "total_pages": run.total_pages,
        "stage_detail": run.stage_detail,
        "progress": progress,
        "page_count": run.page_count,
        "block_count": run.block_count,
        "asset_count": run.asset_count,
        "confidence": float(run.confidence) if run.confidence else None,
        "error_detail": run.error_detail,
        "metrics_json": run.metrics_json,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    })


@router.get("/corpus/documents/{document_id}/blocks", response_model=ApiResponse)
async def list_document_blocks(
    document_id: str,
    page_no: Optional[int] = None,
    block_type: Optional[str] = None,
    review_status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """文档块列表"""
    from sqlalchemy import and_
    from app.models.mysql_models import DocumentBlock

    query = select(DocumentBlock).where(DocumentBlock.document_id == document_id)
    count_query = select(func.count()).select_from(DocumentBlock).where(DocumentBlock.document_id == document_id)

    conditions = []
    if page_no is not None:
        conditions.append(DocumentBlock.page_no == page_no)
    if block_type:
        conditions.append(DocumentBlock.block_type == block_type)
    if review_status:
        conditions.append(DocumentBlock.review_status == review_status)

    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total = await db.scalar(count_query) or 0
    query = query.order_by(DocumentBlock.page_no, DocumentBlock.order_no)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    blocks = result.scalars().all()

    items = [
        {
            "id": b.id,
            "document_id": b.document_id,
            "page_id": b.page_id,
            "page_no": b.page_no,
            "block_type": b.block_type,
            "order_no": b.order_no,
            "content_text": b.content_text,
            "content_md": b.content_md,
            "html_table": b.html_table,
            "latex": b.latex,
            "bbox": b.bbox,
            "confidence": float(b.confidence) if b.confidence else None,
            "review_status": b.review_status,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in blocks
    ]

    return ApiResponse(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/corpus/documents/{document_id}/sections", response_model=ApiResponse)
async def get_document_sections(
    document_id: str,
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
):
    """获取文档的原生标题树"""
    from app.services.document_section_service import DocumentSectionService

    service = DocumentSectionService(db)
    if tree:
        result = await service.get_section_tree(document_id)
    else:
        result = await service.get_sections_flat(document_id)

    return ApiResponse(data=result)


@router.get("/corpus/documents/{document_id}/page-analysis", response_model=ApiResponse)
async def get_document_page_analysis(
    document_id: str,
    page_no: int = Query(..., ge=1, description="页码，从1开始"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取文档指定页的对比分析数据

    返回：
    - 原始PDF该页的图片（base64）
    - 该页的解析blocks
    - 该页的assets
    - 原始解析JSON（document_json中该页的部分）
    """
    import base64
    import io
    from pdf2image import convert_from_path
    from app.services.document_parse_service import DocumentParseService

    service = DocumentParseService(db)
    document = await service.get_document_detail(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 获取原始PDF路径
    corpus_file_result = await db.execute(
        select(CorpusFile).where(CorpusFile.id == document["corpus_file_id"])
    )
    corpus_file = corpus_file_result.scalar_one_or_none()

    if not corpus_file or not corpus_file.local_path:
        raise HTTPException(status_code=404, detail="原始文件不存在")

    pdf_path = Path(corpus_file.local_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF文件不存在于磁盘")

    # 提取PDF指定页为图片
    try:
        images = convert_from_path(
            str(pdf_path),
            first_page=page_no,
            last_page=page_no,
            dpi=150,  # 调整DPI平衡质量和大小
        )

        if not images:
            raise HTTPException(status_code=404, detail=f"无法提取第{page_no}页")

        # 转为base64
        img_byte_arr = io.BytesIO()
        images[0].save(img_byte_arr, format='PNG', optimize=True)
        img_byte_arr.seek(0)
        page_image_base64 = base64.b64encode(img_byte_arr.read()).decode('utf-8')

    except Exception as e:
        logger.error("PDF渲染失败", document_id=document_id, page_no=page_no, error=str(e))
        raise HTTPException(status_code=500, detail=f"PDF渲染失败: {str(e)}")

    # 过滤该页的blocks和assets
    page_blocks = [b for b in document.get("blocks", []) if b["page_no"] == page_no]
    page_assets = [a for a in document.get("assets", []) if a["page_no"] == page_no]

    # 从raw_parser_output中提取该页的原始解析数据
    raw_parse_data = None
    parser_name = None

    if document.get("raw_parser_output"):
        raw_output = document["raw_parser_output"]
        parser_name = raw_output.get("parser") or raw_output.get("parser_name")

        # MinerU 格式：content_list 数组
        if "content_list" in raw_output and isinstance(raw_output["content_list"], list):
            page_items = []
            for item in raw_output["content_list"]:
                # MinerU 使用 page_idx (0-based) 或 page_no (1-based)
                item_page = int(item.get("page_idx", 0) or 0) + 1 if item.get("page_idx") is not None else int(item.get("page_no", 1) or 1)
                if item_page == page_no:
                    page_items.append(item)
            raw_parse_data = {
                "parser": parser_name,
                "content_list": page_items,
            }

        # 回退格式：旧版解析服务透传的整个标准化 payload（含 blocks 数组）
        elif isinstance(raw_output.get("blocks"), list):
            raw_parse_data = {
                "parser": parser_name,
                "blocks": [b for b in raw_output["blocks"] if b.get("page_no") == page_no],
                "assets": [a for a in raw_output.get("assets", []) if a.get("page_no") == page_no],
            }

        # Docling 格式：只有元数据
        elif "metadata" in raw_output:
            raw_parse_data = raw_output

    return ApiResponse(data={
        "document_id": document_id,
        "page_no": page_no,
        "page_image": f"data:image/png;base64,{page_image_base64}",
        "page_info": next((p for p in document.get("pages", []) if p["page_no"] == page_no), None),
        "blocks": page_blocks,
        "assets": page_assets,
        "raw_parse_data": raw_parse_data,
        "parser_name": parser_name,
    })


@router.post("/corpus/documents/{document_id}/extract-sections", response_model=ApiResponse)
async def extract_document_sections(
    document_id: str,
    force: bool = Query(False, description="是否强制重建已有标题树"),
    db: AsyncSession = Depends(get_db),
):
    """从文档中提取标题树"""
    from app.services.document_section_service import DocumentSectionService

    service = DocumentSectionService(db)
    try:
        result = await service.extract_sections(document_id, force=force)
    except ValueError as e:
        detail = str(e)
        status_code = 404 if detail.startswith("文档不存在") else 400
        raise HTTPException(status_code=status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提取失败: {str(e)[:200]}")

    return ApiResponse(data=result)


@router.post("/corpus/documents/{document_id}/map-chapters", response_model=ApiResponse)
async def map_document_chapters(
    document_id: str,
    subject_id: Optional[str] = Query(None, description="学科ID，不传则遍历所有学科匹配"),
    outline_id: Optional[str] = Query(None, description="大纲ID；传入则只匹配该大纲下章节"),
    auto_approve_threshold: float = Query(0.90, description="自动通过阈值"),
    force: bool = Query(False, description="是否强制重建已有章节映射"),
    db: AsyncSession = Depends(get_db),
):
    """将文档的 sections 映射到标准章节"""
    from app.services.chapter_mapping_service import ChapterMappingService

    service = ChapterMappingService(db)
    try:
        result = await service.map_sections(
            document_id=document_id,
            subject_id=subject_id,
            outline_id=outline_id,
            auto_approve_threshold=auto_approve_threshold,
            force=force,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"映射失败: {str(e)[:200]}")

    return ApiResponse(data=result)


@router.get("/corpus/documents/{document_id}/section-mappings", response_model=ApiResponse)
async def get_document_section_mappings(
    document_id: str,
    review_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取文档的 section 映射列表"""
    from app.services.chapter_mapping_service import ChapterMappingService

    service = ChapterMappingService(db)
    result = await service.get_section_mappings(document_id, review_status)

    return ApiResponse(data=result)


@router.get("/corpus/documents/{document_id}/chapter-diagnostics", response_model=ApiResponse)
async def get_document_chapter_diagnostics(
    document_id: str,
    page_no: Optional[int] = Query(None, ge=1, description="只查看指定页"),
    include_blocks: bool = Query(True, description="是否返回块级诊断明细"),
    db: AsyncSession = Depends(get_db),
):
    """获取文档页级/块级章节归属诊断。"""
    from app.services.chapter_mapping_service import ChapterMappingService

    service = ChapterMappingService(db)
    try:
        result = await service.get_chapter_ownership_diagnostics(
            document_id=document_id,
            page_no=page_no,
            include_blocks=include_blocks,
        )
    except ValueError as e:
        detail = str(e)
        status_code = 404 if detail.startswith("文档不存在") else 400
        raise HTTPException(status_code=status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"诊断失败: {str(e)[:200]}")

    return ApiResponse(data=result)


@router.get("/corpus/documents/{document_id}/content-overview", response_model=ApiResponse)
async def get_document_content_overview(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    文档内容总览：知识点按大纲考点分组、题目按题号排列。

    替代原"原生标题映射 + 归属诊断"展示——直接清晰列出解析出的结构化内容。
    """
    from app.services.document_parse_service import DocumentParseService

    service = DocumentParseService(db)
    result = await service.get_content_overview(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="文档不存在")

    return ApiResponse(data=result)


@router.post("/corpus/documents/{document_id}/extract-entities", response_model=ApiResponse)
async def extract_document_entities(
    document_id: str,
    extract_knowledge: bool = Query(True, description="是否抽取知识点"),
    extract_questions: bool = Query(True, description="是否抽取题目"),
    subject_id: Optional[str] = Query(None, description="章节映射不足时使用的兜底学科ID"),
    db: AsyncSession = Depends(get_db),
):
    """从文档中抽取知识点和题目"""
    from app.services.entity_extraction_service import EntityExtractionService

    service = EntityExtractionService(db)
    try:
        result = await service.extract_entities(
            document_id=document_id,
            extract_knowledge=extract_knowledge,
            extract_questions=extract_questions,
            fallback_subject_id=subject_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"抽取失败: {str(e)[:200]}")

    return ApiResponse(data=result)


# ========== 标准章节管理 ==========


@router.post("/canonical-chapters/init", response_model=ApiResponse)
async def init_canonical_chapters(
    subject_id: str = Query(..., description="学科ID"),
    chapters: List[dict] = [],
    db: AsyncSession = Depends(get_db),
):
    """初始化学科的标准章节体系"""
    from app.services.chapter_mapping_service import CanonicalChapterService

    service = CanonicalChapterService(db)
    try:
        result = await service.init_chapters(subject_id, chapters)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(data=result)


@router.get("/canonical-chapters", response_model=ApiResponse)
async def get_canonical_chapters(
    subject_id: str = Query(..., description="学科ID"),
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
):
    """获取学科的标准章节"""
    from app.services.chapter_mapping_service import CanonicalChapterService

    service = CanonicalChapterService(db)
    if tree:
        result = await service.get_chapters(subject_id)
    else:
        result = await service.get_chapters_flat(subject_id)

    return ApiResponse(data=result)


# ========== 审核相关 ==========


@router.get("/review/sections", response_model=ApiResponse, deprecated=True)
async def list_pending_section_mappings(
    subject_id: Optional[str] = None,
    review_status: Optional[str] = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核的 section 映射列表。已废弃，仅保留回滚兼容。"""
    from app.models.mysql_models import DocumentSectionMapping, DocumentSection, Document, CanonicalChapter
    from sqlalchemy import and_

    query = (
        select(DocumentSectionMapping, DocumentSection, CanonicalChapter)
        .join(DocumentSection, DocumentSectionMapping.document_section_id == DocumentSection.id)
        .join(Document, DocumentSection.document_id == Document.id)
        .join(CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id)
    )
    count_query = select(func.count()).select_from(DocumentSectionMapping)

    conditions = []
    if review_status:
        conditions.append(DocumentSectionMapping.review_status == review_status)
    if subject_id:
        conditions.append(
            or_(
                Document.subject_id == subject_id,
                CanonicalChapter.subject_id == subject_id,
            )
        )

    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.join(
            DocumentSection, DocumentSectionMapping.document_section_id == DocumentSection.id
        ).join(
            Document, DocumentSection.document_id == Document.id
        ).join(
            CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id
        ).where(and_(*conditions))

    total = await db.scalar(count_query) or 0
    query = query.order_by(DocumentSectionMapping.created_at.desc(), DocumentSectionMapping.id.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    items = [
        {
            "mapping_id": mapping.id,
            "section_id": section.id,
            "section_title": section.title,
            "section_path": section.section_path,
            "document_id": section.document_id,
            "canonical_chapter_id": chapter.id,
            "canonical_chapter_name": chapter.name,
            "canonical_chapter_code": chapter.code,
            "mapping_type": mapping.mapping_type,
            "confidence": float(mapping.confidence),
            "review_status": mapping.review_status,
            "review_notes": mapping.review_notes,
            "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
        }
        for mapping, section, chapter in rows
    ]

    return ApiResponse(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.post("/review/sections/{mapping_id}", response_model=ApiResponse, deprecated=True)
async def review_section_mapping(
    mapping_id: str,
    review_status: str = Query(..., description="审核状态: approved/rejected"),
    canonical_chapter_id: Optional[str] = None,
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核 section 映射。已废弃，仅保留回滚兼容。"""
    from app.services.chapter_mapping_service import ChapterMappingService

    service = ChapterMappingService(db)
    try:
        result = await service.review_mapping(
            mapping_id=mapping_id,
            review_status=review_status,
            canonical_chapter_id=canonical_chapter_id,
            review_notes=review_notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ApiResponse(data=result)


@router.delete("/review/sections/{mapping_id}", response_model=ApiResponse, deprecated=True)
async def delete_section_mapping(
    mapping_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个 section 映射。已废弃，仅保留回滚兼容。"""
    from app.models.mysql_models import DocumentSectionMapping

    mapping = await db.get(DocumentSectionMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="映射不存在")

    await db.delete(mapping)
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": mapping_id})


@router.post("/review/sections/batch-delete", response_model=ApiResponse, deprecated=True)
async def batch_delete_section_mappings(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除 section 映射。已废弃，仅保留回滚兼容。"""
    from app.models.mysql_models import DocumentSectionMapping

    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(DocumentSectionMapping.id).where(DocumentSectionMapping.id.in_(unique_ids))
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的映射")

    await db.execute(
        delete(DocumentSectionMapping).where(DocumentSectionMapping.id.in_(existing_ids))
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={"deleted_count": len(existing_ids), "requested_count": len(unique_ids)}
    )


@router.get("/review/knowledge", response_model=ApiResponse)
async def list_knowledge_points_for_review(
    subject_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    review_status: Optional[str] = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核的知识点列表"""
    from app.services.review_service import ReviewService

    service = ReviewService(db)
    result = await service.get_knowledge_points_for_review(
        subject_id=subject_id,
        chapter_id=chapter_id,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )

    return ApiResponse(data=result)


@router.post("/review/knowledge/{knowledge_id}", response_model=ApiResponse)
async def review_knowledge_point(
    knowledge_id: str,
    review_status: str = Query(..., description="审核状态: approved/rejected"),
    review_notes: Optional[str] = None,
    primary_chapter_id: Optional[str] = None,
    topic_terms: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核知识点"""
    from app.services.review_service import ReviewService

    service = ReviewService(db)
    try:
        result = await service.review_knowledge_point(
            knowledge_point_id=knowledge_id,
            review_status=review_status,
            review_notes=review_notes,
            primary_chapter_id=primary_chapter_id,
            topic_terms=topic_terms,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ApiResponse(data=result)


@router.get("/review/questions", response_model=ApiResponse)
async def list_questions_for_review(
    subject_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    exam_scope: Optional[str] = None,
    exam_year: Optional[int] = None,
    question_type: Optional[str] = None,
    review_status: Optional[str] = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核的题目列表"""
    from app.services.review_service import ReviewService

    service = ReviewService(db)
    result = await service.get_questions_for_review(
        subject_id=subject_id,
        chapter_id=chapter_id,
        exam_scope=exam_scope,
        exam_year=exam_year,
        question_type=question_type,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )

    return ApiResponse(data=result)


@router.post("/review/questions/backfill-chapters", response_model=ApiResponse)
async def backfill_question_review_chapters(
    review_status: str = Query("pending", description="审核状态过滤，留空表示不过滤"),
    item_status: str = Query("pending", description="题目状态过滤，留空表示不过滤"),
    subject_id: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
    force: bool = Query(False, description="是否覆盖已有章节归属"),
    dry_run: bool = Query(False, description="只预览不写库"),
    db: AsyncSession = Depends(get_db),
):
    """批量回填待审核题目的章节归属。"""
    from app.services.chapter_link_service import ChapterLinkService

    service = ChapterLinkService(db)
    result = await service.backfill_question_chapters(
        review_status=review_status,
        status=item_status,
        subject_id=subject_id,
        limit=limit,
        force=force,
        dry_run=dry_run,
    )
    return ApiResponse(data=result)


@router.post("/review/questions/{question_id}", response_model=ApiResponse)
async def review_question(
    question_id: str,
    review_status: str = Query(..., description="审核状态: approved/rejected"),
    review_notes: Optional[str] = None,
    primary_chapter_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核题目"""
    from app.services.review_service import ReviewService

    service = ReviewService(db)
    try:
        result = await service.review_question(
            question_id=question_id,
            review_status=review_status,
            review_notes=review_notes,
            primary_chapter_id=primary_chapter_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ApiResponse(data=result)


@router.get("/review/relations", response_model=ApiResponse)
async def list_relations_for_review(
    relation_type: Optional[str] = None,
    review_status: Optional[str] = "pending",
    subject_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核的关系列表"""
    from app.services.review_service import ReviewService

    service = ReviewService(db)
    result = await service.get_relations_for_review(
        relation_type=relation_type,
        review_status=review_status,
        subject_id=subject_id,
        page=page,
        page_size=page_size,
    )

    return ApiResponse(data=result)


@router.post("/review/relations/{relation_id}", response_model=ApiResponse)
async def review_relation(
    relation_id: str,
    review_status: str = Query(..., description="审核状态: approved/rejected"),
    relation_type: Optional[str] = None,
    directionality: Optional[str] = None,
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核关系"""
    from app.services.review_service import ReviewService

    service = ReviewService(db)
    try:
        result = await service.review_relation(
            relation_id=relation_id,
            review_status=review_status,
            relation_type=relation_type,
            directionality=directionality,
            review_notes=review_notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ApiResponse(data=result)


@router.delete("/review/relations/{relation_id}", response_model=ApiResponse)
async def delete_review_relation(
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个知识点关系"""
    from app.models.mysql_models import KnowledgeRelation

    relation = await db.get(KnowledgeRelation, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="关系不存在")

    await db.delete(relation)
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": relation_id})


@router.post("/review/relations/batch-delete", response_model=ApiResponse)
async def batch_delete_review_relations(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除知识点关系"""
    from app.models.mysql_models import KnowledgeRelation

    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(KnowledgeRelation.id).where(KnowledgeRelation.id.in_(unique_ids))
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的关系")

    await db.execute(
        delete(KnowledgeRelation).where(KnowledgeRelation.id.in_(existing_ids))
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={"deleted_count": len(existing_ids), "requested_count": len(unique_ids)}
    )


@router.get("/review/stats", response_model=ApiResponse)
async def get_review_stats(
    subject_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取审核统计"""
    from app.services.review_service import ReviewService

    service = ReviewService(db)
    result = await service.get_review_stats(subject_id)

    return ApiResponse(data=result)


# ========== Segment 构建 ==========


@router.post("/segments/build", response_model=ApiResponse)
async def build_segments(
    subject_id: Optional[str] = None,
    document_id: Optional[str] = None,
    rebuild: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    构建检索单元（知识点 + 题目）

    从已审核的知识点和题目构建 RetrievalSegment，
    生成 embedding 并写入 Qdrant。
    """
    from app.services.segment_service import SegmentService

    service = SegmentService(db)
    result = await service.build_all_segments(
        subject_id=subject_id,
        document_id=document_id,
        rebuild=rebuild,
    )

    return ApiResponse(data=result)


@router.post("/segments/build/knowledge", response_model=ApiResponse)
async def build_knowledge_segments(
    subject_id: Optional[str] = None,
    document_id: Optional[str] = None,
    knowledge_point_ids: Optional[List[str]] = None,
    rebuild: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """构建知识点检索单元"""
    from app.services.segment_service import SegmentService

    service = SegmentService(db)
    result = await service.build_knowledge_segments(
        subject_id=subject_id,
        document_id=document_id,
        knowledge_point_ids=knowledge_point_ids,
        rebuild=rebuild,
    )

    return ApiResponse(data=result)


@router.post("/segments/build/questions", response_model=ApiResponse)
async def build_question_segments(
    subject_id: Optional[str] = None,
    document_id: Optional[str] = None,
    question_ids: Optional[List[str]] = None,
    rebuild: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """构建题目检索单元"""
    from app.services.segment_service import SegmentService

    service = SegmentService(db)
    result = await service.build_question_segments(
        subject_id=subject_id,
        document_id=document_id,
        question_ids=question_ids,
        rebuild=rebuild,
    )

    return ApiResponse(data=result)


@router.post("/segments/build/chapters", response_model=ApiResponse)
async def build_chapter_segments(
    subject_id: Optional[str] = None,
    outline_id: Optional[str] = None,
    rebuild: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """构建大纲章节检索单元"""
    from app.services.segment_service import SegmentService

    service = SegmentService(db)
    result = await service.build_canonical_chapter_segments(
        subject_id=subject_id,
        outline_id=outline_id,
        rebuild=rebuild,
    )

    return ApiResponse(data=result)


# ========== 检索调试 ==========


class SearchRequest(BaseModel):
    """检索请求"""
    query: str = Field(..., min_length=1, description="查询文本")
    subject_id: Optional[str] = Field(None, description="学科过滤")
    chapter_ids: Optional[List[str]] = Field(None, description="章节过滤")
    entity_type: Optional[str] = Field(None, description="实体类型过滤")
    mode: str = Field("hybrid", description="检索模式: dense/sparse/hybrid")
    limit: int = Field(10, ge=1, le=50, description="返回数量")
    filters: Optional[Dict[str, Any]] = Field(
        None, description="结构化过滤: exam_year/exam_scope/difficulty/question_type/answer_source/tags"
    )


@router.post("/search", response_model=ApiResponse)
async def search_knowledge(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    检索调试接口

    支持 dense / sparse / hybrid 三种检索模式，
    可按学科和章节过滤。
    """
    from app.services.retrieval_service import RetrievalService

    service = RetrievalService(db)
    results = await service.search(
        query=request.query,
        subject_id=request.subject_id,
        chapter_ids=request.chapter_ids,
        entity_type=request.entity_type,
        mode=request.mode,
        limit=request.limit,
        filters=request.filters,
    )

    return ApiResponse(data={
        "results": [r.to_dict() for r in results],
        "total": len(results),
        "mode": request.mode,
    })


@router.post("/search/with-relations", response_model=ApiResponse)
async def search_with_relations(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    带关系扩展的检索

    先做 hybrid 检索拿到 top-K 知识点，
    再查询关系边，将关联知识点也加入结果。
    """
    from app.services.retrieval_service import RetrievalService

    service = RetrievalService(db)
    result = await service.search_with_relations(
        query=request.query,
        subject_id=request.subject_id,
        chapter_ids=request.chapter_ids,
        limit=request.limit,
    )

    return ApiResponse(data=result)


class SearchWithOutlineRequest(BaseModel):
    """带大纲扩展的检索请求"""
    query: str = Field(..., min_length=1, description="查询文本")
    subject_id: Optional[str] = Field(None, description="学科过滤")
    chapter_ids: Optional[List[str]] = Field(None, description="章节过滤")
    entity_type: Optional[str] = Field(None, description="实体类型过滤")
    mode: str = Field("hybrid", description="检索模式: dense/sparse/hybrid")
    limit: int = Field(10, ge=1, le=50, description="返回数量")
    filters: Optional[Dict[str, Any]] = Field(
        None, description="结构化过滤: exam_year/exam_scope/difficulty/question_type/answer_source/tags"
    )


@router.post("/search/with-outline", response_model=ApiResponse)
async def search_with_outline(
    request: SearchWithOutlineRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Phase 0 + Phase 1 检索：大纲辅助 Query 扩展 + 内容检索

    1. 用户 query → 检索大纲考点（canonical_chapter segment）
    2. 用考点 keywords + enhanced_description 扩展 query
    3. 用扩展后的 query 做 dense/sparse/hybrid 检索
    4. 返回检索结果 + 大纲扩展信息（matched_chapters）
    """
    from app.services.retrieval_service import RetrievalService

    service = RetrievalService(db)
    result = await service.search_with_outline_expansion(
        query=request.query,
        subject_id=request.subject_id,
        chapter_ids=request.chapter_ids,
        entity_type=request.entity_type,
        mode=request.mode,
        limit=request.limit,
        filters=request.filters,
    )

    return ApiResponse(data=result)


class DualPathRecallRequest(BaseModel):
    """双路分层归并请求"""
    expanded_query: str = Field(..., min_length=1, description="（已扩展的）查询文本")
    chapter_ids: List[str] = Field(..., min_length=1, description="Phase 2 展开后的考点范围")
    subject_id: Optional[str] = Field(None, description="学科过滤")
    limit: int = Field(20, ge=1, le=50, description="归并后返回总数")
    per_chapter_cap: int = Field(10, ge=1, le=50, description="路 B 每考点展开上限")


@router.post("/search/dual-path", response_model=ApiResponse)
async def dual_path_recall(
    request: DualPathRecallRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Phase 3 双路分层归并（见设计文档 6.4）

    路 A 向量直接命中（第一梯队，带分数）+ 路 B 考点结构化展开（第二梯队，link JOIN，设上限）。
    分层不混排，路 A 在前、路 B 补网。
    """
    from app.services.retrieval_service import RetrievalService

    service = RetrievalService(db)
    result = await service.merge_dual_path_recall(
        expanded_query=request.expanded_query,
        chapter_ids=request.chapter_ids,
        subject_id=request.subject_id,
        limit=request.limit,
        per_chapter_cap=request.per_chapter_cap,
    )

    return ApiResponse(data=result)


class ChapterExpansionRequest(BaseModel):
    """跨章关联编排请求"""
    chapter_ids: List[str] = Field(..., min_length=1, description="考点 ID 列表")
    max_results: int = Field(10, ge=1, le=50, description="每题点最多返回关联数")


@router.post("/search/chapter-expansion", response_model=ApiResponse)
async def expand_chapters(
    request: ChapterExpansionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    跨章关联在线读取器（见设计文档 6.3 阶段 B）

    对每个 chapter_id 返回两类互不混排的关联：
    - scope_expansion:    在线由 parent_id 计算的结构派生（兄弟/父/子），不入表
    - semantic_relations: 只读 ChapterRelation 已审核行（review_status="approved"）

    审核员对 ChapterRelation 的 approve/reject 直接决定 semantic_relations 返回什么。

    返回: {chapter_id: {scope_expansion: [...], semantic_relations: [...]}}
    """
    from app.services.outline_retrieval_service import expand_related_chapters

    result = await expand_related_chapters(
        db,
        chapter_ids=request.chapter_ids,
        max_results=request.max_results,
    )

    return ApiResponse(data={"relations": result})


# ========== 富化与关系构建 ==========


@router.post("/enrichment/document/{document_id}", response_model=ApiResponse)
async def enrich_document_entities(document_id: str, db: AsyncSession = Depends(get_db)):
    """批量富化某文档下所有已审核的题目和知识点（答案/解析/考点回连 + 知识点增强）。"""
    from app.services.enrichment_service import EnrichmentService

    service = EnrichmentService(db)
    try:
        result = await service.enrich_document(document_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"富化失败: {str(e)[:200]}")
    return ApiResponse(data=result)


@router.post("/enrichment/question/{question_id}", response_model=ApiResponse)
async def enrich_single_question(question_id: str, db: AsyncSession = Depends(get_db)):
    """富化单道题目。"""
    from app.services.enrichment_service import EnrichmentService

    service = EnrichmentService(db)
    try:
        result = await service.enrich_question(question_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ApiResponse(data=result)


@router.post("/enrichment/knowledge/{kp_id}", response_model=ApiResponse)
async def enrich_single_knowledge(kp_id: str, db: AsyncSession = Depends(get_db)):
    """富化单个知识点。"""
    from app.services.enrichment_service import EnrichmentService

    service = EnrichmentService(db)
    try:
        result = await service.enrich_knowledge_point(kp_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ApiResponse(data=result)


@router.post("/relations/build", response_model=ApiResponse)
async def build_knowledge_relations(
    subject_id: Optional[str] = None,
    knowledge_point_ids: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db),
):
    """构建知识点关系（规则 + 语义相似度边）。"""
    from app.services.relation_service import RelationService

    service = RelationService(db)
    try:
        result = await service.build_relations(
            subject_id=subject_id, knowledge_point_ids=knowledge_point_ids
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"关系构建失败: {str(e)[:200]}")
    return ApiResponse(data=result)


# ========== 考点关系管理 ==========


@router.post("/chapter-relations/build", response_model=ApiResponse)
async def build_chapter_relations(
    subject_id: Optional[str] = None,
    outline_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    构建考点间直接关系（从 cross_references + embedding 相似度）

    1. 读取 CanonicalChapter.cross_references（LLM 标注的跨章关联）
    2. 双向写入 ChapterRelation（source_type="llm"）
    3. 对无 cross_references 的考点，用 embedding 相似度兜底（source_type="embedding"）
    """
    from app.services.outline_retrieval_service import (
        validate_cross_references, fallback_chapter_similarity,
    )
    from app.models.mysql_models import CanonicalChapter, ChapterRelation

    query = select(CanonicalChapter).where(CanonicalChapter.status == "active")
    if subject_id:
        query = query.where(CanonicalChapter.subject_id == subject_id)
    if outline_id:
        query = query.where(CanonicalChapter.outline_id == outline_id)

    chapters = (await db.execute(query)).scalars().all()
    if not chapters:
        return ApiResponse(data={"message": "没有可用考点", "created": 0})

    created = 0
    llm_created = 0
    embedding_created = 0
    chapter_map = {ch.id: ch for ch in chapters}
    relation_keys = {
        (row[0], row[1], row[2])
        for row in (await db.execute(
            select(
                ChapterRelation.source_chapter_id,
                ChapterRelation.target_chapter_id,
                ChapterRelation.relation_type,
            )
        )).all()
    }

    for chapter in chapters:
        cross_refs = getattr(chapter, "cross_references", None)

        # Layer 1: 从 LLM cross_references 创建关系
        if cross_refs:
            valid_refs = await validate_cross_references(db, cross_refs)
            for ref in valid_refs:
                target_id = ref["target_chapter_id"]
                if target_id not in chapter_map:
                    continue
                # 双向各写一条（source → target 和 target → source）
                for src, tgt in [(chapter.id, target_id), (target_id, chapter.id)]:
                    relation_type = ref.get("relation_type", "similar_to")
                    relation_key = (src, tgt, relation_type)
                    if src == tgt or relation_key in relation_keys:
                        continue
                    relation_keys.add(relation_key)
                    db.add(ChapterRelation(
                        id=_gen_chrel_id(),
                        source_chapter_id=src,
                        target_chapter_id=tgt,
                        relation_type=relation_type,
                        confidence=0.9,
                        source_type="llm",
                        evidence_text=ref.get("reason"),
                        review_status="pending",
                    ))
                    llm_created += 1
                    created += 1

        # Layer 2: 无 cross_references 的考点用 embedding 相似度兜底
        if not cross_refs:
            sims = await fallback_chapter_similarity(db, chapter.id, top_k=3)
            for target_id, score in sims:
                if target_id not in chapter_map:
                    continue
                relation_key = (chapter.id, target_id, "similar_to")
                if chapter.id == target_id or relation_key in relation_keys:
                    continue
                relation_keys.add(relation_key)
                db.add(ChapterRelation(
                    id=_gen_chrel_id(),
                    source_chapter_id=chapter.id,
                    target_chapter_id=target_id,
                    relation_type="similar_to",
                    confidence=round(score, 4),
                    source_type="embedding",
                    evidence_text=f"语义相似度 {score:.4f}",
                    review_status="pending",
                ))
                embedding_created += 1
                created += 1

    await db.commit()

    return ApiResponse(data={
        "created": created,
        "llm_created": llm_created,
        "embedding_created": embedding_created,
        "chapters_processed": len(chapters),
    })


@router.get("/chapter-relations", response_model=ApiResponse)
async def list_chapter_relations(
    source_chapter_id: Optional[str] = None,
    target_chapter_id: Optional[str] = None,
    relation_type: Optional[str] = None,
    review_status: Optional[str] = None,
    source_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询考点关系列表（用于审核面板）"""
    from app.models.mysql_models import ChapterRelation, CanonicalChapter

    query = (
        select(
            ChapterRelation,
            CanonicalChapter.name.label("source_name"),
            CanonicalChapter.name.label("target_name"),
        )
        .join(CanonicalChapter, ChapterRelation.source_chapter_id == CanonicalChapter.id)
    )
    # 注意：上面的 join 只拿到了 source_name，需要额外查 target
    conditions = []
    if source_chapter_id:
        conditions.append(ChapterRelation.source_chapter_id == source_chapter_id)
    if target_chapter_id:
        conditions.append(ChapterRelation.target_chapter_id == target_chapter_id)
    if relation_type:
        conditions.append(ChapterRelation.relation_type == relation_type)
    if review_status:
        conditions.append(ChapterRelation.review_status == review_status)
    if source_type:
        conditions.append(ChapterRelation.source_type == source_type)

    if conditions:
        query = query.where(and_(*conditions))

    count_query = select(func.count()).select_from(ChapterRelation)
    if conditions:
        count_query = count_query.where(and_(*conditions))
    total = await db.scalar(count_query) or 0

    query = query.order_by(ChapterRelation.created_at.desc(), ChapterRelation.id.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).all()

    items = []
    for row in rows:
        rel, source_name, _ = row
        # 获取 target chapter name
        target_ch = await db.get(CanonicalChapter, rel.target_chapter_id)
        items.append({
            "id": rel.id,
            "source_chapter_id": rel.source_chapter_id,
            "source_chapter_name": source_name,
            "target_chapter_id": rel.target_chapter_id,
            "target_chapter_name": target_ch.name if target_ch else "",
            "relation_type": rel.relation_type,
            "confidence": float(rel.confidence) if rel.confidence else None,
            "source_type": rel.source_type,
            "evidence_text": rel.evidence_text,
            "review_status": rel.review_status,
            "review_notes": rel.review_notes,
            "created_at": rel.created_at.isoformat() if rel.created_at else None,
        })

    return ApiResponse(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.post("/chapter-relations/{relation_id}/review", response_model=ApiResponse)
async def review_chapter_relation(
    relation_id: str,
    review_status: str = Query(..., description="approved / rejected"),
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核考点关系"""
    from app.models.mysql_models import ChapterRelation

    rel = await db.get(ChapterRelation, relation_id)
    if not rel:
        raise HTTPException(status_code=404, detail="关系不存在")

    rel.review_status = review_status
    if review_notes:
        rel.review_notes = review_notes
    rel.reviewed_at = datetime.utcnow()
    await db.commit()

    return ApiResponse(data={"id": relation_id, "review_status": review_status})


@router.delete("/chapter-relations/{relation_id}", response_model=ApiResponse)
async def delete_chapter_relation(
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个考点关系"""
    from app.models.mysql_models import ChapterRelation

    relation = await db.get(ChapterRelation, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="关系不存在")

    await db.delete(relation)
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": relation_id})


@router.post("/chapter-relations/batch-delete", response_model=ApiResponse)
async def batch_delete_chapter_relations(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除考点关系"""
    from app.models.mysql_models import ChapterRelation

    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(ChapterRelation.id).where(ChapterRelation.id.in_(unique_ids))
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的关系")

    await db.execute(
        delete(ChapterRelation).where(ChapterRelation.id.in_(existing_ids))
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={"deleted_count": len(existing_ids), "requested_count": len(unique_ids)}
    )


def _gen_chrel_id() -> str:
    import uuid
    return uuid.uuid4().hex[:32]



# ===== LLM 调用监控 =====


@router.get("/monitor/llm-calls", response_model=ApiResponse)
async def list_llm_call_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    model: Optional[str] = None,
    status: Optional[str] = Query(None, description="success / error / timeout"),
    called_by: Optional[str] = None,
    keyword: Optional[str] = Query(None, description="响应文本模糊搜索"),
    db: AsyncSession = Depends(get_db),
):
    """LLM 调用列表（分页 + 过滤）"""
    from app.services.llm_call_recorder import list_llm_calls

    result = await list_llm_calls(
        session=db,
        page=page,
        page_size=page_size,
        model=model,
        status=status,
        called_by=called_by,
        keyword=keyword,
    )
    return ApiResponse(data=result)


@router.get("/monitor/llm-calls/stats", response_model=ApiResponse)
async def get_llm_calls_stats(
    hours: int = Query(24, ge=1, le=720, description="时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
):
    """LLM 调用聚合统计：QPS / 延迟分布 / Token / 成本 / 按模型分组"""
    from app.services.llm_call_recorder import get_llm_call_stats

    result = await get_llm_call_stats(session=db, hours=hours)
    return ApiResponse(data=result)


@router.get("/monitor/llm-calls/{call_id}", response_model=ApiResponse)
async def get_llm_call_detail_endpoint(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    """LLM 调用详情（含完整请求/响应）"""
    from app.services.llm_call_recorder import get_llm_call_detail

    result = await get_llm_call_detail(session=db, call_id=call_id)
    if not result:
        raise HTTPException(status_code=404, detail="调用记录不存在")
    return ApiResponse(data=result)


@router.delete("/monitor/llm-calls", response_model=ApiResponse)
async def delete_llm_call_logs(
    older_than_days: Optional[int] = Query(None, ge=0, description="按时间清理：删除 N 天前的记录"),
    ids: Optional[str] = Query(None, description="按 ID 清理：逗号分隔"),
    db: AsyncSession = Depends(get_db),
):
    """清理 LLM 调用日志"""
    from app.services.llm_call_recorder import delete_llm_calls

    id_list = [s.strip() for s in (ids or "").split(",") if s.strip()] or None
    deleted = await delete_llm_calls(
        session=db,
        older_than_days=older_than_days,
        ids=id_list,
    )
    return ApiResponse(data={"deleted": deleted})



# ===== 大纲（考试章节体系）独立入库 =====


class OutlinePreviewRequest(BaseModel):
    content: str = Field(..., max_length=2_000_000)
    filename: Optional[str] = ""


class OutlineImportRequest(BaseModel):
    subject_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    year: int = Field(..., ge=2000, le=2100)
    content: str = Field(..., max_length=2_000_000)
    filename: Optional[str] = ""
    version: Optional[str] = "v1.0"
    description: Optional[str] = None
    set_default: bool = False


class OutlineFromDocumentRequest(BaseModel):
    subject_id: str
    document_id: str
    name: str
    year: int = Field(..., ge=2000, le=2100)
    version: Optional[str] = "v1.0"
    set_default: bool = False


class OutlineFromLLMRequest(BaseModel):
    """携带 LLM 拆分结果整体入库（四门课一次入）。"""
    name: str = Field(..., min_length=1, max_length=200)
    year: int = Field(..., ge=2000, le=2100)
    version: Optional[str] = "v1.0"
    description: Optional[str] = None
    set_default: bool = False
    subjects: List[Dict[str, Any]] = Field(..., min_length=1)


@router.get("/outlines", response_model=ApiResponse)
async def list_outlines_endpoint(db: AsyncSession = Depends(get_db)):
    """列出所有大纲"""
    from app.services.outline_import_service import list_outlines
    return ApiResponse(data=await list_outlines(db))


@router.get("/outlines/{outline_id}/chapters", response_model=ApiResponse)
async def get_outline_chapters_endpoint(
    outline_id: str,
    subject_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取大纲下章节树（含原文考点 description + 复习指导 exam_guidance，可按 subject_id 过滤）"""
    from app.services.outline_import_service import get_outline_chapters
    return ApiResponse(data=await get_outline_chapters(db, outline_id, subject_id=subject_id))


@router.get("/outlines/{outline_id}/subjects", response_model=ApiResponse)
async def get_outline_subjects_endpoint(outline_id: str, db: AsyncSession = Depends(get_db)):
    """获取大纲下各门课的考察目标 + 复习指导生成状态"""
    from app.services.outline_import_service import get_outline_subjects
    return ApiResponse(data=await get_outline_subjects(db, outline_id))


@router.post("/outlines/preview", response_model=ApiResponse)
async def preview_outline_import(request: OutlinePreviewRequest, db: AsyncSession = Depends(get_db)):
    """解析大纲文本但不入库（用于前端预览）"""
    from app.services.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.preview(content=request.content, filename=request.filename or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/outlines/import", response_model=ApiResponse)
async def import_outline_endpoint(request: OutlineImportRequest, db: AsyncSession = Depends(get_db)):
    """导入大纲（创建 exam_outlines + canonical_chapters 树）"""
    from app.services.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.import_outline(
            subject_id=request.subject_id,
            name=request.name,
            year=request.year,
            content=request.content,
            filename=request.filename or "",
            version=request.version or "v1.0",
            description=request.description,
            set_default=request.set_default,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/outlines/import-from-document", response_model=ApiResponse)
async def import_outline_from_document(
    request: OutlineFromDocumentRequest,
    db: AsyncSession = Depends(get_db),
):
    """从已解析文档的 document_sections 转换为大纲"""
    from app.services.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.import_from_document_sections(
            subject_id=request.subject_id,
            document_id=request.document_id,
            outline_name=request.name,
            year=request.year,
            version=request.version or "v1.0",
            set_default=request.set_default,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/outlines/document/{document_id}/preview", response_model=ApiResponse)
async def preview_outline_from_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """预览某文档标题树转成的大纲章节树（不入库）。"""
    from app.services.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.preview_from_document_sections(document_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/outlines/import-from-llm", response_model=ApiResponse)
async def import_outline_from_llm(request: OutlineFromLLMRequest, db: AsyncSession = Depends(get_db)):
    """
    把 LLM 拆分出的四门课结果整体入库（含考察目标 + 多层章节树 + 原文考点）。

    改进：支持部分成功，如果某些科目失败但其他成功，仍然入库成功的部分。
    返回 partial=true 标识部分成功。
    """
    from app.services.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        result = await service.import_from_llm_result(
            llm_result={"subjects": request.subjects},
            name=request.name,
            year=request.year,
            version=request.version or "v1.0",
            description=request.description,
            set_default=request.set_default,
        )
        # 如果是部分成功，返回 200 但带 warning 标识
        if result.get("partial"):
            return ApiResponse(
                data=result,
                message=f"部分成功：{result['successful_subjects']}/{result['total_subjects']} 个科目入库成功"
            )
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/outlines/runs/{run_id}", response_model=ApiResponse)
async def get_outline_ingestion_progress(run_id: str, db: AsyncSession = Depends(get_db)):
    """
    查询大纲入库任务进度

    返回:
    {
        "run_id": "...",
        "status": "running / completed / partial_success / failed",
        "outline_name": "2024年408统考大纲",
        "total_subjects": 4,
        "processed_subjects": 2,
        "current_subject": "数据结构",
        "created_at": "...",
        "completed_at": "...",
        "error_message": null
    }
    """
    from app.models.mysql_models import OutlineIngestionRun

    run = await db.get(OutlineIngestionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")

    return ApiResponse(data={
        "id": run.id,
        "document_id": run.document_id,
        "outline_id": run.outline_id,
        "outline_name": run.outline_name,
        "file_name": (run.result_summary or {}).get("file_name") if isinstance(run.result_summary, dict) else None,
        "status": run.status,
        "current_stage": run.current_stage,
        "stage_detail": run.stage_detail,
        "total_subjects": run.total_subjects,
        "processed_subjects": run.processed_subjects,
        "successful_subjects": run.successful_subjects,
        "current_subject_name": run.current_subject_name,
        "error_detail": run.error_detail,
        "result_summary": run.result_summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    })


@router.delete("/outlines/{outline_id}", response_model=ApiResponse)
async def delete_outline(outline_id: str, db: AsyncSession = Depends(get_db)):
    """
    删除大纲及其所有关联数据

    删除内容:
    - ExamOutline 记录
    - ExamOutlineSubject 关联
    - CanonicalChapter 所有章节（级联删除会自动清理关联表）
    """
    from app.models.mysql_models import ExamOutline, ExamOutlineSubject, CanonicalChapter

    outline = await db.get(ExamOutline, outline_id)
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")

    # 统计删除数量
    chapters_count = await db.scalar(
        select(func.count()).select_from(CanonicalChapter).where(
            CanonicalChapter.outline_id == outline_id
        )
    )

    # 删除章节（级联删除会自动清理 chapter links 等）
    await db.execute(
        delete(CanonicalChapter).where(CanonicalChapter.outline_id == outline_id)
    )

    # 删除科目关联
    await db.execute(
        delete(ExamOutlineSubject).where(ExamOutlineSubject.outline_id == outline_id)
    )

    # 删除大纲
    await db.delete(outline)
    await db.commit()

    return ApiResponse(data={
        "outline_id": outline_id,
        "outline_name": outline.name,
        "deleted_chapters": chapters_count,
        "message": "大纲已删除"
    })


@router.post(
    "/outlines/{outline_id}/subjects/{subject_id}/generate-guidance",
    response_model=ApiResponse,
)
async def generate_outline_guidance(
    outline_id: str, subject_id: str, db: AsyncSession = Depends(get_db)
):
    """为某门课的所有章节批量生成复习指导（结合考察目标，写回 exam_guidance）。"""
    from app.services.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.generate_guidance_for_subject(outline_id, subject_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/outlines/upload-parse", response_model=ApiResponse)
async def upload_parse_outline(
    file: UploadFile = File(...),
    parser_name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    上传大纲 PDF 并异步执行「注册 → 解析 → LLM 拆分」，立即返回 run_id。

    前端轮询 GET /outlines/runs/{run_id} 获取进度，完成后再调 /outlines/import-from-llm 入库。
    """
    from app.services.corpus_service import CorpusService, SUPPORTED_EXTENSIONS
    from app.models.mysql_models import OutlineIngestionRun
    import asyncio

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，仅支持 {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    # 1) 保存文件
    upload_dir = Path(__file__).parent.parent.parent / "uploads"
    upload_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_path = upload_dir / f"{timestamp}_{file.filename}"
    file_path.write_bytes(await file.read())

    # 2) 注册文件
    corpus_service = CorpusService(db)
    reg = await corpus_service.register_single_file(
        file_path=str(file_path),
        batch_label=f"outline-{timestamp}",
    )
    corpus_file_id = reg["corpus_file_id"]

    # 3) 立即创建 OutlineIngestionRun（document_id 可空），让任务列表立即可见
    from app.services.document_parse_service import generate_id
    run_id = generate_id()
    run = OutlineIngestionRun(
        id=run_id,
        document_id=None,  # 解析完成后由后台任务填充
        outline_name=file.filename,
        status="processing",
        current_stage="parsing",
        stage_detail=f"文件已上传：{file.filename}",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    await db.commit()

    # 4) 后台异步执行解析 + LLM 拆分
    async def _run_outline_parse_in_background(
        run_id: str, corpus_file_id: str, parser_name: Optional[str], is_new: bool, file_name: str
    ):
        from app.db.mysql import mysql_client
        from app.services.document_parse_service import DocumentParseService
        from app.services.outline_llm_service import OutlineLLMService
        from app.models.mysql_models import DocumentBlock

        async with mysql_client.session() as bg_session:
            try:
                bg_run = await bg_session.get(OutlineIngestionRun, run_id)
                if not bg_run:
                    logger.error("OutlineIngestionRun 不存在", run_id=run_id)
                    return

                # 解析阶段
                bg_run.current_stage = "parsing"
                bg_run.stage_detail = "正在解析 PDF..."
                await bg_session.commit()

                document_id: Optional[str] = None
                parse_service = DocumentParseService(bg_session)

                # 复用既有文档（如果已解析）
                if not is_new:
                    existing_doc = await parse_service._get_document_by_corpus_file_id(corpus_file_id)
                    if existing_doc:
                        block_count = (await bg_session.execute(
                            select(func.count()).select_from(DocumentBlock)
                            .where(DocumentBlock.document_id == existing_doc.id)
                        )).scalar_one()
                        if block_count > 0:
                            document_id = existing_doc.id

                if document_id is None:
                    parse_result = await parse_service.parse_document(corpus_file_id, parser_name=parser_name)
                    document_id = parse_result["document_id"]

                # 更新 run：解析完成，进入拆分
                bg_run.document_id = document_id
                bg_run.current_stage = "splitting"
                bg_run.stage_detail = "正在用 LLM 拆分大纲..."
                await bg_session.commit()

                # LLM 拆分阶段
                llm_service = OutlineLLMService(bg_session)
                split = await llm_service.split_outline_with_progress(run_id, document_id)

                # 完成
                bg_run.status = "done"
                bg_run.current_stage = "completed"
                bg_run.stage_detail = f"拆分完成，共 {len(split['subjects'])} 个科目"
                bg_run.total_subjects = len(split["subjects"])
                bg_run.processed_subjects = len(split["subjects"])
                bg_run.successful_subjects = len([s for s in split["subjects"] if not s.get("error")])
                # 把 file_name 存进 result_summary 方便列表展示
                split_with_meta = {**split, "file_name": file_name}
                bg_run.result_summary = split_with_meta
                bg_run.completed_at = datetime.utcnow()
                await bg_session.commit()

                logger.info("大纲解析+拆分完成", run_id=run_id, document_id=document_id)

            except Exception as e:
                logger.error("大纲后台任务失败", run_id=run_id, error=str(e))
                bg_run = await bg_session.get(OutlineIngestionRun, run_id)
                if bg_run:
                    bg_run.status = "failed"
                    bg_run.current_stage = "failed"
                    bg_run.error_detail = str(e)[:500]
                    bg_run.stage_detail = f"失败：{str(e)[:100]}"
                    bg_run.completed_at = datetime.utcnow()
                    await bg_session.commit()

    asyncio.ensure_future(_run_outline_parse_in_background(
        run_id, corpus_file_id, parser_name, reg["is_new"], file.filename
    ))

    return ApiResponse(message="大纲解析任务已启动", data={
        "run_id": run_id,
        "corpus_file_id": corpus_file_id,
        "file_name": file.filename,
        "status": "processing",
    })


@router.get("/outlines/runs/{run_id}", response_model=ApiResponse)
async def get_outline_run_detail(run_id: str, db: AsyncSession = Depends(get_db)):
    """获取大纲入库任务详情（用于进度轮询）"""
    from app.models.mysql_models import OutlineIngestionRun

    run = await db.get(OutlineIngestionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")

    progress = 0
    if run.total_subjects > 0:
        progress = round((run.processed_subjects / run.total_subjects) * 100, 1)

    return ApiResponse(data={
        "id": run.id,
        "document_id": run.document_id,
        "outline_id": run.outline_id,
        "outline_name": run.outline_name,
        "year": run.year,
        "version": run.version,
        "status": run.status,
        "current_stage": run.current_stage,
        "stage_detail": run.stage_detail,
        "progress": progress,
        "total_subjects": run.total_subjects,
        "processed_subjects": run.processed_subjects,
        "successful_subjects": run.successful_subjects,
        "current_subject_name": run.current_subject_name,
        "created_chapters": run.created_chapters,
        "updated_chapters": run.updated_chapters,
        "error_detail": run.error_detail,
        "result_summary": run.result_summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    })


@router.get("/outlines/runs", response_model=ApiResponse)
async def list_outline_runs(
    document_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """列出大纲入库任务（支持按 document_id 和 status 过滤）"""
    from app.models.mysql_models import OutlineIngestionRun

    query = select(OutlineIngestionRun).order_by(OutlineIngestionRun.created_at.desc()).limit(limit)
    if document_id:
        query = query.where(OutlineIngestionRun.document_id == document_id)
    if status:
        query = query.where(OutlineIngestionRun.status == status)

    runs = (await db.execute(query)).scalars().all()

    return ApiResponse(data={
        "items": [
            {
                "id": r.id,
                "document_id": r.document_id,
                "outline_id": r.outline_id,
                "outline_name": r.outline_name,
                "file_name": (r.result_summary or {}).get("file_name") if isinstance(r.result_summary, dict) else None,
                "status": r.status,
                "current_stage": r.current_stage,
                "stage_detail": r.stage_detail,
                "progress": round((r.processed_subjects / r.total_subjects * 100), 1) if r.total_subjects > 0 else 0,
                "total_subjects": r.total_subjects,
                "processed_subjects": r.processed_subjects,
                "successful_subjects": r.successful_subjects,
                "current_subject_name": r.current_subject_name,
                "created_chapters": r.created_chapters,
                "updated_chapters": r.updated_chapters,
                "error_detail": r.error_detail,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ]
    })


@router.delete("/outlines/runs/{run_id}", response_model=ApiResponse)
async def delete_outline_run(run_id: str, db: AsyncSession = Depends(get_db)):
    """删除大纲入库任务记录（不影响已入库的大纲数据）"""
    from app.models.mysql_models import OutlineIngestionRun

    run = await db.get(OutlineIngestionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")

    await db.delete(run)
    await db.commit()
    return ApiResponse(message="任务记录已删除", data={"run_id": run_id})


@router.post("/outlines/runs/batch-delete", response_model=ApiResponse)
async def batch_delete_outline_runs(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除大纲入库任务记录"""
    from app.models.mysql_models import OutlineIngestionRun

    if not req.ids:
        return ApiResponse(data={"deleted_count": 0, "requested_count": 0})

    result = await db.execute(
        select(OutlineIngestionRun).where(OutlineIngestionRun.id.in_(req.ids))
    )
    runs = result.scalars().all()
    for run in runs:
        await db.delete(run)
    await db.commit()

    return ApiResponse(
        message="批量删除成功",
        data={
            "deleted_count": len(runs),
            "requested_count": len(set(req.ids)),
        },
    )



# ===== 资产托管 =====

@router.get("/assets/{asset_id}/file")
async def serve_asset_file(asset_id: str, db: AsyncSession = Depends(get_db)):
    """根据 asset_id 返回资产文件（图片）"""
    from fastapi.responses import FileResponse
    from app.models.mysql_models import DocumentAsset

    asset = await db.get(DocumentAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    if not asset.file_path:
        raise HTTPException(status_code=404, detail="该资产无文件（可能是公式或表格 HTML）")

    file_path = Path(asset.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {asset.file_path}")
    return FileResponse(path=str(file_path))


@router.get("/assets/{asset_id}", response_model=ApiResponse)
async def get_asset_metadata(asset_id: str, db: AsyncSession = Depends(get_db)):
    """获取资产元数据（不含二进制文件）"""
    from app.models.mysql_models import DocumentAsset

    asset = await db.get(DocumentAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    return ApiResponse(data={
        "id": asset.id,
        "document_id": asset.document_id,
        "page_no": asset.page_no,
        "asset_type": asset.asset_type,
        "file_path": asset.file_path,
        "thumbnail_path": asset.thumbnail_path,
        "caption_text": asset.caption_text,
        "ocr_text": asset.ocr_text,
        "bbox": asset.bbox,
        "metadata": asset.metadata_json,
        "file_url": f"/api/v1/admin/assets/{asset.id}/file" if asset.file_path else None,
    })


# ===== 章节关联 =====

@router.post("/knowledge/{kp_id}/link-chapters", response_model=ApiResponse)
async def link_knowledge_point_to_chapters(kp_id: str, db: AsyncSession = Depends(get_db)):
    """手动触发知识点关联大纲章节"""
    from app.services.chapter_link_service import ChapterLinkService
    service = ChapterLinkService(db)
    try:
        result = await service.link_knowledge_point_to_chapters(kp_id)
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/questions/{question_id}/link-chapters", response_model=ApiResponse)
async def link_question_to_chapters(question_id: str, db: AsyncSession = Depends(get_db)):
    """手动触发题目关联大纲章节"""
    from app.services.chapter_link_service import ChapterLinkService
    service = ChapterLinkService(db)
    try:
        result = await service.link_question_to_chapters(question_id)
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{document_id}/link-chapters", response_model=ApiResponse)
async def batch_link_document_chapters(document_id: str, db: AsyncSession = Depends(get_db)):
    """批量关联文档下所有已审核实体到大纲章节"""
    from app.services.chapter_link_service import ChapterLinkService
    service = ChapterLinkService(db)
    try:
        result = await service.batch_link_document(document_id)
        return ApiResponse(data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chapters/{chapter_id}/entities", response_model=ApiResponse)
async def get_chapter_entities(
    chapter_id: str,
    entity_type: Optional[str] = Query(None, description="实体类型: knowledge_point / question"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """获取某章节下的知识点和题目"""
    from app.models.mysql_models import (
        KnowledgePointChapterLink, QuestionChapterLink,
        KnowledgePoint, Question
    )

    result = {"knowledge_points": [], "questions": []}

    # 查询知识点
    if not entity_type or entity_type == "knowledge_point":
        kp_links = (await db.execute(
            select(KnowledgePointChapterLink, KnowledgePoint)
            .join(KnowledgePoint, KnowledgePoint.id == KnowledgePointChapterLink.knowledge_point_id)
            .where(
                KnowledgePointChapterLink.canonical_chapter_id == chapter_id,
                KnowledgePoint.review_status == "approved"
            )
            .order_by(KnowledgePointChapterLink.relevance.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )).all()

        result["knowledge_points"] = [
            {
                "id": kp.id,
                "title": kp.title,
                "content": kp.content[:200] if kp.content else None,
                "relevance": float(link.relevance),
                "source": link.source,
                "is_primary": link.is_primary,
            }
            for link, kp in kp_links
        ]

    # 查询题目
    if not entity_type or entity_type == "question":
        q_links = (await db.execute(
            select(QuestionChapterLink, Question)
            .join(Question, Question.id == QuestionChapterLink.question_id)
            .where(
                QuestionChapterLink.canonical_chapter_id == chapter_id,
                Question.review_status == "approved"
            )
            .order_by(QuestionChapterLink.relevance.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )).all()

        result["questions"] = [
            {
                "id": q.id,
                "content": q.content[:200] if q.content else None,
                "type": q.type,
                "exam_year": q.exam_year,
                "relevance": float(link.relevance),
                "source": link.source,
                "is_primary": link.is_primary,
            }
            for link, q in q_links
        ]

    return ApiResponse(data=result)
