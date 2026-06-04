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
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
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
    request_id: str = ""


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
    
    支持搜索、筛选、分页。
    """
    # 模拟数据
    mock_persons = [
        {
            "id": "person_001",
            "name": "周杰伦",
            "name_en": "Jay Chou",
            "avatar": "https://example.com/jay.jpg",
            "categories": ["singer", "actor", "director"],
            "nationality": "中国",
            "status": "complete",
            "created_at": "2024-01-01T10:00:00Z"
        },
        {
            "id": "person_002",
            "name": "昆凌",
            "name_en": "Hannah Quinlivan",
            "avatar": None,
            "categories": ["actor", "model"],
            "nationality": "中国",
            "status": "complete",
            "created_at": "2024-01-02T10:00:00Z"
        },
        {
            "id": "person_003",
            "name": "方文山",
            "name_en": "Vincent Fang",
            "avatar": None,
            "categories": ["writer", "director"],
            "nationality": "中国",
            "status": "partial",
            "created_at": "2024-01-03T10:00:00Z"
        }
    ]
    
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": mock_persons,
            "total": 3,
            "page": page,
            "page_size": page_size,
            "total_pages": 1
        }
    )


@router.get("/persons/{person_id}", response_model=ApiResponse)
async def get_person_detail(person_id: str):
    """
    获取艺人详情
    
    返回指定艺人的完整信息。
    """
    mock_person = {
        "id": person_id,
        "name": "周杰伦",
        "name_en": "Jay Chou",
        "avatar": "https://example.com/jay.jpg",
        "gender": "male",
        "birth_date": "1979-01-18",
        "birth_place": "台湾省新北市",
        "nationality": "中国",
        "height": 175,
        "categories": ["singer", "actor", "director"],
        "summary": "华语流行乐男歌手、音乐人、演员、导演、编剧...",
        "biography": "周杰伦（Jay Chou），1979年1月18日出生于台湾省新北市...",
        "status": "complete",
        "source": "wikipedia",
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-15T10:00:00Z"
    }
    
    return ApiResponse(
        code=200,
        message="success",
        data=mock_person
    )


@router.post("/persons", response_model=ApiResponse)
async def create_person():
    """创建艺人"""
    return ApiResponse(code=200, message="创建成功")


@router.put("/persons/{person_id}", response_model=ApiResponse)
async def update_person(person_id: str):
    """更新艺人"""
    return ApiResponse(code=200, message="更新成功")


@router.delete("/persons/{person_id}", response_model=ApiResponse)
async def delete_person(person_id: str):
    """删除艺人"""
    return ApiResponse(code=200, message="删除成功")


# ========== 爬虫管理相关 ==========

@router.get("/crawler/tasks", response_model=ApiResponse)
async def get_crawler_tasks(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None
):
    """
    获取爬虫任务列表
    """
    mock_tasks = [
        {
            "id": "task_001",
            "type": "full",
            "source": "wikipedia",
            "target_count": 1000,
            "completed_count": 750,
            "success_count": 720,
            "fail_count": 30,
            "success_rate": 96.0,
            "progress": 75.0,
            "status": "running",
            "started_at": "2024-01-01T10:00:00Z",
            "completed_at": None,
            "estimated_completion": "2024-01-04T18:00:00Z",
            "error_message": None
        },
        {
            "id": "task_002",
            "type": "incremental",
            "source": "wikipedia",
            "target_count": 100,
            "completed_count": 100,
            "success_count": 98,
            "fail_count": 2,
            "success_rate": 98.0,
            "progress": 100.0,
            "status": "completed",
            "started_at": "2024-01-02T10:00:00Z",
            "completed_at": "2024-01-02T12:00:00Z",
            "estimated_completion": None,
            "error_message": None
        },
        {
            "id": "task_003",
            "type": "targeted",
            "source": "douban",
            "target_count": 50,
            "completed_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "success_rate": 0.0,
            "progress": 0.0,
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "estimated_completion": None,
            "error_message": None
        },
        {
            "id": "task_004",
            "type": "full",
            "source": "wikipedia",
            "target_count": 500,
            "completed_count": 500,
            "success_count": 450,
            "fail_count": 50,
            "success_rate": 90.0,
            "progress": 100.0,
            "status": "failed",
            "started_at": "2024-01-03T09:00:00Z",
            "completed_at": "2024-01-03T11:30:00Z",
            "estimated_completion": None,
            "error_message": "连接超时，部分请求失败"
        },
        {
            "id": "task_005",
            "type": "incremental",
            "source": "wikipedia",
            "target_count": 200,
            "completed_count": 120,
            "success_count": 115,
            "fail_count": 5,
            "success_rate": 95.8,
            "progress": 60.0,
            "status": "stopped",
            "started_at": "2024-01-04T08:00:00Z",
            "completed_at": None,
            "estimated_completion": None,
            "error_message": "用户手动停止"
        }
    ]
    
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": mock_tasks,
            "total": 2,
            "page": page,
            "page_size": page_size,
            "total_pages": 1
        }
    )


@router.post("/crawler/tasks", response_model=ApiResponse)
async def create_crawler_task():
    """创建爬虫任务"""
    return ApiResponse(code=200, message="任务已创建")


@router.post("/crawler/tasks/{task_id}/stop", response_model=ApiResponse)
async def stop_crawler_task(task_id: str):
    """停止爬虫任务"""
    return ApiResponse(code=200, message="任务已停止")


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
                    log_websocket_manager._connections[websocket] = {
                        "task_ids": new_task_ids if new_task_ids else set(),
                        "source_ids": new_source_ids if new_source_ids else set(),
                        "levels": new_levels if new_levels else set(),
                    }
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
    """
    mock_conversations = [
        {
            "id": "conv_001",
            "first_message": "周杰伦的妻子是谁？",
            "message_count": 5,
            "duration": 180,
            "persons": ["周杰伦", "昆凌"],
            "satisfaction": "good",
            "created_at": "2024-01-01T10:00:00Z"
        },
        {
            "id": "conv_002",
            "first_message": "方文山和周杰伦合作过哪些歌？",
            "message_count": 3,
            "duration": 120,
            "persons": ["周杰伦", "方文山"],
            "satisfaction": "good",
            "created_at": "2024-01-02T10:00:00Z"
        }
    ]
    
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": mock_conversations,
            "total": 2,
            "page": page,
            "page_size": page_size,
            "total_pages": 1
        }
    )


# ========== 系统监控相关 ==========

@router.get("/monitor/api", response_model=ApiResponse)
async def get_api_monitor():
    """
    获取 API 性能监控数据
    """
    return ApiResponse(
        code=200,
        message="success",
        data={
            "total_requests": 12580,
            "avg_response_time": 45.2,
            "error_rate": 0.02,
            "qps": 15.6
        }
    )


@router.get("/monitor/database", response_model=ApiResponse)
async def get_database_monitor():
    """
    获取数据库监控数据
    """
    return ApiResponse(
        code=200,
        message="success",
        data={
            "status": "connected",
            "neo4j": {
                "status": "up",
                "nodes": 1256,
                "edges": 8923
            },
            "redis": {
                "status": "up",
                "memory": "256MB",
                "hit_rate": 0.95
            }
        }
    )


@router.get("/monitor/errors", response_model=ApiResponse)
async def get_error_logs(
    level: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """
    获取错误日志
    """
    mock_errors = [
        {
            "id": "err_001",
            "timestamp": "2024-01-01T10:00:00Z",
            "level": "ERROR",
            "service": "backend",
            "message": "Neo4j connection timeout"
        },
        {
            "id": "err_002",
            "timestamp": "2024-01-01T11:00:00Z",
            "level": "WARNING",
            "service": "crawler",
            "message": "Rate limit exceeded"
        }
    ]
    
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": mock_errors,
            "total": 2,
            "page": page,
            "page_size": page_size,
            "total_pages": 1
        }
    )


# ========== 系统配置相关 ==========

@router.get("/settings", response_model=ApiResponse)
async def get_settings():
    """
    获取系统配置
    """
    return ApiResponse(
        code=200,
        message="success",
        data={
            "llm": {
                "model": "gpt-4",
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
                "name": "StarMap",
                "announcement": "",
                "maintenance_mode": False,
                "log_level": "INFO"
            }
        }
    )


@router.put("/settings", response_model=ApiResponse)
async def update_settings():
    """
    更新系统配置
    """
    return ApiResponse(code=200, message="保存成功")
