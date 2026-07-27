# Agent 对话主链

## 适用场景

本分卷覆盖用户端发起一轮对话，到后端创建消息与 Run、Worker 执行、事件投影、SSE 推送，再到前端归并显示
的完整主链。排查“为什么用户没看到最终回答”时应先读本分卷。

## 用户发起一轮对话直到前端显示结果

| 执行序号 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `frontend/src/pages/AgentPage.tsx` | `AgentPage.handleSend` | 输入文本、thread ID、`selectedModelId` | 空会话先建 thread，再提交 turn；模型失效时保留输入并刷新模型列表 | 一次 turn 请求 | `AgentProvider.sendTurn` |
| 2 | `frontend/src/store/agent-context.tsx` | `AgentProvider.sendTurn` | thread、内容、`modelConfigId` | 生成 `client_message_id`，调用后端 turn API，成功后刷新时间线并确保 SSE 已连接 | `TurnCreateResponse` 与最新 timeline | `createTurn` |
| 3 | `frontend/src/api/agent.ts` | `createTurn` | `TurnCreateRequest` | POST `/api/v1/app/agent/threads/{thread_id}/turns` | HTTP 201 或 API 错误 | `create_turn` |
| 4 | `backend/app/modules/agent/router.py` | `create_turn` | 已认证用户、请求体、请求级 session | 处理线程不存在、模型不可用、幂等冲突，剩余逻辑委托给时间线服务 | 用户消息、root run 和 cursor | `AgentTimelineService.create_turn` |
| 5 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService.create_turn` | user/thread/content/client ID/model ID | 在同一事务中创建用户消息、conversation root run、thread item、run/thread 事件与 outbox | `queued` run、可重放时间线事实 | `OutboxStore.enqueue` |
| 6 | `backend/app/modules/agent/outbox.py` | `OutboxStore.enqueue` | root run ID | 创建 `pending` outbox 记录并 flush | Worker 可见的可靠执行任务 | 请求 session 退出 |
| 7 | `backend/app/db/mysql.py` | `MySQLClient.session` | 路由依赖创建的 session | 成功统一 commit，异常统一 rollback | 消息、Run、事件和 outbox 一起可见或一起回滚 | Worker 扫描 |
| 8 | `backend/app/modules/agent/worker.py` | `AgentWorker.start` / `AgentWorker.scan_and_process` | pending outbox | 按轮询批次创建独立 session、原子认领 outbox、串行化同线程执行 | 单个 Run 的独立工作 session | `AgentWorker.process_run` |
| 9 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（L103-L272） | 已认领 run | 进入 running、恢复 checkpoint、执行 workflow、落库 Artifact/最终消息/完成事件；completed 分支额外同事务写摘要维护任务，异常交给 `_record_failure` | completed / waiting / failed run | `WorkflowEngine.execute` / Memory Outbox |
| 9a | `backend/app/modules/agent/memory_projection.py` | `_ensure_memory_update_outbox`、`project_completed_run_facts`（L27-L64、L125-L140） | Router 前显式主题或 worker 已持久化 Artifact | 事实写入后同事务确保 pending Memory Outbox；重放补建缺失任务，并发唯一键冲突限制在 SAVEPOINT | 原子可见的记忆事实与异步任务 | `MemoryOutboxConsumer.scan_and_process` |
| 9b | `backend/app/modules/agent/worker.py`、`backend/app/modules/agent/memory_outbox.py`、`backend/app/modules/agent/memory_item_projection.py` | `AgentWorker.start`（L370-L394）、`MemoryOutboxConsumer.scan_and_process`（L278-L308）、`project_trusted_memory_event`（L154-L166） | pending/过期 processing Memory Outbox | 同一后台循环在 Run 批次后扫描记忆任务；独立事务认领，SAVEPOINT 内按任务类型校验事实或 completed Run，失败延迟重试且不改 Run | topic 物化线程记忆项，approved plan 物化含结构化 goals 的用户目标；Outbox completed/pending/failed | PlanningBundle / 摘要维护 |
| 9c | `backend/app/modules/agent/conversation_summary.py`、`backend/app/modules/agent/memory_outbox.py`、`backend/app/modules/agent/model_runtime/conversation_summary.py` | `enqueue_conversation_summary_maintenance`（L37-L69）、`MemoryOutboxConsumer.process_claimed`（L202-L276）、`ConversationSummaryMaintainer.maintain`（L90-L211）、`ConversationSummaryRuntime.summarize`（L65-L117） | 成功 Run 的摘要任务，触发 Run 模型配置，同线程旧消息 | Run 完成事务只入队；消费时保留最近 12 个用户轮次，选择活跃摘要后最多 24 条旧消息，调用结构化模型滚动合并；落库前锁线程复核活跃版本，变化时重试 | 新摘要记录与旧摘要 `superseded_by_id` 同事务可见；原消息和公开 SSE 不变；失败或并发冲突只重试 Outbox | 后续历史摘要 Bundle / Embedding |
| 10 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | workflow 定义、执行上下文、Run | 每个节点开始写 `step.started` 并 commit；完成/失败再写对应事件并 commit；WAITING 保存 checkpoint | 真实步骤链、最终 `NodeResult` 或断点 | conversation / child workflow 节点 |
| 11 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | 当前消息、筛选后的历史、模型配置 | 用 4096 Token 预算只筛历史，不限制模型总输出；调用 Router 决定 direct/explain/validate/grade/plan/clarify | `RouterDecision` 与下一节点 | `RouterRuntime.decide` |
| 12 | `backend/app/modules/agent/model_runtime/router.py` | `_explicit_workflow_action`、`RouterRuntime.decide`、`RouterRuntime._run` | 当前输入、允许 action、历史与模型配置 | 结构化路由，显式“讲解/出题/批改/计划”由护栏纠偏，`UsageLimits(request_limit=2)` 仅限制请求次数 | 经授权的 `RouterDecision` | direct answer 或 child workflow |
| 13 | `backend/app/modules/agent/workflows/conversation.py` | `_direct_answer_node` | `AgentRunContext` | 把 100ms 聚合后的正文 delta 写 `message.delta` 并 commit，最终输出包装成 message artifact | 增量 assistant 正文与最终 artifact | `DirectAnswerRuntime.answer` |
| 14 | `backend/app/modules/agent/model_runtime/answer.py` | `DirectAnswerRuntime.answer` / `_run_stream` | 当前问题、历史、模型配置和 delta callback | 通过 Pydantic AI `run_stream` 产出结构化正文，增量只发送已确认前缀 | `message.delta` 与 `message.completed` 内容 | `EventStore.append` |
| 15 | `backend/app/modules/agent/events.py` | `EventStore.append` | run 事件类型与 payload | 分配 run 内序号，写 `agent_events`，并触发公开 thread 投影 | 内部事件与公开事件关联 | `ThreadEventStore.project_run_event` |
| 16 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event` / `_project_message_event` | run 事件 | 把 `message.delta`、`message.completed`、`message.failed`、step/tool 事件投影成 thread 事件 | 可按 cursor 消费的公开时间线事实 | `stream_thread_events` |
| 17 | `backend/app/modules/agent/router.py` | `stream_thread_events` | thread ID、`after_sequence` | 校验线程归属，循环补查新事件并输出 SSE heartbeat | `StreamingResponse` | 浏览器 EventSource |
| 18 | `frontend/src/store/agent-context.tsx` | `AgentProvider.connectThreadStream` | thread ID 和 cursor | 建立 EventSource，按事件类型更新 reducer；投影类事件触发时间线快照刷新 | 最新 timeline 与连接状态 | `applyMessageEvent` / `applyWorkflowEvent` |
| 19 | `frontend/src/features/agent/timeline-state.ts` | `applyMessageEvent` | `message.delta` / `message.completed` / `message.failed` | 对 delta 追加正文，对 completed/failed 收敛状态和错误信息 | 规范化消息状态 | `ConversationStream` |
| 20 | `frontend/src/features/agent/ConversationStream.tsx` | `TimelineItemView` / `ConversationStream` | timeline items | 展示 streaming 文本、失败原因、工作流卡片和最终产物；无正文时显示等待三点 | 用户最终看到回答或失败说明 | 页面滚动区 |

## 异常主链：模型或工作流失败如何公开

| 执行序号 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（异常分支） | 节点失败结果或模型异常 | 统一进入失败记录逻辑，不吞掉原始异常 | 待分类内部错误 | `_record_failure` |
| 2 | `backend/app/modules/agent/public_errors.py` | `classify_agent_error` | 原始错误与异常对象 | 映射为稳定 `error_code` 和安全中文说明 | 公开错误对象 | `AgentWorker._record_failure` |
| 3 | `backend/app/modules/agent/worker.py` | `AgentWorker._record_failure` | Run、原始错误、公开错误 | `run.error_message` 保留内部原文，事件写安全说明和稳定码 | `run.failed` 事件 | `ThreadEventStore.project_run_event` |
| 4 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event` / `_project_message_event`（失败分支） | `run.failed` | 不覆盖已有 partial 正文，只在消息状态和错误字段中写失败原因 | 可恢复的失败消息和公开事件 | `applyMessageEvent` |
| 5 | `frontend/src/features/agent/timeline-state.ts` | `applyMessageEvent`（failed 分支） | 实时 `message.failed` | 保留已显示正文，归并 `error_code` / `error_message`，结束 streaming | React timeline state | `ConversationStream` |
| 6 | `frontend/src/features/agent/ConversationStream.tsx` | `TimelineItemView`（failed 分支） | 失败消息和可选 partial 正文 | 有正文则正文与红色原因分开显示，无正文只显示一次原因 | 用户可见失败结果 | 页面消息气泡 |

## 下一步阅读

- 需要看 explain/validate/grade/plan 的 child workflow 链路，转到 `architecture/workflow-branches.md`。
- 需要看消息、步骤、工具活动和错误如何投影/恢复，转到 `implementation/events-timeline-errors.md`。
