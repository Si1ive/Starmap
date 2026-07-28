# 2026-07 Agent 对话进展路由

## 文档地图

| 分卷 | 适用场景 | 更新路由 |
| --- | --- | --- |
| [记忆基础、可信事实与 Outbox](./01-memory-foundation-and-outbox.md) | TurnUnderstanding、Snapshot、事实事件、掌握度、Plan、Memory Outbox | 修改记忆事实、派生和 Outbox 时追加这里 |
| [Validate 记忆消费闭环](./04-validate-memory-consumption.md) | PracticeBundle、检索过滤、缺主题澄清与恢复 | 修改 Validate 记忆消费时追加这里 |
| [记忆失效与删除治理](./05-memory-expiry-and-deletion.md) | 主题轮次 TTL、临时约束、画像衰减与线程删除 | 修改记忆失效或删除策略时追加这里 |
| [RAG、Explain 与故障修复](./02-rag-and-explain-fixes.md) | 检索 DTO、来源回填、活动折叠、Explain fallback、Artifact 契约 | 修改检索或 Explain 时追加这里 |
| [管理端记忆可观测](./06-admin-memory-observability.md) | Run/Snapshot/source 复现、Memory Outbox 运维与管理端 UI | 修改 MEM-008 管理观测与运维时追加这里 |
| [用户端 Agent 外围体验](./07-user-frontend.md) | 全局任务中心等消费 Agent 时间线的用户端外围界面 | 修改非对话主体但消费 Agent 状态的用户端组件时追加这里 |
| [Agent 练习与学习闭环](./08-practice-learning-loop.md) | 对话出题、练习 Session、学习证据、薄弱点与 Capability Harness | 修改四阶段闭环时追加这里 |
| [文档治理与任务规划](./03-documentation-and-planning.md) | 文档迁移、稳定边界校正、任务单创建 | 只有文档路由、职责边界或计划变化时更新 |

## 迁移状态

原 `../2026-07.md` 在 2026-07-26 达到 496 行后迁入本目录；原 `01-memory-and-validation.md` 达到 300 行后又按记忆内核与 Validate 消费拆分。两个旧路径现均为兼容薄索引，正文只在上表主题分卷继续演进。
