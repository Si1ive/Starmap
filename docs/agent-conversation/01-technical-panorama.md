# Agent 对话模块技术实现全景图（薄索引）

旧版全景正文已在 2026-07-25 拆分到 `architecture/` 分卷，当前文件只保留兼容入口，不再追加实现正文。

## 阅读入口

1. [系统边界](./architecture/system-map.md)：先看组件边界、数据所有权和模块职责。
2. [对话主链](./architecture/conversation-mainline.md)：看用户发起一轮对话到 SSE/前端归并的完整链路。
3. [工作流分支](./architecture/workflow-branches.md)：看 explain / validate / grade / plan 的 child workflow。
4. [管理端与模型配置](./architecture/admin-and-model-config.md)：看管理端会话审计、模型配置和无限 Token 契约。

## 迁移说明

- 本文件原先长期累积全景正文，已超过分卷阈值，不再继续演进。
- 后续若入口函数、异步边界或最终消费位置变化，应只更新对应 `architecture/*.md` 分卷。
- 需要实现细节、故障排查和测试入口时，改读 `implementation/` 分卷与 `tasks/` / `progress/`。
