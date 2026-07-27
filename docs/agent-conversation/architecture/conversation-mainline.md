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
| 9 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（L104-L274） | 已认领 run | 进入 running、恢复 checkpoint、执行 workflow、落库 Artifact/最终消息/完成事件；completed 根 conversation 分支同事务写摘要维护和偏好候选抽取任务，异常交给 `_record_failure` | completed / waiting / failed run | `WorkflowEngine.execute` / Memory Outbox |
| 9a | `backend/app/modules/agent/memory_projection.py` | `_ensure_memory_update_outbox`、`project_completed_run_facts`（L27-L64、L125-L140） | Router 前显式主题或 worker 已持久化 Artifact | 事实写入后同事务确保 pending Memory Outbox；重放补建缺失任务，并发唯一键冲突限制在 SAVEPOINT | 原子可见的记忆事实与异步任务 | `MemoryOutboxConsumer.scan_and_process` |
| 9b | `backend/app/modules/agent/worker.py`、`backend/app/modules/agent/memory_outbox.py`、`backend/app/modules/agent/memory_item_projection.py` | `AgentWorker.start`（L372-L396）、`MemoryOutboxConsumer.process_claimed` / `MemoryOutboxConsumer.scan_and_process`（L227-L339）、`project_trusted_memory_event`（L212-L224） | pending/过期 processing Memory Outbox | Run 批次后独立事务认领；SAVEPOINT 内分派可信事实、摘要、偏好、线程删除或向量任务 | active/失效记忆状态与 Outbox completed/pending/failed；失败不反向修改 Run | PlanningBundle / 摘要 / 偏好 / 向量消费者 |
| 9c | `backend/app/modules/agent/conversation_summary.py`、`backend/app/modules/agent/memory_outbox.py`、`backend/app/modules/agent/model_runtime/conversation_summary.py` | `enqueue_conversation_summary_maintenance`（L38-L70）、`MemoryOutboxConsumer.process_claimed`（L227-L307）、`ConversationSummaryMaintainer.maintain`（L91-L231）、`ConversationSummaryRuntime.summarize`（L65-L117） | 成功 Run 的摘要任务，触发 Run 模型配置，同线程旧消息 | Run 完成事务只入队；消费时滚动合并旧消息并锁线程复核版本；新摘要落库后追加版本化向量 upsert | 新摘要、旧摘要 superseded 与 pending 向量任务同事务可见；失败只重试 Outbox | 历史摘要 Bundle / 向量消费者 |
| 9d | `backend/app/modules/agent/memory_vector.py`、`backend/app/modules/agent/memory_outbox.py` | `MemoryVectorLifecycle.process_outbox`（L198-L253）、`memory_vector_point_id`（L86-L94）、`MemoryOutboxConsumer.process_claimed`（L227-L307） | 版本化向量任务、当前 MySQL source、Embedding 配置 | 稳定 UUID upsert；成功后删除旧点，失效 source 只删除，collection 不存在幂等完成 | Qdrant 当前点；异常回滚 SAVEPOINT 并重试 | `MemoryVectorLifecycle.recall` / 管理端 Outbox |
| 9e | `backend/app/modules/agent/preference_memory.py`、`backend/app/modules/agent/model_runtime/preference_extractor.py` | `enqueue_preference_candidate_extraction`（L122-L166）、`PreferenceCandidateProjector.process_outbox`（L175-L244）、`PreferenceExtractionRuntime.extract`（L92-L144） | 已完成根 conversation Run、同作用域原始 user message、Run 绑定模型配置 | 只把最多五个结构化 key/value/scope/confidence 提案写成 pending candidate；高低置信度都不自动生效，来源重放先读既有 candidate，模型或落库错误只重试 Outbox | 带 source、extractor/model 版本的 `agent_preference_candidates`；completed Run 和公开 SSE 不变 | 用户候选治理 API / 偏好选择器 |
| 9f | `backend/app/modules/agent/router.py`、`backend/app/modules/agent/thread_memory_deletion.py`、`backend/app/modules/agent/memory_vector.py` | `delete_agent_thread`（L714-L726）、`delete_thread_memory`（L30-L161）、`ThreadMemoryDeletionProcessor.process_outbox`（L171-L196）、`MemoryVectorLifecycle.delete_sources`（L194-L196） | 当前用户与 thread ID、线程级派生记录及其 source versions | HTTP 事务先软删线程、清热状态、失效摘要/线程来源候选与记忆项并写唯一 task-key Outbox；消费者复核 deleted 线程后删除向量 | MySQL 立即不可召回；Qdrant 删除可重试。用户掌握度和独立批准用户目标保留 | Memory Outbox / 后续治理审计 |
| 10 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | workflow 定义、执行上下文、Run | 每个节点开始写 `step.started` 并 commit；完成/失败再写对应事件并 commit；WAITING 保存 checkpoint | 真实步骤链、最终 `NodeResult` 或断点 | conversation / child workflow 节点 |
| 11 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | 当前消息、筛选后的历史、模型配置 | 用 4096 Token 预算只筛历史，不限制模型总输出；调用 Router 决定 direct/explain/validate/grade/plan/clarify | `RouterDecision` 与下一节点 | `RouterRuntime.decide` |
| 12 | `backend/app/modules/agent/model_runtime/router.py` | `RouterDeps`、`_router_policy`、`RouterRuntime.decide`（L30-L189） | 当前输入、允许 action、近期历史、冻结摘要与模型配置 | 摘要作为不可信动态 instructions；结构化路由后显式工作流意图仍由护栏纠偏 | 经授权的 `RouterDecision` | direct answer 或 child workflow |
| 13 | `backend/app/modules/agent/workflows/conversation.py` | `_direct_answer_node`（L158-L196） | 含近期历史和冻结摘要的 `AgentRunContext` | 把摘要交给受控依赖，把 100ms 聚合后的正文 delta 写 `message.delta` 并 commit，最终输出包装成 message artifact | 增量 assistant 正文与最终 artifact | `DirectAnswerRuntime.answer` |
| 14 | `backend/app/modules/agent/model_runtime/answer.py` | `DirectAnswerDeps`、`_controlled_context`、`DirectAnswerRuntime.answer`（L22-L170） | 当前问题、近期历史、冻结摘要、模型配置和 delta callback | 摘要只进入声明为不可信数据的动态 instructions；Pydantic AI `run_stream` 产出结构化正文，增量只发送已确认前缀 | `message.delta` 与 `message.completed` 内容 | `EventStore.append` |
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
