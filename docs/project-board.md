# StarMap 项目看板

> 本看板由 PM 维护，每日更新
> 最后更新：2026-06-04

---

## 📋 Backlog（待办）

### Week 1-2 任务

| 任务ID | 任务描述 | 负责人 | 优先级 | 预计时间 |
|--------|----------|--------|--------|----------|
| B-001 | 实现Neo4j连接封装 (`app/db/neo4j.py`) | Backend | P0 | Day 5-6 |
| B-002 | 实现ChromaDB连接 (`app/db/chroma.py`) | Backend | P0 | Day 5-6 |
| B-003 | 实现Redis连接 (`app/db/redis.py`) | Backend | P0 | Day 5-6 |
| B-005 | 实现错误处理中间件 (`app/middleware/`) | Backend | P1 | Day 6 |
| B-006 | 配置日志系统 (`app/core/logging.py`) | Backend | P1 | Day 6 |
| B-007 | 编写单元测试框架 (`tests/`) | Backend | P1 | Day 7 |
| F-004 | 对接真实API（替换TODO） | Frontend | P0 | Week 2 |
| F-005 | 实现搜索结果列表组件 | Frontend | P1 | Week 2 |
| F-006 | 实现人物信息卡片组件 | Frontend | P1 | Week 2 |
| F-007 | 实现消息组件 | Frontend | P1 | Week 2 |
| D-005 | 爬取10个艺人测试数据 | Data | P0 | Day 6-7 |
| D-006 | 实现数据导入Neo4j脚本 | Data | P0 | Week 2 |
| PM-005 | Week 1验收报告 | PM | P0 | Day 7 |

### 后台管理端任务（Week 4-5）

| 任务ID | 任务描述 | 负责人 | 优先级 | 预计时间 |
|--------|----------|--------|--------|----------|
| ADMIN-FE-001 | 创建后台管理端项目 (`frontend-admin/`) | Frontend | P0 | Week 4 Day 1 |
| ADMIN-FE-002 | 实现登录认证 + 布局框架 | Frontend | P0 | Week 4 Day 2 |
| ADMIN-FE-003 | 实现数据看板页面 | Frontend | P0 | Week 4 Day 3 |
| ADMIN-FE-004 | 实现艺人管理（列表/详情/编辑） | Frontend | P0 | Week 4 Day 4-5 |
| ADMIN-FE-005 | 实现作品管理 + 爬虫管理 | Frontend | P0 | Week 4 Day 6 |
| ADMIN-FE-006 | 实现对话管理 + 系统监控 | Frontend | P1 | Week 4 Day 7 |
| ADMIN-FE-007 | 实现系统配置 + 用户管理 | Frontend | P1 | Week 5 Day 8-9 |
| ADMIN-FE-008 | 测试 + 优化 + 部署 | Frontend | P1 | Week 5 Day 10-13 |
| ADMIN-BE-001 | 实现JWT认证 + 权限控制 | Backend | P0 | Week 4 Day 1 |
| ADMIN-BE-002 | 实现看板统计API | Backend | P0 | Week 4 Day 2 |
| ADMIN-BE-003 | 实现艺人管理API（CRUD） | Backend | P0 | Week 4 Day 3 |
| ADMIN-BE-004 | 实现作品管理API | Backend | P1 | Week 4 Day 3 |
| ADMIN-BE-005 | 实现爬虫管理API（含WebSocket日志） | Backend | P0 | Week 4 Day 4 |
| ADMIN-BE-006 | 实现对话管理API | Backend | P1 | Week 4 Day 5 |
| ADMIN-BE-007 | 实现系统监控API | Backend | P1 | Week 4 Day 6 |
| ADMIN-BE-008 | 实现系统配置API | Backend | P1 | Week 4 Day 7 |
| ADMIN-BE-009 | 实现用户管理 + 审计日志 | Backend | P1 | Week 5 Day 8-9 |
| ADMIN-BE-010 | 限流 + 安全加固 + 测试 | Backend | P1 | Week 5 Day 10-13 |
| ADMIN-BE-011 | 实现爬取统计API（含数据源/失败分析/实时速率） | Backend | P0 | Week 4 Day 4 |
| ADMIN-FE-009 | 实现爬取统计页面（含图表/实时活动） | Frontend | P0 | Week 4 Day 6 |
| ADMIN-PM-001 | 后台管理端PRD | PM | P0 | Week 3（已完成） |
| ADMIN-PM-002 | 后台管理端验收 | PM | P0 | Week 5 Day 14 |

### MySQL 引入任务

| 任务ID | 任务描述 | 负责人 | 优先级 | 预计时间 |
|--------|----------|--------|--------|----------|
| MYSQL-001 | 更新 Docker Compose 添加 MySQL 服务 | Backend | P0 | 2026-06-03 |
| MYSQL-002 | 编写 MySQL 初始化脚本（表结构 + 默认数据） | Backend | P0 | 2026-06-03 |
| MYSQL-003 | 创建 MySQL 连接封装模块 (`app/db/mysql.py`) | Backend | P0 | 2026-06-03 |
| MYSQL-004 | 创建 SQLAlchemy ORM 模型 (`app/models/mysql_models.py`) | Backend | P0 | 2026-06-03 |
| MYSQL-005 | 更新配置文件添加 MySQL 环境变量 | Backend | P0 | 2026-06-03 |
| MYSQL-006 | 安装 MySQL 依赖（SQLAlchemy + asyncmy + aiomysql） | Backend | P0 | 2026-06-03 |
| MYSQL-007 | 编写 MySQL → Neo4j 同步脚本 | Data | P0 | 2026-06-03 |
| MYSQL-008 | 更新架构文档（添加 MySQL 组件） | PM | P1 | 2026-06-03 |
| MYSQL-009 | 更新数据模型文档（MySQL 表结构 + 同步机制） | PM | P1 | 2026-06-03 |
| MYSQL-010 | 更新决策记录（MySQL 引入决策） | PM | P1 | 2026-06-03 |

---

## 🔄 In Progress（进行中）

| 任务ID | 任务描述 | 负责人 | 开始时间 | 进度 |
|--------|----------|--------|----------|------|
| PM-001 | 搭建项目看板 | PM | 2026-06-03 | ✅ 已完成 |
| PM-002 | 验收环境搭建 | PM | 2026-06-03 | ✅ 已完成 |
| PM-003 | 验收数据采集框架 | PM | 2026-06-03 | ✅ 已完成 |
| PM-004 | 中期检查报告 | PM | 2026-06-03 | ✅ 已完成 |
| B-000 | 创建FastAPI项目结构 (`backend/`) | Backend | 2026-06-02 | ✅ 已完成 |
| B-000 | 配置Docker Compose | Backend | 2026-06-02 | ✅ 已完成 |
| F-000 | 创建React + Vite项目 (`frontend/`) | Frontend | 2026-06-02 | ✅ 已完成 |
| F-000 | 配置TypeScript + ESLint | Frontend | 2026-06-02 | ✅ 已完成 |
| F-001 | 配置UI组件库（Ant Design） | Frontend | 2026-06-02 | ✅ 已完成 |
| F-002 | 实现HTTP客户端封装 | Frontend | 2026-06-02 | ✅ 已完成 |
| F-003 | 实现路由框架 | Frontend | 2026-06-02 | ✅ 已完成 |
| F-004 | 实现布局组件 | Frontend | 2026-06-02 | ✅ 已完成 |
| F-005 | 配置状态管理（Zustand） | Frontend | 2026-06-02 | ✅ 已完成 |
| D-000 | 实现爬虫框架 (`crawler/base.py`) | Data | 2026-06-02 | ✅ 已完成 |
| D-000 | 实现维基百科页面下载 (`crawler/wikipedia.py`) | Data | 2026-06-02 | ✅ 已完成 |
| D-002 | 实现HTML解析器 (`crawler/parser.py`) | Data | 2026-06-02 | ✅ 已完成 |
| D-003 | 实现数据清洗管道 (`crawler/cleaner.py`) | Data | 2026-06-02 | ✅ 已完成 |
| D-004 | 实现数据验证规则 (`crawler/validator.py`) | Data | 2026-06-02 | ✅ 已完成 |

---

## 👀 Review（审核中）

| 任务ID | 任务描述 | 负责人 | 提交时间 | 审核人 |
|--------|----------|--------|----------|--------|
| - | - | - | - | - |

---

## ✅ Done（已完成）

| 任务ID | 任务描述 | 负责人 | 完成时间 | 备注 |
|--------|----------|--------|----------|------|
| INIT-001 | 项目初始化 - 创建目录结构 | PM | 2026-06-02 | 基础框架就绪 |
| INIT-002 | 编写团队角色文档 | PM | 2026-06-02 | 4个角色文档完成 |
| INIT-003 | 编写开发路线文档 | PM | 2026-06-02 | 4周路线图完成 |
| INIT-004 | 编写技术架构文档 | PM | 2026-06-02 | 技术选型确定 |
| INIT-005 | 编写接口文档 | PM | 2026-06-02 | API规范完成 |
| B-000 | 后端基础项目结构 | Backend | 2026-06-02 | FastAPI + API路由 |
| B-000 | Docker Compose配置 | Backend | 2026-06-02 | 5个服务定义完整 |
| F-000 | 前端基础项目结构 | Frontend | 2026-06-02 | React + Vite + TS |
| F-000 | 前端依赖配置 | Frontend | 2026-06-02 | package.json完整 |
| F-000 | 前端类型定义 | Frontend | 2026-06-02 | types + utils + store |
| F-000 | 前端页面实现 | Frontend | 2026-06-02 | 6个页面 + 布局组件 |
| F-000 | 前端API封装 | Frontend | 2026-06-02 | client + person + chat |
| D-000 | 爬虫基础框架 | Data | 2026-06-02 | BaseCrawler + 频率控制 |
| D-000 | 维基百科爬虫 | Data | 2026-06-02 | 页面爬取 + 搜索 + 分类 |
| D-000 | 数据模型定义 | Data | 2026-06-02 | Person + Work + Relation |
| D-000 | HTML解析器 | Data | 2026-06-02 | 信息框提取 + 人物解析 |
| D-000 | 数据清洗管道 | Data | 2026-06-02 | 清洗规则完整 |
| D-000 | 数据验证规则 | Data | 2026-06-02 | 验证器完整 |
| D-000 | 实体识别模块 | Data | 2026-06-02 | NER实现 |
| D-000 | 关系抽取模块 | Data | 2026-06-02 | 关系抽取实现 |
| D-000 | 实体链接模块 | Data | 2026-06-02 | 实体链接实现 |
| PM-001 | 搭建项目看板 | PM | 2026-06-03 | docs/project-board.md |
| PM-002 | 验收环境搭建 | PM | 2026-06-03 | Docker配置检查完成 |
| PM-003 | 验收数据采集框架 | PM | 2026-06-03 | 爬虫测试通过 |
| PM-004 | 中期检查报告 | PM | 2026-06-03 | docs/weekly-reports/week1-mid-check.md |
| PM-005 | Week 1周报 | PM | 2026-06-03 | docs/weekly-reports/week1-summary.md |

---

## 📊 本周进度概览

### Week 1: 基础设施搭建（2026-06-02 ~ 2026-06-08）

| 角色 | 总任务 | 已完成 | 进行中 | 待办 | 进度 | 状态 |
|------|--------|--------|--------|------|------|------|
| PM | 5 | 5 | 0 | 0 | 100% | 🟢 正常 |
| Backend | 7 | 4 | 0 | 3 | 57% | 🟢 正常 |
| Frontend | 7 | 7 | 0 | 0 | 100% | 🟢 超前 |
| Data | 7 | 6 | 0 | 1 | 86% | 🟢 正常 |
| **总计** | **26** | **22** | **0** | **4** | **85%** | 🟢 **正常** |

---

## 🚨 阻塞问题

| 问题ID | 问题描述 | 影响 | 负责人 | 状态 | 优先级 |
|--------|----------|------|--------|------|--------|
| BLOCK-001 | ~~Docker未安装（本地开发环境）~~ | ~~无法一键启动基础设施~~ | Backend/PM | ✅ 已解决 | P0 |
| BLOCK-002 | ~~后端Python依赖未安装~~ | ~~无法运行后端服务~~ | Backend | ✅ 已解决 | P1 |
| BLOCK-003 | 前端node_modules未安装 | 无法运行前端服务 | Frontend | 🟡 待处理 | P1 |
| BLOCK-004 | 维基百科搜索API 403 | 搜索功能受限 | Data | 🟡 已规避 | P2 |
| BLOCK-005 | ~~MySQL 服务未部署~~ | ~~无法测试数据库连接~~ | Backend | ✅ 已解决 | P1 |

---

## 📈 里程碑状态

### Milestone 1: 基础设施就绪（Week 1结束）

| 检查项 | 标准 | 状态 | 备注 |
|--------|------|------|------|
| Docker环境 | `docker-compose up -d` 一键启动 | ✅ 已满足 | Docker 29.4.0 已安装 |
| 后端服务 | `http://localhost:8000/health` 返回200 | ⏳ 待验证 | Python依赖已安装，需启动服务 |
| 前端服务 | `http://localhost:5173` 可访问 | ⏳ 待验证 | 需npm install后测试 |
| 数据库 | MySQL、Neo4j、Redis、ChromaDB正常运行 | ⚠️ 部分满足 | MySQL已运行，其他待启动 |
| 爬虫 | 能爬取并解析维基百科页面 | ✅ 已验证 | 成功爬取并解析周杰伦页面 |
| 测试数据 | Neo4j中有10个艺人数据 | ⏳ 待验证 | 依赖数据采集完成 |

**Milestone 1 完成度：3/6（50%）**

---

## 📝 变更记录

| 日期 | 变更内容 | 变更人 | 影响 |
|------|----------|--------|------|
| 2026-06-03 | 创建项目看板 | PM | 无 |
| 2026-06-03 | 更新阻塞问题：Docker未安装 | PM | 需协调本地开发方案 |
| 2026-06-03 | 完成中期检查报告 | PM | 识别Backend滞后风险 |
| 2026-06-03 | 完成Week 1周报 | PM | 记录本周进度和风险 |
| 2026-06-03 | 规划后台管理端 | PM | 新增PRD + 前后端开发路线 |
| 2026-06-03 | 更新项目看板 | PM | 添加后台管理端任务 |
| 2026-06-04 | 增强爬虫管理模块 | PM | 补充爬取统计报表功能（PRD+前后端路线+看板） |
| 2026-06-04 | 引入 MySQL 主存储 | PM | 更新架构文档、数据模型、Docker配置、决策记录 |
| 2026-06-04 | 创建 MySQL 连接模块 | Backend | 连接池 + ORM + 同步脚本 |
| 2026-06-04 | 启动 MySQL Docker 服务 | Backend | MySQL 8.0.46 运行正常 |
| 2026-06-04 | 初始化 MySQL 数据库 | Backend | 8张表 + 2视图 + 默认管理员 |
| 2026-06-04 | 验证 MySQL CRUD | Backend | 连接/创建/查询/更新/删除 全部通过 |
