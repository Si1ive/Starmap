# 408考研智能学习平台 - 系统架构

## 系统架构图

```text
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI API Gateway                      │
├──────────────────────┬───────────────────────────────────────┤
│ 领域模块路由         │ 对话与检索接口                        │
│ /api/v1/admin/*      │ /api/v1/chat  /api/v1/admin/search    │
├──────────────────────┴───────────────────────────────────────┤
│                 Modular Application Layer                   │
│ Catalog / Content / Corpus / Retrieval / Crawler / Ops      │
├──────────────────────────────────────────────────────────────┤
│                    Async Infrastructure                      │
│ Redis Cache / Task Queue / Log Stream / Session Store       │
├──────────────────────────────────────────────────────────────┤
│                        Data Layer                            │
│ MySQL                 Qdrant                 Redis           │
│ 业务主存储            检索索引                缓存与队列      │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    Scrapy Service / PDF 解析
```

## 当前架构结论

- 当前向量数据库是 `Qdrant`
- `MySQL` 是业务事实源
- `Redis` 负责缓存、会话、任务队列和实时日志
- `Scrapy Service` 负责 PDF / 文件解析与结构化入库
- 后端正在从巨型管理路由和共享 Service 目录演进为领域化模块单体
- 新模块边界和迁移顺序见[后端模块化单体演进方案](./backend-modular-monolith.md)

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| API | FastAPI + Uvicorn | 管理端 API、对话 API |
| ORM | SQLAlchemy 2.x | MySQL ORM |
| 主数据库 | MySQL 8 | 学科、章节、知识点、题目、语料、审核数据 |
| 向量数据库 | Qdrant | `retrieval_segments` 召回索引 |
| 缓存 / 队列 | Redis | 会话缓存、Scrapy 队列、日志流 |
| 文档解析 | Scrapy Service | PDF 解析、内容抽取 |
| LLM | OpenAI | 抽取增强、RAG 回答 |

## 数据职责划分

| 组件 | 主要职责 |
|------|----------|
| `MySQL` | `subjects`、`chapters`、`knowledge_points`、`questions`、`documents`、`retrieval_segments`、审核表 |
| `Qdrant` | `knowledge_segments`、`question_segments` collection 检索 |
| `Redis` | 会话历史、任务队列、进度广播、实时日志 |
| `Scrapy Service` | 文件解析、知识点/题目抽取、入库任务执行 |

## 核心接口分组

### 管理端接口

管理端 URL 保持 `/api/v1/admin/*` 不变，内部按领域模块逐步拆分：

- 认证：`/admin/auth/*`
- 看板：`/admin/dashboard/*`
- 爬虫与任务：`/admin/crawler/*`
- 学科与章节：`/admin/subjects`、`/admin/subjects/{subject_id}/chapters`
- 知识点与题目：`/admin/knowledge/points*`、`/admin/questions*`
- PDF 入库：`/admin/knowledge/ingest`
- 语料与解析：`/admin/corpus/*`
- 审核：`/admin/review/*`
- 检索调试：`/admin/search`、`/admin/search/with-relations`

已迁移模块：

- `backend/app/modules/catalog/router.py`：学科与章节目录
- `backend/app/modules/content`：题目、知识点及审核元数据
- `backend/app/modules/corpus`：语料文件、解析任务和文档抽取工作流
- `backend/app/modules/operations`：数据库管理员认证、JWT、用户与部署校验

### 对话接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat` | RAG 问答 |
| GET | `/api/v1/chat/{session_id}/history` | 获取会话历史 |

## RAG 流程

```text
用户问题
  ↓
RetrievalService 生成 embedding
  ↓
Qdrant 检索 knowledge/question segments
  ↓
MySQL 补全来源、章节、实体信息
  ↓
ChatService 组装上下文
  ↓
OpenAI 生成回答
  ↓
返回回答 + citations
```

## 入库流程

```text
PDF / 文档文件
  ↓
Scrapy KnowledgeSpider / 语料扫描
  ↓
MySQL: corpus_files / parse_runs / documents / blocks / assets
  ↓
知识点 / 题目抽取
  ↓
retrieval_segments 构建
  ↓
Qdrant collection 写入
```

## 文档修订说明

本文件只描述当前 408 平台的主架构。
