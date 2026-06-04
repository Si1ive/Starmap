# 爬虫管理模块增强计划

> 版本：v2.0  
> 日期：2026-06-05  
> 负责人：PM  
> 状态：规划中  
> 优先级：P0（最高优先级）

---

## 1. 现状分析

### 1.1 现有功能

| 模块 | 已有功能 | 状态 |
|------|----------|------|
| 数据库 | `crawl_tasks` 表（基础任务信息） | ✅ 可用 |
| 数据库 | `crawl_logs` 表（基础日志记录） | ✅ 可用 |
| 后端 API | 任务列表、创建、停止 | ⚠️ 模拟数据 |
| 后端 API | 日志查看 | ⚠️ 未实现 |
| 前端 | 任务列表页 | ⚠️ 基础UI，功能未完全对接 |
| 前端 | 统计报表 | ❌ 未实现 |
| 前端 | 爬取源管理 | ❌ 未实现 |
| 前端 | 定时任务 | ❌ 未实现 |

### 1.2 核心问题

1. **爬取源管理缺失** - 无法动态添加/配置爬取源
2. **统计维度不足** - 无法评估各爬取源的效果（请求数 vs 有效数据数）
3. **定时任务缺失** - 无法设置周期性爬取任务
4. **手动执行受限** - 无法手动触发并实时查看状态
5. **日志系统不可用** - 日志表存在但 API 未实现，前端无法查看
6. **大量模拟数据** - 后端 API 返回 mock 数据，未连接真实数据库

---

## 2. 需求增强

### 2.1 爬取源管理（Source Management）

**目标**：动态管理爬取源，评估各源的有效性

#### 功能需求

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 爬取源 CRUD | 添加、编辑、启用/禁用、删除爬取源 | P0 |
| 源配置管理 | 每个源的配置参数（URL模板、选择器、频率限制等） | P0 |
| 源健康检查 | 自动检测源是否可用 | P1 |
| 源分类标签 | 按类型分类（百科/社交媒体/新闻/官网等） | P1 |

#### 数据模型

```sql
-- 爬取源表（新增）
CREATE TABLE crawl_sources (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    name VARCHAR(100) NOT NULL COMMENT '源名称（如：维基百科中文）',
    code VARCHAR(50) NOT NULL UNIQUE COMMENT '源编码（如：wikipedia_zh）',
    type VARCHAR(50) COMMENT '源类型：encyclopedia/social/official/news',
    base_url VARCHAR(500) COMMENT '基础URL',
    
    -- 配置（JSON格式，灵活扩展）
    config JSON COMMENT '源配置：选择器、字段映射等',
    
    -- 频率控制
    request_interval DECIMAL(3,1) DEFAULT 1.0 COMMENT '请求间隔(秒)',
    daily_limit INT DEFAULT 1000 COMMENT '每日请求上限',
    concurrent_limit INT DEFAULT 5 COMMENT '并发数限制',
    
    -- 状态
    status ENUM('active', 'inactive', 'error', 'deprecated') DEFAULT 'active',
    health_status ENUM('healthy', 'degraded', 'down') DEFAULT 'healthy',
    last_health_check DATETIME COMMENT '最后健康检查时间',
    
    -- 统计（冗余字段，便于快速查询）
    total_requests BIGINT DEFAULT 0 COMMENT '累计请求数',
    total_success BIGINT DEFAULT 0 COMMENT '累计成功数',
    total_failed BIGINT DEFAULT 0 COMMENT '累计失败数',
    avg_response_time DECIMAL(8,2) COMMENT '平均响应时间(ms)',
    
    -- 时间戳
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_status (status),
    INDEX idx_type (type),
    INDEX idx_health (health_status)
) COMMENT='爬取源配置表';
```

#### 配置示例

```json
{
  "wikipedia_zh": {
    "base_url": "https://zh.wikipedia.org/wiki/",
    "search_url": "https://zh.wikipedia.org/w/index.php?search={keyword}",
    "selectors": {
      "title": "h1.firstHeading",
      "summary": "div.mw-parser-output > p:first-of-type",
      "infobox": "table.infobox",
      "birth_date": "span.bday",
      "occupation": "td.role"
    },
    "field_mapping": {
      "birth_date": "birth_date",
      "occupation": "categories"
    },
    "anti_detection": {
      "user_agent_rotation": true,
      "referer": "https://zh.wikipedia.org/",
      "delay_range": [1.0, 3.0]
    }
  }
}
```

---

### 2.2 爬取效果统计（Source Statistics）

**目标**：清晰展示每个爬取源的投入产出比，便于优化调整

#### 统计维度

| 维度 | 指标 | 说明 |
|------|------|------|
| **请求效率** | 请求数 / 有效数据数 | 评估源的"性价比" |
| **成功率** | 成功请求 / 总请求 | 评估源稳定性 |
| **数据质量** | 字段完整度 / 数据准确率 | 评估源数据质量 |
| **响应速度** | 平均响应时间 / P95响应时间 | 评估源性能 |
| **成本效益** | 数据量 / 时间成本 / 资源消耗 | 综合评估 |

#### 统计报表设计

**总体概览卡片**
```
┌─────────────┬─────────────┬─────────────┬─────────────┐
│  活跃源数   │  今日请求   │  今日成功   │  整体成功率  │
│     5      │   1,234    │    987     │    79.9%   │
└─────────────┴─────────────┴─────────────┴─────────────┘
```

**各源效果对比表**
| 源名称 | 类型 | 状态 | 今日请求 | 今日成功 | 成功率 | 平均响应 | 数据完整度 | 操作 |
|--------|------|------|----------|----------|--------|----------|------------|------|
| 维基百科 | 百科 | 健康 | 500 | 450 | 90% | 1.2s | 85% | 详情/配置 |
| 豆瓣电影 | 社交 | 健康 | 300 | 210 | 70% | 2.5s | 60% | 详情/配置 |
| 百度百科 | 百科 | 降级 | 200 | 120 | 60% | 5.0s | 45% | 详情/配置 |

**效率分析图表**
- 各源请求数 vs 有效数据数（散点图）
- 各源成功率趋势（折线图，7天）
- 各源响应时间分布（箱线图）
- 数据完整度对比（雷达图）

#### 数据模型

```sql
-- 爬取源统计表（按天汇总，新增）
CREATE TABLE crawl_source_stats (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_id VARCHAR(32) NOT NULL COMMENT '爬取源ID',
    stat_date DATE NOT NULL COMMENT '统计日期',
    
    -- 请求统计
    total_requests INT DEFAULT 0 COMMENT '总请求数',
    success_requests INT DEFAULT 0 COMMENT '成功请求数',
    failed_requests INT DEFAULT 0 COMMENT '失败请求数',
    timeout_requests INT DEFAULT 0 COMMENT '超时请求数',
    rate_limited_requests INT DEFAULT 0 COMMENT '被限流请求数',
    
    -- 数据产出
    persons_extracted INT DEFAULT 0 COMMENT '提取人物数',
    works_extracted INT DEFAULT 0 COMMENT '提取作品数',
    relations_extracted INT DEFAULT 0 COMMENT '提取关系数',
    valid_records INT DEFAULT 0 COMMENT '有效记录数（通过验证）',
    duplicate_records INT DEFAULT 0 COMMENT '重复记录数',
    
    -- 性能指标
    avg_response_time DECIMAL(8,2) COMMENT '平均响应时间(ms)',
    min_response_time DECIMAL(8,2) COMMENT '最小响应时间(ms)',
    max_response_time DECIMAL(8,2) COMMENT '最大响应时间(ms)',
    p95_response_time DECIMAL(8,2) COMMENT 'P95响应时间(ms)',
    
    -- 数据质量
    avg_completeness DECIMAL(5,2) COMMENT '平均字段完整度(%)',
    
    -- 资源消耗
    total_duration INT DEFAULT 0 COMMENT '总耗时(秒)',
    data_size_mb DECIMAL(8,2) COMMENT '数据大小(MB)',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_source_date (source_id, stat_date),
    INDEX idx_stat_date (stat_date),
    INDEX idx_source_id (source_id)
) COMMENT='爬取源日统计表';
```

---

### 2.3 定时任务管理（Scheduled Tasks）

**目标**：灵活配置周期性爬取任务，自动化数据采集

#### 功能需求

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 任务模板 | 预定义任务模板（全量更新/增量更新/定向爬取） | P0 |
| Cron表达式 | 支持标准Cron表达式配置执行周期 | P0 |
| 可视化配置 | 提供可视化时间选择器（非技术人员友好） | P1 |
| 任务依赖 | 支持任务间依赖（如：先爬人物再爬关系） | P2 |
| 执行历史 | 查看每次执行的结果和日志 | P0 |
| 失败重试 | 自动重试失败任务，可配置重试策略 | P1 |
| 并发控制 | 限制同时运行的定时任务数量 | P1 |

#### 任务类型

```
定时任务类型：
├── 全量更新（Full Update）
│   └── 周期：每周一次，重新爬取所有活跃源
├── 增量更新（Incremental Update）
│   └── 周期：每天一次，只爬取更新的内容
├── 定向爬取（Targeted Crawl）
│   └── 周期：自定义，针对特定人物/作品
├── 健康检查（Health Check）
│   └── 周期：每小时，检测各源可用性
└── 数据清洗（Data Cleanup）
    └── 周期：每周一次，清理重复/过期数据
```

#### 数据模型

```sql
-- 定时任务表（新增）
CREATE TABLE crawl_schedules (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    name VARCHAR(200) NOT NULL COMMENT '任务名称',
    description TEXT COMMENT '任务描述',
    
    -- 任务配置
    task_type ENUM('full', 'incremental', 'targeted', 'health_check', 'cleanup') NOT NULL,
    source_ids JSON COMMENT '关联的爬取源ID列表',
    target_config JSON COMMENT '目标配置（如：指定人物ID列表）',
    
    -- 调度配置
    cron_expression VARCHAR(100) NOT NULL COMMENT 'Cron表达式',
    timezone VARCHAR(50) DEFAULT 'Asia/Shanghai' COMMENT '时区',
    
    -- 执行控制
    is_enabled BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    max_retries INT DEFAULT 3 COMMENT '失败重试次数',
    retry_interval INT DEFAULT 300 COMMENT '重试间隔(秒)',
    concurrent_limit INT DEFAULT 1 COMMENT '并发数限制',
    timeout INT DEFAULT 3600 COMMENT '任务超时(秒)',
    
    -- 通知配置
    notify_on_success BOOLEAN DEFAULT FALSE COMMENT '成功时通知',
    notify_on_failure BOOLEAN DEFAULT TRUE COMMENT '失败时通知',
    notify_emails JSON COMMENT '通知邮箱列表',
    
    -- 执行统计
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

-- 定时任务执行历史表（新增）
CREATE TABLE crawl_schedule_runs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    schedule_id VARCHAR(32) NOT NULL COMMENT '定时任务ID',
    task_id VARCHAR(32) COMMENT '关联的爬取任务ID',
    
    -- 执行信息
    status ENUM('running', 'success', 'failed', 'timeout', 'cancelled') NOT NULL,
    started_at DATETIME NOT NULL COMMENT '开始时间',
    completed_at DATETIME COMMENT '完成时间',
    duration INT COMMENT '执行耗时(秒)',
    
    -- 执行结果
    total_requests INT DEFAULT 0,
    success_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    error_message TEXT COMMENT '错误信息',
    
    -- 日志
    log_summary TEXT COMMENT '日志摘要',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_schedule_id (schedule_id),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at)
) COMMENT='定时任务执行历史表';
```

---

### 2.4 手动执行与状态监控（Manual Execution）

**目标**：支持手动触发爬取，实时查看执行状态

#### 功能需求

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 快速启动 | 一键启动预配置任务 | P0 |
| 自定义启动 | 选择源、目标、参数后启动 | P0 |
| 实时状态 | WebSocket 推送执行进度 | P0 |
| 实时日志 | 查看正在执行任务的实时日志 | P0 |
| 强制停止 | 可中断正在运行的任务 | P0 |
| 执行历史 | 查看所有手动执行记录 | P1 |

#### 状态流转

```
待启动 (pending)
    ↓ 用户点击"启动"
运行中 (running) ←──────┐
    ↓ 完成              │
已完成 (completed)      │
    ↓ 失败              │
失败 (failed)           │
    ↓ 用户点击"停止"    │
已停止 (stopped) ───────┘
    ↓ 用户点击"重试"
运行中 (running)
```

---

### 2.5 日志系统增强（Logging System）

**目标**：完整的日志记录、查询、分析能力

#### 现状问题

1. `crawl_logs` 表已存在，但：
   - 后端 API 未实现查询接口
   - 前端页面未实现日志查看
   - 日志写入逻辑未集成到爬虫基类

#### 增强需求

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 日志写入 | 爬虫执行时自动写入日志 | P0 |
| 日志查询 | 按任务/源/级别/时间筛选 | P0 |
| 实时日志 | WebSocket 实时推送 | P0 |
| 日志分析 | 错误分类统计、趋势分析 | P1 |
| 日志导出 | 支持导出为 CSV/JSON | P2 |

#### 日志级别定义

```python
class CrawlLogLevel:
    DEBUG = "debug"      # 调试信息（开发用）
    INFO = "info"        # 一般信息（请求开始/完成）
    SUCCESS = "success"  # 成功信息（数据提取成功）
    WARNING = "warning"  # 警告信息（重试、降级）
    ERROR = "error"      # 错误信息（请求失败、解析失败）
    CRITICAL = "critical" # 严重错误（源不可用、系统异常）
```

#### 日志内容规范

```json
{
  "timestamp": "2026-06-05T10:30:00Z",
  "task_id": "task_001",
  "source_id": "wikipedia_zh",
  "level": "info",
  "stage": "fetch",  // fetch/parse/validate/store
  "url": "https://zh.wikipedia.org/wiki/周杰伦",
  "resource_name": "周杰伦",
  "resource_type": "person",
  "status": "success",
  "duration_ms": 1250,
  "message": "Successfully fetched and parsed person data",
  "details": {
    "fields_extracted": ["name", "birth_date", "nationality"],
    "fields_missing": ["height", "biography"],
    "completeness": 0.6
  }
}
```

---

### 2.6 模拟数据问题分析

#### 现状

当前后端 API (`backend/app/api/admin.py`) 返回的全是模拟数据：
- `dashboard/stats` - 硬编码数字
- `persons` - 固定3条mock数据
- `crawler/tasks` - 固定2条mock任务
- `conversations` - 固定2条mock对话
- `monitor/*` - 硬编码监控数据

#### 根因

1. **数据库已就绪** - MySQL 表结构已创建
2. **ORM 模型已就绪** - SQLAlchemy 模型已定义
3. **连接层已就绪** - `mysql.py` 客户端可用
4. **但缺少**：
   - Service 层（业务逻辑）
   - API 实现（从 mock 切换到真实数据）
   - 前端 API 对接

#### 解决方案

**Phase 1**：实现基础 CRUD（替换 mock 数据）
- 实现 `CrawlerService` 类
- 实现 `CrawlerSourceService` 类
- 实现 `CrawlerScheduleService` 类
- 更新 admin API 路由

**Phase 2**：实现统计报表
- 实现统计聚合查询
- 实现图表数据接口

**Phase 3**：实现实时功能
- WebSocket 实时日志
- 任务状态实时推送

---

## 3. 前端页面规划

### 3.1 页面结构

```
爬虫管理（/admin/crawler）
├── 📊 统计概览（/admin/crawler/dashboard）
│   ├── 核心指标卡片
│   ├── 各源效果对比
│   ├── 趋势图表
│   └── 效率分析
│
├── 🕷️ 爬取源管理（/admin/crawler/sources）
│   ├── 源列表
│   ├── 源详情/配置
│   ├── 源健康状态
│   └── 源统计
│
├── 📋 任务管理（/admin/crawler/tasks）
│   ├── 任务列表
│   ├── 新建任务（手动执行）
│   ├── 任务详情
│   └── 实时日志
│
├── ⏰ 定时任务（/admin/crawler/schedules）
│   ├── 定时任务列表
│   ├── 新建/编辑定时任务
│   ├── 执行历史
│   └── Cron可视化配置
│
└── 📝 日志中心（/admin/crawler/logs）
    ├── 日志列表（筛选/搜索）
    ├── 日志详情
    ├── 实时日志流
    └── 错误分析
```

### 3.2 关键页面设计

#### 爬取源管理页

```
┌─────────────────────────────────────────────────────────────┐
│  爬取源管理                                    [+ 添加源]   │
├─────────────────────────────────────────────────────────────┤
│  筛选：[全部类型 ▼] [全部状态 ▼]        搜索：[________]   │
├─────────────────────────────────────────────────────────────┤
│  名称        类型      状态    成功率   响应时间   今日请求   │
│  ─────────────────────────────────────────────────────────  │
│  维基百科    百科      🟢健康   90%     1.2s      500       │
│  豆瓣电影    社交      🟢健康   70%     2.5s      300       │
│  百度百科    百科      🟡降级   60%     5.0s      200       │
│  ...                                                      │
├─────────────────────────────────────────────────────────────┤
│  操作：[查看详情] [编辑配置] [禁用] [删除]                  │
└─────────────────────────────────────────────────────────────┘
```

#### 新建定时任务页

```
┌─────────────────────────────────────────────────────────────┐
│  新建定时任务                                               │
├─────────────────────────────────────────────────────────────┤
│  任务名称：[________________] *                             │
│  任务类型：[全量更新 ▼]                                     │
│  选择源：  [☑] 维基百科  [☑] 豆瓣电影  [☐] 百度百科        │
│  执行周期：                                                │
│    [○] 每天 [○] 每周 [○] 每月 [●] Cron表达式              │
│    Cron：[0 2 * * *]  ← 每天凌晨2点                        │
│    [可视化配置 ▼]                                          │
│  高级选项：                                                │
│    超时时间：[3600] 秒                                     │
│    失败重试：[3] 次                                        │
│    并发限制：[1] 个                                        │
│  通知设置：                                                │
│    [☑] 失败时通知邮箱：[admin@example.com]                 │
├─────────────────────────────────────────────────────────────┤
│                                    [取消]  [保存并启用]     │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 后端 API 规划

### 4.1 API 列表

#### 爬取源管理 API

| 方法 | 路径 | 说明 | 优先级 |
|------|------|------|--------|
| GET | `/admin/crawler/sources` | 爬取源列表 | P0 |
| POST | `/admin/crawler/sources` | 创建爬取源 | P0 |
| GET | `/admin/crawler/sources/:id` | 爬取源详情 | P0 |
| PUT | `/admin/crawler/sources/:id` | 更新爬取源 | P0 |
| DELETE | `/admin/crawler/sources/:id` | 删除爬取源 | P1 |
| POST | `/admin/crawler/sources/:id/health` | 健康检查 | P1 |
| GET | `/admin/crawler/sources/:id/stats` | 源统计 | P0 |

#### 统计报表 API

| 方法 | 路径 | 说明 | 优先级 |
|------|------|------|--------|
| GET | `/admin/crawler/stats/overview` | 总体概览 | P0 |
| GET | `/admin/crawler/stats/sources` | 各源统计 | P0 |
| GET | `/admin/crawler/stats/trend` | 趋势数据 | P0 |
| GET | `/admin/crawler/stats/efficiency` | 效率分析 | P1 |

#### 定时任务 API

| 方法 | 路径 | 说明 | 优先级 |
|------|------|------|--------|
| GET | `/admin/crawler/schedules` | 定时任务列表 | P0 |
| POST | `/admin/crawler/schedules` | 创建定时任务 | P0 |
| GET | `/admin/crawler/schedules/:id` | 定时任务详情 | P0 |
| PUT | `/admin/crawler/schedules/:id` | 更新定时任务 | P0 |
| DELETE | `/admin/crawler/schedules/:id` | 删除定时任务 | P1 |
| POST | `/admin/crawler/schedules/:id/toggle` | 启用/禁用 | P0 |
| GET | `/admin/crawler/schedules/:id/runs` | 执行历史 | P0 |

#### 任务执行 API

| 方法 | 路径 | 说明 | 优先级 |
|------|------|------|--------|
| POST | `/admin/crawler/tasks` | 创建并启动任务 | P0 |
| POST | `/admin/crawler/tasks/:id/stop` | 停止任务 | P0 |
| GET | `/admin/crawler/tasks/:id/status` | 任务状态 | P0 |
| GET | `/admin/crawler/tasks/:id/logs` | 任务日志 | P0 |
| GET | `/admin/crawler/tasks/:id/progress` | 任务进度 | P0 |

#### 日志 API

| 方法 | 路径 | 说明 | 优先级 |
|------|------|------|--------|
| GET | `/admin/crawler/logs` | 日志列表 | P0 |
| GET | `/admin/crawler/logs/stream` | 实时日志流 (WebSocket) | P0 |
| GET | `/admin/crawler/logs/analysis` | 日志分析 | P1 |

---

## 5. 数据库变更计划

### 5.1 新增表

1. `crawl_sources` - 爬取源配置表
2. `crawl_source_stats` - 爬取源统计表（日汇总）
3. `crawl_schedules` - 定时任务配置表
4. `crawl_schedule_runs` - 定时任务执行历史表

### 5.2 修改表

1. `crawl_tasks` - 增加 source_id 字段，关联爬取源
2. `crawl_logs` - 增加 source_id 字段，增加 details JSON 字段

### 5.3 迁移脚本

```sql
-- 迁移脚本：v2.0_crawler_enhancement.sql
-- 执行顺序：
-- 1. 创建新表
-- 2. 修改现有表
-- 3. 创建视图（方便查询）
-- 4. 初始化数据（默认爬取源）
```

---

## 6. 开发计划

### 6.1 阶段划分

| 阶段 | 时间 | 内容 | 产出 |
|------|------|------|------|
| **Phase 1** | Week 1 Day 1-3 | 数据库变更 + 基础 API | 表结构、CRUD API |
| **Phase 2** | Week 1 Day 4-5 | 统计报表 + 日志系统 | 统计接口、日志查询 |
| **Phase 3** | Week 2 Day 1-3 | 定时任务 + 手动执行 | 定时调度、任务控制 |
| **Phase 4** | Week 2 Day 4-5 | 前端页面开发 | 管理界面 |
| **Phase 5** | Week 2 Day 6-7 | 联调 + 测试 | 完整功能可用 |

### 6.2 任务分配

| 角色 | 任务 | 工期 |
|------|------|------|
| Backend | 数据库迁移脚本 | Day 1 |
| Backend | 爬取源管理 API | Day 1-2 |
| Backend | 统计报表 API | Day 2-3 |
| Backend | 日志系统 API | Day 3-4 |
| Backend | 定时任务调度 | Day 4-5 |
| Backend | 手动执行控制 | Day 5-6 |
| Frontend | 爬取源管理页面 | Day 4-5 |
| Frontend | 统计报表页面 | Day 5-6 |
| Frontend | 定时任务页面 | Day 6-7 |
| Frontend | 日志中心页面 | Day 7-8 |
| Data | 爬虫基类集成日志 | Day 1-2 |
| Data | 默认爬取源配置 | Day 2-3 |
| PM | 验收测试 | Day 9-10 |

---

## 7. 验收标准

### 7.1 功能验收

| 检查项 | 标准 | 优先级 |
|--------|------|--------|
| 爬取源 CRUD | 可添加、编辑、禁用、删除源 | P0 |
| 源统计 | 各源请求数/成功数/成功率准确统计 | P0 |
| 定时任务 | 可配置Cron，自动执行 | P0 |
| 手动执行 | 可手动启动任务，实时查看进度 | P0 |
| 实时日志 | WebSocket推送，延迟<5s | P0 |
| 效率分析 | 可识别低效源，给出优化建议 | P1 |
| 数据真实性 | 所有数据来自真实数据库，无mock | P0 |

### 7.2 性能验收

| 指标 | 标准 |
|------|------|
| 列表查询 | < 1s（1000条数据） |
| 统计聚合 | < 2s（30天数据） |
| 日志查询 | < 1s（带筛选） |
| 实时推送 | < 5s延迟 |

---

## 8. 风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 定时任务调度复杂 | 高 | 使用成熟库 APScheduler，避免自研 |
| WebSocket 并发 | 中 | 使用 Redis 作为消息代理 |
| 统计查询慢 | 中 | 预计算日汇总，避免实时聚合 |
| 爬虫基类改动大 | 中 | 先实现日志接口，逐步集成 |

---

## 9. 附录

### 9.1 相关文档

- [数据模型文档](../tech/data-model.md)
- [后台管理PRD](./PRD.md)
- [后端开发路线](./backend-roadmap.md)
- [前端开发路线](./frontend-roadmap.md)

### 9.2 术语表

| 术语 | 说明 |
|------|------|
| 爬取源 | 数据来源网站/平台 |
| Cron | 定时任务表达式 |
| WebSocket | 全双工通信协议，用于实时推送 |
| APScheduler | Python 定时任务调度库 |

---

**文档状态**：✅ 已完成  
**下次更新**：Phase 1 完成后（根据实际进度调整）
