# Agent Runs 与模型调用审计

## 适用场景

本分卷描述管理员如何从 Thread 级列表进入多轮问答详情，并查看某一轮中的 runs、events、approvals、artifacts
和模型配置使用情况。

## 会话列表与状态统计

| 执行阶段 | 文件 | 符号 | 职责 |
| --- | --- | --- | --- |
| 会话状态统计 | `backend/app/modules/agent/admin_router.py` | `get_run_stats` | 用窗口函数取每个 Thread 最新 root run，并按状态聚合计数 |
| 会话分页 | `backend/app/modules/agent/admin_router.py` | `list_all_runs` | 以 Thread 为主实体分页，再批量聚合该页的 run 数、turn 数和事件数 |
| 管理端契约 | `frontend-admin/src/api/agentRuns.ts` | `AdminAgentSession` / `AdminAgentTurn` / `AdminAgentSessionDetail` | 定义会话摘要、多轮问答和单轮内嵌事实结构 |
| 列表消费 | `frontend-admin/src/pages/AgentRunsPage.tsx` | `AgentRunsPage` | 展示会话标题、Thread ID、最新状态、回合数和事件数，并进入详情 |

## 单轮详情如何归并 root/child Run

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 旧链接兼容 | `backend/app/modules/agent/admin_router.py` | `_resolve_thread` | 详情路径中的 Thread ID 或旧 Run ID | 统一解析为 Thread，避免历史书签失效 | Thread 实体 | `get_run_detail` |
| 明细查询 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | 已解析 Thread | 一次读取 messages、runs、events、approvals、artifacts | 全量事实集合 | `_build_turns` |
| 按轮归并 | `backend/app/modules/agent/admin_router.py` | `_build_turns` | 会话内五类事实记录 | 以 root run 为边界，把用户消息、assistant 消息、child runs 和审批/产物归到同一轮 | `turns[]` | 前端详情 |
| 多轮折叠渲染 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `AgentRunDetailPage` | `session.turns` | 每一轮渲染一级 Collapse，默认展开最后一轮 | 轮级详情视图 | `TurnDetail` |
| 单轮事件折叠 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `TurnDetail` | 单轮 messages、runs、events、approvals、artifacts | 运行链路、事件流、审批和产物分别二次折叠 | 管理员审计界面 | 页面交互 |

## 模型调用审计入口

| 执行阶段 | 文件 | 符号 | 职责 |
| --- | --- | --- | --- |
| 运行时模型绑定 | `backend/app/modules/agent/model_runtime/config.py` | `open_agent_model` | 读取 run 绑定的模型配置，构建独立客户端，并把实际使用的配置写回 run metadata |
| Run 执行链 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | 在 Run 进入 running、完成或失败时统一写事件和状态，形成可审计主链 |
| 工作流步骤链 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | 每个 step 的开始、完成、失败都进入 `agent_steps` 与 `agent_events` |
| 检索活动公开载荷 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | 工具公开元数据包含 query 摘要、命中数和文档摘要，便于后台复盘 explain/validate 检索链路 |

## 排查建议

1. 用户说“页面失败了”，先从 `get_run_detail` 看 root run 和 child run 的状态，再看 `run.error_message` 与公开 `error_code` 是否一致。
2. 用户说“解释型工作流卡住”，优先检查该轮的 `step.started` / `step.completed` 是否完整，以及 `tool.called` / `tool.result` 是否成对出现。
3. 用户说“模型没按我选的走”，查看 run metadata 是否记录了 `model_config_id` 与实际模型名称，再回到 `open_agent_model` 调用链。

## 下一步阅读

- 需要看事件和错误如何投影到用户端，转到 `implementation/events-timeline-errors.md`。
- 需要看模型配置、Token 和 child run 继承模型，转到 `implementation/model-runtime-streaming.md`。
