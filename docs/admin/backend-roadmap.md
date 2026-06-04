# 后台管理端 - 后端开发路线

> 负责人：Backend
> 时间：Week 4-5
> 依赖：主站后端框架 + 数据库连接

---

## Week 4：核心API开发

### Day 1（周一）：认证与权限框架

**目标**：实现管理员认证和权限控制

| 任务 | 产出 | 说明 |
|------|------|------|
| 设计管理员用户模型 | `app/models/admin.py` | 用户、角色、权限 |
| 实现JWT认证 | `app/core/auth.py` | Token生成/验证/刷新 |
| 实现密码加密 | `app/core/security.py` | bcrypt加密 |
| 实现权限装饰器 | `app/core/permissions.py` | @require_permission |
| 实现登录API | `app/api/admin/auth.py` | POST /admin/auth/login |
| 实现登出API | `app/api/admin/auth.py` | POST /admin/auth/logout |
| 实现获取当前用户 | `app/api/admin/auth.py` | GET /admin/auth/me |

**管理员用户模型**：
```python
class AdminUser(BaseModel):
    id: str
    username: str
    email: str
    role: str  # super_admin / data_admin / operator
    permissions: List[str]
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime

class AdminRole(Enum):
    SUPER_ADMIN = "super_admin"    # L3 - 全部权限
    DATA_ADMIN = "data_admin"      # L2 - 数据管理
    OPERATOR = "operator"          # L1 - 查看权限

# 权限定义
PERMISSIONS = {
    "dashboard:view": "查看数据看板",
    "person:view": "查看艺人",
    "person:edit": "编辑艺人",
    "person:create": "创建艺人",
    "person:delete": "删除艺人",
    "crawler:control": "控制爬虫",
    "crawler:config": "配置爬虫",
    "conversation:view": "查看对话",
    "monitor:view": "查看监控",
    "settings:manage": "管理系统配置",
}

ROLE_PERMISSIONS = {
    AdminRole.OPERATOR: [
        "dashboard:view", "person:view", "conversation:view", "monitor:view"
    ],
    AdminRole.DATA_ADMIN: [
        "dashboard:view", "person:view", "person:edit", "person:create",
        "crawler:control", "conversation:view", "monitor:view"
    ],
    AdminRole.SUPER_ADMIN: list(PERMISSIONS.keys()),
}
```

**JWT配置**：
```python
# app/core/auth.py
from datetime import datetime, timedelta
from jose import JWTError, jwt

SECRET_KEY = "your-secret-key"  # 从环境变量读取
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24小时

class TokenData(BaseModel):
    user_id: str
    role: str
    permissions: List[str]

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenData(**payload)
    except JWTError:
        return None
```

---

### Day 2（周二）：看板API + 艺人管理API

**目标**：实现数据看板和艺人CRUD API

| 任务 | 产出 | 说明 |
|------|------|------|
| 实现看板统计API | `app/api/admin/dashboard.py` | GET /admin/dashboard/stats |
| 实现看板图表数据 | `app/api/admin/dashboard.py` | GET /admin/dashboard/charts |
| 实现艺人列表API | `app/api/admin/person.py` | GET /admin/persons |
| 实现艺人详情API | `app/api/admin/person.py` | GET /admin/persons/:id |
| 实现艺人创建API | `app/api/admin/person.py` | POST /admin/persons |
| 实现Neo4j统计查询 | `app/services/stats.py` | 节点/边数量统计 |

**看板统计API**：
```python
@router.get("/dashboard/stats")
async def get_dashboard_stats(
    current_user: AdminUser = Depends(get_current_admin_user)
):
    """获取看板核心指标"""
    stats = {
        "person_count": await neo4j_service.count_nodes("Person"),
        "work_count": await neo4j_service.count_nodes("Work"),
        "relation_count": await neo4j_service.count_relationships(),
        "today_conversations": await redis_service.get_today_conversation_count(),
        "data_completeness": await calculate_data_completeness(),
        "api_avg_response": await redis_service.get_avg_response_time(),
    }
    return {"code": 200, "data": stats}

@router.get("/dashboard/charts")
async def get_dashboard_charts(
    days: int = Query(7, ge=1, le=30),
    current_user: AdminUser = Depends(get_current_admin_user)
):
    """获取看板图表数据"""
    charts = {
        "conversation_trend": await get_conversation_trend(days),
        "category_distribution": await get_category_distribution(),
        "hot_search": await get_hot_search_keywords(10),
        "crawler_status": await get_crawler_tasks_status(),
    }
    return {"code": 200, "data": charts}
```

**艺人列表API**：
```python
@router.get("/persons")
async def list_persons(
    q: Optional[str] = Query(None, description="搜索关键词"),
    category: Optional[str] = Query(None),
    nationality: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: AdminUser = Depends(get_current_admin_user)
):
    """获取艺人列表（支持搜索、筛选、排序、分页）"""
    # 构建查询条件
    filters = {}
    if q:
        filters["name"] = {"$regex": q, "$options": "i"}
    if category:
        filters["categories"] = category
    if nationality:
        filters["nationality"] = nationality
    if status:
        filters["status"] = status
    
    # 执行查询
    persons, total = await neo4j_service.find_persons(
        filters=filters,
        sort={sort_by: sort_order},
        skip=(page - 1) * page_size,
        limit=page_size
    )
    
    return {
        "code": 200,
        "data": {
            "items": [p.to_dict() for p in persons],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    }
```

---

### Day 3（周三）：艺人编辑 + 作品管理API

**目标**：实现艺人编辑和作品管理

| 任务 | 产出 | 说明 |
|------|------|------|
| 实现艺人更新API | `app/api/admin/person.py` | PUT /admin/persons/:id |
| 实现艺人删除API | `app/api/admin/person.py` | DELETE /admin/persons/:id |
| 实现艺人批量操作 | `app/api/admin/person.py` | POST /admin/persons/batch |
| 实现作品列表API | `app/api/admin/work.py` | GET /admin/works |
| 实现作品CRUD | `app/api/admin/work.py` | POST/PUT/DELETE |
| 实现数据验证 | `app/schemas/admin.py` | Pydantic模型 |

**艺人更新API**：
```python
class PersonUpdateRequest(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    avatar: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[str] = None
    birth_place: Optional[str] = None
    nationality: Optional[str] = None
    height: Optional[float] = None
    summary: Optional[str] = None
    biography: Optional[str] = None
    categories: Optional[List[str]] = None
    works: Optional[List[str]] = None  # 关联作品ID列表

@router.put("/persons/{person_id}")
async def update_person(
    person_id: str,
    request: PersonUpdateRequest,
    current_user: AdminUser = Depends(require_permission("person:edit"))
):
    """更新艺人信息"""
    # 检查艺人是否存在
    person = await neo4j_service.get_person(person_id)
    if not person:
        raise HTTPException(status_code=404, detail="艺人不存在")
    
    # 更新数据
    update_data = request.dict(exclude_unset=True)
    update_data["updated_at"] = datetime.now().isoformat()
    update_data["updated_by"] = current_user.id
    
    await neo4j_service.update_person(person_id, update_data)
    
    # 记录编辑历史
    await log_edit_history("person", person_id, current_user.id, update_data)
    
    return {"code": 200, "message": "更新成功"}
```

---

### Day 4（周四）：爬虫管理API

**目标**：实现爬虫任务管理和控制

| 任务 | 产出 | 说明 |
|------|------|------|
| 设计爬虫任务模型 | `app/models/crawler_task.py` | 任务状态、进度 |
| 实现任务列表API | `app/api/admin/crawler.py` | GET /admin/crawler/tasks |
| 实现创建任务API | `app/api/admin/crawler.py` | POST /admin/crawler/tasks |
| 实现停止任务API | `app/api/admin/crawler.py` | POST /admin/crawler/tasks/:id/stop |
| 实现任务日志API | `app/api/admin/crawler.py` | GET /admin/crawler/tasks/:id/logs |
| 实现爬虫配置API | `app/api/admin/crawler.py` | GET/PUT /admin/crawler/config |
| 实现爬取统计API | `app/api/admin/crawler.py` | GET /admin/crawler/stats |
| 实现数据源统计API | `app/api/admin/crawler.py` | GET /admin/crawler/stats/sources |
| 实现失败分析API | `app/api/admin/crawler.py` | GET /admin/crawler/stats/failures |
| 实现实时速率API | `app/api/admin/crawler.py` | GET /admin/crawler/stats/realtime |

**爬虫任务模型**：
```python
class CrawlerTaskStatus(str, Enum):
    PENDING = "pending"      # 待启动
    RUNNING = "running"      # 运行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    STOPPED = "stopped"      # 已停止

class CrawlerTask(BaseModel):
    id: str
    name: str
    task_type: str  # full / incremental / targeted
    source: str     # wikipedia / douban
    target_count: int
    completed_count: int
    status: CrawlerTaskStatus
    progress: float  # 0-100
    config: Dict[str, Any]
    logs: List[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_by: str

class CrawlerConfig(BaseModel):
    delay: float = 1.0
    timeout: int = 30
    max_retries: int = 3
    use_proxy: bool = False
    proxy_url: Optional[str] = None
    concurrent_limit: int = 1
    daily_limit: Optional[int] = None
```

**爬虫控制API**：
```python
# 任务管理
@router.get("/crawler/tasks")
async def list_crawler_tasks(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: AdminUser = Depends(require_permission("crawler:control"))
):
    """获取爬虫任务列表"""
    tasks = await crawler_service.list_tasks(status, page, page_size)
    return {"code": 200, "data": tasks}

@router.post("/crawler/tasks")
async def create_crawler_task(
    request: CreateCrawlerTaskRequest,
    background_tasks: BackgroundTasks,
    current_user: AdminUser = Depends(require_permission("crawler:control"))
):
    """创建并启动爬虫任务"""
    task = await crawler_service.create_task(
        name=request.name,
        task_type=request.task_type,
        source=request.source,
        target_count=request.target_count,
        config=request.config,
        created_by=current_user.id
    )
    
    # 后台启动爬虫
    background_tasks.add_task(crawler_service.run_task, task.id)
    
    return {"code": 200, "data": {"task_id": task.id}}

@router.post("/crawler/tasks/{task_id}/stop")
async def stop_crawler_task(
    task_id: str,
    current_user: AdminUser = Depends(require_permission("crawler:control"))
):
    """停止爬虫任务"""
    await crawler_service.stop_task(task_id)
    return {"code": 200, "message": "任务已停止"}

# 实时日志（WebSocket）
@router.websocket("/crawler/tasks/{task_id}/logs")
async def crawler_logs_websocket(
    websocket: WebSocket,
    task_id: str
):
    """实时推送爬虫日志"""
    await websocket.accept()
    
    # 订阅任务日志
    async for log in crawler_service.subscribe_logs(task_id):
        await websocket.send_text(log)
    
    await websocket.close()

# 爬取统计API
@router.get("/crawler/stats")
async def get_crawler_statistics(
    days: int = Query(7, ge=1, le=30),
    current_user: AdminUser = Depends(require_permission("crawler:control"))
):
    """获取爬取统计报表"""
    stats = {
        "overview": {
            "total_tasks": await crawler_service.count_total_tasks(),
            "total_crawled": await crawler_service.count_total_crawled(),
            "total_success": await crawler_service.count_total_success(),
            "total_failed": await crawler_service.count_total_failed(),
            "overall_success_rate": await crawler_service.get_overall_success_rate(),
            "today_crawled": await crawler_service.count_today_crawled(),
        },
        "task_execution": {
            "running_tasks": await crawler_service.count_running_tasks(),
            "pending_tasks": await crawler_service.count_pending_tasks(),
            "today_completed": await crawler_service.count_today_completed(),
            "today_failed": await crawler_service.count_today_failed(),
            "avg_task_duration": await crawler_service.get_avg_task_duration(days),
            "avg_crawl_speed": await crawler_service.get_avg_crawl_speed(),
        },
        "source_distribution": await crawler_service.get_source_distribution(days),
        "failure_analysis": {
            "top_failure_reasons": await crawler_service.get_top_failure_reasons(5),
            "failure_trend": await crawler_service.get_failure_trend(days),
            "retry_success_rate": await crawler_service.get_retry_success_rate(),
            "failed_resources": await crawler_service.get_recent_failed_resources(10),
        },
        "coverage": {
            "person_count": await crawler_service.get_crawled_person_count(),
            "work_count": await crawler_service.get_crawled_work_count(),
            "category_distribution": await crawler_service.get_category_distribution(),
            "nationality_distribution": await crawler_service.get_nationality_distribution(),
            "data_completeness": await crawler_service.get_data_completeness(),
        },
    }
    return {"code": 200, "data": stats}

@router.get("/crawler/stats/sources")
async def get_crawler_source_stats(
    days: int = Query(7, ge=1, le=30),
    current_user: AdminUser = Depends(require_permission("crawler:control"))
):
    """获取数据源统计"""
    sources = await crawler_service.get_source_statistics(days)
    return {"code": 200, "data": sources}

@router.get("/crawler/stats/failures")
async def get_crawler_failure_stats(
    days: int = Query(7, ge=1, le=30),
    current_user: AdminUser = Depends(require_permission("crawler:control"))
):
    """获取失败分析统计"""
    failures = await crawler_service.get_failure_statistics(days)
    return {"code": 200, "data": failures}

@router.get("/crawler/stats/realtime")
async def get_crawler_realtime_stats(
    current_user: AdminUser = Depends(require_permission("crawler:control"))
):
    """获取实时爬取速率"""
    realtime = {
        "current_speed": await crawler_service.get_current_crawl_speed(),
        "running_tasks_progress": await crawler_service.get_running_tasks_progress(),
        "recent_logs": await crawler_service.get_recent_logs(10),
        "system_load": await crawler_service.get_system_load(),
    }
    return {"code": 200, "data": realtime}
```

---

### Day 5（周五）：对话管理API

**目标**：实现对话记录查询和分析

| 任务 | 产出 | 说明 |
|------|------|------|
| 实现对话列表API | `app/api/admin/conversation.py` | GET /admin/conversations |
| 实现对话详情API | `app/api/admin/conversation.py` | GET /admin/conversations/:id |
| 实现对话统计API | `app/api/admin/conversation.py` | GET /admin/conversations/stats |
| 实现热门问题API | `app/api/admin/conversation.py` | GET /admin/conversations/hot |
| 实现质量标注API | `app/api/admin/conversation.py` | POST /admin/conversations/:id/annotate |

**对话查询API**：
```python
@router.get("/conversations")
async def list_conversations(
    q: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: AdminUser = Depends(require_permission("conversation:view"))
):
    """获取对话记录列表"""
    filters = {}
    if q:
        filters["message_content"] = {"$regex": q}
    if person_id:
        filters["mentioned_persons"] = person_id
    if start_date and end_date:
        filters["created_at"] = {"$gte": start_date, "$lte": end_date}
    
    conversations = await conversation_service.list_conversations(
        filters, page, page_size
    )
    return {"code": 200, "data": conversations}

@router.get("/conversations/stats")
async def get_conversation_stats(
    days: int = Query(7, ge=1, le=30),
    current_user: AdminUser = Depends(require_permission("conversation:view"))
):
    """获取对话统计"""
    stats = {
        "total_conversations": await conversation_service.count_conversations(days),
        "avg_messages_per_conversation": await conversation_service.avg_messages(),
        "top_questions": await conversation_service.get_top_questions(10),
        "unanswered_questions": await conversation_service.get_unanswered_questions(),
        "person_mention_rank": await conversation_service.get_person_mention_rank(10),
    }
    return {"code": 200, "data": stats}
```

---

### Day 6（周六）：系统监控API

**目标**：实现系统监控和日志查询

| 任务 | 产出 | 说明 |
|------|------|------|
| 实现API性能监控 | `app/api/admin/monitor.py` | GET /admin/monitor/api |
| 实现数据库监控 | `app/api/admin/monitor.py` | GET /admin/monitor/database |
| 实现错误日志查询 | `app/api/admin/monitor.py` | GET /admin/monitor/errors |
| 实现性能指标收集 | `app/core/metrics.py` | 中间件收集 |
| 实现健康检查 | `app/api/admin/monitor.py` | GET /admin/monitor/health |

**监控API**：
```python
@router.get("/monitor/api")
async def get_api_metrics(
    hours: int = Query(24, ge=1, le=168),
    current_user: AdminUser = Depends(require_permission("monitor:view"))
):
    """获取API性能指标"""
    metrics = {
        "total_requests": await metrics_service.get_total_requests(hours),
        "avg_response_time": await metrics_service.get_avg_response_time(hours),
        "p95_response_time": await metrics_service.get_p95_response_time(hours),
        "p99_response_time": await metrics_service.get_p99_response_time(hours),
        "error_rate": await metrics_service.get_error_rate(hours),
        "qps": await metrics_service.get_qps(),
        "slow_queries": await metrics_service.get_slow_queries(10),
        "endpoint_stats": await metrics_service.get_endpoint_stats(),
    }
    return {"code": 200, "data": metrics}

@router.get("/monitor/database")
async def get_database_metrics(
    current_user: AdminUser = Depends(require_permission("monitor:view"))
):
    """获取数据库状态"""
    metrics = {
        "neo4j": {
            "status": await neo4j_service.health_check(),
            "node_count": await neo4j_service.count_nodes(),
            "relationship_count": await neo4j_service.count_relationships(),
            "storage_used": await neo4j_service.get_storage_usage(),
        },
        "redis": {
            "status": await redis_service.health_check(),
            "memory_used": await redis_service.get_memory_usage(),
            "hit_rate": await redis_service.get_hit_rate(),
            "connected_clients": await redis_service.get_connected_clients(),
        },
        "chromadb": {
            "status": await chroma_service.health_check(),
            "collection_count": await chroma_service.get_collection_count(),
        },
    }
    return {"code": 200, "data": metrics}

@router.get("/monitor/errors")
async def get_error_logs(
    level: Optional[str] = Query(None),  # ERROR / WARNING / INFO
    service: Optional[str] = Query(None),  # backend / crawler / agent
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: AdminUser = Depends(require_permission("monitor:view"))
):
    """获取错误日志"""
    logs = await log_service.query_logs(
        level=level,
        service=service,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size
    )
    return {"code": 200, "data": logs}
```

---

### Day 7（周日）：系统配置API

**目标**：实现系统配置管理

| 任务 | 产出 | 说明 |
|------|------|------|
| 实现配置读取API | `app/api/admin/settings.py` | GET /admin/settings |
| 实现配置更新API | `app/api/admin/settings.py` | PUT /admin/settings |
| 实现配置验证 | `app/schemas/settings.py` | Pydantic模型 |
| 实现配置缓存 | `app/core/settings_cache.py` | Redis缓存 |
| 实现配置变更日志 | `app/services/settings.py` | 记录变更历史 |

**配置管理API**：
```python
class LLMConfig(BaseModel):
    model: str = "gpt-4"
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: int = Field(2000, ge=100, le=8000)
    system_prompt: str = ""
    retry_attempts: int = Field(3, ge=1, le=10)

class SearchConfig(BaseModel):
    default_page_size: int = Field(20, ge=10, le=100)
    max_results: int = Field(100, ge=50, le=500)
    similarity_threshold: float = Field(0.7, ge=0, le=1)
    cache_ttl: int = Field(3600, ge=60)

class CrawlerConfig(BaseModel):
    delay: float = Field(1.0, ge=0.5)
    timeout: int = Field(30, ge=10)
    max_retries: int = Field(3, ge=1, le=10)
    concurrent_limit: int = Field(1, ge=1, le=5)

class SystemSettings(BaseModel):
    llm: LLMConfig
    search: SearchConfig
    crawler: CrawlerConfig
    site_name: str = "StarMap"
    announcement: str = ""
    maintenance_mode: bool = False
    log_level: str = "INFO"

@router.get("/settings")
async def get_settings(
    current_user: AdminUser = Depends(require_permission("settings:manage"))
):
    """获取系统配置"""
    settings = await settings_service.get_settings()
    return {"code": 200, "data": settings}

@router.put("/settings")
async def update_settings(
    request: SystemSettings,
    current_user: AdminUser = Depends(require_permission("settings:manage"))
):
    """更新系统配置"""
    # 验证配置
    await settings_service.validate_settings(request)
    
    # 保存配置
    await settings_service.save_settings(request)
    
    # 记录变更
    await settings_service.log_changes(current_user.id, request)
    
    # 刷新缓存
    await settings_service.refresh_cache()
    
    return {"code": 200, "message": "配置已更新"}
```

---

## Week 5：完善与优化

### Day 8-9（周一-周二）：用户管理 + 安全加固

| 任务 | 产出 | 说明 |
|------|------|------|
| 实现用户列表API | `app/api/admin/user.py` | GET /admin/users |
| 实现用户CRUD | `app/api/admin/user.py` | POST/PUT/DELETE |
| 实现密码重置 | `app/api/admin/user.py` | POST /admin/users/:id/reset-password |
| 实现登录日志 | `app/api/admin/user.py` | GET /admin/users/:id/login-history |
| 实现API限流 | `app/middleware/rate_limit.py` | 基于Redis |
| 实现操作审计 | `app/middleware/audit.py` | 记录所有管理操作 |
| 实现输入验证 | `app/middleware/validation.py` | 防SQL注入/XSS |

**审计日志中间件**：
```python
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """记录管理操作日志"""
    start_time = time.time()
    
    response = await call_next(request)
    
    # 只记录管理API的操作
    if request.url.path.startswith("/api/v1/admin"):
        duration = time.time() - start_time
        await audit_service.log(
            user_id=get_current_user_id(request),
            action=f"{request.method} {request.url.path}",
            ip=request.client.host,
            user_agent=request.headers.get("user-agent"),
            status_code=response.status_code,
            duration=duration,
        )
    
    return response
```

---

### Day 10-11（周三-周四）：测试与文档

| 任务 | 产出 | 说明 |
|------|------|------|
| 编写API测试 | `tests/admin/` | pytest |
| 测试认证流程 | `tests/admin/test_auth.py` | 登录/权限/Token |
| 测试CRUD操作 | `tests/admin/test_person.py` | 艺人CRUD |
| 测试爬虫控制 | `tests/admin/test_crawler.py` | 任务管理 |
| 编写API文档 | 自动生成 | Swagger/ReDoc |
| 性能测试 | - | 压测关键接口 |

---

### Day 12-13（周五-周六）：部署准备

| 任务 | 产出 | 说明 |
|------|------|------|
| 配置生产环境 | `.env.production` | 环境变量 |
| 编写Dockerfile | `backend/Dockerfile.admin` | 容器化 |
| 配置Nginx | `nginx/admin.conf` | 反向代理 |
| 编写部署脚本 | `scripts/deploy-admin.sh` | 自动化部署 |

---

### Day 14（周日）：验收

| 任务 | 产出 | 负责人 |
|------|------|--------|
| API功能验收 | 验收清单 | PM |
| 安全验收 | 安全检查表 | Backend |
| 性能验收 | 压测报告 | Backend |
| 文档验收 | 完整性检查 | PM |

---

## API清单汇总

### 认证模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | /admin/auth/login | 登录 | 公开 |
| POST | /admin/auth/logout | 登出 | 已登录 |
| GET | /admin/auth/me | 获取当前用户 | 已登录 |
| POST | /admin/auth/refresh | 刷新Token | 已登录 |

### 看板模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /admin/dashboard/stats | 核心指标 | L1+ |
| GET | /admin/dashboard/charts | 图表数据 | L1+ |

### 艺人模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /admin/persons | 艺人列表 | L1+ |
| GET | /admin/persons/:id | 艺人详情 | L1+ |
| POST | /admin/persons | 创建艺人 | L2+ |
| PUT | /admin/persons/:id | 更新艺人 | L2+ |
| DELETE | /admin/persons/:id | 删除艺人 | L3 |
| POST | /admin/persons/batch | 批量操作 | L2+ |
| POST | /admin/persons/import | 导入艺人 | L2+ |
| GET | /admin/persons/export | 导出艺人 | L2+ |

### 作品模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /admin/works | 作品列表 | L1+ |
| POST | /admin/works | 创建作品 | L2+ |
| PUT | /admin/works/:id | 更新作品 | L2+ |
| DELETE | /admin/works/:id | 删除作品 | L3 |

### 爬虫模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /admin/crawler/tasks | 任务列表 | L1+ |
| POST | /admin/crawler/tasks | 创建任务 | L2+ |
| GET | /admin/crawler/tasks/:id | 任务详情 | L1+ |
| POST | /admin/crawler/tasks/:id/stop | 停止任务 | L2+ |
| GET | /admin/crawler/tasks/:id/logs | 任务日志 | L1+ |
| WS | /admin/crawler/tasks/:id/logs | 实时日志 | L1+ |
| GET | /admin/crawler/config | 获取配置 | L3 |
| PUT | /admin/crawler/config | 更新配置 | L3 |
| GET | /admin/crawler/stats | 爬取统计 | L1+ |
| GET | /admin/crawler/stats/sources | 数据源统计 | L1+ |
| GET | /admin/crawler/stats/failures | 失败分析 | L1+ |
| GET | /admin/crawler/stats/realtime | 实时速率 | L1+ |

### 对话模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /admin/conversations | 对话列表 | L1+ |
| GET | /admin/conversations/:id | 对话详情 | L1+ |
| GET | /admin/conversations/stats | 对话统计 | L1+ |
| GET | /admin/conversations/hot | 热门问题 | L1+ |
| POST | /admin/conversations/:id/annotate | 质量标注 | L2+ |

### 监控模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /admin/monitor/api | API性能 | L1+ |
| GET | /admin/monitor/database | 数据库状态 | L2+ |
| GET | /admin/monitor/errors | 错误日志 | L2+ |
| GET | /admin/monitor/health | 健康检查 | L1+ |

### 配置模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /admin/settings | 获取配置 | L3 |
| PUT | /admin/settings | 更新配置 | L3 |

### 用户模块

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /admin/users | 用户列表 | L3 |
| POST | /admin/users | 创建用户 | L3 |
| PUT | /admin/users/:id | 更新用户 | L3 |
| DELETE | /admin/users/:id | 删除用户 | L3 |
| POST | /admin/users/:id/reset-password | 重置密码 | L3 |
| GET | /admin/users/:id/login-history | 登录历史 | L3 |

---

## 技术要点

### 目录结构

```
backend/app/
├── api/
│   ├── admin/              # 后台管理API
│   │   ├── __init__.py
│   │   ├── auth.py         # 认证
│   │   ├── dashboard.py    # 看板
│   │   ├── person.py       # 艺人管理
│   │   ├── work.py         # 作品管理
│   │   ├── crawler.py      # 爬虫管理
│   │   ├── conversation.py # 对话管理
│   │   ├── monitor.py      # 系统监控
│   │   ├── settings.py     # 系统配置
│   │   └── user.py         # 用户管理
│   └── ...
├── core/
│   ├── auth.py             # JWT认证
│   ├── permissions.py      # 权限控制
│   ├── security.py         # 密码加密
│   ├── metrics.py          # 性能指标
│   └── settings_cache.py   # 配置缓存
├── middleware/
│   ├── audit.py            # 审计日志
│   ├── rate_limit.py       # 限流
│   └── validation.py       # 输入验证
├── models/
│   ├── admin.py            # 管理员模型
│   └── crawler_task.py     # 爬虫任务模型
├── schemas/
│   └── admin.py            # Pydantic模型
└── services/
    ├── stats.py            # 统计服务
    ├── audit.py            # 审计服务
    └── settings.py         # 配置服务
```

### 依赖注入

```python
# 获取当前管理员用户
async def get_current_admin_user(
    token: str = Header(..., alias="Authorization")
) -> AdminUser:
    """从Token解析当前管理员用户"""
    token_data = verify_token(token.replace("Bearer ", ""))
    if not token_data:
        raise HTTPException(status_code=401, detail="无效的Token")
    
    user = await admin_service.get_user(token_data.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    
    return user

# 权限检查
def require_permission(permission: str):
    """权限装饰器工厂"""
    async def checker(
        current_user: AdminUser = Depends(get_current_admin_user)
    ):
        if permission not in current_user.permissions:
            raise HTTPException(status_code=403, detail="权限不足")
        return current_user
    return checker
```

---

## 验收标准

| 检查项 | 标准 | 优先级 |
|--------|------|--------|
| 认证功能 | JWT登录/登出/刷新正常 | P0 |
| 权限控制 | 不同角色访问不同接口 | P0 |
| 艺人CRUD | 完整的增删改查，含搜索筛选 | P0 |
| 爬虫控制 | 可创建/停止任务，查看日志 | P0 |
| 看板数据 | 统计数据准确，图表正常 | P0 |
| 对话查询 | 可按条件查询，支持时间范围 | P1 |
| 系统监控 | API性能、数据库状态实时 | P1 |
| 系统配置 | 配置可修改，生效验证 | P1 |
| 用户管理 | 超级管理员可管理其他用户 | P1 |
| 审计日志 | 所有操作有记录 | P1 |
| API限流 | 防止暴力请求 | P1 |
| 单元测试 | 覆盖率 ≥ 70% | P1 |
| API文档 | Swagger文档完整 | P1 |

---

**进度跟踪**：见项目看板 `docs/project-board.md`
