# Run/Thread 事件、时间线与错误投影

## 适用场景

本分卷说明内部 Run 事件如何投影到 thread 时间线，为什么刷新后仍能恢复消息、工作流步骤和工具活动，以及
失败错误如何既保留管理端审计信息，又向用户公开安全提示。

## 事件写入与公开投影

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 内部事件追加 | `backend/app/modules/agent/events.py` | `EventStore.append` | L24-L69 | run 事件类型和 payload | 分配 run 内 sequence，写入 `agent_events`，并触发 thread 投影 | 内部事件事实 | `ThreadEventStore.project_run_event` |
| Thread 投影总入口 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event` | L103-L212 | `run.status_changed`、`step.*`、`tool.*`、`message.*`、`run.failed` | 把内部事件映射成统一的公开 thread 事件，并保持 cursor 单调递增 | `agent_thread_events` | SSE / 时间线刷新 |
| 消息投影 | `backend/app/modules/agent/thread_events.py` | `_project_message_event` | L240-L346 | `message.delta`、`message.completed`、`message.failed` | 第一个 delta 创建 assistant item，后续 delta 追加正文；completed/failed 收敛状态 | 可恢复消息事实 | `AgentTimelineService.get_timeline` |
| 时间线快照构建 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService.get_timeline`、`message_view`、`_build_workflow_views` | L319-L572 | Thread 下消息、Run、步骤、事件、Artifact、审批 | 按 root run 聚合并重建消息、工作流步骤、活动与 Artifact | 刷新可恢复的 timeline snapshot | HTTP / 前端刷新 |
| SSE 消费 | `frontend/src/store/agent-context.tsx` | `AgentProvider.connectThreadStream` | L246-L362 | thread ID、cursor | 连接 EventSource，实时归并消息/工作流事件，必要时回拉快照 | 浏览器状态 | `timeline-state` reducer |

## 失败错误如何公开且不覆盖正文

| 执行阶段 | 文件 | 符号 | 代码范围 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 错误分类 | `backend/app/modules/agent/public_errors.py` | `classify_agent_error` / `public_error_message` | L39-L96 | worker 得到异常或刷新时重建错误文案 | 生成稳定 `error_code` 与安全中文提示，不暴露供应商敏感原文 | Worker / timeline 刷新 |
| 失败持久化 | `backend/app/modules/agent/worker.py` | `AgentWorker._record_failure` | L269-L304 | Run 执行失败 | `run.error_message` 保留原始错误；metadata 和事件写稳定码与公开消息 | 管理端审计 + 用户端安全错误 |
| 失败消息投影 | `backend/app/modules/agent/thread_events.py` | `_project_message_event`（failed 分支） | L316-L346 | 失败前已有 partial 正文 | 不再把失败文案写进 `content_text`，只更新状态和错误字段 | 刷新后仍保留 partial 正文 |
| 刷新恢复 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService.message_view` | L553-L572 | 页面刷新读取 `AgentMessage` | 用持久化的 `error_code` 重建 `error_message`，无需新增列 | `TimelineResponse` |
| 前端失败归并 | `frontend/src/features/agent/timeline-state.ts` | `applyMessageEvent`（failed 分支） | L142-L162 | 实时 `message.failed` | 同时保留 content、error_code、error_message | React 消息状态 |
| 前端失败显示 | `frontend/src/features/agent/ConversationStream.tsx` | `TimelineItemView`（failed 分支） | L52-L82 | assistant status 为 failed | 有正文时正文与红字原因分开显示；无正文只显示一次原因 | 用户对话页面 |

## 工作流步骤与活动为什么刷新后不丢

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| Artifact 工厂契约 | `backend/app/modules/agent/workflows/contracts.py` | `NodeResult.success` | L27-L48 | render 节点可通过统一工厂方法同时返回 `output`、`next_node` 和最终 `artifact`，避免 completed 之前丢失产物 |
| 节点进度持久化 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | L61-L212 | 每个 step 的开始、完成、失败都写 `agent_steps` 和 `agent_events`，并在关键边界 commit |
| 当前公开步骤 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L127-L209 | run 进入 running 和完成时维护 `current_public_step`、最终 artifact 和消息完成事件 |
| 最终正文与产物落库 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L183-L251 | workflow 返回 completed 后创建 `AgentArtifact`、写 `artifact.rendered` / `message.completed` / `run.completed`，让刷新可恢复最终正文和 artifact |
| 时间线步骤重建 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._build_workflow_views` | L399-L538 | 按 root run 聚合 child runs、steps、tool events、pending input 和 approvals |
| 活动按 ID 归并 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._activity_views` | L506-L538 | `tool.called` + `tool.result` 共享同一 `activity_id` 时可在刷新后重建成一个活动 |

## 回归测试入口

| 验证目标 | 文件 | 符号 | 代码范围 | 覆盖内容 |
| --- | --- | --- | --- | --- |
| 工作流公开步骤持久化 | `backend/tests/test_agent_workflow_engine.py` | `test_engine_persists_public_step_for_timeline_snapshot` | L72-L143 | 校验 step.started / step.completed 真实提交后，时间线刷新仍能恢复当前步骤 |
| Explain 最终 Artifact 不再丢失 | `backend/tests/test_agent_workflow_engine.py` | `test_explain_workflow_keeps_artifact_through_render_and_completion` | L146-L257 | 真正执行 explain workflow 到 `render_artifact -> completed`，确认 `NodeResult.success(..., artifact=...)` 可把 artifact 保留到最终结果 |
| Explain 无资料回退在 worker 持久化后仍可刷新恢复 | `backend/tests/test_agent_explain_worker.py` | `test_worker_persists_zero_hit_fallback_answer_without_citations`、`test_worker_persists_retrieval_error_fallback_answer_without_citations` | L123-L264 | 真实执行 `AgentWorker.process_run`，覆盖零命中和检索异常两条路径的活动卡片、artifact、最终消息与线程刷新恢复 |

## 当前整改关注点

1. `FLOW-001` 已在 2026-07-25 完成：workflow 最终 Artifact 通过 `NodeResult.success(..., artifact=...)` 进入 `context.artifacts`，Explain 渲染链已补回归测试。
2. `ACT-001` 要稳定逻辑 `activity_id`，否则即便后端只是在重试，时间线刷新和 SSE 都会显示成多张活动卡片。
3. `EXP-001` 已在 2026-07-26 补齐 worker 级验收：零命中和工具异常两条公开路径都会保留正确活动语义，且最终正文、artifact 与空 citations 均可在刷新后恢复。

## 下一步阅读

- 检索和工具当前实现，见 `implementation/rag-and-tools.md`。
- 管理端如何读取这些事实并按 Thread/turn 展示，见 `implementation/admin-observability.md`。
