# 技术选型详细说明

## 总体结论

当前 408 平台以“管理端 + FastAPI + MySQL + Qdrant + Redis + Scrapy Service”为主链。

## 前端

### React 18

用于 `frontend-admin` 管理端页面开发。

选择原因：

- 生态成熟
- 与现有组件体系兼容
- 适合中后台页面组织

### TypeScript 5

选择原因：

- 类型约束明确
- 便于维护 API 类型与页面表单

### Vite

选择原因：

- 启动快
- 开发体验稳定
- 与 React + TypeScript 配套成熟

### Ant Design

选择原因：

- 适合管理端
- 表格、表单、详情页组件齐全

### Zustand

选择原因：

- 轻量
- 适合局部状态管理

## 后端

### FastAPI

当前承担：

- 管理端 API
- 对话 API
- 检索调试接口
- 语料与审核接口

选择原因：

- 异步支持完善
- Pydantic 模型协作顺畅
- Swagger 文档对联调友好

### SQLAlchemy 2.x

当前用于：

- MySQL ORM
- 多模态语料与业务实体落库

### Redis

当前用于：

- 会话缓存
- Scrapy 任务队列
- 进度与日志通道

### Qdrant

当前用于：

- `knowledge_segments`
- `question_segments`
- dense / sparse / hybrid 检索

选择原因：

- payload filter 适合学科、章节、来源过滤
- 更贴近当前多模态检索场景

### Scrapy Service

当前用于：

- PDF / 文件解析任务消费
- 结构化抽取
- 与 Redis 队列解耦

## 模型与 RAG

### OpenAI

当前用于：

- 问答生成
- 抽取增强
- 检索上下文回答

### RetrievalService

当前能力：

- 学科过滤
- 章节过滤
- 知识点 / 题目双路检索
- 关系扩展检索

## 运行基础设施

### MySQL

当前用于：

- 学科、章节、知识点、题目
- 语料文件、文档、解析记录
- 审核数据、任务数据

### Podman / podman-compose

当前文档基线使用：

- `podman-compose -f docker-compose.podman.yml up -d`
- 独立 `Qdrant` 容器

## 文档边界

- 本文件只描述当前 408 平台实际使用或明确规划使用的技术
