# 技术文档

## 目录

- [技术选型](./tech-stack.md) - 当前平台技术栈
- [数据模型](./data-model.md) - 数据结构与检索模型
- [架构设计](./architecture.md) - 系统架构
- [后端模块化单体演进方案](./backend-modular-monolith.md) - 后端边界、依赖规则与分阶段重构路线
- [408 学习 Agent 对话运行时技术设计](./408-agent-conversation-runtime-design.md) - Agent 线程与运行、Worker、数据模型、HTTP/SSE、恢复、工具、评测与发布门禁
- [408 学习 Agent 工作流编排技术设计](./408-agent-workflow-orchestration-design.md) - 工作流图、节点契约、模型边界、质量闸门、核心学习路径与轨迹评测
- [408 学习 Agent 工作流技术选型与风险分析](./408-agent-workflow-technology-selection-and-risk-analysis.md) - 主流方案对比、技术栈评价、生产风险、负责人决策清单与 PoC/ADR 验收
- [用户端 Agent 技术架构](./user-agent-client-architecture.md) - Web-first 客户端、Agent Runtime、能力适配与安全边界
- [408 Agent 对话界面实现逻辑与代码缺口](./408-agent-conversation-ui-implementation-gap.md) - thread 时间线、消息流、workflow 内嵌、SSE 恢复与分阶段代码改造
- [用户认证技术方案与数据模型](./authentication-architecture-options.md) - 认证方案对比、关系表、API、安全基线与迁移路线
- [用户端真实模拟考与练习实现](./user-practice-implementation.md) - 真题组卷、冻结快照、计时作答、交卷批改、复盘、覆盖统计与番茄钟
- [真实学习进度与艾宾浩斯投影](./learning-progress-ebbinghaus.md) - 题目/知识点关键词归并、记忆强度更新、复习阈值、真实时长与用户端曲线
- [多模态入库与检索设计](./multimodal-ingestion-retrieval-design.md) - 语料入库与检索方案
- [MinerU 解析运行时设计](./pdf-parser-runtime-design.md) - 解析契约、模块边界和部署目标
- [MinerU 解析服务部署](./pdf-parser-deployment.md) - Podman / 远程服务部署说明
- [多模态数据结构与迁移清单](./multimodal-schema-migration-plan.md) - 迁移与回填说明
- [部署指南](./deployment.md) - 本地开发与部署

### 语料与检索

- [语料富化增强与关联建立架构](./enrichment-architecture.md) - 富化、双向关联、结构化检索全链路实现
- [章节关联匹配策略深度设计](./chapter-linking-strategy.md) - 4 层匹配策略、边界处理与质量监控
- [跨章节大纲检索关联设计](./outline-retrieval-cross-chapter-association-design.md) - 大纲辅助检索与跨章扩展
- [考试大纲管理系统设计](./exam-outline-system-design.md) - 大纲数据模型与拆分入库方案
- [题目提取（bbox 坐标分组）设计](./bbox-question-extraction.md) - 基于 MinerU bbox 的题目分组重构
- [语料管线计划](./corpus-pipeline-plan.md) - 采集、解析、抽取管线

### 认证

- [本地认证联调](./local-auth-integration.md) - 本地 OAuth / SMTP 联调
- [环境问题排查](./environment-troubleshooting.md) - 常见本地环境故障

### 规范

- [工程规范目录](./conventions/README.md) - Git 提交、命令执行、版本控制、开发日志规范

### 路线图

- [408 学习 Agent 分步实施路线图](./roadmap/408-agent-implementation-roadmap.md) - 由编排与运行时设计整合的实施步骤

## 快速参考

### 技术栈总览

| 层级 | 技术 | 说明 |
|------|------|------|
| 用户端 | React 18 + TypeScript + Vite | Web-first 学习 Agent 工作台，按需扩展 Tauri 或浏览器能力 |
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
| `backend/app/modules` | 按领域组织的后端模块 |
| `backend/app/modules/chat` | 当前 RAG 问答服务，后续作为 Agent 讲解工具演进 |
| `backend/app/modules/content` | 题目与知识点管理 |
| `backend/app/modules/corpus` | MinerU 语料解析与实体抽取 |
| `backend/app/modules/retrieval` | 检索、关系扩展与 segment 管理 |
| `backend/app/db/qdrant.py` | Qdrant 连接与 collection 管理 |
| `backend/app/models/mysql_models.py` | MySQL ORM 模型 |
| `backend/scrapy_service/starmap_scrapy/spiders/knowledge_spider.py` | 408 PDF 采集与解析 spider |
| `frontend/src` | 用户端 React 应用 |
| `frontend-admin/src/router/index.tsx` | 管理端路由 |

### 文档维护原则

- 文档以当前 408 平台为准
- 向量数据库统一表述为 `Qdrant`
- 若某能力仍是过渡态，需明确标注适用范围
