# Router、上下文与当前记忆边界

## 适用场景

本分卷解释当前 Router 如何消费历史消息和 Artifact、`context_builder` 现在能提供什么，以及为什么任务单里把
“分层长期记忆”列为后续整改项。

## 当前上下文构建链

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 上下文数据结构 | `backend/app/modules/agent/context_builder.py` | `AgentRunContext` | 线程、消息、Artifact、选择审计 | 定义当前可传给 Router/child workflow 的消息、Artifact、active topic、独立请求和 snapshot ID | `AgentRunContext` | `ThreadContextBuilder.build` |
| 历史、Artifact 与热状态选择 | `backend/app/modules/agent/context_builder.py` | `ThreadContextBuilder.build`、`_load_thread_memory_state` | thread ID、root run、token budget、可见 Artifact、线程热状态 | 选择近期消息、当前轮前后的 Artifact、待处理交互，并读取线程 `active_topic` / `memory_state_version` | 受控上下文与热状态 | `_route_node` |
| 独立请求、约束、快照与显式主题事实 | `backend/app/modules/agent/turn_understanding.py`（L112-L193、L196-L281）；`backend/app/modules/agent/memory_projection.py`（L67-L122） | `_parse_chapter_ordinal`、`_derive_constraints`、`build_turn_understanding`、`ensure_turn_memory_snapshot`、`project_topic_confirmed_fact` | 当前输入、context refs、线程 active topic | 确定性生成 `TurnUnderstanding`，抽取难度与“第 N 章”约束并补全独立请求；创建/复用 snapshot、递增热状态版本；若首个主题来自本轮显式 `context_ref`，在 Router 模型调用前按 Run 幂等写 `topic_confirmed`。仅从 `thread_memory` 继承时不重复冒充用户确认 | 含 `difficulty:*` / `chapter_ordinal:*` 的理解、snapshot、热状态与可选线程主题事实；事实/数据库错误与 route 节点同事务传播 | `_route_node` 的 Router 调用 |
| Conversation 路由 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | 当前输入、受控上下文、独立请求、允许 action | 先构建并持久化 `TurnUnderstanding`，再把 `standalone_request` 和历史交给 Router，决定 direct/explain/validate/grade/plan/clarify | `RouterDecision`、run metadata 中的 `memory_snapshot_id` / `turn_understanding` | `_direct_answer_node` / `_dispatch_workflow_node` |
| Child 元数据交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | 父 run 的上下文审计、active topic、独立请求和模型配置 | 复制筛选后的消息/Artifact ID、`active_topic`、`standalone_request`、`memory_snapshot_id` 和模型配置 ID，仍不复制敏感密钥 | child run metadata | `_dispatch_workflow_node` |
| Child Run 派发 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | Router action、parent/root run、独立请求 | 创建 child run 和 workflow 时间线项；child run 的 `input_message` 改为 `standalone_request`，从而不再只依赖原始短句和消息 ID | queue 中的 child run | worker |

## 已落库的记忆基础契约

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 记忆能力与分区命名 | `backend/app/modules/agent/memory_contracts.py` | `MemoryPartition`、`MemoryNeed`、`MemoryFactType`、`MEMORY_NEED_PARTITIONS` | 任务单中的分层记忆边界 | 固化九类分区、六类能力标签与五类事实事件类型，明确能力声明不绑定 explain/validate/grade/plan 名称 | 稳定命名契约 | 快照选择器 / 完成事实投影 / workflow adapter |
| 记忆 ORM 基础表 | `backend/app/modules/agent/models.py` | `AgentThreadMemoryState`、`AgentMemoryEvent`、`AgentMemorySnapshot`、`AgentMemorySnapshotItem`、`AgentMemoryUpdateOutbox`、`UserLearningMastery`、`AgentConversationSummary`、`AgentMemoryItem` | 线程、Run、用户和未来投影事件 | 定义热状态、事件、快照、Outbox、掌握度、对话摘要和长期记忆项的单表契约 | Base metadata 中的记忆表结构 | Alembic 迁移 / 后续 selector 与 projector |
| 首个 Bundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L128-L211、L264-L423） | `_load_excluded_question_ids`、`_load_chapter_ids`、`_resolve_explicit_chapter_ids`、`_load_unique_weak_topic`、`load_practice_bundle`、`build_practice_query`、`build_practice_filters` | child run、snapshot/items、近期 practice 事实、掌握度、显式章节序号 | 校验归属并组装 `PracticeBundle`；显式 `chapter_ordinal:*` 只在知识点唯一确定学科时按 active 一级标准章节顺序解析，成功后覆盖知识点默认章节并标记 `chapter_scope_source=explicit`；不能解析则写 `unresolved_constraints`；无显式章节才读取知识点章节关系。其余继续装载难度、Artifact、排除集与唯一薄弱点 | 含 `chapter_ids` / `chapter_scope_source` / `unresolved_constraints` 的 `PracticeBundle` | `validate._load_learning_evidence_node` / `_question_discovery_node` |
| 可信事实与 Outbox 生产 | `backend/app/modules/agent/memory_projection.py`（L27-L413） | `_ensure_memory_update_outbox`、`project_topic_confirmed_fact`、`project_completed_run_facts`、`_record_explanation_artifact_created`、`_record_plan_confirmed`、`_record_practice_artifact_created`、`_record_grade_result_confirmed` | snapshot 显式主题，或 completed run 的已持久化 Artifact | 写五类事实后在同一事务确保 pending Memory Outbox；新事实先 flush 取得 ID，重放已有事实会补建缺失任务；SAVEPOINT 收敛数据库唯一键并发冲突，不污染外层 Run 事务 | `agent_memory_events` 与 `agent_memory_update_outbox` 原子可见；事件载荷只含 memory event ID/fact type；不满足事实条件时两者均不写 | 后续 Memory Outbox 消费者 |
| Memory Outbox 消费与运行时接入 | `backend/app/modules/agent/memory_outbox.py`（L25-L279）；`backend/app/modules/agent/worker.py`（L368-L392） | `MemoryOutboxStore.scan_due`、`MemoryOutboxStore.claim`、`MemoryOutboxStore.complete`、`MemoryOutboxStore.fail`、`MemoryOutboxConsumer.process_claimed`、`MemoryOutboxConsumer.scan_and_process`、`AgentWorker.start` | pending 或租约过期的 processing 任务、worker ID、重试与租约参数 | Agent Worker 每轮在 Run Outbox 后扫描记忆任务；消费者以条件 UPDATE 原子认领，`scheduled_at` 在 processing 状态表示租约截止；投影前校验 Outbox 与事实的 run/thread/user/type 归属并在 SAVEPOINT 内调用 projector | 成功写 completed；异常只回滚派生投影并延迟重试/最终 failed，原 completed Run 不变；完成/失败均校验 worker 所有权 | `project_trusted_memory_event` |
| 可信事实派生记忆项 | `backend/app/modules/agent/memory_item_projection.py`（L14-L165） | `_upsert_memory_item`、`_project_topic_context`、`_project_confirmed_plan_goal`、`project_trusted_memory_event` | 已通过 Outbox 归属校验的五类事实；Plan 额外读取同 Run Artifact | `topic_confirmed` 按事实幂等键 upsert 线程级 `topic_context`；`plan_confirmed` 再校验用户级作用域、Artifact 类型和 approval ID，提炼标题/目标为用户级 `learning_goal`；Explain/Practice/Grade 保持 Artifact、事实事件和掌握度为权威落点，不复制正文 | `agent_memory_items` 与 Outbox completed 同事务可见；格式/归属错误进入 Outbox 重试，不改 Run | 后续 selector / 摘要与 Embedding projector |

## 当前能力边界

1. 当前系统已经能选取近期消息、Artifact、待处理交互，并在 Router 前读取线程热状态中的 `active_topic`。
2. `MEM-003` 的第一阶段已打通：conversation run 会生成确定性 `TurnUnderstanding`、创建不可变 snapshot，并把 `standalone_request` 与 `memory_snapshot_id` 传给 child run。
3. `MEM-004` / `MEM-005` 的第二阶段已打通到过滤参数和首个澄清闭环：Validate 会从 snapshot 装载 `PracticeBundle`，继承主题、别名、难度约束、知识点 ID 和选中的 Artifact，并据此生成检索 query 与 retrieval filters；若缺少主题，会创建 `practice_topic` 输入项并在用户补充后从断点继续检索。
4. 真实排除集已闭环：Validate 完成时写 `practice_artifact_created` 事实事件，下一次练习通过 `PracticeBundle.excluded_question_ids` 自动排除近期已出过的题。
5. 掌握度已形成安全的读写边界：无主题时按“唯一低掌握度知识点”回退练习主题；携带真实结构化评分证据的 Feedback Artifact 能写 `grade_result_confirmed` 并更新 `user_learning_mastery`。当前 P1 Grade 仍只有固定反馈，不生产 verdict，因此真实线上数据源仍需后续评分服务接入。
6. 本轮显式 `context_ref` 主题已在 Router 调用前写成 `topic_confirmed`；因此 Router/模型失败只会阻止 Agent 输出，不会丢失用户已表达的主题。继承的热状态主题不会重复产生确认事件。
7. Explain 成功产出 Artifact 时已写 `explanation_artifact_created`，包括零命中/检索异常后的无引用 fallback；事件不复制正文，也不修改掌握度。
8. Plan 只有在审批记录属于同一 Run、状态为 approved，且成功生成携带 approval ID 的 Artifact 后才写用户级 `plan_confirmed`；拒绝、pending、缺失审批或旁路恢复均不写长期目标。
9. 当前仍未实现歧义场景下的结构化指代消解模型，也还没有把历史摘要做成可复用的 bundle。

## 现状问题与整改入口

| 问题 | 当前代码锚点 | 现状 | 任务单对应项 |
| --- | --- | --- | --- |
| 主题继承还未消费掌握度/摘要等深层记忆 | `backend/app/modules/agent/context_builder.py` `ThreadContextBuilder.build` | 已能读取 `active_topic`，但还没有选择 `user_learning_mastery`、历史摘要或排除集 | `MEM-003`、`MEM-004` |
| 只有 Validate 已接入 bundle 化记忆 | `backend/app/modules/agent/memory_selector.py` `load_practice_bundle`；`backend/app/modules/agent/workflows/validate.py` `_load_learning_evidence_node` | Validate 已能消费 `PracticeBundle`；Explain / Grade / Plan 仍未声明并装载各自的 bundle | `MEM-004`、`MEM-005` |
| 掌握度投影已通但真实评分源未接入 | `backend/app/modules/agent/workflows/grade.py::_objective_grade_node`（L34-L51）、`_render_artifact_node`（L108-L137）；`backend/app/modules/agent/memory_projection.py::_record_grade_result_confirmed`（L308-L413） | 投影器只接受结构化真实评分证据并能安全更新掌握度；当前 P1 Grade 仍不产生 verdict | `MEM-004`、`MEM-006` |
| 异步派生仍缺摘要与 Embedding | `backend/app/modules/agent/memory_item_projection.py::project_trusted_memory_event`（L153-L165） | Memory Outbox 已在 Agent Worker 中运行，并物化显式主题与批准计划；Explain/Practice/Grade 只确认其既有权威落点。历史对话摘要、Embedding 和偏好候选仍未实现 | `MEM-006`、`MEM-007` |

## 设计约束

1. 原始消息和 Artifact 仍是事实源；未来长期记忆必须由它们和真实评分/审批事件投影而来。
2. Router 历史筛选使用 `token_budget=4096` 是“选择多少历史”的预算，不是模型最终输入加输出的全局上限。
3. 后续记忆闭环必须围绕事实类型和 `MemoryNeed` 稳定，而不是把 explain / validate / grade / plan 写死进存储结构。

## 下一步阅读

- 检索与 explain/validate 的现状，见 `implementation/rag-and-tools.md`。
- 模型调用预算、流式正文和 child run 继承模型配置，见 `implementation/model-runtime-streaming.md`。
