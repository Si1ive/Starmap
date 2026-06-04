# 后端开发路线 - 爬虫管理增强

> 版本：v2.0  
> 日期：2026-06-05  
> 负责人：Backend  
> 状态：规划中

---

## 1. 新增模块结构

```
backend/
├── app/
│   ├── api/
│   │   └── admin.py              # 扩展现有文件
│   ├── services/
│   │   ├── crawler_service.py    # 爬虫业务逻辑（新增）
│   │   ├── source_service.py     # 爬取源管理（新增）
│   │   ├── schedule_service.py   # 定时任务管理（新增）
│   │   └── stats_service.py      # 统计报表（新增）
│   ├── tasks/
│   │   └── scheduler.py          # 定时任务调度器（新增）
│   └── websocket/
│       └── log_ws.py             # 日志WebSocket（新增）
├── scripts/
│   └── migrate_crawler_v2.sql   # 数据库迁移脚本（新增）
└── requirements.txt              # 新增依赖
```

---

## 2. 数据库迁移

### 2.1 迁移脚本

```sql
-- scripts/migrate_crawler_v2.sql
-- 版本：v2.0
-- 说明：爬虫管理增强模块数据库迁移

-- 1. 创建爬取源表
CREATE TABLE crawl_sources (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    name VARCHAR(100) NOT NULL COMMENT '源名称',
    code VARCHAR(50) NOT NULL UNIQUE COMMENT '源编码',
    type VARCHAR(50) COMMENT '源类型',
    base_url VARCHAR(500) COMMENT '基础URL',
    config JSON COMMENT '源配置',
    request_interval DECIMAL(3,1) DEFAULT 1.0 COMMENT '请求间隔(秒)',
    daily_limit INT DEFAULT 1000 COMMENT '每日请求上限',
    concurrent_limit INT DEFAULT 5 COMMENT '并发数限制',
    status ENUM('active', 'inactive', 'error', 'deprecated') DEFAULT 'active',
    health_status ENUM('healthy', 'degraded', 'down') DEFAULT 'healthy',
    last_health_check DATETIME COMMENT '最后健康检查时间',
    total_requests BIGINT DEFAULT 0 COMMENT '累计请求数',
    total_success BIGINT DEFAULT 0 COMMENT '累计成功数',
    total_failed BIGINT DEFAULT 0 COMMENT '累计失败数',
    avg_response_time DECIMAL(8,2) COMMENT '平均响应时间(ms)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_type (type),
    INDEX idx_health (health_status)
) COMMENT='爬取源配置表';

-- 2. 创建爬取源统计表
CREATE TABLE crawl_source_stats (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_id VARCHAR(32) NOT NULL COMMENT '爬取源ID',
    stat_date DATE NOT NULL COMMENT '统计日期',
    total_requests INT DEFAULT 0 COMMENT '总请求数',
    success_requests INT DEFAULT 0 COMMENT '成功请求数',
    failed_requests INT DEFAULT 0 COMMENT '失败请求数',
    timeout_requests INT DEFAULT 0 COMMENT '超时请求数',
    rate_limited_requests INT DEFAULT 0 COMMENT '被限流请求数',
    persons_extracted INT DEFAULT 0 COMMENT '提取人物数',
    works_extracted INT DEFAULT 0 COMMENT '提取作品数',
    relations_extracted INT DEFAULT 0 COMMENT '提取关系数',
    valid_records INT DEFAULT 0 COMMENT '有效记录数',
    duplicate_records INT DEFAULT 0 COMMENT '重复记录数',
    avg_response_time DECIMAL(8,2) COMMENT '平均响应时间(ms)',
    min_response_time DECIMAL(8,2) COMMENT '最小响应时间(ms)',
    max_response_time DECIMAL(8,2) COMMENT '最大响应时间(ms)',
    p95_response_time DECIMAL(8,2) COMMENT 'P95响应时间(ms)',
    avg_completeness DECIMAL(5,2) COMMENT '平均字段完整度(%)',
    total_duration INT DEFAULT 0 COMMENT '总耗时(秒)',
    data_size_mb DECIMAL(8,2) COMMENT '数据大小(MB)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_source_date (source_id, stat_date),
    INDEX idx_stat_date (stat_date),
    INDEX idx_source_id (source_id)
) COMMENT='爬取源日统计表';

-- 3. 创建定时任务表
CREATE TABLE crawl_schedules (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    name VARCHAR(200) NOT NULL COMMENT '任务名称',
    description TEXT COMMENT '任务描述',
    task_type ENUM('full', 'incremental', 'targeted', 'health_check', 'cleanup') NOT NULL,
    source_ids JSON COMMENT '关联的爬取源ID列表',
    target_config JSON COMMENT '目标配置',
    cron_expression VARCHAR(100) NOT NULL COMMENT 'Cron表达式',
    timezone VARCHAR(50) DEFAULT 'Asia/Shanghai' COMMENT '时区',
    is_enabled BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    max_retries INT DEFAULT 3 COMMENT '失败重试次数',
    retry_interval INT DEFAULT 300 COMMENT '重试间隔(秒)',
    concurrent_limit INT DEFAULT 1 COMMENT '并发数限制',
    timeout INT DEFAULT 3600 COMMENT '任务超时(秒)',
    notify_on_success BOOLEAN DEFAULT FALSE COMMENT '成功时通知',
    notify_on_failure BOOLEAN DEFAULT TRUE COMMENT '失败时通知',
    notify_emails JSON COMMENT '通知邮箱列表',
    total_runs INT DEFAULT 0 COMMENT '总执行次数',
    success_runs INT DEFAULT 0 COMMENT '成功次数',
    failed_runs INT DEFAULT 0 COMMENT '失败次数',
    last_run_at DATETIME COMMENT '最后执行时间',
    last_run_status ENUM('success', 'failed', 'running', 'timeout') COMMENT '最后执行状态',
    last_run_duration INT COMMENT '最后执行耗时(秒)',
    next_run_at DATETIME COMMENT '下次执行时间',
    created_by VARCHAR(32) COMMENT '创建者',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_enabled (is_enabled),
    INDEX idx_next_run (next_run_at),
    INDEX idx_task_type (task_type)
) COMMENT='定时任务配置表';

-- 4. 创建定时任务执行历史表
CREATE TABLE crawl_schedule_runs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    schedule_id VARCHAR(32) NOT NULL COMMENT '定时任务ID',
    task_id VARCHAR(32) COMMENT '关联的爬取任务ID',
    status ENUM('running', 'success', 'failed', 'timeout', 'cancelled') NOT NULL,
    started_at DATETIME NOT NULL COMMENT '开始时间',
    completed_at DATETIME COMMENT '完成时间',
    duration INT COMMENT '执行耗时(秒)',
    total_requests INT DEFAULT 0,
    success_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    error_message TEXT COMMENT '错误信息',
    log_summary TEXT COMMENT '日志摘要',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_schedule_id (schedule_id),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at)
) COMMENT='定时任务执行历史表';

-- 5. 修改现有表
ALTER TABLE crawl_tasks 
    ADD COLUMN source_id VARCHAR(32) COMMENT '爬取源ID',
    ADD INDEX idx_source_id (source_id);

ALTER TABLE crawl_logs 
    ADD COLUMN source_id VARCHAR(32) COMMENT '爬取源ID',
    ADD COLUMN details JSON COMMENT '详细日志信息',
    ADD INDEX idx_source_id (source_id);

-- 6. 初始化默认爬取源
INSERT INTO crawl_sources (id, name, code, type, base_url, config, status) VALUES
('src_001', '维基百科（中文）', 'wikipedia_zh', 'encyclopedia', 'https://zh.wikipedia.org/wiki/', 
 '{"selectors": {"title": "h1.firstHeading", "summary": "div.mw-parser-output > p:first-of-type"}, "anti_detection": {"user_agent_rotation": true, "delay_range": [1.0, 3.0]}}', 
 'active'),
('src_002', '豆瓣电影', 'douban_movie', 'social', 'https://movie.douban.com/',
 '{"selectors": {"title": "span[property=\"v:itemreviewed\"]", "rating": "strong[property=\"v:average\"]"}, "anti_detection": {"user_agent_rotation": true, "delay_range": [2.0, 5.0]}}',
 'active');
```

---

## 3. Service 层实现

### 3.1 CrawlerSourceService

```python
# app/services/source_service.py
from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import CrawlSource
from app.schemas.crawler import CrawlSourceCreate, CrawlSourceUpdate, CrawlSourceStats

class CrawlerSourceService:
    """爬取源管理服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_sources(
        self, 
        skip: int = 0, 
        limit: int = 20,
        status: Optional[str] = None,
        source_type: Optional[str] = None
    ) -> tuple[List[CrawlSource], int]:
        """获取爬取源列表"""
        query = select(CrawlSource)
        
        if status:
            query = query.where(CrawlSource.status == status)
        if source_type:
            query = query.where(CrawlSource.type == source_type)
        
        # 统计总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query)
        
        # 分页查询
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        sources = result.scalars().all()
        
        return list(sources), total
    
    async def get_source_stats(self, source_id: str, days: int = 30) -> CrawlSourceStats:
        """获取爬取源统计"""
        # 查询日统计表
        query = select(
            CrawlSourceStats
        ).where(
            CrawlSourceStats.source_id == source_id,
            CrawlSourceStats.stat_date >= func.date_sub(func.current_date(), days)
        ).order_by(CrawlSourceStats.stat_date)
        
        result = await self.db.execute(query)
        daily_stats = result.scalars().all()
        
        # 聚合计算
        total_requests = sum(s.total_requests for s in daily_stats)
        total_success = sum(s.success_requests for s in daily_stats)
        
        return CrawlSourceStats(
            source_id=source_id,
            total_requests=total_requests,
            total_success=total_success,
            success_rate=total_success / total_requests if total_requests > 0 else 0,
            daily_stats=daily_stats
        )
    
    async def health_check(self, source_id: str) -> dict:
        """爬取源健康检查"""
        source = await self.db.get(CrawlSource, source_id)
        if not source:
            return {"status": "not_found"}
        
        # 尝试请求源的基础URL
        try:
            # 发送HEAD请求检查可用性
            response = requests.head(source.base_url, timeout=10)
            if response.status_code == 200:
                source.health_status = "healthy"
            else:
                source.health_status = "degraded"
        except Exception:
            source.health_status = "down"
        
        source.last_health_check = datetime.utcnow()
        await self.db.commit()
        
        return {
            "source_id": source_id,
            "status": source.health_status,
            "checked_at": source.last_health_check.isoformat()
        }
```

### 3.2 CrawlerScheduleService

```python
# app/services/schedule_service.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

class CrawlerScheduleService:
    """定时任务管理服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
    
    async def create_schedule(self, data: CrawlScheduleCreate) -> CrawlSchedule:
        """创建定时任务"""
        schedule = CrawlSchedule(**data.dict())
        
        # 计算下次执行时间
        schedule.next_run_at = self._calculate_next_run(schedule.cron_expression)
        
        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        
        # 注册到调度器
        if schedule.is_enabled:
            self._register_job(schedule)
        
        return schedule
    
    def _register_job(self, schedule: CrawlSchedule):
        """注册定时任务到调度器"""
        job_id = f"schedule_{schedule.id}"
        
        self.scheduler.add_job(
            func=self._execute_schedule,
            trigger=CronTrigger.from_crontab(schedule.cron_expression),
            id=job_id,
            args=[schedule.id],
            replace_existing=True
        )
    
    async def _execute_schedule(self, schedule_id: str):
        """执行定时任务"""
        # 创建爬取任务
        task_service = CrawlerTaskService(self.db)
        task = await task_service.create_task_from_schedule(schedule_id)
        
        # 执行爬取
        await task_service.execute_task(task.id)
    
    async def toggle_schedule(self, schedule_id: str, enabled: bool) -> CrawlSchedule:
        """启用/禁用定时任务"""
        schedule = await self.db.get(CrawlSchedule, schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        schedule.is_enabled = enabled
        
        if enabled:
            self._register_job(schedule)
        else:
            job_id = f"schedule_{schedule.id}"
            self.scheduler.remove_job(job_id)
        
        await self.db.commit()
        await self.db.refresh(schedule)
        
        return schedule
```

### 3.3 CrawlerStatsService

```python
# app/services/stats_service.py
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta

class CrawlerStatsService:
    """爬虫统计服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_overview(self) -> dict:
        """获取总体概览"""
        # 活跃源数
        active_sources = await self.db.scalar(
            select(func.count()).where(CrawlSource.status == 'active')
        )
        
        # 今日请求数
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_requests = await self.db.scalar(
            select(func.sum(CrawlSourceStats.total_requests))
            .where(CrawlSourceStats.stat_date == today.date())
        ) or 0
        
        # 今日成功数
        today_success = await self.db.scalar(
            select(func.sum(CrawlSourceStats.success_requests))
            .where(CrawlSourceStats.stat_date == today.date())
        ) or 0
        
        # 整体成功率
        total_requests = await self.db.scalar(
            select(func.sum(CrawlSourceStats.total_requests))
        ) or 0
        total_success = await self.db.scalar(
            select(func.sum(CrawlSourceStats.success_requests))
        ) or 0
        
        success_rate = total_success / total_requests if total_requests > 0 else 0
        
        return {
            "active_sources": active_sources,
            "today_requests": today_requests,
            "today_success": today_success,
            "today_success_rate": today_success / today_requests if today_requests > 0 else 0,
            "total_requests": total_requests,
            "total_success": total_success,
            "overall_success_rate": success_rate
        }
    
    async def get_source_comparison(self, days: int = 7) -> List[dict]:
        """获取各源对比数据"""
        start_date = datetime.now().date() - timedelta(days=days)
        
        query = select(
            CrawlSource.id,
            CrawlSource.name,
            CrawlSource.type,
            CrawlSource.status,
            func.sum(CrawlSourceStats.total_requests).label('total_requests'),
            func.sum(CrawlSourceStats.success_requests).label('success_requests'),
            func.avg(CrawlSourceStats.avg_response_time).label('avg_response_time'),
            func.avg(CrawlSourceStats.avg_completeness).label('avg_completeness')
        ).join(
            CrawlSourceStats, CrawlSource.id == CrawlSourceStats.source_id
        ).where(
            CrawlSourceStats.stat_date >= start_date
        ).group_by(
            CrawlSource.id
        )
        
        result = await self.db.execute(query)
        rows = result.all()
        
        return [
            {
                "source_id": row.id,
                "name": row.name,
                "type": row.type,
                "status": row.status,
                "total_requests": row.total_requests or 0,
                "success_requests": row.success_requests or 0,
                "success_rate": (row.success_requests or 0) / (row.total_requests or 1),
                "avg_response_time": round(row.avg_response_time or 0, 2),
                "avg_completeness": round(row.avg_completeness or 0, 2)
            }
            for row in rows
        ]
    
    async def get_trend(self, days: int = 30) -> List[dict]:
        """获取趋势数据"""
        start_date = datetime.now().date() - timedelta(days=days)
        
        query = select(
            CrawlSourceStats.stat_date,
            func.sum(CrawlSourceStats.total_requests).label('requests'),
            func.sum(CrawlSourceStats.success_requests).label('successes'),
            func.sum(CrawlSourceStats.failed_requests).label('failures')
        ).where(
            CrawlSourceStats.stat_date >= start_date
        ).group_by(
            CrawlSourceStats.stat_date
        ).order_by(
            CrawlSourceStats.stat_date
        )
        
        result = await self.db.execute(query)
        rows = result.all()
        
        return [
            {
                "date": row.stat_date.isoformat(),
                "requests": row.requests or 0,
                "successes": row.successes or 0,
                "failures": row.failures or 0,
                "success_rate": (row.successes or 0) / (row.requests or 1)
            }
            for row in rows
        ]
```

---

## 4. API 路由实现

### 4.1 扩展 admin.py

```python
# app/api/admin.py 新增路由

# ========== 爬取源管理 ==========

@router.get("/crawler/sources", response_model=ApiResponse)
async def get_crawler_sources(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取爬取源列表"""
    service = CrawlerSourceService(db)
    sources, total = await service.get_sources(
        skip=(page - 1) * page_size,
        limit=page_size,
        status=status,
        source_type=type
    )
    
    return ApiResponse(
        data={
            "items": [source.to_dict() for source in sources],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    )

@router.post("/crawler/sources", response_model=ApiResponse)
async def create_crawler_source(
    data: CrawlSourceCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建爬取源"""
    service = CrawlerSourceService(db)
    source = await service.create_source(data)
    return ApiResponse(data=source.to_dict())

@router.get("/crawler/sources/{source_id}/stats", response_model=ApiResponse)
async def get_source_stats(
    source_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """获取爬取源统计"""
    service = CrawlerSourceService(db)
    stats = await service.get_source_stats(source_id, days)
    return ApiResponse(data=stats.dict())

@router.post("/crawler/sources/{source_id}/health", response_model=ApiResponse)
async def check_source_health(
    source_id: str,
    db: AsyncSession = Depends(get_db)
):
    """爬取源健康检查"""
    service = CrawlerSourceService(db)
    result = await service.health_check(source_id)
    return ApiResponse(data=result)

# ========== 统计报表 ==========

@router.get("/crawler/stats/overview", response_model=ApiResponse)
async def get_crawler_overview(db: AsyncSession = Depends(get_db)):
    """获取爬虫总体概览"""
    service = CrawlerStatsService(db)
    overview = await service.get_overview()
    return ApiResponse(data=overview)

@router.get("/crawler/stats/sources", response_model=ApiResponse)
async def get_source_comparison(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """获取各源对比数据"""
    service = CrawlerStatsService(db)
    comparison = await service.get_source_comparison(days)
    return ApiResponse(data=comparison)

@router.get("/crawler/stats/trend", response_model=ApiResponse)
async def get_crawler_trend(
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """获取趋势数据"""
    service = CrawlerStatsService(db)
    trend = await service.get_trend(days)
    return ApiResponse(data=trend)

# ========== 定时任务 ==========

@router.get("/crawler/schedules", response_model=ApiResponse)
async def get_crawler_schedules(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """获取定时任务列表"""
    service = CrawlerScheduleService(db)
    schedules, total = await service.get_schedules(
        skip=(page - 1) * page_size,
        limit=page_size
    )
    return ApiResponse(
        data={
            "items": [s.to_dict() for s in schedules],
            "total": total
        }
    )

@router.post("/crawler/schedules", response_model=ApiResponse)
async def create_crawler_schedule(
    data: CrawlScheduleCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建定时任务"""
    service = CrawlerScheduleService(db)
    schedule = await service.create_schedule(data)
    return ApiResponse(data=schedule.to_dict())

@router.post("/crawler/schedules/{schedule_id}/toggle", response_model=ApiResponse)
async def toggle_crawler_schedule(
    schedule_id: str,
    enabled: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """启用/禁用定时任务"""
    service = CrawlerScheduleService(db)
    schedule = await service.toggle_schedule(schedule_id, enabled)
    return ApiResponse(data=schedule.to_dict())

@router.get("/crawler/schedules/{schedule_id}/runs", response_model=ApiResponse)
async def get_schedule_runs(
    schedule_id: str,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """获取定时任务执行历史"""
    service = CrawlerScheduleService(db)
    runs, total = await service.get_runs(
        schedule_id=schedule_id,
        skip=(page - 1) * page_size,
        limit=page_size
    )
    return ApiResponse(
        data={
            "items": [r.to_dict() for r in runs],
            "total": total
        }
    )

# ========== 日志系统 ==========

@router.get("/crawler/logs", response_model=ApiResponse)
async def get_crawler_logs(
    task_id: Optional[str] = None,
    source_id: Optional[str] = None,
    level: Optional[str] = None,
    status: Optional[str] = None,
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
        start_time=start_time,
        end_time=end_time,
        skip=(page - 1) * page_size,
        limit=page_size
    )
    return ApiResponse(
        data={
            "items": [log.to_dict() for log in logs],
            "total": total
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
    return ApiResponse(data=analysis)
```

---

## 5. WebSocket 实现

### 5.1 日志实时推送

```python
# app/websocket/log_ws.py
from fastapi import WebSocket, WebSocketDisconnect
from typing import Set
import asyncio
import json

class LogWebSocketManager:
    """日志WebSocket管理器"""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
    
    async def broadcast(self, message: dict):
        """广播日志消息"""
        if not self.active_connections:
            return
        
        message_json = json.dumps(message)
        disconnected = set()
        
        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception:
                disconnected.add(connection)
        
        # 清理断开的连接
        for conn in disconnected:
            self.active_connections.discard(conn)

log_manager = LogWebSocketManager()

# 在爬虫执行时调用
async def push_log(log_entry: dict):
    """推送日志到WebSocket"""
    await log_manager.broadcast(log_entry)

# API路由
@router.websocket("/crawler/logs/stream")
async def log_stream(websocket: WebSocket):
    """日志实时流"""
    await log_manager.connect(websocket)
    try:
        while True:
            # 保持连接
            await websocket.receive_text()
    except WebSocketDisconnect:
        log_manager.disconnect(websocket)
```

---

## 6. 依赖更新

```txt
# requirements.txt 新增依赖

# 定时任务调度
APScheduler==3.10.4

# WebSocket
websockets==12.0

# 请求库（用于健康检查）
requests==2.31.0
```

---

## 7. 开发顺序

### Week 1

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1 | 数据库迁移脚本 + 执行 | 表结构就绪 |
| Day 2 | CrawlerSourceService + API | 源管理可用 |
| Day 3 | CrawlerStatsService + API | 统计报表可用 |
| Day 4 | CrawlerLogService + API | 日志查询可用 |
| Day 5 | 爬虫基类集成日志写入 | 日志自动记录 |

### Week 2

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1 | APScheduler 集成 + 定时任务Service | 调度器可用 |
| Day 2 | 定时任务API + 手动执行控制 | 任务控制可用 |
| Day 3 | WebSocket 日志推送 | 实时日志可用 |
| Day 4 | 联调 + Bug修复 | 功能完整 |
| Day 5 | 性能优化 + 测试 | 验收通过 |

---

## 8. 验收 checklist

- [ ] 爬取源 CRUD API 可用
- [ ] 源统计 API 返回真实数据
- [ ] 定时任务可配置 Cron 表达式
- [ ] 定时任务自动执行
- [ ] 手动任务可启动/停止
- [ ] 日志自动写入数据库
- [ ] 日志查询 API 可用
- [ ] WebSocket 实时推送日志
- [ ] 所有 API 返回真实数据，无 mock
- [ ] 列表查询 < 1s
- [ ] 统计聚合 < 2s

---

**文档状态**：✅ 已完成  
**下次更新**：Week 1 结束后
