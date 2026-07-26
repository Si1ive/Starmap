# Router、上下文与当前记忆边界

## 适用场景

本分卷解释当前 Router 如何消费历史消息和 Artifact、`context_builder` 现在能提供什么，以及为什么任务单里把
“分层长期记忆”列为后续整改项。

## 当前上下文构建链

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 上下文数据结构 | `backend/app/modules/agent/context_builder.py` | `AgentRunContext` | 线程、消息、Artifact、选择审计 | 定义当前可传给 Router/child workflow 的消息、Artifact、active topic、独立请求和 snapshot ID | `AgentRunContext` | `ThreadContextBuilder.build` |
| 历史、Artifact 与热状态选择 | `backend/app/modules/agent/context_builder.py` | `ThreadContextBuilder.build`、`_load_thread_memory_state` | thread ID、root run、token budget、可见 Artifact、线程热状态 | 选择近期消息、当前轮前后的 Artifact、待处理交互，并读取线程 `active_topic` / `memory_state_version` | 受控上下文与热状态 | `_route_node` |
| 独立请求、快照与显式主题事实 | `backend/app/modules/agent/turn_understanding.py`（L105-L157、L161-L246）；`backend/app/modules/agent/memory_projection.py`（L19-L73） | `build_turn_understanding`、`ensure_turn_memory_snapshot`、`project_topic_confirmed_fact` | 当前输入、context refs、线程 active topic | 确定性生成 `TurnUnderstanding`，抽取难度并补全独立请求；创建/复用 snapshot、递增热状态版本；若首个主题来自本轮显式 `context_ref`，在 Router 模型调用前按 Run 幂等写 `topic_confirmed`。仅从 `thread_memory` 继承时不重复冒充用户确认 | `TurnUnderstanding`、snapshot、热状态，以及可选的线程级主题事实；事实/数据库错误与 route 节点同事务传播，Router 后续失败时已 flush 的用户主题会随 step 失败提交保留 | `_route_node` 的 Router 调用 |
| Conversation 路由 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | 当前输入、受控上下文、独立请求、允许 action | 先构建并持久化 `TurnUnderstanding`，再把 `standalone_request` 和历史交给 Router，决定 direct/explain/validate/grade/plan/clarify | `RouterDecision`、run metadata 中的 `memory_snapshot_id` / `turn_understanding` | `_direct_answer_node` / `_dispatch_workflow_node` |
| Child 元数据交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | 父 run 的上下文审计、active topic、独立请求和模型配置 | 复制筛选后的消息/Artifact ID、`active_topic`、`standalone_request`、`memory_snapshot_id` 和模型配置 ID，仍不复制敏感密钥 | child run metadata | `_dispatch_workflow_node` |
| Child Run 派发 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | Router action、parent/root run、独立请求 | 创建 child run 和 workflow 时间线项；child run 的 `input_message` 改为 `standalone_request`，从而不再只依赖原始短句和消息 ID | queue 中的 child run | worker |

## 已落库的记忆基础契约

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 记忆能力与分区命名 | `backend/app/modules/agent/memory_contracts.py` | `MemoryPartition`、`MemoryNeed`、`MemoryFactType`、`MEMORY_NEED_PARTITIONS` | 任务单中的分层记忆边界 | 固化九类分区、六类能力标签与五类事实事件类型，明确能力声明不绑定 explain/validate/grade/plan 名称 | 稳定命名契约 | 快照选择器 / 完成事实投影 / workflow adapter |
| 记忆 ORM 基础表 | `backend/app/modules/agent/models.py` | `AgentThreadMemoryState`、`AgentMemoryEvent`、`AgentMemorySnapshot`、`AgentMemorySnapshotItem`、`AgentMemoryUpdateOutbox`、`UserLearningMastery`、`AgentConversationSummary`、`AgentMemoryItem` | 线程、Run、用户和未来投影事件 | 定义热状态、事件、快照、Outbox、掌握度、对话摘要和长期记忆项的单表契约 | Base metadata 中的记忆表结构 | Alembic 迁移 / 后续 selector 与 projector |
| 首个 Bundle 选择器 | `backend/app/modules/agent/memory_selector.py` | `_load_excluded_question_ids`、`_load_unique_weak_topic`、`load_practice_bundle`、`build_practice_query`、`build_practice_filters` | child run 的 `run_id` / `user_id`、snapshot metadata、selected snapshot items、近期 `practice_artifact_created` 事实事件、`user_learning_mastery` | 校验 run 与 snapshot 归属，从 snapshot 和选中的 `topic_focus` / `practice_generation` items 组装 `PracticeBundle`，提取 `difficulty`、`knowledge_point_ids` 和 selected artifacts；按用户维度从最近 10 个 practice 事实事件装载去重后的 `excluded_question_ids`（最多 50 道，最新优先）；快照拿不到主题时回退唯一薄弱点——恰好一个 `mastery_score < 0.6` 且 `evidence_count > 0` 的知识点才构造 `source="learning_mastery"` 的 TopicBundle（标题/aliases 取自 `knowledge_points`）并记录 `mastery_signals`，多个则维持澄清；再用 topic title + aliases 构造 query 与检索过滤条件，无主题时返回空 query，避免静默默认主题 | `PracticeBundle`（含真实排除集与薄弱点回退）、确定性 query、结构化 filters | `validate._load_learning_evidence_node` / `_question_discovery_node` |
| 可信事实投影 | `backend/app/modules/agent/memory_projection.py`（L19-L290） | `project_topic_confirmed_fact`、`project_completed_run_facts`、`_record_explanation_artifact_created`、`_record_practice_artifact_created`、`_record_grade_result_confirmed` | snapshot 中的显式主题，或 completed run 的已持久化 Artifact | 显式主题在 Router 前写线程事实；Run 完成时按 artifact 类型分派（不读 workflow 名）：explanation 只记录 Artifact/snapshot ID，practice 提取题目 ID，feedback 校验真实评分证据、去重知识点并更新掌握度；四类事件都有稳定幂等键 | `topic_confirmed` / `explanation_artifact_created` / `practice_artifact_created` / `grade_result_confirmed`、可选的 `user_learning_mastery` 更新；继承主题、无题目 ID、缺评分证据均无副作用返回；数据库异常沿所在事务传播 | 下一轮 `ThreadContextBuilder` / `memory_selector._load_excluded_question_ids` / `_load_unique_weak_topic` |

## 当前能力边界

1. 当前系统已经能选取近期消息、Artifact、待处理交互，并在 Router 前读取线程热状态中的 `active_topic`。
2. `MEM-003` 的第一阶段已打通：conversation run 会生成确定性 `TurnUnderstanding`、创建不可变 snapshot，并把 `standalone_request` 与 `memory_snapshot_id` 传给 child run。
3. `MEM-004` / `MEM-005` 的第二阶段已打通到过滤参数和首个澄清闭环：Validate 会从 snapshot 装载 `PracticeBundle`，继承主题、别名、难度约束、知识点 ID 和选中的 Artifact，并据此生成检索 query 与 retrieval filters；若缺少主题，会创建 `practice_topic` 输入项并在用户补充后从断点继续检索。
4. 真实排除集已闭环：Validate 完成时写 `practice_artifact_created` 事实事件，下一次练习通过 `PracticeBundle.excluded_question_ids` 自动排除近期已出过的题。
5. 掌握度已形成安全的读写边界：无主题时按“唯一低掌握度知识点”回退练习主题；携带真实结构化评分证据的 Feedback Artifact 能写 `grade_result_confirmed` 并更新 `user_learning_mastery`。当前 P1 Grade 仍只有固定反馈，不生产 verdict，因此真实线上数据源仍需后续评分服务接入。
6. 本轮显式 `context_ref` 主题已在 Router 调用前写成 `topic_confirmed`；因此 Router/模型失败只会阻止 Agent 输出，不会丢失用户已表达的主题。继承的热状态主题不会重复产生确认事件。
7. Explain 成功产出 Artifact 时已写 `explanation_artifact_created`，包括零命中/检索异常后的无引用 fallback；事件不复制正文，也不修改掌握度。
8. 当前仍未实现歧义场景下的结构化指代消解模型，也还没有把历史摘要做成可复用的 bundle。

## 现状问题与整改入口

| 问题 | 当前代码锚点 | 现状 | 任务单对应项 |
| --- | --- | --- | --- |
| 主题继承还未消费掌握度/摘要等深层记忆 | `backend/app/modules/agent/context_builder.py` `ThreadContextBuilder.build` | 已能读取 `active_topic`，但还没有选择 `user_learning_mastery`、历史摘要或排除集 | `MEM-003`、`MEM-004` |
| 只有 Validate 已接入 bundle 化记忆 | `backend/app/modules/agent/memory_selector.py` `load_practice_bundle`；`backend/app/modules/agent/workflows/validate.py` `_load_learning_evidence_node` | Validate 已能消费 `PracticeBundle`；Explain / Grade / Plan 仍未声明并装载各自的 bundle | `MEM-004`、`MEM-005` |
| 掌握度投影已通但真实评分源未接入 | `backend/app/modules/agent/workflows/grade.py::_objective_grade_node`（L34-L51）、`_render_artifact_node`（L108-L137）；`backend/app/modules/agent/memory_projection.py::_record_grade_result_confirmed`（L186-L290） | 投影器只接受结构化真实评分证据并能安全更新掌握度；当前 P1 Grade 仍把所有作答视为主观固定反馈，不产生 verdict，所以不会误写但也没有线上掌握度证据 | `MEM-004`（EvaluationBundle）、`MEM-006`（真实评分生产者） |
| 长期回写尚未覆盖全部事实和 Outbox | `backend/app/modules/agent/turn_understanding.py::ensure_turn_memory_snapshot`（L161-L246）；`backend/app/modules/agent/memory_projection.py::project_topic_confirmed_fact`（L19-L73）、`project_completed_run_facts`（L76-L89）、`_record_explanation_artifact_created`（L92-L130） | 显式主题已在 Router 前写事实；Run 完成事务已分派 explanation、practice 与有真实证据的 feedback；计划确认以及 Memory Outbox 异步投影仍未实现 | `MEM-006` |

## 设计约束

1. 原始消息和 Artifact 仍是事实源；未来长期记忆必须由它们和真实评分/审批事件投影而来。
2. Router 历史筛选使用 `token_budget=4096` 是“选择多少历史”的预算，不是模型最终输入加输出的全局上限。
3. 后续记忆闭环必须围绕事实类型和 `MemoryNeed` 稳定，而不是把 explain / validate / grade / plan 写死进存储结构。

## 下一步阅读

- 检索与 explain/validate 的现状，见 `implementation/rag-and-tools.md`。
- 模型调用预算、流式正文和 child run 继承模型配置，见 `implementation/model-runtime-streaming.md`。
