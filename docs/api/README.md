# StarMap API 契约

> 版本：v1.0  
> 日期：2026-06-06  
> 负责人：Backend 维护，PM 审核  
> 适用范围：前端、管理端、后端、爬虫服务、数据库模型

---

## 1. 契约原则

1. 本文件是前后端和数据库字段对齐的真相源。
2. 所有字段使用 `snake_case`。
3. 管理端接口统一挂载在 `/api/v1/admin/*`。
4. 分页统一使用 `page`、`page_size`、`total`、`total_pages`。
5. 时间统一返回 ISO 8601 字符串，例如 `2026-06-06T13:00:00Z`。
6. 任务类型字段统一使用 `task_type`，禁止在响应中用 `type` 表示任务类型。
7. 失败数字段统一使用 `failed_count`，禁止使用 `fail_count`。
8. 修改接口、字段、枚举、数据结构时，必须同步更新本文件、前端类型、后端模型、迁移脚本和 `CHANGELOG.md`。

---

## 2. 通用响应

### 2.1 成功响应

```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "request_id": "req_abc123"
}
```

### 2.2 错误响应

HTTP 状态码必须与错误结果一致，`code` 与 HTTP 状态码保持一致。

```json
{
  "code": 404,
  "message": "爬取源不存在",
  "data": null,
  "request_id": "req_abc123"
}
```

### 2.3 分页响应

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "total_pages": 0
}
```

---

## 3. 枚举

| 名称 | 值 |
|------|----|
| `crawler_source_type` | `encyclopedia`, `social`, `official`, `news`, `other` |
| `crawler_source_status` | `active`, `inactive`, `error`, `deprecated` |
| `health_status` | `healthy`, `degraded`, `down` |
| `crawler_task_type` | `full`, `incremental`, `targeted`, `health_check`, `cleanup` |
| `crawler_task_status` | `pending`, `running`, `completed`, `failed`, `stopped` |
| `crawler_log_level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `crawler_log_stage` | `execution`, `fetch`, `parse`, `validate`, `store`, `sync` |
| `crawler_log_status` | `pending`, `success`, `failed`, `retry` |
| `resource_type` | `person`, `work`, `relation`, `page` |
| `schedule_run_status` | `running`, `success`, `failed`, `timeout`, `cancelled` |

---

## 4. 数据体

### 4.1 CrawlerSource

```json
{
  "id": "src_001",
  "name": "维基百科中文",
  "code": "wikipedia_zh",
  "type": "encyclopedia",
  "base_url": "https://zh.wikipedia.org/wiki/",
  "config": {
    "spider_type": "person",
    "selectors": {},
    "field_mapping": {},
    "anti_detection": {
      "user_agent_rotation": true,
      "delay_range": [1.0, 3.0]
    }
  },
  "request_interval": 1.0,
  "daily_limit": 1000,
  "concurrent_limit": 5,
  "status": "active",
  "health_status": "healthy",
  "last_health_check": null,
  "total_requests": 0,
  "total_success": 0,
  "total_failed": 0,
  "avg_response_time": null,
  "created_at": "2026-06-06T13:00:00Z",
  "updated_at": "2026-06-06T13:00:00Z"
}
```

### 4.2 CrawlerTask

```json
{
  "id": "task_001",
  "name": "爬取周杰伦信息",
  "task_type": "targeted",
  "source_id": "src_001",
  "source_code": "wikipedia_zh",
  "target_count": 1,
  "completed_count": 0,
  "success_count": 0,
  "failed_count": 0,
  "success_rate": 0,
  "progress": 0,
  "status": "pending",
  "config": {
    "spider_type": "person",
    "keywords": ["周杰伦"],
    "concurrent_limit": 3,
    "delay": 1.0,
    "timeout": 30
  },
  "started_at": null,
  "completed_at": null,
  "created_by": "admin_001",
  "created_at": "2026-06-06T13:00:00Z",
  "updated_at": "2026-06-06T13:00:00Z",
  "error_message": null
}
```

### 4.3 CrawlerSchedule

```json
{
  "id": "sch_001",
  "name": "每日增量更新",
  "description": "每天凌晨更新活跃源",
  "task_type": "incremental",
  "source_ids": ["src_001"],
  "target_config": {
    "spider_type": "person",
    "keywords": []
  },
  "cron_expression": "0 2 * * *",
  "timezone": "Asia/Shanghai",
  "is_enabled": true,
  "max_retries": 3,
  "retry_interval": 300,
  "concurrent_limit": 1,
  "timeout": 3600,
  "total_runs": 0,
  "success_runs": 0,
  "failed_runs": 0,
  "last_run_at": null,
  "last_run_status": null,
  "next_run_at": "2026-06-07T02:00:00+08:00",
  "created_by": "admin_001",
  "created_at": "2026-06-06T13:00:00Z",
  "updated_at": "2026-06-06T13:00:00Z"
}
```

### 4.4 CrawlerLog

```json
{
  "id": 1,
  "task_id": "task_001",
  "source_id": "src_001",
  "level": "INFO",
  "stage": "fetch",
  "resource_url": "https://zh.wikipedia.org/wiki/周杰伦",
  "resource_name": "周杰伦",
  "resource_type": "person",
  "action": "download",
  "status": "success",
  "duration_ms": 320,
  "message": "Fetched person page",
  "error_type": null,
  "error_detail": null,
  "retry_count": 0,
  "details": {},
  "created_at": "2026-06-06T13:00:00Z"
}
```

---

## 5. 爬取源 API

### GET `/api/v1/admin/crawler/sources`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 默认 `1` |
| `page_size` | int | 否 | 默认 `20` |
| `status` | string | 否 | 见 `crawler_source_status` |
| `source_type` | string | 否 | 见 `crawler_source_type` |

响应：`ApiResponse<PaginatedResponse<CrawlerSource>>`

### POST `/api/v1/admin/crawler/sources`

请求：

```json
{
  "name": "维基百科中文",
  "code": "wikipedia_zh",
  "type": "encyclopedia",
  "base_url": "https://zh.wikipedia.org/wiki/",
  "config": {
    "spider_type": "person",
    "selectors": {},
    "field_mapping": {}
  },
  "request_interval": 1.0,
  "daily_limit": 1000,
  "concurrent_limit": 5
}
```

响应：`ApiResponse<CrawlerSource>`

### GET `/api/v1/admin/crawler/sources/{source_id}`

响应：`ApiResponse<CrawlerSource>`

### PUT `/api/v1/admin/crawler/sources/{source_id}`

请求：`Partial<CrawlerSource>`，禁止修改 `id`、`created_at`、`updated_at`。

响应：`ApiResponse<CrawlerSource>`

### DELETE `/api/v1/admin/crawler/sources/{source_id}`

软删除，将 `status` 更新为 `deprecated`。

响应：`ApiResponse<null>`

### POST `/api/v1/admin/crawler/sources/{source_id}/health`

响应：

```json
{
  "source_id": "src_001",
  "status": "healthy",
  "checked_at": "2026-06-06T13:00:00Z",
  "response_time_ms": 120,
  "status_code": 200
}
```

### GET `/api/v1/admin/crawler/sources/{source_id}/stats`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `days` | int | 否 | 默认 `30` |

响应：

```json
{
  "source_id": "src_001",
  "source_name": "维基百科中文",
  "total_requests": 100,
  "total_success": 90,
  "total_failed": 10,
  "success_rate": 90.0,
  "daily_stats": []
}
```

---

## 6. 爬虫任务 API

### GET `/api/v1/admin/crawler/tasks`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 默认 `1` |
| `page_size` | int | 否 | 默认 `20` |
| `status` | string | 否 | 见 `crawler_task_status` |
| `task_type` | string | 否 | 见 `crawler_task_type` |
| `source_id` | string | 否 | 爬取源 ID |

响应：`ApiResponse<PaginatedResponse<CrawlerTask>>`

### POST `/api/v1/admin/crawler/tasks`

请求：

```json
{
  "name": "爬取周杰伦信息",
  "task_type": "targeted",
  "source_ids": ["src_001"],
  "config": {
    "spider_type": "person",
    "keywords": ["周杰伦"],
    "concurrent_limit": 3,
    "delay": 1.0,
    "timeout": 30
  },
  "execute_now": true
}
```

响应：`ApiResponse<CrawlerTask>`

### POST `/api/v1/admin/crawler/tasks/{task_id}/start`

响应：`ApiResponse<CrawlerTask>`

### POST `/api/v1/admin/crawler/tasks/{task_id}/stop`

响应：`ApiResponse<CrawlerTask>`

### DELETE `/api/v1/admin/crawler/tasks/{task_id}`

删除非运行中任务及其日志。运行中任务必须先停止。

响应：

```json
{
  "id": "task_001"
}
```

---

## 7. 爬虫统计 API

### GET `/api/v1/admin/crawler/stats/overview`

响应：

```json
{
  "active_sources": 2,
  "total_tasks": 12,
  "today_requests": 100,
  "today_success": 90,
  "today_success_rate": 90.0,
  "total_requests": 1000,
  "total_success": 860,
  "total_failed": 140,
  "overall_success_rate": 86.0,
  "recent_records": [],
  "category_distribution": [],
  "scrapy_status": {
    "status": "connected",
    "queue_length": 0,
    "redis_connected": true
  }
}
```

### GET `/api/v1/admin/crawler/stats/sources`

查询参数：`days`，默认 `7`。

响应：`ApiResponse<CrawlerSourceComparison[]>`

响应项包含：`source_id`、`name`、`type`、`status`、`health_status`、`total_requests`、`success_requests`、`failed_requests`、`success_rate`、`avg_response_time`、`avg_completeness`。

### GET `/api/v1/admin/crawler/stats/trend`

查询参数：`days`，默认 `30`。

响应：`ApiResponse<CrawlerTrendPoint[]>`

响应项包含：`date`、`requests`、`successes`、`failures`、`success_rate`。

### GET `/api/v1/admin/crawler/stats/efficiency`

查询参数：`days`，默认 `7`。

响应：`ApiResponse<CrawlerEfficiencyPoint[]>`

### GET `/api/v1/admin/crawler/scrapy/status`

响应：

```json
{
  "status": "connected",
  "queue_length": 0,
  "redis_connected": true
}
```

### Redis 队列与事件

FastAPI 与 Scrapy Service 通过 Redis 解耦：

| 类型 | Key/Channel | 方向 | 用途 |
|------|-------------|------|------|
| 任务队列 | `starmap:crawl:tasks` | FastAPI -> Scrapy | 发布待执行爬虫任务 |
| 进度事件 | `starmap:crawl:progress` | Scrapy -> FastAPI | 更新 `crawl_tasks` 状态、进度和计数 |
| 日志事件 | `starmap:crawl:logs` | Scrapy -> FastAPI | 写入 `crawl_logs` 并广播 WebSocket |

任务消息：

```json
{
  "task_id": "task_001",
  "task_type": "targeted",
  "spider_type": "person",
  "source": "baike",
  "keywords": ["周杰伦"],
  "config": {},
  "published_at": "2026-06-06T13:00:00Z"
}
```

进度事件：

```json
{
  "task_id": "task_001",
  "status": "running",
  "progress": 50,
  "items_scraped": 1,
  "requests_made": 2,
  "responses_received": 2,
  "errors": 0
}
```

---

## 8. 定时任务 API

### GET `/api/v1/admin/crawler/schedules`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 默认 `1` |
| `page_size` | int | 否 | 默认 `20` |
| `is_enabled` | bool | 否 | 启用状态 |

响应：`ApiResponse<PaginatedResponse<CrawlerSchedule>>`

### POST `/api/v1/admin/crawler/schedules`

请求：

```json
{
  "name": "每日增量更新",
  "description": "每天凌晨更新活跃源",
  "task_type": "incremental",
  "source_ids": ["src_001"],
  "target_config": {
    "spider_type": "person",
    "keywords": []
  },
  "cron_expression": "0 2 * * *",
  "timezone": "Asia/Shanghai",
  "is_enabled": true,
  "max_retries": 3,
  "retry_interval": 300,
  "concurrent_limit": 1,
  "timeout": 3600
}
```

响应：`ApiResponse<CrawlerSchedule>`

执行规则：

- 调度触发后先创建 `crawl_tasks` 记录和 `crawl_schedule_runs(status=running)`。
- Scrapy/健康检查/清理任务到达 `completed`、`failed`、`stopped` 或超时后，才更新执行历史终态。
- `crawl_schedule_runs.task_id` 必须关联实际创建的爬虫任务。

### GET `/api/v1/admin/crawler/schedules/{schedule_id}`

响应：`ApiResponse<CrawlerSchedule>`

### PUT `/api/v1/admin/crawler/schedules/{schedule_id}`

请求：`Partial<CrawlerSchedule>`，禁止修改 `id`、`created_at`、`updated_at`。

响应：`ApiResponse<CrawlerSchedule>`

### DELETE `/api/v1/admin/crawler/schedules/{schedule_id}`

响应：`ApiResponse<null>`

### POST `/api/v1/admin/crawler/schedules/{schedule_id}/toggle`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `enabled` | bool | 是 | `true` 启用，`false` 禁用 |

响应：

```json
{
  "id": "sch_001",
  "is_enabled": true
}
```

### GET `/api/v1/admin/crawler/schedules/{schedule_id}/runs`

查询参数：`page`、`page_size`、`status`。

响应：`ApiResponse<PaginatedResponse<CrawlerScheduleRun>>`

---

## 9. 日志 API

### GET `/api/v1/admin/crawler/logs`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 否 | 任务 ID |
| `source_id` | string | 否 | 爬取源 ID |
| `level` | string | 否 | 见 `crawler_log_level` |
| `status` | string | 否 | 见 `crawler_log_status` |
| `resource_type` | string | 否 | 见 `resource_type` |
| `start_time` | string | 否 | ISO 8601 |
| `end_time` | string | 否 | ISO 8601 |
| `page` | int | 否 | 默认 `1` |
| `page_size` | int | 否 | 默认 `50` |

响应：`ApiResponse<PaginatedResponse<CrawlerLog>>`

### GET `/api/v1/admin/crawler/logs/analysis`

查询参数：`days`，默认 `7`。

响应：

```json
{
  "period_days": 7,
  "level_distribution": [],
  "status_distribution": [],
  "error_distribution": [],
  "source_distribution": [],
  "daily_trend": []
}
```

### WebSocket `/api/v1/admin/crawler/logs/stream`

连接参数：`task_id`、`source_id`、`level`。

客户端心跳：

```json
{
  "type": "ping"
}
```

服务端心跳响应：

```json
{
  "type": "pong"
}
```

客户端动态筛选：

```json
{
  "type": "filter",
  "task_ids": ["task_001"],
  "source_ids": ["src_001"],
  "levels": ["INFO", "ERROR"]
}
```

服务端日志消息：

```json
{
  "type": "log",
  "data": {
    "id": 1,
    "task_id": "task_001",
    "level": "INFO",
    "message": "Fetched person page",
    "created_at": "2026-06-06T13:00:00Z"
  }
}
```

动态筛选确认：

```json
{
  "type": "filter_updated",
  "task_ids": ["task_001"],
  "source_ids": ["src_001"],
  "levels": ["INFO", "ERROR"]
}
```

---

## 10. 当前实现对齐清单

以下条目是当前开发必须修复或确认的对齐项：

- [x] 后端任务列表响应字段从 `type` 改为 `task_type`。
- [x] 后端任务列表响应字段从 `fail_count` 改为 `failed_count`。
- [x] 前端 `CrawlerTask` 类型同步使用 `task_type` 和 `failed_count`。
- [x] `CrawlTask.task_type` 枚举扩展到 `health_check`、`cleanup`。
- [x] `CrawlTask` 模型和表结构补齐任务统计和错误字段，或删除未持久化字段使用。
- [x] `CrawlerSourceService.get_source_stats` 修复 `failed_failed_requests` 拼写。
- [x] Scrapy 入库完成后写入 `crawl_source_stats`，统计页移除硬编码 mock。
- [x] 管理端日志页通过 WebSocket 动态渲染实时日志并同步筛选条件。
- [x] 管理端任务列表支持删除非运行中任务、运行中自动刷新和真实数据源选择。
- [x] 定时任务执行历史从“发布即成功”改为跟踪实际爬虫任务终态。
- [x] 所有 `ApiResponse` 补齐 `request_id`。
- [ ] HTTP 错误状态码与响应体 `code` 保持一致。
- [ ] 管理端所有爬虫页面禁止使用未标注的 mock 数据。
