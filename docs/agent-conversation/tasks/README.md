# Agent 对话任务路由

本目录只保存跨提交任务的状态与验收边界。稳定实现说明进入 `../implementation/`，一次性故障证据进入
`../incidents/`，提交进展进入 `../progress/`。

## 当前任务

| 任务 | 状态入口 | 主题分卷 |
| --- | --- | --- |
| RAG、Explain 与分层记忆整改 | [总览](./2026-07-26-rag-explain-memory-remediation.md) | [已完成整改与基础](./2026-07-26-rag-explain-memory-remediation-completed.md) · [记忆生命周期](./2026-07-26-rag-explain-memory-remediation-memory-lifecycle.md) · [管理端可观测性](./2026-07-26-rag-explain-memory-remediation-observability.md) |
| Agent 练习与学习闭环 | [四阶段任务单](./2026-07-28-agent-practice-learning-loop.md) | 出题持久化 · 学习证据 · 薄弱点统一 · Capability Harness |
| 自适应学习 Agent 与掌握度闭环 | [落实步骤](./2026-07-29-adaptive-learning-agent.md)（阶段一至阶段五已完成，阶段六待实施） | ConversationTutorAgent · LearningObserverAgent · 开放题评估 · 掌握度/薄弱点投影 |

## 更新规则

1. 先更新总览中的任务状态，再只修改一个与本次实现直接相关的主题分卷。
2. 总览保持薄路由，不承载实现正文；同一事实只在一个主题分卷保留权威说明。
3. 单个任务分卷达到 300 行或 30 KB 时评估拆分，达到 500 行或 50 KB 前必须先拆分。
4. 任务状态不替代实现教学文档和月度进展；Agent 代码提交仍需同步更新两者。
