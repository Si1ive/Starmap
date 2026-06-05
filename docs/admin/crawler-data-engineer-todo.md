# 爬虫模块 - 数据工程师待办清单

> 更新日期：2026-06-05
> 负责人：数据工程师
> 状态：基于已完成功能的剩余工作梳理

---

## 已完成功能（本次提交）

### 1. 数据库层
- [x] 新增 `crawl_sources` 表（爬取源配置）
- [x] 新增 `crawl_source_stats` 表（日统计）
- [x] 新增 `crawl_schedules` 表（定时任务配置）
- [x] 新增 `crawl_schedule_runs` 表（执行历史）
- [x] 修改 `crawl_tasks` 表（增加 `source_id`）
- [x] 修改 `crawl_logs` 表（增加 `source_id`、`stage`、`details`）
- [x] SQL 迁移脚本：`scripts/migrate_crawler_v2.sql`

### 2. Service 层
- [x] `CrawlerSourceService`（爬取源 CRUD、健康检查、统计查询）
- [x] `CrawlerStatsService`（总体概览、源对比、趋势、效率分析）
- [x] `CrawlerScheduleService`（定时任务 CRUD、启用/禁用、执行历史）
- [x] `CrawlerLogService`（日志查询、分析、写入）

### 3. API 层
- [x] 爬取源管理 API（7 个端点）
- [x] 统计报表 API（4 个端点）
- [x] 定时任务 API（7 个端点）
- [x] 日志系统 API（2 个端点）
- [x] WebSocket 实时日志推送

### 4. 爬虫基类
- [x] `BaseCrawler` 集成 `log_callback` 自动日志写入
- [x] `fetch()` 和 `fetch_with_retry()` 自动记录日志

### 5. 基础设施
- [x] `LogWebSocketManager`（WebSocket 连接管理、过滤推送）
- [x] `get_db()` 依赖注入（FastAPI AsyncSession）
- [x] 依赖更新（APScheduler、websockets、pytz）

---

## 剩余工作（数据工程师需完成）

### 一、高优先级（P0）

#### 1.1 APScheduler 定时调度器集成
**现状**：`CrawlerScheduleService` 有 `_calculate_next_run()` 方法计算下次执行时间，但**没有真正启动 APScheduler 调度器**。定时任务创建后不会自动执行。

**需完成**：
- 在 `app/tasks/scheduler.py` 创建全局 `AsyncIOScheduler` 实例
- 应用启动时从数据库加载所有 `is_enabled=True` 的定时任务并注册到调度器
- 实现 `_execute_schedule()` 方法，真正创建并执行爬取任务
- 任务执行完成后更新 `crawl_schedule_runs` 表
- 应用关闭时优雅停止调度器

**参考实现**：
```python
# app/tasks/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

async def init_scheduler():
    """初始化调度器，加载所有启用的定时任务"""
    # 从数据库加载任务并注册
    pass

async def shutdown_scheduler():
    """关闭调度器"""
    scheduler.shutdown()
```

#### 1.2 爬虫任务执行引擎
**现状**：`CrawlerScheduleService._execute_schedule()` 是空的，没有真正执行爬取逻辑。

**需完成**：
- 创建 `CrawlerTaskService` 或扩展现有服务，实现：
  - `create_task_from_schedule()`：根据定时任务配置创建 `CrawlTask` 记录
  - `execute_task()`：执行实际爬取流程
  - 爬取流程：读取源配置 → 调用对应爬虫类 → 解析数据 → 清洗 → 验证 → 导入
- 任务状态流转：`pending → running → completed/failed/stopped`
- 实时进度更新（写入 `crawl_tasks` 表的 `progress` 字段）

#### 1.3 日统计数据采集
**现状**：`crawl_source_stats` 表已创建，但**没有自动写入统计数据的逻辑**。

**需完成**：
- 在爬虫执行过程中实时统计并写入 `crawl_source_stats`：
  - 每次请求后更新 `total_requests`、`success_requests`、`failed_requests`
  - 记录响应时间（用于计算 avg/min/max/p95）
  - 记录提取的数据量（`persons_extracted`、`works_extracted`）
  - 记录有效/重复记录数
- 或创建定时任务（每天凌晨）汇总前一天数据

#### 1.4 日志 WebSocket 与数据库写入联动
**现状**：`BaseCrawler._log()` 支持 `log_callback` 回调，但**没有将 WebSocket 广播与数据库写入串联**。

**需完成**：
- 创建一个统一的日志处理函数：
  1. 写入数据库（`CrawlerLogService.create_log()`）
  2. 广播到 WebSocket（`log_websocket_manager.broadcast()`）
- 将该函数作为 `log_callback` 传递给 `BaseCrawler`
- 确保异步上下文正确（`log_callback` 当前是同步调用，需要适配）

**问题**：`BaseCrawler._log()` 中的 `log_callback` 是同步调用，但数据库写入和 WebSocket 广播都是异步操作。需要：
- 方案 A：将 `log_callback` 改为异步，但 `BaseCrawler` 是同步类
- 方案 B：使用 `asyncio.run_coroutine_threadsafe()` 或消息队列
- 方案 C：在 `BaseCrawler` 外层的异步任务中统一处理日志

### 二、中优先级（P1）

#### 2.1 现有 mock API 替换为真实数据
**现状**：`admin.py` 中以下路由仍返回 mock 数据：
- `GET /dashboard/stats`（看板统计）
- `GET /dashboard/charts`（看板图表）
- `GET /persons`（艺人列表）
- `GET /persons/{id}`（艺人详情）
- `POST /persons`（创建艺人）
- `PUT /persons/{id}`（更新艺人）
- `DELETE /persons/{id}`（删除艺人）
- `GET /crawler/tasks`（爬虫任务列表）- **仍是 mock**
- `POST /crawler/tasks`（创建任务）- **空实现**
- `POST /crawler/tasks/{id}/stop`（停止任务）- **空实现**
- `GET /conversations`（对话记录）
- `GET /monitor/api`（API 监控）
- `GET /monitor/database`（数据库监控）
- `GET /monitor/errors`（错误日志）
- `GET /settings`（系统配置）
- `PUT /settings`（更新配置）

**注意**：虽然这些不在本次爬虫增强的需求范围内，但需求文档明确提到"所有 API 返回真实数据，无 mock"是 P0 验收标准。

#### 2.2 MySQL 连接初始化
**现状**：`app/main.py` 的 `lifespan` 中初始化了 Neo4j、Redis、ChromaDB，但**没有初始化 MySQL 连接**。

**需完成**：
- 在 `lifespan` 启动阶段调用 `mysql_client.connect()`
- 在关闭阶段调用 `mysql_client.close()`
- 在健康检查接口中增加 MySQL 状态检查

#### 2.3 数据库迁移脚本执行
**现状**：`scripts/migrate_crawler_v2.sql` 已创建，但**未在应用启动时自动执行**。

**需完成**：
- 在 `lifespan` 或初始化脚本中执行迁移
- 或使用 Alembic 等迁移工具管理版本

### 三、低优先级（P2）

#### 3.1 日志导出功能
- 支持导出 CSV/JSON 格式
- API：`GET /crawler/logs/export`

#### 3.2 效率分析优化建议
- 根据统计数据自动生成优化建议
- 例如："百度百科成功率低于 60%，建议降低请求频率或更换源"

#### 3.3 数据清洗定时任务
- 实现 `cleanup` 类型的定时任务
- 清理重复/过期数据

---

## 验收 Checklist（数据工程师视角）

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 数据库表结构正确 | ✅ | 迁移脚本已创建 |
| ORM 模型与表一致 | ✅ | 模型已更新 |
| Service 层逻辑正确 | ✅ | 4 个 Service 已实现 |
| API 路由无 mock | ⚠️ | 爬虫相关 API 已完成，其他仍为 mock |
| 定时任务自动执行 | ❌ | APScheduler 未集成 |
| 日志自动写入 | ⚠️ | BaseCrawler 支持回调，但未串联数据库+WebSocket |
| WebSocket 实时推送 | ⚠️ | 管理器已实现，但未与爬虫执行联动 |
| 日统计自动采集 | ❌ | 无写入逻辑 |
| MySQL 连接初始化 | ❌ | main.py 未初始化 |
| 迁移脚本自动执行 | ❌ | 未集成到启动流程 |

---

## 下一步建议

1. **立即**：在 `main.py` 中添加 MySQL 初始化
2. **Day 1**：实现 APScheduler 集成 + 任务执行引擎
3. **Day 2**：实现日志回调统一处理（数据库+WebSocket）
4. **Day 3**：实现日统计自动采集
5. **Day 4**：将剩余 mock API 替换为真实数据（或与后端工程师分工）
