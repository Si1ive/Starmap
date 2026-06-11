# 408考研智能学习平台 - 项目看板

> 最后更新：2026-06-08

---

## 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 数据模型设计 | ✅ | Subject/Chapter/KnowledgePoint/Question/UserQuestionRecord |
| MySQL建表脚本 | ✅ | init_408_tables.sql + 种子数据 |
| Qdrant集成 | ✅ | knowledge/question segments collection + 搜索方法 |
| KnowledgePointItem/QuestionItem | ✅ | Scrapy Item定义 |
| KnowledgeSpider | ✅ | PDF解析spider |
| Storage Pipeline | ✅ | 知识点/题目存储路由 |
| RAG ChatService | ✅ | Qdrant检索 + OpenAI生成 |
| 知识点管理API | ✅ | CRUD接口 |
| 题目管理API | ✅ | CRUD接口 |
| Dashboard API | ✅ | 真实统计数据 |
| README更新 | ✅ | 408平台文档 |
| 技术文档更新 | ✅ | data-model.md, architecture.md |
| PRD更新 | ✅ | 产品需求文档 |

---

## 进行中

| 任务 | 状态 | 说明 |
|------|------|------|
| 前端改造 | 🔄 | Dashboard/知识点/题目页面 |

---

## 待办

### 前端改造

| 任务 | 优先级 | 说明 |
|------|--------|------|
| Dashboard页面改造 | P0 | 展示学科/知识点/题目统计 |
| 学科管理页面 | P0 | 学科列表 + 章节树 |
| 知识点列表页面 | P0 | 分页、筛选、搜索 |
| 知识点详情页面 | P0 | 查看内容、编辑 |
| 题目列表页面 | P0 | 分页、筛选 |
| 题目详情页面 | P0 | 查看答案、编辑 |
| 对话页面适配 | P1 | RAG问答界面 |
| 路由更新 | P0 | 更新路由配置 |

### 数据入库

| 任务 | 优先级 | 说明 |
|------|--------|------|
| 准备PDF文件 | P0 | 王道/天勤教材PDF |
| 执行PDF入库 | P0 | 运行knowledge spider |
| 数据质量校正 | P1 | 校正LLM生成的元数据 |

### 部署

| 任务 | 优先级 | 说明 |
|------|--------|------|
| 清理旧代码 | P2 | 移除Person/Work相关代码 |
| 数据库迁移 | P1 | Alembic迁移脚本 |
| 端到端测试 | P1 | 完整流程验证 |

---

## 决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| 2026-06-08 | 项目定位转为"408考研学习平台" | 408考研有明确受众和痛点 |
| 2026-06-08 | 采用RAG架构而非简单搜索 | 需要基于知识库的精准回答，而非通用大模型 |
| 2026-06-08 | 采用 MySQL+Qdrant+Redis 主数据架构 | 结构化存储、检索索引与缓存职责清晰 |
