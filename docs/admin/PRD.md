# 408考研智能学习平台 - 产品需求文档 (PRD)

> 版本：v2.1
> 日期：2026-06-12
> 状态：开发中

---

## 1. 产品概述

### 1.1 产品定位

408考研智能学习平台是一个基于 RAG 的结构化学习系统，专为计算机考研 408 学科打造。系统将教材 PDF 解析入库，按大纲结构化组织知识点，提供智能问答、刷题练习等功能。

### 1.2 目标用户

| 用户类型 | 需求 |
|---------|------|
| **考研学生** | 结构化学习408知识、刷题练习、智能问答 |
| **内容管理员** | 管理知识点、题目、校正数据质量 |

### 1.3 核心价值

- **结构化**：按408大纲组织，不是散乱的文章集合
- **精准**：带难度/考频标签，针对性复习
- **智能**：RAG问答，基于知识库的精准回答
- **高效**：PDF自动入库，减少人工整理工作

---

## 2. 功能模块

### 2.1 功能矩阵

| 模块 | 功能 | 说明 |
|------|------|------|
| **数据看板** | 核心指标概览 | 学科数、知识点数、题目数、问答数 |
| | 图表展示 | 学科分布、难度分布、题型分布 |
| **学科管理** | 学科列表 | 408四门学科 |
| | 章节管理 | 每门学科的章节树 |
| **知识点管理** | 知识点列表 | 分页、按学科/章节/难度筛选 |
| | 知识点详情 | 查看完整内容、标签、关联 |
| | 知识点编辑 | 校正LLM生成的内容 |
| | 语料入库联动 | 从语料解析结果进入知识点抽取 |
| **题目管理** | 题目列表 | 分页、按学科/题型/难度筛选 |
| | 题目详情 | 查看题目、选项、答案、解析 |
| | 题目编辑 | 校正题目内容 |
| **智能问答** | RAG问答 | 基于知识库的智能回答 |
| | 对话历史 | 查看历史问答记录 |
| | 来源引用 | 显示回答的知识点来源 |
| **系统监控** | 服务状态 | MySQL/Redis/Qdrant |
| | 爬虫状态 | 任务进度、日志 |
| **系统配置** | 用户管理 | 管理员账号 |
| | LLM配置 | OpenAI模型参数 |
| | MinerU解析配置 | 本地/远程部署目标、超时、窗口与探活 |

---

## 3. 模块详细设计

### 3.1 数据看板（Dashboard）

**页面**：`/admin/dashboard`

**展示内容**：

| 指标 | 数据源 | 说明 |
|------|--------|------|
| 学科数量 | MySQL subjects | 408四门学科 |
| 章节数量 | MySQL chapters | 所有章节总数 |
| 知识点数量 | MySQL knowledge_points | 已入库知识点总数 |
| 题目数量 | MySQL questions | 已入库题目总数 |
| 学科分布 | MySQL 聚合 | 各学科知识点数量饼图 |
| 难度分布 | MySQL 聚合 | 简单/中等/困难分布柱状图 |
| 题型分布 | MySQL 聚合 | 选择/填空/简答等分布 |

### 3.2 知识点管理

**列表页**：`/admin/knowledge`

**功能**：
- 按学科、章节、难度筛选
- 关键词搜索标题
- 分页展示
- 批量操作（删除、修改状态）

**详情页**：`/admin/knowledge/:id`

**功能**：
- 查看完整知识点内容（Markdown渲染）
- 查看标签、要点、关联知识点
- 编辑内容、调整难度/考频

### 3.5 语料与解析

**页面**：`/admin/ingest`、`/admin/corpus/*`

**功能**：
- 扫描并注册 `download/` 目录中的文件
- 触发文档解析、原生标题抽取、章节映射、实体抽取
- 查看 `documents/pages/blocks/assets` 解析产物
- 从系统设置读取 MinerU 运行状态和部署位置

### 3.6 系统配置

**页面**：`/admin/settings`

**功能**：
- 维护 LLM / 搜索 / 爬虫 / 系统参数
- 配置 MinerU 的本地/远程部署位置、服务地址、超时和处理窗口
- 查看 MinerU 运行状态与配置变更审计历史

### 3.3 题目管理

**列表页**：`/admin/questions`

**功能**：
- 按学科、题型、难度筛选
- 分页展示
- 查看答案和解析

**详情页**：`/admin/questions/:id`

**功能**：
- 查看题目内容、选项
- 查看标准答案和解析
- 编辑内容

### 3.4 智能问答

**页面**：`/admin/conversations`

**功能**：
- 对话式界面
- 显示回答 + 来源引用
- 会话历史

---

## 4. 数据模型

详见 [docs/tech/data-model.md](../tech/data-model.md)

### 核心实体

| 实体 | 说明 |
|------|------|
| Subject | 学科（数据结构/计组/操作系统/计网） |
| Chapter | 章节 |
| KnowledgePoint | 知识点 |
| Question | 题目 |
| UserQuestionRecord | 做题记录 |

---

## 5. API 接口

详见 [docs/api/README.md](../api/README.md)

### 主要接口

| 接口 | 方法 | 说明 |
|------|------|------|
| /admin/subjects | GET | 学科列表 |
| /admin/subjects/{id}/chapters | GET | 章节列表 |
| /admin/knowledge/points | GET | 知识点列表 |
| /admin/knowledge/points/{id} | GET/PUT | 知识点详情/编辑 |
| /admin/questions | GET | 题目列表 |
| /admin/questions/{id} | GET/PUT | 题目详情/编辑 |
| /admin/dashboard/stats | GET | 看板统计 |
| /admin/dashboard/charts | GET | 图表数据 |
| /admin/corpus/files | GET | 语料文件列表 |
| /admin/corpus/files/{id}/parse | POST | 触发文档解析 |
| /admin/settings | GET/PUT | 系统配置 |
| /admin/settings/pdf-parser/history | GET | MinerU运行配置变更历史 |
| /chat | POST | RAG问答 |

---

## 6. 技术架构

详见 [docs/tech/architecture.md](../tech/architecture.md)

---

## 7. 开发计划

### Phase 1: 数据模型（已完成）
- MySQL表结构设计
- 种子数据（4门学科 + 26个章节）

### Phase 2: 爬虫改造（已完成）
- PDF解析 spider
- 知识点/题目 Item
- Storage pipeline

### Phase 3: RAG问答（已完成）
- Qdrant 向量检索
- OpenAI API集成
- ChatService实现

### Phase 4: 管理端完善（进行中）
- Dashboard改造
- 语料入库与解析页面
- 系统设置与 MinerU 解析服务配置
- 知识点/题目/审核页面

### Phase 5: 清理收敛
- 清理旧代码与旧文档
- 数据库迁移与端到端验证
- 设置与语料链路联调
