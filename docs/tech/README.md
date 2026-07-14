# 技术文档

## 目录

- [技术选型](./tech-stack.md) - 当前平台技术栈
- [数据模型](./data-model.md) - 数据结构与检索模型
- [架构设计](./architecture.md) - 系统架构
- [后端模块化单体演进方案](./backend-modular-monolith.md) - 后端边界、依赖规则与分阶段重构路线
- [多模态入库与检索设计](./multimodal-ingestion-retrieval-design.md) - 语料入库与检索方案
- [MinerU 解析运行时设计](./pdf-parser-runtime-design.md) - 解析契约、模块边界和部署目标
- [MinerU 解析服务部署](./pdf-parser-deployment.md) - Podman / 远程服务部署说明
- [多模态数据结构与迁移清单](./multimodal-schema-migration-plan.md) - 迁移与回填说明
- [部署指南](./deployment.md) - 本地开发与部署

## 快速参考

### 技术栈总览

| 层级 | 技术 | 说明 |
|------|------|------|
| 管理端 | React 18 + TypeScript + Vite + Ant Design | 后台管理界面 |
| 后端 | FastAPI + SQLAlchemy | API、任务编排、RAG 服务 |
| 主数据库 | MySQL 8 | 学科、章节、知识点、题目、语料元数据 |
| 向量数据库 | Qdrant | 检索 segment 与混合检索 |
| 缓存 / 队列 | Redis | 会话、任务、实时日志 |
| 采集 / 解析 | Scrapy Service | PDF 入库与结构化抽取 |
| 模型服务 | OpenAI | 回答生成与抽取增强 |

### 当前数据架构

- `MySQL`：业务主存储与事实源
- `Qdrant`：检索索引与召回层
- `Redis`：缓存、队列、日志与会话

### 核心环境变量

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=starmap
MYSQL_PASSWORD=starmap123
MYSQL_DATABASE=starmap
REDIS_URL=redis://localhost:6379
QDRANT_HOST=localhost
QDRANT_PORT=6333
VITE_API_BASE_URL=http://localhost:8000
```

### 常用端口

| 服务 | 端口 |
|------|------|
| 后端 API | 8000 |
| 管理端前端 | 5174 |
| MySQL | 3306 |
| Redis | 6379 |
| Qdrant HTTP | 6333 |
| Qdrant gRPC | 6334 |

### 关键代码位置

| 路径 | 说明 |
|------|------|
| `backend/app/api/admin.py` | 管理端 API |
| `backend/app/api/chat.py` | 问答 API |
| `backend/app/db/qdrant.py` | Qdrant 连接与 collection 管理 |
| `backend/app/services/retrieval_service.py` | 检索服务 |
| `backend/app/modules/chat/service.py` | RAG 对话服务 |
| `backend/app/models/mysql_models.py` | MySQL ORM 模型 |
| `backend/scrapy_service/starmap_scrapy/spiders/knowledge_spider.py` | 408 PDF 采集与解析 spider |
| `frontend-admin/src/router/index.tsx` | 管理端路由 |

### 文档维护原则

- 文档以当前 408 平台为准
- 向量数据库统一表述为 `Qdrant`
- 若某能力仍是过渡态，需明确标注适用范围
