# Router、上下文与当前记忆边界

## 适用场景

本分卷解释当前 Router 如何消费历史消息和 Artifact、`context_builder` 现在能提供什么，以及为什么任务单里把
“分层长期记忆”列为后续整改项。

## 当前上下文构建链

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 上下文数据结构 | `backend/app/modules/agent/context_builder.py`（L53-L62、L84-L110） | `ArtifactContext`、`AgentRunContext` | 线程、消息、Artifact、选择审计 | 定义当前可传给 Router/child workflow 的消息、Artifact 摘要及结构化实体引用、active topic、独立请求和 snapshot ID | `AgentRunContext` | `ThreadContextBuilder.build` |
| 历史、Artifact 与热状态选择 | `backend/app/modules/agent/context_builder.py`（L381-L449、L661-L694） | `ThreadContextBuilder._load_artifacts`、`ThreadContextBuilder._extract_artifact_reference_entities` | thread ID、root run、token budget、可见 Artifact 的 `artifact_type` / `content_json` | 按用户、线程、可见性和预算选择近期 Artifact；仅从 practice 产物的 `content.question_ids` 提取去重后的 question 引用，绝不从标题或摘要反推 ID | 按时间升序的 `ArtifactContext`，question 引用携带来源 Artifact ID；查询/结构错误随上下文构建传播 | `build_turn_understanding` |
| 独立请求、约束与候选选择 | `backend/app/modules/agent/turn_understanding.py`（L126-L184、L187-L264、L267-L345、L347-L403） | `_parse_chapter_ordinal`、`_derive_constraints`、`_resolve_question_artifact_reference`、`build_ambiguous_referent_candidates`、`hydrate_referent_candidate_labels`、`apply_referent_resolution`、`build_turn_understanding` | 当前输入、context refs、近期 Artifact 结构化引用、线程 active topic、active 题库实体 | 先确定性生成 `TurnUnderstanding`；最新 practice 只有一个 question ID 时直接解析，多题或裸词“这个”才构造候选。question 候选必须从题库水合 active 题面，失效/缺失实体会被丢弃；模型选择或 unresolved 审计再合入理解 | 含约束、`reference_sources` 与可选 `reference_resolution` 的理解；数据库错误直接传播 | `ensure_turn_memory_snapshot` |
| 结构化指代模型 | `backend/app/modules/agent/model_runtime/referent.py`（L22-L169） | `ReferentCandidate`、`ReferentResolution`、`ReferentRuntime.resolve` | 确定性阶段仍有歧义且存在带语义标签的服务端候选 | 使用 Run 绑定模型输出 resolved/unresolved；resolved 只能原样选择候选键，返回后再次白名单校验，低于 0.8 降级 unresolved；候选文本按不可信数据处理 | 合法候选选择或 unresolved；非法键/缺标签/模型异常向 route 节点传播 | `apply_referent_resolution` |
| Conversation 路由、快照与显式主题事实 | `backend/app/modules/agent/workflows/conversation.py`（L50-L151）；`backend/app/modules/agent/turn_understanding.py`（L405-L490）；`backend/app/modules/agent/memory_projection.py`（L67-L122） | `_route_node`、`ensure_turn_memory_snapshot`、`project_topic_confirmed_fact` | 完整 TurnUnderstanding、允许 action | 仅在存在歧义候选时先调用指代模型，然后创建不可变 snapshot、递增热状态版本并用 standalone request 调 Router；显式 context ref 主题在 Router 前按 Run 幂等写事实，继承主题不冒充用户确认 | `RouterDecision`、含 `memory_snapshot_id` / `turn_understanding` 的 run metadata、热状态与可选主题事实；异常交给 workflow engine | `_direct_answer_node` / `_dispatch_workflow_node` |
| Child 元数据交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | 父 run 的上下文审计、active topic、独立请求和模型配置 | 复制筛选后的消息/Artifact ID、`active_topic`、`standalone_request`、`memory_snapshot_id` 和模型配置 ID，仍不复制敏感密钥 | child run metadata | `_dispatch_workflow_node` |
| Child Run 派发 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | Router action、parent/root run、独立请求 | 创建 child run 和 workflow 时间线项；child run 的 `input_message` 改为 `standalone_request`，从而不再只依赖原始短句和消息 ID | queue 中的 child run | worker |

## 已落库的记忆基础契约

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 记忆能力与分区命名 | `backend/app/modules/agent/memory_contracts.py` | `MemoryPartition`、`MemoryNeed`、`MemoryFactType`、`MEMORY_NEED_PARTITIONS` | 任务单中的分层记忆边界 | 固化九类分区、六类能力标签与五类事实事件类型，明确能力声明不绑定 explain/validate/grade/plan 名称 | 稳定命名契约 | 快照选择器 / 完成事实投影 / workflow adapter |
| 记忆 ORM 基础表 | `backend/app/modules/agent/models.py` | `AgentThreadMemoryState`、`AgentMemoryEvent`、`AgentMemorySnapshot`、`AgentMemorySnapshotItem`、`AgentMemoryUpdateOutbox`、`UserLearningMastery`、`AgentConversationSummary`、`AgentMemoryItem` | 线程、Run、用户和未来投影事件 | 定义热状态、事件、快照、Outbox、掌握度、对话摘要和长期记忆项的单表契约 | Base metadata 中的记忆表结构 | Alembic 迁移 / 后续 selector 与 projector |
| PracticeBundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L474-L797） | `_load_excluded_question_ids`、`_load_chapter_ids`、`_resolve_explicit_chapter_ids`、`_load_unique_weak_topic`、`load_practice_bundle`、`build_practice_query`、`build_practice_filters` | Validate child run、snapshot/items、近期 practice 事实、掌握度、显式章节序号 | 校验归属并组装 `PracticeBundle`；显式 `chapter_ordinal:*` 只在知识点唯一确定学科时按 active 一级标准章节顺序解析，成功后覆盖知识点默认章节并标记 `chapter_scope_source=explicit`；不能解析则写 `unresolved_constraints`；无显式章节才读取知识点章节关系。其余继续装载难度、Artifact、排除集与唯一薄弱点 | 含 `chapter_ids` / `chapter_scope_source` / `unresolved_constraints` 的 `PracticeBundle` | `validate._load_learning_evidence_node` / `_question_discovery_node` |
| PlanningBundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L59-L77、L185-L337） | `PlanningTarget`、`PlanningBundle`、`load_planning_bundle` | Plan child run、同用户 snapshot、最新 active `learning_goal`、真实评分掌握度 | 先校验 run/snapshot 用户归属；依次装载当前主题、最新批准计划的结构化 goals，以及 `mastery_score < 0.6 && evidence_count > 0` 的 active 知识点；按标题去重并记录来源/证据 ID，跨用户、superseded/deleted 或无真实题面的数据不进入 bundle | 可为空的最小 `PlanningBundle`；查询错误向 Plan 聚合节点传播 | `plan._aggregate_learning_evidence_node` |
| EvaluationBundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L80-L137、L340-L471） | `EvaluationQuestion`、`EvaluationBundle`、`_extract_user_answer`、`load_evaluation_bundle` | Grade child run、同用户/线程 snapshot、快照 question 引用、题库标准答案与本轮原始输入 | 先校验 Run 与 snapshot 作用域，再要求唯一 question ID；只读取 active、未拒绝且 `answer_source` 非 none 的题目，合并题目 JSON 与关系表知识点，并仅从显式“我的答案是 / 我选”句式提取作答。多题、缺题、缺答案或跨作用域均返回稳定 unresolved reason | 最小 `EvaluationBundle`，含题面、可信标准答案、知识点、来源 Artifact 和作答；不确定时无题面 Bundle | `grade._load_attempt_snapshot_node` |
| ConversationBundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L800-L956） | `ConversationTurn`、`ConversationBundle.to_message_history`、`load_conversation_bundle` | Explain child run、同用户/线程 snapshot、冻结消息/Artifact ID、结构化理解 | 只按 snapshot ID 集合重读 completed、visible 的用户/助手消息和非隐藏公开 Artifact，再校验用户/线程，不重新扩大最近历史；首次 query 按唯一 active question 题面→topic title+aliases→standalone request 决定 | Pydantic AI history、Artifact 摘要、结构化引用与确定性 `retrieval_query` | `explain._load_scope_node` |
| 可信事实与 Outbox 生产 | `backend/app/modules/agent/memory_projection.py`（L27-L413） | `_ensure_memory_update_outbox`、`project_topic_confirmed_fact`、`project_completed_run_facts`、`_record_explanation_artifact_created`、`_record_plan_confirmed`、`_record_practice_artifact_created`、`_record_grade_result_confirmed` | snapshot 显式主题，或 completed run 的已持久化 Artifact | 写五类事实后在同一事务确保 pending Memory Outbox；新事实先 flush 取得 ID，重放已有事实会补建缺失任务；SAVEPOINT 收敛数据库唯一键并发冲突，不污染外层 Run 事务 | `agent_memory_events` 与 `agent_memory_update_outbox` 原子可见；事件载荷只含 memory event ID/fact type；不满足事实条件时两者均不写 | 后续 Memory Outbox 消费者 |
| 摘要维护任务生产 | `backend/app/modules/agent/worker.py`（L185-L227）；`backend/app/modules/agent/conversation_summary.py`（L37-L69） | `AgentWorker.process_run`、`enqueue_conversation_summary_maintenance` | workflow 返回 completed，Run、Artifact、最终消息和 `run.completed` 已写入当前事务 | 每个成功 Run 按 `(run_id, conversation_summary_maintenance)` 幂等写一个 Memory Outbox；任务只携带类型和触发 Run ID，并发重复由 SAVEPOINT 与现有唯一键收敛 | Run 完成事实与 pending 摘要任务原子可见；失败 Run、waiting Run 不入队 | `MemoryOutboxConsumer.scan_and_process` |
| Memory Outbox 消费与运行时接入 | `backend/app/modules/agent/memory_outbox.py`（L30-L308）；`backend/app/modules/agent/worker.py`（L370-L394） | `MemoryOutboxStore.scan_due`、`MemoryOutboxStore.claim`、`MemoryOutboxStore.complete`、`MemoryOutboxStore.fail`、`MemoryOutboxConsumer.process_claimed`、`MemoryOutboxConsumer.scan_and_process`、`AgentWorker.start` | pending 或租约过期的 processing 任务、worker ID、重试与租约参数 | Agent Worker 每轮在 Run Outbox 后扫描记忆任务；消费者以条件 UPDATE 原子认领，`scheduled_at` 在 processing 状态表示租约截止；可信事实任务校验 memory event，摘要任务复核 completed Run 的 run/thread/user/type 后进入 maintainer | 成功写 completed；异常只回滚派生投影并延迟重试/最终 failed，原 completed Run 不变；完成/失败均校验 worker 所有权 | `project_trusted_memory_event` / `ConversationSummaryMaintainer.maintain` |
| 可信事实派生记忆项 | `backend/app/modules/agent/memory_item_projection.py`（L14-L166） | `_upsert_memory_item`、`_project_topic_context`、`_project_confirmed_plan_goal`、`project_trusted_memory_event` | 已通过 Outbox 归属校验的五类事实；Plan 额外读取同 Run Artifact | `topic_confirmed` 按事实幂等键 upsert 线程级 `topic_context`；`plan_confirmed` 再校验用户级作用域、Artifact 类型和 approval ID，把标题、周期和结构化 goals 写为用户级 `learning_goal`，供 PlanningBundle 下一轮消费；Explain/Practice/Grade 保持既有权威落点 | `agent_memory_items` 与 Outbox completed 同事务可见；格式/归属错误进入 Outbox 重试，不改 Run | PlanningBundle / 摘要与 Embedding projector |
| 历史消息增量摘要 | `backend/app/modules/agent/conversation_summary.py`（L72-L318） | `ConversationSummaryMaintainer.maintain`、`ConversationSummaryMaintainer._load_active_summary`、`ConversationSummaryMaintainer._load_raw_window_start`、`ConversationSummaryMaintainer._load_new_messages` | 已校验的 completed Run 摘要任务；同用户、同 active/archived 线程 | 保留最近 12 个用户轮次原文，只按活跃摘要末尾到近期窗口起点之间读取最多 24 条 visible、completed、非空 user/assistant 消息；把旧摘要与新增消息交给模型合并，不重读整线程原文；模型返回后短暂锁线程并复核活跃版本 | 新 `AgentConversationSummary` 保存稳定 sequence 范围、完整来源消息 ID 和递增版本；旧活跃摘要写 `superseded_by_id`，原 `AgentMessage` 不修改；作用域、模型或并发版本变化交给 Outbox 重试 | 后续历史摘要 Bundle / 向量化 |

## 当前能力边界

1. 当前系统已经能选取近期消息、Artifact、待处理交互，并在 Router 前读取线程热状态中的 `active_topic`。
2. `MEM-003` 已闭环：conversation run 先做确定性理解；最新单题直接绑定，裸词“这个”或多题场景才进入候选受限的结构化模型。模型只能选择带 active 题面/Artifact 摘要的候选键，低置信度保持 unresolved，最终选择与审计一并冻结到 snapshot 并传给 child run。
3. `MEM-004` / `MEM-005` 的第二阶段已打通到过滤参数和首个澄清闭环：Validate 会从 snapshot 装载 `PracticeBundle`，继承主题、别名、难度约束、知识点 ID 和选中的 Artifact，并据此生成检索 query 与 retrieval filters；若缺少主题，会创建 `practice_topic` 输入项并在用户补充后从断点继续检索。
4. 真实排除集已闭环：Validate 完成时写 `practice_artifact_created` 事实事件，下一次练习通过 `PracticeBundle.excluded_question_ids` 自动排除近期已出过的题。
5. 掌握度已形成首个真实读写闭环：无主题时按“唯一低掌握度知识点”回退练习主题；Grade 通过 `EvaluationBundle` 读取唯一可信客观题、标准答案和显式作答，确定性产生 verdict 后由 Feedback Artifact 写 `grade_result_confirmed` 并更新 `user_learning_mastery`。主观题、缺快照、歧义题目或无可信标准答案会在 Artifact 前失败，不写掌握度。
6. 本轮显式 `context_ref` 主题已在 Router 调用前写成 `topic_confirmed`；因此 Router/模型失败只会阻止 Agent 输出，不会丢失用户已表达的主题。继承的热状态主题不会重复产生确认事件。
7. Explain 成功产出 Artifact 时已写 `explanation_artifact_created`，包括零命中/检索异常后的无引用 fallback；事件不复制正文，也不修改掌握度。
8. Plan 只有在审批记录属于同一 Run、状态为 approved，且成功生成携带 approval ID 的 Artifact 后才写用户级 `plan_confirmed`；拒绝、pending、缺失审批或旁路恢复均不写长期目标。
9. PlanningBundle 已接入 Plan，EvaluationBundle 已接入 Grade，ConversationBundle 已接入 Explain；硬编码学习证据和固定批改反馈均已移除。Explain 的规划与生成模型使用 snapshot 冻结 history，首次检索使用冻结题面/主题 query。当前仍未实现历史摘要 bundle；结构化指代 unresolved 仍由 Router 决定是否澄清。
10. 历史摘要生产已形成异步最小闭环：成功 Run 只负责同事务入队，Outbox 在 Run 事务之外保留最近 12 轮并滚动合并更旧区间。摘要正文不会进入公开 SSE，也尚未被 ConversationBundle 召回；消费和 Embedding 属于后续提交。

## 现状问题与整改入口

| 问题 | 当前代码锚点 | 现状 | 任务单对应项 |
| --- | --- | --- | --- |
| 主题继承还未消费掌握度/摘要等深层记忆 | `backend/app/modules/agent/context_builder.py` `ThreadContextBuilder.build` | 已能读取 `active_topic`，但还没有选择 `user_learning_mastery`、历史摘要或排除集 | `MEM-003`、`MEM-004` |
| Explain、Validate、Grade 与 Plan 已接入 bundle 化记忆 | `backend/app/modules/agent/memory_selector.py` `load_conversation_bundle` / `load_practice_bundle` / `load_evaluation_bundle` / `load_planning_bundle` | Explain 消费 `ConversationBundle`，Validate 消费 `PracticeBundle`，Grade 消费 `EvaluationBundle`，Plan 消费 `PlanningBundle`；历史摘要已增量生成，但尚未进入选择器和 snapshot | `MEM-004`、`MEM-005`、`MEM-007` |
| 客观题掌握度已闭环，主观评分未实现 | `backend/app/modules/agent/workflows/grade.py::_load_attempt_snapshot_node`（L40-L78）、`_objective_grade_node`（L81-L129）、`_render_artifact_node`（L191-L218）；`backend/app/modules/agent/memory_projection.py::_record_grade_result_confirmed`（L308-L413） | 选择、填空、判断题用可信标准答案确定性产生 verdict 并幂等更新掌握度；主观题无可靠 rubric/model 评分器，安全失败且不写 Artifact/掌握度 | `MEM-004`、`MEM-006` |
| 异步派生仍缺 Embedding 与偏好候选 | `backend/app/modules/agent/conversation_summary.py::ConversationSummaryMaintainer.maintain`（L90-L211）；`backend/app/modules/agent/memory_item_projection.py::project_trusted_memory_event`（L154-L166） | Memory Outbox 已物化显式主题、批准计划并增量生成历史摘要；摘要尚未向量化或进入 Bundle，偏好候选也未实现 | `MEM-006`、`MEM-007` |

## 设计约束

1. 原始消息和 Artifact 仍是事实源；未来长期记忆必须由它们和真实评分/审批事件投影而来。
2. Router 历史筛选使用 `token_budget=4096` 是“选择多少历史”的预算，不是模型最终输入加输出的全局上限。
3. 后续记忆闭环必须围绕事实类型和 `MemoryNeed` 稳定，而不是把 explain / validate / grade / plan 写死进存储结构。

## 下一步阅读

- 检索与 explain/validate 的现状，见 `implementation/rag-and-tools.md`。
- 模型调用预算、流式正文和 child run 继承模型配置，见 `implementation/model-runtime-streaming.md`。
