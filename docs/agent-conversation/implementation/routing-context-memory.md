# Router、上下文与当前记忆边界

## 适用场景

本分卷解释当前 Router 如何消费历史消息和 Artifact、`context_builder` 现在能提供什么，以及为什么任务单里把
“分层长期记忆”列为后续整改项。

## 当前上下文构建链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 上下文数据结构 | `backend/app/modules/agent/context_builder.py` | `AgentRunContext` | L82-L116 | 线程、消息、Artifact、选择审计 | 定义当前可传给 Router/child workflow 的消息、Artifact 和丢弃记录 | `AgentRunContext` | `ThreadContextBuilder.build` |
| 历史与 Artifact 选择 | `backend/app/modules/agent/context_builder.py` | `ThreadContextBuilder.build` | L133-L246 | thread ID、root run、token budget、可见 Artifact | 选择近期消息、当前轮前后的 Artifact，并记录被丢弃的消息/产物 ID | 受控上下文与审计信息 | `_route_node` |
| Conversation 路由 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | L45-L100 | 当前输入、受控上下文、允许 action | 把筛选后的历史交给 Router，决定 direct/explain/validate/grade/plan/clarify | `RouterDecision` | `_direct_answer_node` / `_dispatch_workflow_node` |
| Child 元数据交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | L163-L186 | 父 run 的上下文审计与模型配置 | 只复制已选消息/Artifact 的 ID 和模型配置 ID，不复制完整主题快照 | child run metadata | `_dispatch_workflow_node` |
| Child Run 派发 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | L189-L234 | Router action、parent/root run、触发消息 | 创建 child run 和 workflow 时间线项；当前 child 侧主要依赖输入消息和显式参数，不消费独立记忆快照 | queue 中的 child run | worker |

## 当前能力边界

1. 当前系统已经能选取近期消息和 Artifact，足以支撑 direct answer 与“本轮紧邻事实”的 explain / plan 等场景。
2. 当前系统还没有把“活跃主题、待处理任务、用户偏好、学习掌握度、历史主题摘要”冻结成可复用快照。
3. child run 当前继承的是“被选中的消息/Artifact ID + 模型配置 ID”，不是任务单规划中的 `TurnUnderstanding` /
   `snapshot_id`。

## 现状问题与整改入口

| 问题 | 当前代码锚点 | 现状 | 任务单对应项 |
| --- | --- | --- | --- |
| 主题继承只靠消息历史 | `backend/app/modules/agent/context_builder.py` `ThreadContextBuilder.build` L133-L246 | 没有显式 `active_topic`、主题栈或独立请求 | `MEM-001`、`MEM-003` |
| child workflow 只拿已选消息 ID | `backend/app/modules/agent/workflows/conversation.py` `_child_context_metadata` L163-L186 | Validate 无法直接消费主题快照、排除集和约束 | `MEM-003`、`MEM-004` |
| Validate 仍主要使用硬编码薄弱点 | `backend/app/modules/agent/workflows/validate.py` `_load_learning_evidence_node` / `_question_discovery_node` L17-L52 | 不能把“讲解后出题”稳定落到当前主题 | `MEM-005` |
| 长期回写尚未实现 | `backend/app/modules/agent/worker.py` `AgentWorker.process_run` L150-L222 | Run 完成时只落消息/Artifact/Event，没有 Memory Outbox | `MEM-006` |

## 设计约束

1. 原始消息和 Artifact 仍是事实源；未来长期记忆必须由它们和真实评分/审批事件投影而来。
2. Router 历史筛选使用 `token_budget=4096` 是“选择多少历史”的预算，不是模型最终输入加输出的全局上限。
3. 后续记忆闭环必须围绕事实类型和 `MemoryNeed` 稳定，而不是把 explain / validate / grade / plan 写死进存储结构。

## 下一步阅读

- 检索与 explain/validate 的现状，见 `implementation/rag-and-tools.md`。
- 模型调用预算、流式正文和 child run 继承模型配置，见 `implementation/model-runtime-streaming.md`。
