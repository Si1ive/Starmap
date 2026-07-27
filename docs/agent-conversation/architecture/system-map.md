# Agent 对话模块系统边界

## 适用场景

本分卷说明 Agent 对话模块当前的系统目标、边界划分和数据所有权，帮助维护者先建立“谁负责什么”的总体图，
再进入主链或具体实现分卷。

## 模块目标

1. 用户端支持多轮对话、工作流卡片、SSE 增量更新和刷新恢复。
2. 后端把一次用户输入拆成用户消息、根 Run、可选 child Run、事件、Artifact 和公开时间线。
3. 管理端能够从 Thread 维度审计每轮消息、Run、步骤、工具活动、审批和产物。

## 代码边界与所有权

| 系统边界 | 文件 | 符号 | 职责 |
| --- | --- | --- | --- |
| 用户端页面入口 | `frontend/src/pages/AgentPage.tsx` | `AgentPage` | 负责 thread 选择、发送消息、时间线加载、SSE 生命周期和空会话首页/会话内两种布局 |
| 用户端状态容器 | `frontend/src/store/agent-context.tsx` | `AgentProvider` | 统一维护 timeline、EventSource、turn 提交、工作流交互和错误恢复 |
| 用户端 HTTP/SSE 契约 | `frontend/src/api/agent.ts` | `createTurn`、`listSelectableAgentModels`、`streamThreadEvents` | 定义 Agent 用户侧接口和事件流契约 |
| HTTP 入口 | `backend/app/modules/agent/router.py` | `create_turn`、`stream_thread_events`、`submit_input_answer` | 认证、参数校验、调用时间线服务和对外提供 SSE |
| 对话时间线 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService.create_turn`、`AgentTimelineService.get_timeline` | 原子创建用户消息/root run/outbox，聚合消息、工作流、活动、审批和 Artifact 快照 |
| Run 事件投影 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event` | 把内部 Run 事件投影成对外可见的 thread 事件，并统一 cursor |
| 执行调度 | `backend/app/modules/agent/outbox.py`、`backend/app/modules/agent/worker.py` | `OutboxStore.enqueue`、`AgentWorker.process_run` | 使用 outbox 保证可靠执行，串行处理同一线程下的 Run，维护完成/失败状态 |
| 工作流引擎 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | 逐节点执行 workflow，写 step 事件，保存 WAITING checkpoint，向 worker 返回最终 NodeResult |
| Conversation 路由 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node`、`_dispatch_workflow_node` | 选择 direct answer 或 explain/validate/grade/plan child Run，并绑定本轮模型配置 |
| 模型运行时 | `backend/app/modules/agent/model_runtime/router.py`、`answer.py`、`explanation.py`、`preference_extractor.py` | `RouterRuntime.decide`、`DirectAnswerRuntime.answer`、`ExplanationRuntime.generate`、`PreferenceExtractionRuntime.extract` | 负责结构化路由、普通回答流式生成、explain 双阶段调用，以及只产出 pending 记录的偏好候选抽取 |
| 上下文选择 | `backend/app/modules/agent/context_builder.py` | `ThreadContextBuilder.build` | 从消息、Artifact 和 root run 历史中选取本轮上下文，并记录丢弃审计 |
| 检索与工具 | `backend/app/modules/agent/tools/retrieve_knowledge.py`、`backend/app/modules/retrieval/service.py` | `retrieve_knowledge`、`RetrievalService.search_with_outline_expansion` | explain/validate 的知识检索入口，负责公开工具活动和真实混合检索 |
| 领域持久化 | `backend/app/modules/agent/models.py` | `AgentThread`、`AgentRun`、`AgentEvent`、`AgentArtifact`、`AgentPreferenceCandidate` 等模型 | 定义对话、执行事实、审批、候选治理、输入和 outbox 的结构与约束 |
| 管理员监控 | `backend/app/modules/agent/admin_router.py` | `list_all_runs`、`get_run_detail` | 以 Thread 为主实体聚合会话统计、详情和多轮运行事实 |
| 管理员页面 | `frontend-admin/src/pages/AgentRunsPage.tsx`、`AgentRunDetailPage.tsx`、`AgentModelsPage.tsx` | `AgentRunsPage`、`AgentRunDetailPage`、`AgentModelsPage` | 负责会话监控、单轮审计和模型配置管理 |

## 数据来源与事实边界

1. `agent_messages` 保存用户与 assistant 的最终消息正文；`message.delta` 只作为中间事件，不直接成为长期事实。
2. `agent_runs`、`agent_steps`、`agent_events` 描述执行链；`agent_thread_events` 是对用户端和管理端公开消费的投影。
3. `agent_artifacts` 保存 explain / practice / feedback / plan 等结构化产物；时间线刷新时以数据库快照重建。
4. `agent_outbox` 是执行可靠性的边界；HTTP 事务只负责创建事实，不直接调用 LLM。
5. 检索正文、章节扩展和来源信息由 `retrieval_segments`、`documents` 与 Qdrant collection 共同提供。

## 下一步阅读

- 需要看“用户发起一轮对话直到前端显示结果”的完整顺序，转到 `architecture/conversation-mainline.md`。
- 需要看 explain/validate/grade/plan 的分支和旁路，转到 `architecture/workflow-branches.md`。
- 需要看管理端与模型配置链路，转到 `architecture/admin-and-model-config.md`。
