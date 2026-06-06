# 爬虫优先交付计划

> 版本：v1.0  
> 日期：2026-06-06  
> 负责人：PM  
> 状态：执行基线  
> 适用范围：PM / Backend / Frontend / Data / DevOps

---

## 1. PM 结论

项目还处在早期开发阶段，但已经出现了“代码、文档、接口字段不完全一致”的信号。爬虫模块又同时牵涉前端页面、后端 API、MySQL 表、Redis 队列、Scrapy 服务、日志和统计，因此本阶段必须先冻结爬虫契约，再逐步实现。

本阶段优先目标：

1. 以 `docs/api/README.md` 作为前后端和数据库字段对齐的接口真相源。
2. 以 MySQL 作为爬虫任务、源配置、日志、统计和采集结果的主存储。
3. 以 FastAPI 管理任务，以 Redis 解耦任务队列和实时进度，以 Scrapy Service 执行实际爬取。
4. 先交付爬取源管理、手动任务、日志、统计，再交付定时任务和下游同步增强。

---

## 2. 目标架构

```text
frontend-admin
  -> FastAPI /api/v1/admin/crawler/*
  -> MySQL: crawl_sources / crawl_tasks / crawl_logs / crawl_source_stats / crawl_schedules
  -> Redis: starmap:crawl:tasks / starmap:crawl:progress / starmap:crawl:logs
  -> Scrapy Service
  -> MySQL: persons / works / person_relations / crawl_logs / crawl_source_stats
  -> FastAPI WebSocket: /api/v1/admin/crawler/logs/stream
  -> frontend-admin realtime logs/progress

MySQL -> Sync Jobs -> Neo4j / ChromaDB
```

职责边界：

| 模块 | 责任 | 禁止事项 |
|------|------|----------|
| `frontend-admin` | 管理界面、表单校验、列表/图表/日志展示 | 不写死 mock 字段，不自行猜测响应结构 |
| `backend/app/api/admin.py` | 管理端 HTTP/WebSocket 路由 | 不直接拼业务逻辑，不返回未文档化字段 |
| `backend/app/services/*` | 任务、源、日志、统计、调度业务逻辑 | 不绕过 MySQL 模型写库 |
| `backend/scrapy_service` | 实际网页抓取、解析、校验、入库、进度上报 | 不承担管理端权限和调度 UI 逻辑 |
| MySQL | 主存储和契约字段来源 | 不把临时字段只存在内存对象上 |
| Neo4j/ChromaDB | 图谱查询和语义检索的下游索引 | 不作为爬虫原始数据主存储 |

---

## 3. 需求拆解

### P0：爬虫 MVP 闭环

| ID | 需求 | 验收标准 | 责任角色 |
|----|------|----------|----------|
| CR-001 | 爬取源 CRUD | 可新增、编辑、禁用、软删除源；字段符合 API 文档 | Backend + Frontend |
| CR-002 | 手动创建任务 | 可选择源、任务类型、关键词并创建任务 | Backend + Frontend |
| CR-003 | 任务启动/停止 | 任务可进入 `running`，可停止为 `stopped` | Backend |
| CR-004 | Redis 任务队列 | FastAPI 发布任务，Scrapy Service 可消费 | Backend + Data |
| CR-005 | 日志查询 | 日志按任务、源、级别、状态、时间筛选 | Backend + Frontend |
| CR-006 | 实时日志 | WebSocket 可推送日志，前端可动态更新筛选条件 | Backend + Frontend |
| CR-007 | 结果入库 | 人物、作品、关系写入 MySQL，记录 `crawl_task_id` 和源信息 | Data + Backend |
| CR-008 | 基础统计 | 概览、趋势、源对比、效率分析来自真实统计表 | Backend + Frontend |

### P1：稳定性与自动化

| ID | 需求 | 验收标准 | 责任角色 |
|----|------|----------|----------|
| CR-101 | 定时任务 | 支持 Cron 创建、启停、执行历史 | Backend + Frontend |
| CR-102 | 源健康检查 | 可手动检查源状态，定时任务可批量检查 | Backend + Data |
| CR-103 | 失败重试 | 网络错误、限流、解析错误可分类并按策略重试 | Data |
| CR-104 | 数据质量评分 | 计算字段完整度、重复记录、有效记录数 | Data |
| CR-105 | 下游同步 | MySQL 采集结果可同步到 Neo4j/ChromaDB | Backend + Data |

### P2：运营增强

| ID | 需求 | 验收标准 | 责任角色 |
|----|------|----------|----------|
| CR-201 | 日志导出 | 支持 CSV/JSON 导出 | Frontend + Backend |
| CR-202 | 优化建议 | 基于成功率、完整度、响应时间给出源优化提示 | Backend |
| CR-203 | 告警通知 | 任务失败或源降级时可通知管理员 | DevOps + Backend |

---

## 4. 当前架构缺口

以下问题进入 P0 修复清单，开发时必须优先处理：

| 问题 | 影响 | 处理要求 |
|------|------|----------|
| `docs/api/README.md` 为空 | 前后端无法对齐 | 以本次补充后的 API 契约为准 |
| `pydantic_settings` 未在 `backend/requirements.txt` 中声明 | 后端可能启动失败 | 已补齐 Pydantic v2 和 `pydantic-settings` 依赖 |
| `app.tasks.scheduler` 在 `main.py` 中被导入但模块需确认 | 生命周期启动可能报错 | Backend 补齐调度器模块或显式降级 |
| `CrawlTask.task_type` 只支持 3 类，但业务使用 `health_check/cleanup` | 定时任务创建的任务可能无法入库 | 已扩展 MySQL 枚举、ORM、迁移脚本 |
| 任务服务写入 `total_requests/error_message`，模型中缺字段 | 统计和失败原因无法持久化 | 已增加持久化字段 |
| 源统计存在 `failed_failed_requests` 拼写错误 | 源详情统计接口会失败 | 已修复为 `failed_requests` |
| 任务响应存在 `type/fail_count` 与 `task_type/failed_count` 冲突 | 前端类型和后端字段冲突 | 已统一使用 `task_type` 和 `failed_count` |
| `ApiResponse.request_id` 未稳定返回 | 排错和前端契约不完整 | 已由请求上下文自动注入 |
| `backend/scrapy_service/venv` 出现在工作区 | 依赖和提交体积风险 | 加入忽略并避免提交虚拟环境 |
| Scrapy consumer 依赖 `spider_idle` 且空队列会退出 | Redis 队列无人持续消费 | 已改为常驻 Redis `brpop` consumer，单任务子进程执行 |
| Scrapy `works/person_relations` 写入字段与 MySQL 表不一致 | 采集结果落库失败 | 已按当前表结构写入，扩展字段进入 `raw_data/properties` |
| FastAPI 进度订阅依赖请求 session | 任务进度和日志可能丢失 | 已改为应用级 Redis 事件监听器独立持久化 |

发现上述问题时，遵守 `docs/team/collaboration-rules.md` 的“发现即停止”原则，不允许猜字段继续开发。

---

## 5. 开发安排

### Sprint Crawler-0：契约冻结与启动修复（1 天）

| 任务 | 产出 | 负责人 |
|------|------|--------|
| 冻结 API 契约 | `docs/api/README.md` | PM + Backend + Frontend |
| 梳理字段冲突 | 对齐清单和修复任务 | PM |
| 修复后端启动阻塞 | 依赖、调度器、健康检查可启动 | Backend |
| 确认 Scrapy Service 启动方式 | `consumer` 模式可连接 Redis | Data + DevOps |

### Sprint Crawler-1：真实任务闭环（5 天）

| 天 | Backend | Data | Frontend | PM 验收点 |
|----|---------|------|----------|-----------|
| Day 1 | 修复 ORM/迁移/字段枚举 | 确认 Item 与 MySQL 字段映射 | 更新 TS 类型为契约字段 | 表结构、类型、文档一致 |
| Day 2 | 完成源 CRUD 和任务 CRUD | 源配置读取与限速配置 | 源列表、任务列表接真实 API | 无 mock 数据 |
| Day 3 | 完成 Redis 发布、状态更新 | Scrapy 消费任务并上报进度 | 任务启动/停止交互 | 任务生命周期可演示 |
| Day 4 | 完成日志查询和 WebSocket | 抓取、解析、校验、入库日志 | 日志中心和实时日志 | 可按任务筛选日志 |
| Day 5 | 完成统计 API | 写入日统计和质量指标 | 概览、趋势、效率图表 | 统计来自真实表 |

### Sprint Crawler-2：定时任务与数据质量（5 天）

| 天 | Backend | Data | Frontend | PM 验收点 |
|----|---------|------|----------|-----------|
| Day 1 | 调度器初始化和任务装载 | 健康检查爬虫逻辑 | 定时任务列表 | 重启后定时任务恢复 |
| Day 2 | 定时任务 CRUD/启停/执行历史 | 重试和错误分类 | Cron 表单 | Cron 可配置 |
| Day 3 | MySQL -> Neo4j/Chroma 同步任务 | 去重和质量评分 | 数据质量展示 | 采集数据可进入下游索引 |
| Day 4 | 权限、审计、错误响应统一 | 反爬策略参数化 | 空状态和错误态完善 | 运营可定位失败原因 |
| Day 5 | 联调和回归 | 采集样本验收 | UI 回归 | 完成端到端验收 |

---

## 6. 接口与数据体对齐规则

1. 所有管理端 HTTP 接口使用 `/api/v1/admin/*`。
2. JSON 字段统一使用 `snake_case`。
3. 分页统一使用 `page`、`page_size`、`total`、`total_pages`。
4. 任务类型字段统一为 `task_type`，禁止响应中再使用 `type` 表示任务类型。
5. 失败数字段统一为 `failed_count`，禁止使用 `fail_count`。
6. 时间字段统一为 ISO 8601 字符串，后端内部存 UTC，展示层按本地时区转换。
7. 所有跨角色字段变更必须同步更新 `docs/api/README.md`、前端 TypeScript 类型、后端 Pydantic/ORM 模型、数据库迁移脚本和 `CHANGELOG.md`。

---

## 7. 验收场景

### 场景 A：手动爬取人物

1. 管理员新增或启用 `wikipedia_zh` 爬取源。
2. 管理员创建 `targeted` 任务，关键词为 `["周杰伦"]`，选择人物爬虫。
3. 后端创建 `crawl_tasks` 记录并发布 Redis 任务。
4. Scrapy Service 消费任务，写入日志和采集结果。
5. 管理端任务进度更新，日志中心实时展示 `fetch/parse/validate/store`。
6. 任务完成后，`success_count`、`failed_count`、`progress`、统计报表同步更新。

### 场景 B：源健康检查

1. 管理员点击源健康检查。
2. 后端访问 `base_url` 并更新 `health_status`。
3. 管理端源列表状态立即刷新。
4. 健康检查失败必须有 `crawl_logs` 记录和错误类型。

### 场景 C：定时增量任务

1. 管理员创建每天 02:00 执行的 `incremental` 定时任务。
2. 调度器根据 Cron 创建任务并写入执行历史。
3. 任务完成后更新 `last_run_at`、`next_run_at`、`success_runs/failed_runs`。

---

## 8. 角色启动要求

每个角色开发前必须执行：

```bash
./scripts/session-start.sh backend
./scripts/session-start.sh frontend
./scripts/session-start.sh data
./scripts/session-start.sh pm
```

角色开始编码前必须回答：

1. 当前要改哪些文件？
2. 是否影响 API、数据模型或环境变量？
3. 是否需要更新 `docs/api/README.md` 和 `CHANGELOG.md`？
4. 是否存在未提交的其他人改动？

---

## 9. PM 每日检查清单

- [ ] API 文档是否与后端实现一致
- [ ] 前端 TypeScript 类型是否与 API 文档一致
- [ ] ORM 模型是否与迁移脚本一致
- [ ] 爬虫日志是否写入真实数据库
- [ ] 统计是否来自真实表而不是 mock
- [ ] 新增字段是否记录到 `CHANGELOG.md`
- [ ] 每个角色是否更新自己的开发日志
