"""
后台管理 API 路由

提供管理员认证和后台管理相关的 RESTful API：
- POST /auth/login - 管理员登录
- POST /auth/logout - 管理员登出
- GET /auth/me - 获取当前管理员信息
- GET /dashboard/stats - 看板统计数据
- GET /dashboard/charts - 看板图表数据
- GET /persons - 艺人列表
- GET /persons/{id} - 艺人详情
- POST /persons - 创建艺人
- PUT /persons/{id} - 更新艺人
- DELETE /persons/{id} - 删除艺人
- GET /crawler/tasks - 爬虫任务列表
- POST /crawler/tasks - 创建爬虫任务
- POST /crawler/tasks/{id}/stop - 停止爬虫任务
- GET /conversations - 对话记录列表
- GET /monitor/api - API 性能监控
- GET /monitor/database - 数据库监控
- GET /settings - 系统配置
- PUT /settings - 更新系统配置
"""

import json
import os
import asyncio
from pathlib import Path
from typing import Optional, List, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, get_request_id
from app.core.websocket import log_websocket_manager
from app.db import get_db
from app.services.source_service import CrawlerSourceService
from app.services.stats_service import CrawlerStatsService
from app.services.schedule_service import CrawlerScheduleService
from app.services.log_service import CrawlerLogService
from app.models.mysql_models import DownloadedFile, CorpusFile, ParseRun, Document

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["后台管理"])


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
    person_count: int
    work_count: int
    relation_count: int
    today_chat_count: int
    data_completeness: float
    api_avg_response: float


@router.get("/dashboard/stats", response_model=ApiResponse)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """获取看板统计数据（408考研平台）"""
    from app.models.mysql_models import Subject, Chapter, KnowledgePoint, Question
    from sqlalchemy import func

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

    return ApiResponse(
        code=200,
        message="success",
        data={
            "subject_count": subject_count,
            "chapter_count": chapter_count,
            "knowledge_point_count": knowledge_point_count,
            "question_count": question_count,
            "today_chat_count": 0
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
    page: int = 1,
    page_size: int = 20,
    q: Optional[str] = None
):
    """
    获取对话记录列表
    
    TODO: 从数据库查询真实的对话记录。
    """
    # 临时返回空列表
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0
        }
    )


# ========== 系统监控相关 ==========

@router.get("/monitor/api", response_model=ApiResponse)
async def get_api_monitor():
    """
    获取 API 性能监控数据
    
    返回实时的 API 性能指标。
    """
    from app.core.monitoring import get_api_metrics
    
    metrics = await get_api_metrics()
    
    return ApiResponse(
        code=200,
        message="success",
        data=metrics
    )


@router.get("/monitor/database", response_model=ApiResponse)
async def get_database_monitor():
    """
    获取数据库监控数据
    
    返回各数据库连接状态和统计信息。
    """
    from app.core.monitoring import get_database_status
    
    status = await get_database_status()
    
    return ApiResponse(
        code=200,
        message="success",
        data=status
    )


@router.get("/monitor/errors", response_model=ApiResponse)
async def get_error_logs(
    level: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    获取错误日志
    
    从数据库查询真实的错误日志。
    """
    from app.services.log_service import CrawlerLogService
    
    service = CrawlerLogService(db)
    
    # 查询 ERROR 和 WARNING 级别的日志
    logs, total = await service.get_logs(
        skip=(page - 1) * page_size,
        limit=page_size,
        level=level or "ERROR",
    )
    
    items = []
    for log in logs:
        items.append({
            "id": str(log.id),
            "timestamp": log.created_at.isoformat() if log.created_at else None,
            "level": log.level,
            "service": "crawler",
            "message": log.message,
            "task_id": log.task_id,
            "source_id": log.source_id,
            "stage": log.stage,
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


# ========== 系统配置相关 ==========

@router.get("/settings", response_model=ApiResponse)
async def get_settings():
    """
    获取系统配置
    
    返回当前系统配置，从环境变量和配置文件读取。
    """
    from app.core.config import settings
    
    return ApiResponse(
        code=200,
        message="success",
        data={
            "llm": {
                "model": settings.OPENAI_MODEL,
                "temperature": 0.7,
                "max_tokens": 2000,
                "system_prompt": "你是一个专业的艺人知识助手..."
            },
            "search": {
                "default_page_size": 20,
                "max_results": 100,
                "similarity_threshold": 0.8,
                "weights": {
                    "name": 1.0,
                    "category": 0.8,
                    "relation": 0.6
                },
                "cache_ttl": 300
            },
            "crawler": {
                "request_interval": 1.0,
                "max_concurrency": 5,
                "timeout": 30,
                "user_agents": [],
                "proxy": None
            },
            "system": {
                "name": settings.APP_NAME,
                "announcement": "",
                "maintenance_mode": False,
                "log_level": settings.LOG_LEVEL
            }
        }
    )


@router.put("/settings", response_model=ApiResponse)
async def update_settings(data: dict):
    """
    更新系统配置
    
    TODO: 实现配置持久化存储
    """
    return ApiResponse(code=200, message="保存成功", data=data)




# ========== 对话详情相关 ==========

@router.get("/conversations/{conversation_id}", response_model=ApiResponse)
async def get_conversation_detail(conversation_id: str):
    """
    获取对话详情
    
    返回指定对话的完整内容，包括消息列表。
    """
    # 临时返回 mock 数据
    return ApiResponse(
        code=200,
        message="success",
        data={
            "id": conversation_id,
            "first_message": "周杰伦的妻子是谁？",
            "messages": [
                {
                    "id": "msg_001",
                    "role": "user",
                    "content": "周杰伦的妻子是谁？",
                    "timestamp": "2024-01-01T10:00:00Z",
                    "sources": [],
                },
                {
                    "id": "msg_002",
                    "role": "assistant",
                    "content": "周杰伦的妻子是昆凌（Hannah Quinlivan）。",
                    "timestamp": "2024-01-01T10:00:05Z",
                    "sources": [
                        {"person_id": "person_002", "name": "昆凌", "relation": "妻子"}
                    ],
                },
                {
                    "id": "msg_003",
                    "role": "user",
                    "content": "他们什么时候结婚的？",
                    "timestamp": "2024-01-01T10:00:30Z",
                    "sources": [],
                },
                {
                    "id": "msg_004",
                    "role": "assistant",
                    "content": "周杰伦和昆凌于2015年1月17日在英国举行婚礼。",
                    "timestamp": "2024-01-01T10:00:35Z",
                    "sources": [
                        {"person_id": "person_001", "name": "周杰伦"},
                        {"person_id": "person_002", "name": "昆凌"},
                    ],
                },
            ],
            "persons": ["周杰伦", "昆凌"],
            "satisfaction": "good",
            "created_at": "2024-01-01T10:00:00Z",
            "updated_at": "2024-01-01T10:00:35Z",
        }
    )

# ========== P1: 用户管理相关 ==========

MOCK_USERS = [
    {
        "id": "1",
        "username": "admin",
        "email": "admin@starmap.com",
        "role": "super_admin",
        "permissions": [
            "dashboard:view", "person:manage", "work:manage",
            "crawler:manage", "conversation:view", "monitor:view",
            "settings:manage", "user:manage",
        ],
        "is_active": True,
        "last_login_at": "2024-01-07 15:30:00",
        "created_at": "2024-01-01",
    },
    {
        "id": "2",
        "username": "data_admin",
        "email": "data@starmap.com",
        "role": "data_admin",
        "permissions": ["dashboard:view", "person:manage", "work:manage", "crawler:manage", "monitor:view"],
        "is_active": True,
        "last_login_at": "2024-01-06 10:00:00",
        "created_at": "2024-01-02",
    },
    {
        "id": "3",
        "username": "operator1",
        "email": "op1@starmap.com",
        "role": "operator",
        "permissions": ["dashboard:view", "conversation:view"],
        "is_active": True,
        "last_login_at": "2024-01-05 09:00:00",
        "created_at": "2024-01-03",
    },
    {
        "id": "4",
        "username": "operator2",
        "email": "op2@starmap.com",
        "role": "operator",
        "permissions": ["dashboard:view", "conversation:view"],
        "is_active": False,
        "last_login_at": None,
        "created_at": "2024-01-04",
    },
]


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
async def get_users():
    """获取用户列表"""
    return ApiResponse(
        code=200,
        message="success",
        data={"users": MOCK_USERS}
    )


@router.post("/users", response_model=ApiResponse)
async def create_user(req: CreateUserRequest):
    """创建用户"""
    # Mock: 简单返回成功
    new_user = {
        "id": str(len(MOCK_USERS) + 1),
        "username": req.username,
        "email": req.email,
        "role": req.role,
        "permissions": req.permissions,
        "is_active": req.is_active,
        "last_login_at": None,
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }
    MOCK_USERS.append(new_user)
    return ApiResponse(code=200, message="创建成功", data={"user": new_user})


@router.put("/users/{user_id}", response_model=ApiResponse)
async def update_user(user_id: str, req: UpdateUserRequest):
    """更新用户"""
    for user in MOCK_USERS:
        if user["id"] == user_id:
            if req.email is not None:
                user["email"] = req.email
            if req.role is not None:
                user["role"] = req.role
            if req.permissions is not None:
                user["permissions"] = req.permissions
            if req.is_active is not None:
                user["is_active"] = req.is_active
            return ApiResponse(code=200, message="更新成功", data={"user": user})
    raise HTTPException(status_code=404, detail="用户不存在")


@router.delete("/users/{user_id}", response_model=ApiResponse)
async def delete_user(user_id: str):
    """删除用户"""
    for i, user in enumerate(MOCK_USERS):
        if user["id"] == user_id:
            MOCK_USERS.pop(i)
            return ApiResponse(code=200, message="删除成功")
    raise HTTPException(status_code=404, detail="用户不存在")


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
    """获取知识点详情"""
    from app.models.mysql_models import KnowledgePoint
    result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.id == point_id)
    )
    point = result.scalar_one_or_none()
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")

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
    """获取题目详情"""
    from app.models.mysql_models import Question
    result = await db.execute(
        select(Question).where(Question.id == question_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    return ApiResponse(data={
        "id": question.id,
        "subject_id": question.subject_id,
        "chapter_id": question.chapter_id,
        "type": question.type,
        "content": question.content,
        "options": question.options,
        "answer": question.answer,
        "explanation": question.explanation,
        "difficulty": question.difficulty,
        "source": question.source,
        "exam_year": question.exam_year,
        "knowledge_point_ids": question.knowledge_point_ids,
        "tags": question.tags,
        "status": question.status,
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


@router.post("/corpus/files/{file_id}/parse", response_model=ApiResponse)
async def parse_corpus_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """触发文档解析"""
    from app.services.document_parse_service import DocumentParseService

    service = DocumentParseService(db)
    try:
        result = await service.parse_document(file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)[:200]}")

    return ApiResponse(data=result)
