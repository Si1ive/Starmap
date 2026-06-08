# 408考研智能学习平台 - 后端架构设计

## 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway                               │
│                    (FastAPI + Uvicorn)                           │
├─────────────┬─────────────┬─────────────┬───────────────────────┤
│  知识点接口  │   对话接口   │   题目接口   │    学科/章节接口      │
│ /knowledge/  │   /chat     │ /questions/  │    /subjects/        │
│   points     │             │              │                      │
├─────────────┴─────────────┴─────────────┴───────────────────────┤
│                      Service Layer                               │
│         KnowledgeService   │        ChatService (RAG)           │
│         QuestionService    │        SubjectService               │
├──────────────────────────────┼───────────────────────────────────┤
│         Cache Layer          │        Session Layer              │
│         (Redis)              │        (Redis)                    │
├──────────────────────────────┴───────────────────────────────────┤
│                      Data Access Layer                           │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│   │  MySQL   │  │  Neo4j   │  │ ChromaDB │  │  Redis   │      │
│   │ 主存储    │  │ 知识图谱  │  │ 语义搜索  │  │  缓存    │      │
│   │ 学科/章节 │  │ 知识点   │  │ 知识点   │  │ 会话数据  │      │
│   │ 知识点   │  │ 关联关系  │  │ 向量嵌入  │  │ 热点数据  │      │
│   │ 题目     │  │          │  │          │  │          │      │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| Web框架 | FastAPI | 0.136+ | API服务 |
| 服务器 | Uvicorn | 0.23+ | ASGI服务器 |
| 数据验证 | Pydantic | 2.13+ | 模型验证 |
| 主数据库 | MySQL | 8.0+ | 结构化数据存储 |
| 图数据库 | Neo4j | 5.11+ | 知识点关联关系 |
| 向量数据库 | ChromaDB | 0.4.6+ | 语义搜索 |
| 缓存 | Redis | 7.0+ | 会话/结果缓存 |
| ORM | SQLAlchemy | 2.0+ | MySQL ORM |
| RAG | LangChain + OpenAI | - | 检索增强生成 |
| 爬虫 | Scrapy | 2.11+ | PDF解析/网页爬取 |

## 数据库职责划分

| 数据库 | 存储内容 | 查询场景 |
|--------|----------|----------|
| **MySQL** | 学科、章节、知识点、题目、做题记录、管理员 | 列表查询、分页、筛选、CRUD |
| **Neo4j** | 知识点关联关系 | 图遍历、路径查询、关联推荐 |
| **ChromaDB** | 知识点向量嵌入 | 语义搜索、相似度查询 |
| **Redis** | 会话状态、缓存 | 快速读取、会话管理 |

## API 路由设计

### 管理端 API (`/api/v1/admin/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /subjects | 学科列表 |
| GET | /subjects/{id}/chapters | 章节列表 |
| GET | /knowledge/points | 知识点列表（分页、筛选） |
| GET | /knowledge/points/{id} | 知识点详情 |
| PUT | /knowledge/points/{id} | 编辑知识点 |
| POST | /knowledge/ingest | 触发PDF入库任务 |
| GET | /questions | 题目列表 |
| GET | /questions/{id} | 题目详情 |
| PUT | /questions/{id} | 编辑题目 |
| GET | /dashboard/stats | 看板统计 |
| GET | /dashboard/charts | 图表数据 |

### 对话 API (`/api/v1/chat/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /chat | RAG智能问答 |
| GET | /chat/history/{session_id} | 对话历史 |
| DELETE | /chat/session/{session_id} | 清除会话 |

## RAG 问答流程

```
用户提问
    ↓
ChromaDB 向量检索（top-5 相关知识点）
    ↓
构建带上下文的 prompt
    ↓
OpenAI API 生成回答
    ↓
返回回答 + 来源引用
```

## PDF 入库流程

```
教材 PDF 文件
    ↓
pdfplumber 文本提取
    ↓
按章节标题分割
    ↓
内容分块（500-2000字）
    ↓
Scrapy KnowledgeSpider
    ↓
KnowledgePointItem
    ↓
DatabasePipeline
    ├→ MySQL (knowledge_points)
    └→ ChromaDB (knowledge_points collection)
```

## 服务间通信

```
FastAPI Backend  ←──Redis Queue──→  Scrapy Service
     ↓                                    ↓
   MySQL                            PDF 解析
   ChromaDB                         数据入库
   Neo4j
```
