# 工程师任务分配与开发路线

> 版本：v1.0  
> 日期：2026-06-05  
> 负责人：PM  
> 状态：已分配

---

## 0. 当前执行基线（2026-06-06）

本项目当前优先完善爬虫相关功能。所有角色以以下文档作为执行依据：

| 类型 | 文档 | 用途 |
|------|------|------|
| PM 计划 | `docs/roadmap/crawler-first-delivery-plan.md` | 需求、架构、排期、验收 |
| API 契约 | `docs/api/README.md` | 前后端和数据库字段对齐 |
| 架构约束 | `docs/tech/architecture.md` | 服务职责和数据流 |
| 协作规范 | `docs/team/collaboration-rules.md` | 发现即停止、变更流程 |

执行规则：

1. 爬虫相关接口字段以 `docs/api/README.md` 为准。
2. 任何接口、表结构、枚举变更必须同步更新 `CHANGELOG.md`。
3. 前端不得继续扩展未标注 mock 数据，后端不得返回未文档化字段。
4. 数据工程师写入 MySQL 的采集结果必须保留来源、任务 ID、原始 URL 和原始数据。

---

## 1. 团队角色定义

| 角色 | 职责 | 当前任务 |
|------|------|----------|
| **Backend 工程师** | 后端 API、数据库、业务逻辑 | 爬虫管理增强后端实现 |
| **Frontend 工程师** | 前端页面、组件、API 对接 | 爬虫管理增强前端实现 |
| **Data 工程师** | 爬虫开发、数据清洗、数据质量 | 爬虫基类改造、日志集成 |
| **DevOps 工程师** | 部署、监控、基础设施 | 数据库迁移、环境配置 |

---

## 2. 当前冲刺：爬虫管理增强（Sprint 3）

### 2.1 冲刺目标

**目标**：实现完整的爬虫管理机制，包括源管理、统计、定时任务、手动执行、日志

**时间**：2周（Week 3-4）

**验收标准**：
- [ ] 可动态添加/配置爬取源
- [ ] 可查看各源爬取效果统计
- [ ] 可配置定时任务（Cron）
- [ ] 可手动启动/停止爬取任务
- [ ] 可实时查看爬取日志
- [ ] 所有数据来自真实数据库

---

## 3. 任务分配详情

### 3.1 Backend 工程师

#### Week 3

| 天数 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **Day 1** | 执行数据库迁移脚本 | 新表创建完成 | DevOps |
| **Day 2** | 实现 CrawlerSourceService | 爬取源 CRUD | Day 1 |
| **Day 3** | 实现 CrawlerStatsService | 统计报表 API | Day 1 |
| **Day 4** | 实现 CrawlerLogService | 日志查询 API | Day 1 |
| **Day 5** | 更新 admin.py API 路由 | 替换 mock 数据 | Day 2-4 |

#### Week 4

| 天数 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **Day 1** | 集成 APScheduler | 定时任务调度器 | - |
| **Day 2** | 实现 CrawlerScheduleService | 定时任务 CRUD | Day 1 |
| **Day 3** | 实现手动任务控制 API | 启动/停止/状态 | Day 2 |
| **Day 4** | 实现 WebSocket 日志推送 | 实时日志流 | Day 3 |
| **Day 5** | API 联调 + Bug 修复 | 功能完整 | Frontend |

#### 技术要点

```python
# 关键依赖
APScheduler==3.10.4      # 定时任务调度
websockets==12.0         # WebSocket 实时推送
requests==2.31.0         # 健康检查

# 代码规范
- Service 层必须继承 BaseService
- API 返回统一使用 ApiResponse 格式
- 数据库操作使用 async/await
- 日志使用 structlog，统一格式
```

#### 注意事项

1. **数据库连接**：使用已有的 `mysql_client`，不要重复创建连接池
2. **事务处理**：Service 层方法必须使用事务装饰器
3. **错误处理**：统一使用 `CrawlerError` 异常类
4. **性能优化**：统计查询使用预计算日汇总表，避免实时聚合

---

### 3.2 Frontend 工程师

#### Week 3

| 天数 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **Day 1** | 搭建页面框架 + 路由配置 | 可访问的空页面 | - |
| **Day 2** | 爬取源列表页 | 源 CRUD UI | Backend Day 5 |
| **Day 3** | 统计概览页 | 图表 + 指标卡片 | Backend Day 5 |
| **Day 4** | 任务管理页增强 | 手动执行 + 进度 | Backend Day 5 |
| **Day 5** | 日志中心页 | 日志查询 + 筛选 | Backend Day 5 |

#### Week 4

| 天数 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **Day 1** | 定时任务列表页 | 任务列表 UI | Backend Day 2 |
| **Day 2** | 定时任务表单页 | Cron 配置 | Backend Day 2 |
| **Day 3** | CronPicker 组件 | 可视化配置 | - |
| **Day 4** | WebSocket 实时日志 | 实时推送 | Backend Day 4 |
| **Day 5** | 联调 + Bug 修复 | 功能完整 | Backend |

#### 技术要点

```typescript
// 关键依赖
// 已有：React 18 + TypeScript + Ant Design + React Query

// 新增组件
// components/Crawler/
//   ├── StatCard.tsx
//   ├── ProgressBar.tsx
//   ├── CronPicker.tsx
//   ├── LogViewer.tsx
//   └── EfficiencyTable.tsx

// 代码规范
- 使用 React Query 进行数据获取和缓存
- 表单使用 Ant Design Form 组件
- 图表使用 ECharts
- WebSocket 使用原生 API
```

#### 注意事项

1. **API 对接**：等待 Backend 完成 API 后再对接，不要写死 mock 数据
2. **状态管理**：使用 Zustand 管理全局状态（用户信息、权限）
3. **实时更新**：WebSocket 连接在组件卸载时记得关闭
4. **性能优化**：大列表使用虚拟滚动，图表懒加载

---

### 3.3 Data 工程师

#### Week 3

| 天数 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **Day 1** | 改造 BaseCrawler 集成日志 | 自动写入 crawl_logs | Backend Day 1 |
| **Day 2** | 实现日志写入方法 | CrawlerLogService 调用 | Day 1 |
| **Day 3** | 配置默认爬取源 | 初始化数据 | Backend Day 1 |
| **Day 4** | 测试爬虫日志 | 验证日志写入 | Day 2 |
| **Day 5** | 数据质量评估 | 字段完整度计算 | - |

#### Week 4

| 天数 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **Day 1** | 爬取源健康检查脚本 | 检测源可用性 | Backend |
| **Day 2** | 失败重试策略优化 | 指数退避 | - |
| **Day 3** | 数据去重逻辑 | 重复数据检测 | - |
| **Day 4** | 数据清洗规则 | 自动化清洗 | - |
| **Day 5** | 联调 + Bug 修复 | 功能完整 | Backend |

#### 技术要点

```python
# 日志集成示例
class BaseCrawler:
    def __init__(self, source_id: str = None, task_id: str = None):
        self.source_id = source_id
        self.task_id = task_id
        self.log_service = CrawlerLogService()
    
    async def log(self, level: str, message: str, **kwargs):
        """自动写入日志"""
        await self.log_service.create_log(
            task_id=self.task_id,
            source_id=self.source_id,
            level=level,
            message=message,
            **kwargs
        )
    
    def fetch(self, url: str):
        """请求时自动记录"""
        start_time = time.time()
        result = self._do_fetch(url)
        duration = (time.time() - start_time) * 1000
        
        if result.success:
            self.log("info", f"Fetched {url}", 
                    status="success", duration_ms=duration)
        else:
            self.log("error", f"Failed to fetch {url}: {result.error}",
                    status="failed", duration_ms=duration, 
                    error_type=result.error_type)
        
        return result
```

#### 注意事项

1. **日志性能**：批量写入日志，避免每次请求都写数据库
2. **错误分类**：区分网络错误、解析错误、反爬错误
3. **数据质量**：计算字段完整度，标记低质量数据
4. **源配置**：每个源的配置使用 JSON 存储，灵活扩展

---

### 3.4 DevOps 工程师

#### Week 3

| 天数 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **Day 1** | 执行数据库迁移 | 新表创建 | - |
| **Day 2** | 配置 APScheduler | 定时任务调度器 | - |
| **Day 3** | 配置 WebSocket | 实时推送服务 | - |
| **Day 4** | 环境变量配置 | 配置文件更新 | - |
| **Day 5** | 监控告警配置 | 异常通知 | - |

#### Week 4

| 天数 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **Day 1** | 性能测试 | 压测报告 | Backend |
| **Day 2** | 安全审计 | 安全报告 | Backend |
| **Day 3** | 部署脚本 | 自动化部署 | - |
| **Day 4** | 备份策略 | 数据备份 | - |
| **Day 5** | 文档更新 | 运维文档 | - |

#### 注意事项

1. **数据库迁移**：使用 Alembic 管理迁移，记录版本号
2. **环境隔离**：开发/测试/生产环境配置分离
3. **监控告警**：异常时通知 Slack/邮件
4. **备份策略**：每日自动备份 MySQL 数据

---

## 4. 协作规范

### 4.1 代码提交规范

```bash
# 提交格式
type(scope): subject

# 示例
feat(crawler): 添加爬取源管理 API
fix(schedule): 修复定时任务重复执行问题
docs(api): 更新爬虫管理接口文档
test(source): 添加爬取源单元测试
```

### 4.2 分支管理

```
main                    # 主分支，只接受 PR
├── feature/crawler-source      # Backend: 爬取源管理
├── feature/crawler-stats       # Backend: 统计报表
├── feature/crawler-schedule    # Backend: 定时任务
├── feature/crawler-log         # Backend: 日志系统
├── feature/crawler-ui          # Frontend: 爬虫管理页面
├── feature/crawler-ws          # Backend: WebSocket
└── fix/mock-data               # 修复 mock 数据问题
```

### 4.3 每日站会

**时间**：每天上午 10:00
**内容**：
1. 昨天完成了什么？
2. 今天计划做什么？
3. 有什么阻塞？

### 4.4 代码审查

**审查人**：
- Backend PR → Backend 同事审查
- Frontend PR → Frontend 同事审查
- 跨模块 PR → PM 审查

**审查标准**：
- 代码规范检查
- 单元测试通过
- API 文档同步更新

---

## 5. 风险与应对

| 风险 | 影响 | 应对措施 | 负责人 |
|------|------|----------|--------|
| Backend API 延迟 | Frontend 无法对接 | Frontend 先写接口定义，Mock 数据 | Frontend |
| 数据库性能问题 | 统计查询慢 | 预计算日汇总，加索引 | Backend |
| WebSocket 并发高 | 服务器压力大 | 使用 Redis 广播，限制连接数 | DevOps |
| 爬虫反爬升级 | 大量请求失败 | 动态调整请求频率，切换 User-Agent | Data |

---

## 6. 验收计划

### 6.1 内部验收（Week 4 Day 5）

| 检查项 | 验收人 | 标准 |
|--------|--------|------|
| 爬取源 CRUD | PM | 可添加、编辑、禁用、删除 |
| 统计报表 | PM | 数据准确，图表正常 |
| 定时任务 | PM | Cron 配置正确，自动执行 |
| 手动执行 | PM | 可启动/停止，实时进度 |
| 实时日志 | PM | WebSocket 推送正常 |

### 6.2 用户验收（Week 4 Day 7）

| 检查项 | 验收人 | 标准 |
|--------|--------|------|
| 功能完整性 | PM | 所有 P0 功能可用 |
| 性能指标 | DevOps | 查询 < 1s，推送 < 5s |
| 数据准确性 | Data | 统计与数据库一致 |

---

## 7. 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 爬虫管理增强需求 | `docs/admin/crawler-management-enhancement.md` | 详细需求文档 |
| 前端开发路线 | `docs/admin/frontend-roadmap-crawler.md` | 前端实现指南 |
| 后端开发路线 | `docs/admin/backend-roadmap-crawler.md` | 后端实现指南 |
| 项目看板 | `docs/project-board-crawler-enhancement.md` | 任务跟踪 |
| 数据库迁移脚本 | `backend/scripts/migrate_crawler_v2.sql` | SQL 迁移 |

---

**文档状态**：✅ 已完成  
**下次更新**：每日站会后
