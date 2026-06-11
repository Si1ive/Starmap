# 408考研智能学习平台 - 变更日志

## 格式说明

每条记录包含：
- **日期**：变更时间
- **类型**：feat/fix/docs/refactor/test
- **影响**：影响范围
- **详细描述**：具体变更内容

---

## 2026-06-08

### [docs] 多模态检索设计补充知识点关系图基线
- **类型**：docs
- **影响**：`README.md`, `docs/tech/`, `docs/api/`, `docs/roadmap/`
- **描述**：
  - 明确知识点关系图不是“学习路径功能”的附属物，而是系统构建阶段必须沉淀的基础能力
  - 新增 `knowledge_relations` 设计，用于承载先修、对比、易混、相似等关系
  - 检索链路补充 relation-aware retrieval，知识点检索和问答需返回易混点、前置点、对比点
  - 后端交付计划增加关系构建、关系增强召回、关系调试与验收标准

### [docs] 多模态检索设计补充双层章节体系
- **类型**：docs
- **影响**：`README.md`, `docs/tech/`, `docs/api/`, `docs/roadmap/`
- **描述**：
  - 明确“标准章节体系”和“文档原生标题树”必须分层建模，不能继续只依赖单一 `chapter_id`
  - 新增 `canonical_chapters`、`document_sections`、`document_section_mappings`
  - 新增 `knowledge_point_chapter_links`、`question_chapter_links`，支撑跨章节归属与扩展检索
  - 检索契约补充 `chapter_match_mode`，支持严格章节匹配与扩展章节匹配

### [docs] 新增多模态执行清单并细化前后端作业项
- **类型**：docs
- **影响**：`README.md`, `docs/roadmap/`
- **描述**：
  - 新增 `docs/roadmap/multimodal-execution-checklist.md`，将方案细化为可直接开工的执行清单
  - 前端交付单补充 section 映射审核页、关系审核页、关系增强问答展示
  - 数据交付单补充标准章节体系、标题映射标注集、知识点关系评测集

### [docs] 执行清单继续细化到接口级与审核口径
- **类型**：docs
- **影响**：`docs/roadmap/`
- **描述**：
  - 在执行清单中补充接口级开发清单，按端点列出输入、输出、依赖和验收
  - 补充统一审核状态机，覆盖 section 映射、实体、关系和回写规则
  - 补充解析、映射、关系、检索、问答的统一验收口径

### [docs] 项目定位转型 - 从艺人知识图谱到408考研学习平台
- **类型**：refactor
- **影响**：全项目
- **描述**：
  - 项目定位从"艺人知识图谱"转为"408考研智能学习平台"
  - 原因：艺人信息缺乏壁垒，通用大模型即可查询；408考研有明确受众和真实痛点
  - 差异化：结构化知识库 + 难度/考频标签 + RAG精准问答

### [backend] 新增408数据模型
- **类型**：feat
- **影响**：backend/app/models/mysql_models.py
- **描述**：
  - 新增 Subject（学科）、Chapter（章节）、KnowledgePoint（知识点）、Question（题目）、UserQuestionRecord（做题记录）模型
  - 创建 init_408_tables.sql 建表脚本 + 种子数据（4门学科 + 26个章节）

### [backend] ChromaDB知识点向量支持
- **类型**：feat
- **影响**：backend/app/db/chroma.py
- **描述**：
  - 新增 knowledge_points collection
  - 新增 add_knowledge_point() 和 search_knowledge_points() 方法

### [backend] PDF解析爬虫
- **类型**：feat
- **影响**：backend/scrapy_service/
- **描述**：
  - 新增 KnowledgePointItem 和 QuestionItem
  - 新增 knowledge_spider.py - 解析PDF为结构化知识点
  - 更新 storage.py 支持新Item类型存储

### [backend] RAG智能问答实现
- **类型**：feat
- **影响**：backend/app/services/chat_service.py
- **描述**：
  - 实现完整RAG流程：ChromaDB检索 → 构建prompt → OpenAI生成回答
  - 替换原有的echo模式

### [backend] 知识点/题目管理API
- **类型**：feat
- **影响**：backend/app/api/admin.py
- **描述**：
  - 新增 /admin/subjects - 学科列表
  - 新增 /admin/subjects/{id}/chapters - 章节列表
  - 新增 /admin/knowledge/points - 知识点CRUD
  - 新增 /admin/questions - 题目CRUD
  - 更新 /admin/dashboard/stats - 真实统计数据

### [docs] 文档全面更新
- **类型**：docs
- **影响**：README.md, docs/
- **描述**：
  - 重写 README.md 为408考研平台文档
  - 更新 data-model.md - 新数据模型
  - 更新 architecture.md - 新架构设计
  - 更新 PRD.md - 新产品需求
  - 更新 project-board.md - 新项目看板

---

## 2026-06-07

### [会话-Frontend] 修复数据源管理入口不可见
- **类型**：fix
- **影响**：frontend-admin/
- **描述**：
  - 路由守卫和侧边栏统一复用权限 Hook，超级管理员不再被旧权限数组拦截
  - 侧边栏权限过滤改为不可变处理，避免首次渲染后永久移除数据源菜单
  - 任务创建弹窗在暂无数据源时提供“管理数据源”跳转入口

### [会话-Backend/Frontend] 完善数据源管理能力
- **类型**：feat
- **影响**：backend/app/api/, backend/app/services/, frontend-admin/, docs/api/
- **描述**：
  - 修复管理员权限缺少 `crawler:manage` 导致数据源入口不可见的问题
  - 数据源列表补齐配置、并发、更新时间、健康检查时间等管理字段
  - 新增默认数据源初始化接口，管理端可一键恢复默认源
  - 数据源管理页补齐状态/类型筛选、详情抽屉、启停、健康检查、废弃和 JSON 配置编辑
  - 创建数据源时校验编码唯一性，避免任务源映射冲突

### [会话-Backend/Data/Frontend] 修复爬虫核心数据源输入链路
- **类型**：fix
- **影响**：backend/app/services/, backend/app/api/, backend/scripts/, frontend-admin/, docs/api/
- **描述**：
  - 数据源列表和任务创建时自动初始化默认源，避免新环境 `crawl_sources` 为空导致无法创建有效爬虫任务
  - 任务创建强制校验有效数据源和关键词，并将 `source_ids`、`config.source`、`config.keywords` 统一规范化
  - 管理端新建任务表单改为显式选择数据源 ID，提交时映射为 Scrapy 支持的源编码
  - 初始化 SQL 补齐 `crawl_sources`、`crawl_source_stats` 和默认源数据
  - 前端错误提示显示 FastAPI `detail`，便于定位无源、无关键词等创建失败原因

## 2026-06-06

### [会话-Backend/Data/Frontend] 完成爬虫稳定性运营能力
- **类型**：feat
- **影响**：backend/app/services/, backend/app/api/, backend/scrapy_service/, frontend-admin/, docs/api/
- **描述**：
  - 新增日志导出接口与管理端 CSV/JSON 导出按钮，复用日志页筛选条件
  - 新增运营优化建议接口和统计页建议面板，覆盖健康、成功率、限流、超时、延迟、完整度和错误类型
  - 健康检查写入 `crawl_logs`，并返回耗时、HTTP 状态、错误类型和错误详情
  - Scrapy 落库计算人物数据质量评分，并汇总写入 `crawl_source_stats.avg_completeness`
  - Scrapy 运行日志补齐 `source_id` 和稳定错误分类，便于前端筛选和运营追踪

### [会话-Backend/Frontend] 强化定时任务执行闭环
- **类型**：feat
- **影响**：backend/app/tasks/, backend/app/services/, frontend-admin/
- **描述**：
  - 调度触发后先记录 `crawl_schedule_runs(status=running)`，并关联实际创建的 `crawl_tasks`
  - 调度器轮询爬虫任务终态，按 `completed/failed/stopped/timeout` 更新执行历史和聚合计数
  - 定时任务表单补齐真实数据源、爬虫类型、关键词和运行配置，历史弹窗自动刷新
  - API 文档明确执行历史必须以实际任务终态为准，禁止“发布即成功”

### [会话-Backend/Frontend] 完善爬虫任务管理能力
- **类型**：feat
- **影响**：backend/app/api/, backend/app/services/, frontend-admin/
- **描述**：
  - 新增 `DELETE /crawler/tasks/{task_id}`，非运行中任务可删除并清理关联日志
  - 管理端任务列表删除按钮接入真实 API，运行中任务列表自动轮询刷新
  - 新建任务数据源下拉改为读取真实爬取源，避免前端固定源编码和后端源 ID 脱节
  - API 文档补齐任务删除接口和任务管理对齐状态

### [会话-Backend/Frontend] 实现管理端实时日志渲染
- **类型**：feat
- **影响**：backend/app/api/, backend/app/core/, frontend-admin/
- **描述**：
  - 管理端日志页自动连接同源 WebSocket，实时日志进入表格顶部并支持本地关键词过滤
  - WebSocket 动态筛选与页面 `task_id`、`source_id`、`level` 筛选保持同步
  - 后端 WebSocket 管理器提供公开筛选更新方法，进度广播补齐 `source_id`
  - Vite 开发代理开启 WebSocket 转发，避免前端硬编码 `localhost:8000`

### [会话-Backend/Data/Frontend] 补齐爬虫统计写入闭环
- **类型**：feat
- **影响**：backend/app/services/, backend/scrapy_service/, frontend-admin/, docs/api/
- **描述**：
  - FastAPI 发布 Scrapy 任务时透传 `source_id` 并按爬取源编码对齐 Scrapy source
  - Scrapy MySQL Pipeline 在任务结束时 upsert `crawl_source_stats` 并累计更新 `crawl_sources`
  - 管理端统计页改为消费真实统计数组，移除硬编码趋势、数据源和统计卡片 mock
  - API 文档补齐统计概览、源对比字段和统计写入闭环状态
- **注意**：新环境默认源增加 `baidu_baike`，避免 `baike` 任务统计无法归因

### [会话-Backend/Data] 完善 Scrapy 爬虫任务闭环
- **类型**：feat
- **影响**：backend/app/services/, backend/scrapy_service/, docker-compose.yml, frontend-admin/
- **描述**：
  - FastAPI 启动 Scrapy Redis 事件监听器，统一持久化进度和日志并广播到管理端 WebSocket
  - Scrapy Service 改为 Redis 阻塞消费队列，每个任务独立子进程执行，避免空队列退出和 Twisted reactor 重启问题
  - Scrapy MySQL 落库字段对齐当前 works、person_relations 表结构，避免写入不存在列
  - 管理端任务表统一读取 task_type，Docker Compose 增加 scrapy-service 消费服务
- **注意**：backend/scrapy_service/venv 不应提交，提交时需依赖 .gitignore 排除虚拟环境

### [会话-PM] 制定爬虫优先交付基线
- **类型**：docs
- **影响**：docs/roadmap/, docs/api/, docs/tech/, docs/team/
- **描述**：
  - 新增 `docs/roadmap/crawler-first-delivery-plan.md`
  - 补齐 `docs/api/README.md` 作为前后端和数据库字段契约
  - 在架构文档中明确 FastAPI + Redis + Scrapy Service 的爬虫目标链路
  - 更新工程师任务分配文档，要求所有角色以爬虫契约为准
  - 新增爬虫优先交付架构决策记录
- **注意**：@All 爬虫接口字段统一使用 `task_type`、`failed_count`、`snake_case`；任何字段变更必须同步更新 API 文档和前端类型

### [会话-Backend] 对齐爬虫接口与数据字段
- **类型**：fix
- **影响**：backend/, frontend-admin/, docs/api/
- **描述**：
  - 后端爬虫任务响应统一使用 `task_type` 和 `failed_count`
  - `CrawlTask` 模型和初始化/迁移脚本补齐 `health_check`、`cleanup`、`total_requests`、`error_message`
  - 修复源统计 `failed_failed_requests` 拼写错误
  - 管理端 `CrawlerTask` 类型和任务列表字段同步更新
  - 管理端成功响应自动携带 `request_id`
- **注意**：@Frontend 请停止使用旧字段 `type` 和 `fail_count`

## 2026-06-05

### [会话-PM] 新增团队协作规范
- **类型**：docs
- **影响**：docs/team/
- **描述**：
  - 创建 `docs/team/collaboration-rules.md`
  - 定义"发现即停止"原则
  - 规范数据库变更流程
  - 添加检查清单
- **注意**：@All 请阅读并遵守协作规范

### [会话-Data] 爬虫管理增强模块
- **类型**：feat
- **影响**：backend/ (数据库 + API)
- **描述**：
  - 新增4个表：crawl_sources, crawl_source_stats, crawl_schedules, crawl_schedule_runs
  - 修改现有表结构
  - 创建SQL迁移脚本
  - 实现4个服务层：CrawlerSourceService, CrawlerStatsService, CrawlerScheduleService, CrawlerLogService
  - 扩展18个管理API端点
  - 集成BaseCrawler自动日志写入
  - 添加WebSocket实时日志流功能
- **注意**：@Backend 请确认API端点与前端对接需求

### [会话-Backend] 修复演示数据导入脚本
- **类型**：fix
- **影响**：scripts/
- **描述**：
  - 适配Podman容器运行时
  - 修复MySQL数据导入时字段名不匹配问题
  - 验证搜索API返回真实数据
- **注意**：@All 现在使用Podman替代Docker

### [会话-PM] 工程师任务分配与开发路线
- **类型**：docs
- **影响**：docs/roadmap/
- **描述**：
  - 制定Sprint 3开发计划（2周）
  - 分配Backend/Frontend/Data角色任务
  - 更新项目看板

### [会话-PM] 爬虫管理模块增强计划
- **类型**：docs
- **影响**：docs/
- **描述**：
  - 编写爬虫管理增强需求文档
  - 定义前后端开发路线

### [会话-Backend] 更新API接口文档
- **类型**：docs
- **影响**：docs/api/
- **描述**：
  - 同步后端代码更新API文档
  - 补充爬虫管理相关接口
- **注意**：@Frontend 请按最新文档对接

### [会话-Backend] 迁移到Podman容器运行时
- **类型**：feat
- **影响**：docker-compose.yml, scripts/
- **描述**：
  - 将Docker Compose配置迁移到Podman
  - 更新启动脚本适配Podman
- **注意**：@All 需要安装Podman并了解基本命令

---

## 2026-06-04

### [会话-Backend] 引入MySQL作为主存储
- **类型**：feat
- **影响**：backend/, docker-compose.yml
- **描述**：
  - 添加MySQL数据库支持
  - 创建MySQL连接模块
  - 添加MySQL数据模型
  - 创建数据库初始化脚本
  - 创建同步到Neo4j脚本
  - 创建MySQL连接测试
  - 更新requirements.txt添加mysql-connector-python
- **注意**：@Backend 需要配置MySQL环境变量

### [会话-Frontend] 实现核心页面功能和组件
- **类型**：feat
- **影响**：frontend/
- **描述**：
  - 实现搜索页面（真实搜索功能，对接API）
  - 实现人物详情页（完整信息展示）
  - 实现对话页面（消息发送接收）
  - 实现关系图谱页（D3.js力导向图）
  - 实现领域浏览页（分类展示）
  - 添加错误边界组件
  - 添加加载组件
  - 添加人物卡片组件
  - 更新API客户端封装
  - 更新状态管理（Zustand）
- **注意**：@Backend 前端已对接API，请确保后端服务正常运行

### [会话-Backend] 完善人物数据模型和服务层
- **类型**：feat
- **影响**：backend/
- **描述**：
  - 扩展Person模型字段（name_en, gender, categories等）
  - 更新人物服务层支持新字段
  - 更新Neo4j连接封装
- **注意**：@Data 爬虫采集时需要填充新字段

### [会话-Backend] 添加后台管理端项目
- **类型**：feat
- **影响**：frontend-admin/
- **描述**：
  - 创建独立的后台管理前端项目
  - 配置React + Ant Design Pro框架
  - 添加用户管理、人物管理、数据管理页面
  - 添加启动文档
- **注意**：@Frontend 管理端使用独立项目，技术栈有差异

### [会话-Backend] 更新项目文档和架构设计
- **类型**：docs
- **影响**：docs/
- **描述**：
  - 大幅更新README，添加项目介绍和快速开始
  - 添加MySQL数据模型设计（表结构、索引、关系）
  - 更新系统架构文档，反映MySQL集成
  - 更新决策记录，添加技术选型决策
  - 更新项目看板，反映当前进度
  - 更新PRD和开发路线图
  - 添加MySQL集成总结文档

### [会话-Backend] 更新Docker Compose配置
- **类型**：chore
- **影响**：docker-compose.yml
- **描述**：
  - 添加MySQL服务配置
  - 更新后端服务依赖
  - 添加健康检查

---

## 2026-06-03

### [会话-PM] 初始化StarMap项目
- **类型**：feat
- **影响**：项目整体
- **描述**：
  - 创建项目目录结构
  - 初始化Git仓库
  - 创建基础文档体系

### [会话-Backend] 添加版本控制机制
- **类型**：feat
- **影响**：docs/tech/, scripts/
- **描述**：
  - 创建Git Flow分支策略文档
  - 创建版本号规范
  - 创建发布流程文档
  - 添加版本升级脚本
  - 添加发布脚本
  - 添加回滚脚本

### [会话-Backend] 添加Git提交规范
- **类型**：docs
- **影响**：docs/tech/
- **描述**：
  - 创建Git提交规范文档
  - 定义提交信息格式
  - 规范提交时机

### [会话-Backend] 添加开发日志规范
- **类型**：docs
- **影响**：docs/tech/, docs/logs/
- **描述**：
  - 创建开发日志规范文档
  - 创建各角色日志模板
  - 创建问题追踪表
  - 创建技术知识库

### [会话-Backend] 添加命令执行规范
- **类型**：docs
- **影响**：docs/tech/
- **描述**：
  - 创建命令执行透明度规范
  - 定义执行前/后模板
  - 规范命令分类说明

---

## 2024-01-15

### [会话-PM] 项目初始化
- **类型**：docs
- **影响**：项目文档
- **描述**：
  - 创建项目目录结构
  - 创建团队角色文档（PM/Backend/Frontend/Data）
  - 创建开发路线图
  - 创建技术文档

### [会话-Backend] 后端框架搭建
- **类型**：feat
- **影响**：backend/
- **描述**：
  - 初始化FastAPI项目
  - 配置Docker Compose
  - 添加基础API路由

### [会话-Frontend] 前端框架搭建
- **类型**：feat
- **影响**：frontend/
- **描述**：
  - 初始化React + Vite项目
  - 配置Ant Design
  - 添加基础路由

### [会话-Data] 数据模型设计
- **类型**：docs
- **影响**：docs/tech/data-model.md
- **描述**：
  - 设计Neo4j图模型
  - 定义实体关系

---

## 模板

```markdown
### [会话-角色] 变更标题
- **类型**：feat/fix/docs/refactor/test
- **影响**：影响范围
- **描述**：
  - 具体变更1
  - 具体变更2
- **注意**：需要其他会话注意的事项
```

---

## 使用说明

1. **每次变更后**，在顶部添加新记录
2. **切换会话前**，阅读最新变更记录
3. **遇到问题时**，查看相关变更记录
