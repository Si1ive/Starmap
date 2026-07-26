# Router、上下文与当前记忆边界

## 适用场景

本分卷解释当前 Router 如何消费历史消息和 Artifact、`context_builder` 现在能提供什么，以及为什么任务单里把
“分层长期记忆”列为后续整改项。

## 当前上下文构建链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 上下文数据结构 | `backend/app/modules/agent/context_builder.py` | `AgentRunContext` | L82-L121 | 线程、消息、Artifact、选择审计 | 定义当前可传给 Router/child workflow 的消息、Artifact、active topic、独立请求和 snapshot ID | `AgentRunContext` | `ThreadContextBuilder.build` |
| 历史、Artifact 与热状态选择 | `backend/app/modules/agent/context_builder.py` | `ThreadContextBuilder.build`、`_load_thread_memory_state` | L138-L256、L489-L501 | thread ID、root run、token budget、可见 Artifact、线程热状态 | 选择近期消息、当前轮前后的 Artifact、待处理交互，并读取线程 `active_topic` / `memory_state_version` | 受控上下文与热状态 | `_route_node` |
| 独立请求与快照 | `backend/app/modules/agent/turn_understanding.py` | `build_turn_understanding`、`ensure_turn_memory_snapshot` | L81-L201 | 当前输入、context refs、线程 active topic | 确定性生成 `TurnUnderstanding`，对“给我出道题”这类泛化输入补全 `standalone_request`，并创建 `agent_memory_snapshots` / `agent_memory_snapshot_items`、递增热状态版本 | `TurnUnderstanding`、`snapshot_id`、更新后的热状态 | `_route_node` |
| Conversation 路由 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | L46-L121 | 当前输入、受控上下文、独立请求、允许 action | 先构建并持久化 `TurnUnderstanding`，再把 `standalone_request` 和历史交给 Router，决定 direct/explain/validate/grade/plan/clarify | `RouterDecision`、run metadata 中的 `memory_snapshot_id` / `turn_understanding` | `_direct_answer_node` / `_dispatch_workflow_node` |
| Child 元数据交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | L183-L209 | 父 run 的上下文审计、active topic、独立请求和模型配置 | 复制筛选后的消息/Artifact ID、`active_topic`、`standalone_request`、`memory_snapshot_id` 和模型配置 ID，仍不复制敏感密钥 | child run metadata | `_dispatch_workflow_node` |
| Child Run 派发 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | L212-L260 | Router action、parent/root run、独立请求 | 创建 child run 和 workflow 时间线项；child run 的 `input_message` 改为 `standalone_request`，从而不再只依赖原始短句和消息 ID | queue 中的 child run | worker |

## 已落库的记忆基础契约

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 记忆能力与分区命名 | `backend/app/modules/agent/memory_contracts.py` | `MemoryPartition`、`MemoryNeed`、`MEMORY_NEED_PARTITIONS` | L8-L65 | 任务单中的分层记忆边界 | 固化九类分区与六类能力标签，明确能力声明不绑定 explain/validate/grade/plan 名称 | 稳定命名契约 | 快照选择器 / workflow adapter |
| 记忆 ORM 基础表 | `backend/app/modules/agent/models.py` | `AgentThreadMemoryState`、`AgentMemoryEvent`、`AgentMemorySnapshot`、`AgentMemorySnapshotItem`、`AgentMemoryUpdateOutbox`、`UserLearningMastery`、`AgentConversationSummary`、`AgentMemoryItem` | L487-L754 | 线程、Run、用户和未来投影事件 | 定义热状态、事件、快照、Outbox、掌握度、对话摘要和长期记忆项的单表契约 | Base metadata 中的记忆表结构 | Alembic 迁移 / 后续 selector 与 projector |

## 当前能力边界

1. 当前系统已经能选取近期消息、Artifact、待处理交互，并在 Router 前读取线程热状态中的 `active_topic`。
2. `MEM-003` 的第一阶段已打通：conversation run 会生成确定性 `TurnUnderstanding`、创建不可变 snapshot，并把 `standalone_request` 与 `memory_snapshot_id` 传给 child run。
3. 当前仍未实现歧义场景下的结构化指代消解模型，也还没有把掌握度、历史摘要和排除集真正做成按 `MemoryNeed` 选择的 bundle。

## 现状问题与整改入口

| 问题 | 当前代码锚点 | 现状 | 任务单对应项 |
| --- | --- | --- | --- |
| 主题继承还未消费掌握度/摘要等深层记忆 | `backend/app/modules/agent/context_builder.py` `ThreadContextBuilder.build` L138-L256 | 已能读取 `active_topic`，但还没有选择 `user_learning_mastery`、历史摘要或排除集 | `MEM-003`、`MEM-004` |
| child workflow 尚未读取 bundle 化记忆 | `backend/app/modules/agent/workflows/conversation.py` `_child_context_metadata` L183-L209 | 现在已传 `snapshot_id` 和 `standalone_request`，但 Validate/Explain 还没有真正按 `MemoryNeed` 读取 snapshot items | `MEM-004`、`MEM-005` |
| Validate 仍主要使用硬编码薄弱点 | `backend/app/modules/agent/workflows/validate.py` `_load_learning_evidence_node` / `_question_discovery_node` L17-L52 | 不能把“讲解后出题”稳定落到当前主题 | `MEM-005` |
| 长期回写尚未实现 | `backend/app/modules/agent/worker.py` `AgentWorker.process_run` L150-L222 | Run 完成时只落消息/Artifact/Event，没有 Memory Outbox | `MEM-006` |

## 设计约束

1. 原始消息和 Artifact 仍是事实源；未来长期记忆必须由它们和真实评分/审批事件投影而来。
2. Router 历史筛选使用 `token_budget=4096` 是“选择多少历史”的预算，不是模型最终输入加输出的全局上限。
3. 后续记忆闭环必须围绕事实类型和 `MemoryNeed` 稳定，而不是把 explain / validate / grade / plan 写死进存储结构。

## 下一步阅读

- 检索与 explain/validate 的现状，见 `implementation/rag-and-tools.md`。
- 模型调用预算、流式正文和 child run 继承模型配置，见 `implementation/model-runtime-streaming.md`。
