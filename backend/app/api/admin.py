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
import asyncio
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, get_request_id
from app.core.websocket import log_websocket_manager
from app.db import get_db
from app.services.source_service import CrawlerSourceService
from app.services.stats_service import CrawlerStatsService
from app.services.schedule_service import CrawlerScheduleService
from app.services.log_service import CrawlerLogService

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
    data: Optional[dict] = None
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
            "crawler:view", "crawler:control",
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
async def get_dashboard_stats():
    """
    获取看板统计数据
    
    返回系统核心运营指标。
    """
    return ApiResponse(
        code=200,
        message="success",
        data={
            "person_count": 1256,
            "work_count": 3421,
            "relation_count": 8923,
            "today_chat_count": 156,
            "data_completeness": 87.5,
            "api_avg_response": 45.2
        }
    )


@router.get("/dashboard/charts", response_model=ApiResponse)
async def get_dashboard_charts():
    """
    获取看板图表数据
    
    返回趋势图、分布图等图表所需数据。
    """
    return ApiResponse(
        code=200,
        message="success",
        data={
            "chat_trend": [
                {"date": "2024-01-01", "count": 120},
                {"date": "2024-01-02", "count": 145},
                {"date": "2024-01-03", "count": 132},
                {"date": "2024-01-04", "count": 156},
                {"date": "2024-01-05", "count": 178},
                {"date": "2024-01-06", "count": 165},
                {"date": "2024-01-07", "count": 190}
            ],
            "category_distribution": [
                {"name": "演员", "value": 456},
                {"name": "歌手", "value": 342},
                {"name": "导演", "value": 198},
                {"name": "制片人", "value": 87},
                {"name": "编剧", "value": 173}
            ],
            "hot_search": [
                {"name": "周杰伦", "value": 1250},
                {"name": "刘德华", "value": 980},
                {"name": "成龙", "value": 876},
                {"name": "周星驰", "value": 754},
                {"name": "张艺谋", "value": 621},
                {"name": "巩俐", "value": 543},
                {"name": "周润发", "value": 498},
                {"name": "梁朝伟", "value": 432},
                {"name": "张曼玉", "value": 387},
                {"name": "王家卫", "value": 321}
            ],
            "crawler_status": [
                {"name": "运行中", "value": 3},
                {"name": "已完成", "value": 12},
                {"name": "失败", "value": 2},
                {"name": "已停止", "value": 1},
                {"name": "待启动", "value": 5}
            ]
        }
    )


# ========== 艺人管理相关 ==========

class PersonListItem(BaseModel):
    """艺人列表项"""
    id: str
    name: str
    name_en: Optional[str] = None
    avatar: Optional[str] = None
    categories: List[str] = []
    nationality: Optional[str] = None
    status: str
    created_at: str


class PaginatedResponse(BaseModel):
    """分页响应"""
    items: List[dict]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("/persons", response_model=ApiResponse)
async def get_person_list(
    page: int = 1,
    page_size: int = 20,
    q: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None
):
    """
    获取艺人列表
    
    支持搜索、筛选、分页。从 Neo4j 查询真实数据。
    """
    from app.services.person_service import PersonService
    from app.models.person import PersonListItem, PersonSearchResult
    
    service = PersonService()
    
    # 如果有搜索关键词，使用搜索接口
    if q:
        result = await service.search_persons(
            keyword=q,
            category=category,
            page=page,
            page_size=page_size
        )
        items = [item.model_dump() for item in result.items]
        total = result.total
    else:
        # 使用搜索接口获取所有人物（空关键词）
        result = await service.search_persons(
            keyword="*",
            category=category,
            page=page,
            page_size=page_size
        )
        items = [item.model_dump() for item in result.items]
        total = result.total
    
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


@router.get("/persons/{person_id}", response_model=ApiResponse)
async def get_person_detail(person_id: str):
    """
    获取艺人详情
    
    返回指定艺人的完整信息。从 Neo4j 查询真实数据。
    """
    from app.services.person_service import PersonService
    
    service = PersonService()
    person = await service.get_person_by_id(person_id)
    
    if not person:
        raise HTTPException(status_code=404, detail="艺人不存在")
    
    return ApiResponse(
        code=200,
        message="success",
        data=person.model_dump()
    )


@router.post("/persons", response_model=ApiResponse)
async def create_person(data: dict):
    """创建艺人"""
    # TODO: 实现艺人创建逻辑
    return ApiResponse(
        code=200,
        message="创建成功",
        data={"id": "new_person_id", "name": data.get("name", "")}
    )


@router.put("/persons/{person_id}", response_model=ApiResponse)
async def update_person(person_id: str, data: dict):
    """更新艺人"""
    # TODO: 实现艺人更新逻辑
    return ApiResponse(
        code=200,
        message="更新成功",
        data={"id": person_id, **data}
    )


@router.delete("/persons/{person_id}", response_model=ApiResponse)
async def delete_person(person_id: str):
    """删除艺人"""
    # TODO: 实现艺人删除逻辑
    return ApiResponse(code=200, message="删除成功")


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
    target_config = {
        **config,
        "source_ids": data.get("source_ids", []),
    }
    
    task = await service.create_task(
        name=data.get("name", "手动任务"),
        task_type=data.get("task_type", "targeted"),
        source_ids=data.get("source_ids", []),
        target_config=target_config,
        created_by=data.get("created_by"),
    )
    
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
                "total_requests": s.total_requests,
                "total_success": s.total_success,
                "total_failed": s.total_failed,
                "avg_response_time": float(s.avg_response_time) if s.avg_response_time else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
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
    source = await service.create_source(data)
    return ApiResponse(code=200, message="创建成功", data={"id": source.id})


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


@router.get("/crawler/stats/efficiency", response_model=ApiResponse)
async def get_crawler_efficiency(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """获取效率分析"""
    service = CrawlerStatsService(db)
    efficiency = await service.get_efficiency(days)
    return ApiResponse(code=200, message="success", data=efficiency)


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
                "cron_expression": s.cron_expression,
                "timezone": s.timezone,
                "is_enabled": s.is_enabled,
                "max_retries": s.max_retries,
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


# ========== 作品管理相关 ==========

@router.get("/works", response_model=ApiResponse)
async def get_work_list(
    page: int = 1,
    page_size: int = 20,
    q: Optional[str] = None,
    type: Optional[str] = None,
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    获取作品列表
    
    支持搜索、筛选、分页。
    """
    from app.services.work_service import WorkService
    
    service = WorkService(db)
    works, total = await service.get_works(
        skip=(page - 1) * page_size,
        limit=page_size,
        keyword=q,
        work_type=type,
        year=year,
    )
    
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [{
                "id": w.id,
                "title": w.title,
                "title_en": w.title_en,
                "type": w.type,
                "release_date": w.release_date.isoformat() if w.release_date else None,
                "poster": w.poster,
                "rating": float(w.rating) if w.rating else None,
                "status": w.status,
                "genre": w.genre,
                "summary": w.summary,
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "updated_at": w.updated_at.isoformat() if w.updated_at else None,
            } for w in works],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        }
    )


@router.get("/works/{work_id}", response_model=ApiResponse)
async def get_work_detail(
    work_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    获取作品详情
    """
    from app.services.work_service import WorkService
    
    service = WorkService(db)
    work = await service.get_work_by_id(work_id)
    
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    
    return ApiResponse(
        code=200,
        message="success",
        data={
            "id": work.id,
            "title": work.title,
            "title_en": work.title_en,
            "type": work.type,
            "release_date": work.release_date.isoformat() if work.release_date else None,
            "poster": work.poster,
            "summary": work.summary,
            "cover": work.cover,
            "rating": float(work.rating) if work.rating else None,
            "status": work.status,
            "source": work.source,
            "genres": work.genres,
            "tags": work.tags,
            "director": work.director,
            "actors": work.actors,
            "box_office": work.box_office,
            "episodes": work.episodes,
            "platform": work.platform,
            "artist": work.artist,
            "record_company": work.record_company,
            "track_list": work.track_list,
            "author": work.author,
            "publisher": work.publisher,
            "isbn": work.isbn,
            "related_persons": [{
                "id": p.id,
                "name": p.name,
                "role": p.role,
            } for p in (work.related_persons or [])],
            "created_at": work.created_at.isoformat() if work.created_at else None,
            "updated_at": work.updated_at.isoformat() if work.updated_at else None,
        }
    )


@router.post("/works", response_model=ApiResponse)
async def create_work(
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    创建作品
    """
    from app.services.work_service import WorkService
    
    service = WorkService(db)
    work = await service.create_work(data)
    
    return ApiResponse(
        code=200,
        message="创建成功",
        data={"id": work.id, "title": work.title}
    )


@router.put("/works/{work_id}", response_model=ApiResponse)
async def update_work(
    work_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    更新作品
    """
    from app.services.work_service import WorkService
    
    service = WorkService(db)
    work = await service.update_work(work_id, data)
    
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    
    return ApiResponse(
        code=200,
        message="更新成功",
        data={"id": work.id, "title": work.title}
    )


@router.delete("/works/{work_id}", response_model=ApiResponse)
async def delete_work(
    work_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    删除作品
    """
    from app.services.work_service import WorkService
    
    service = WorkService(db)
    success = await service.delete_work(work_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="作品不存在")
    
    return ApiResponse(code=200, message="删除成功")


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
