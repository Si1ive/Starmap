# Agent 对话模块细致讲解（薄索引）

旧版实现细节正文已在 2026-07-25 拆分到 `implementation/` 分卷，当前文件只保留兼容入口，不再追加实现正文。

## 阅读入口

1. [上下文与当前记忆边界](./implementation/routing-context-memory.md)
2. [模型运行时、Token 与流式输出](./implementation/model-runtime-streaming.md)
3. [RAG、实体类型与工具活动](./implementation/rag-and-tools.md)
4. [Run/Thread 事件、时间线与错误投影](./implementation/events-timeline-errors.md)
5. [Agent Runs 与模型调用审计](./implementation/admin-observability.md)
6. [用户端交互与视觉](./implementation/frontend-experience.md)
7. [数据库迁移与结构守卫](./implementation/database-migrations.md)

## 迁移说明

- 旧文件曾同时承担架构说明、实现细节、故障复盘和视觉记录，已超过分卷硬上限。
- 后续 Agent 实现只更新最小相关分卷；复杂待做项进入 `tasks/`，提交记录进入 `progress/`。
- 若需要历史问题或一次性故障记录，请从 `tasks/` 或未来的 `incidents/` 目录进入。
