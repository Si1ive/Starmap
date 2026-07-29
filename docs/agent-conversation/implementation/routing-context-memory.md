# Router、上下文与当前记忆边界

## 适用场景

本分卷解释当前 Router 如何消费历史消息和 Artifact、`context_builder` 现在能提供什么，以及为什么任务单里把
“分层长期记忆”列为后续整改项。

## 当前上下文构建链

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 上下文数据结构 | `backend/app/modules/agent/context_builder.py`（L54-L63、L85-L112） | `ArtifactContext`、`AgentRunContext` | 线程、消息、Artifact、摘要与选择审计 | 定义当前可传给 Router/child workflow 的原始消息、版本化摘要来源、Artifact 摘要、active topic、独立请求和 snapshot ID | `AgentRunContext` | `ThreadContextBuilder.build` |
| 历史摘要选择 | `backend/app/modules/agent/context_builder.py`（L141-L276、L533-L569） | `ThreadContextBuilder.build`、`ThreadContextBuilder._load_conversation_summary` | 同用户/线程、最早近期消息 sequence、原始消息选择后的剩余 Token 预算 | 近期完整轮次优先；只选唯一 active 且 `end_sequence` 早于最早原始消息的摘要，预算不足、空正文或双活摘要均不注入 | `conversation_summary` 与含 ID/版本/范围/来源/token 的 source；错误向 Router 节点传播 | snapshot / Router / direct answer |
| 历史、Artifact 与热状态选择 | `backend/app/modules/agent/context_builder.py`（L395-L463、L713-L746） | `ThreadContextBuilder._load_artifacts`、`ThreadContextBuilder._extract_artifact_reference_entities` | thread ID、root run、token budget、可见 Artifact 的 `artifact_type` / `content_json` | 按用户、线程、可见性和预算选择近期 Artifact；仅从 practice 产物的 `content.question_ids` 提取去重后的 question 引用，绝不从标题或摘要反推 ID | 按时间升序的 `ArtifactContext`，question 引用携带来源 Artifact ID；查询/结构错误随上下文构建传播 | `build_turn_understanding` |
| 线程主题轮次失效 | `backend/app/modules/agent/context_builder.py`（L141-L276、L749-L772）；`backend/app/modules/agent/turn_understanding.py`（L405-L515、L539-L554） | `ThreadContextBuilder.build`、`_active_topic_from_state`、`ensure_turn_memory_snapshot`、`_topic_state_payload` | 热状态 version、主题 `confirmed_state_version`、本轮显式或继承主题 | 显式主题把当前状态版本记为确认版本；继承主题保留原版本。读取时版本差不超过 6 才暴露主题，第 7 个后续轮次失效；旧版无标记 JSON 首次兼容，继承写回时补标记；非法标记安全失效 | 有界 `active_topic` 或 None；数据库事实仍保留，后续明确主题可重置版本 | `build_turn_understanding` / Router |
| 独立请求、约束与候选选择 | `backend/app/modules/agent/turn_understanding.py` | `_derive_retrieval_query`（L144-L158）、`_topic_from_explicit_explanation`（L161-L172）、`build_turn_understanding`（L396-L450） | 当前输入、context refs、线程 active topic | 先使用可信引用/热状态；若没有主题但用户明确“讲解 X”，从去壳后的短检索词生成 `current_turn` 临时主题并进入本轮 snapshot。后续“给我出道题”会据此生成“给用户出一道关于 X 的练习题”，不再无条件询问范围 | `TurnUnderstanding.topic_entities`、`standalone_request` 与检索焦点；snapshot/线程热状态持久化 | Router、child workflow |
| 结构化指代模型 | `backend/app/modules/agent/model_runtime/referent.py`（L22-L169） | `ReferentCandidate`、`ReferentResolution`、`ReferentRuntime.resolve` | 确定性阶段仍有歧义且存在带语义标签的服务端候选 | 使用 Run 绑定模型输出 resolved/unresolved；resolved 只能原样选择候选键，返回后再次白名单校验，低于 0.8 降级 unresolved；候选文本按不可信数据处理 | 合法候选选择或 unresolved；非法键/缺标签/模型异常向 route 节点传播 | `apply_referent_resolution` |
| Conversation 路由、能力快照与显式主题事实 | `backend/app/modules/agent/workflows/conversation.py`、`backend/app/modules/agent/capabilities.py`、`backend/app/modules/agent/model_runtime/router.py` | `_route_node`（L45-L157）、`CapabilityRegistry.model_manifest` / `audit_manifest`（L62-L74）、`_router_policy`（L100-L122） | 完整 TurnUnderstanding、服务端能力目录、可选历史摘要 | snapshot 冻结当前理解和摘要副本；Router 只收到 action/key/description 的最小能力清单，并被明确告知不能直接写数据库、学习记录或薄弱点。选定能力和完整安全属性写 root Run 审计快照 | `RouterDecision`、可复现 memory snapshot、`capability_snapshot` 与可选主题事实；异常交给 workflow engine | `_direct_answer_node` / `_dispatch_workflow_node` |
| Child 元数据交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | L219-L254；父 run 的上下文审计、active topic、独立请求、选定能力和模型配置 | 复制筛选后的消息/Artifact ID、`active_topic`、`standalone_request`、`memory_snapshot_id`、模型配置和当前能力审计，不复制敏感密钥或可执行函数 | child run metadata | `_dispatch_workflow_node` |
| Child Run 派发 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | Router action、parent/root run、独立请求 | 创建 child run 和 workflow 时间线项；child run 的 `input_message` 改为 `standalone_request`，从而不再只依赖原始短句和消息 ID | queue 中的 child run | worker |

## 阶段二：ConversationTutorAgent 决策契约

当前在线入口只有一个 `ConversationTutorAgent`。`action` 是需要持久化的业务分支，
`teaching_mode` 是该分支采用的教学策略；两者必须由同一次结构化模型调用产出，
避免 Router 先选 `validate`、另一个 Tutor 再次选择 `validate`。策略事实只用于
冻结 child workflow 的输入，不是学习证据，也不能直接更新掌握度或薄弱点。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 决策 Schema | `backend/app/modules/agent/model_runtime/schema.py` | `ConversationDecision`、`TeachingMode`、`ReadToolIntent` | L65-L183 | 当前请求和模型结构化输出 | 校验 action、confidence、稳定 `reason_code(s)`、教学模式、知识点 ID、诊断标记和只读意图；`extra=forbid` 拒绝 `mastery_score` 等写字段；`RouterDecision` 仍是兼容别名 | 单次 `ConversationDecision`；不写数据库 | `ConversationTutorRuntime.decide` |
| LearningSnapshot 摘要 | `backend/app/modules/agent/learning_snapshot.py` | `LearningSnapshotSummary`、`LearningSnapshotReader.read`、`LearningSnapshotReader._ensure_learning_state`、`load_learning_snapshot_summary` | L39-L70、L280-L382、L384-L478、L704-L719 | 当前 Run 的 snapshot ID、同用户/线程、active topic、用户已有 mastery/活动事实和未过期 Observer 活动 | 首次读取按 active topic/有效掌握度顺序复制知识点级 raw/effective mastery、uncertainty、evidence source、error tags 和推荐复习原因，并用 `WeaknessProjector` 写入快照项；同时复制 14 天内 diagnostic hypotheses。初始化标记后只读 Snapshot Item，来源改名或新证据不会漂移；找不到 snapshot 或非 UUID 兼容用户返回安全空摘要 | 同一 `learning_snapshot` 中的 mastery、weakness findings、diagnostic hypotheses、状态版本和 source item IDs；只新增当前 Run 冻结副本，不修改活动或 mastery | `RouterDeps.learning_snapshot` |
| Tutor 运行时 | `backend/app/modules/agent/model_runtime/router.py` | `RouterDeps`、`_router_policy`、`ConversationTutorRuntime.decide` | L45-L58、L128-L167、L233-L320 | 用户/线程/Run ID、允许 action、冻结 LearningSnapshot 摘要、能力清单和只读意图 allowlist | 将历史摘要和学习快照标为不可信动态资料；模型只声明只读意图，不获得 session、ORM 或写函数；显式讲解/出题/批改/计划护栏覆盖错误 action，并补齐旧输出的默认教学模式 | 受控 `ConversationDecision`；非法 action、知识点目标或只读意图沿 route 节点失败 | `_route_node` |
| 只读能力目录 | `backend/app/modules/agent/capabilities.py` | `READ_ONLY_CAPABILITIES`、`CapabilityRegistry.read_only_model_manifest`、`read_only_audit_manifest`、`allowed_read_tool_intents` | L15-L31、L95-L121 | 阶段六固定的四个只读意图 | 模型视图只暴露名称/描述，审计视图额外记录 policy version；真实执行仍须进入 `ToolRegistry` 的 workflow、参数和用户所有权门禁，未注册的写能力不在 manifest 中 | `get_learning_snapshot`、`get_weakness_findings`、`retrieve_knowledge`、`search_question_candidates` allowlist | 路由或业务 workflow |
| 策略冻结 | `backend/app/modules/agent/model_runtime/teaching_policy.py`、`backend/app/modules/agent/worker.py` | `FrozenTeachingPolicy.from_decision`、`load_frozen_teaching_policy`、`freeze_teaching_policy`、`AgentWorker.process_run` | L19-L47、L67-L101、L104-L109；worker L180-L205 | root metadata 的完整 decision/policy，或旧 child Run | 只复制 workflow action、teaching mode、知识点目标、诊断标记、只读意图和 reason codes；Worker 把 child metadata 注入 ExecutionContext，Explain/Validate/Grade 只读取并在私有 Artifact metadata 留审计副本，不再重新路由 | child workflow 的可回放教学策略；策略不进入 LearningActivityEvent 或掌握度 projector | Explain/Validate/Grade 节点 |

### 策略默认值与错误传播

旧测试模型或历史 Run 未携带 `teaching_mode` 时，运行时按 action 补齐：
`direct_answer → answer_only`、`explain → explain`、`validate → practice_weakness`、
`grade → feedback`、`plan → plan`、`clarify → clarify`；`need_diagnostic_check=true`
且 action 为 direct/explain 时使用 `explain_then_micro_check`。结构化输出失败、
action 不在本轮能力清单、目标知识点不在冻结范围或只读意图未授权时，当前
conversation Run 失败，不创建 child Run；任何教学策略字段都不会进入学习证据投影。

## 阶段六：冻结学习状态与薄弱点派生

阶段六把“掌握度读取”和“薄弱点建议”放进同一个 Snapshot 边界。这样 Router 可以同时看到低掌握度、高不确定性、仅有 exposure、明确 misconception 和已衰减复习需求，但不能把这些读模型写回权威事实。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 快照摘要契约 | `backend/app/modules/agent/learning_snapshot.py` | `LearningSnapshotSummary` | L39-L70 | Snapshot Item 中的 mastery、weakness 和 hypothesis 载荷 | 只暴露稳定字段；`known_knowledge_point_ids` 合并 active topic、mastery、finding 和 hypothesis，供 Tutor 做范围校验 | Pydantic 摘要，不写掌握度 | `LearningSnapshotReader.read` / Router |
| 首次冻结学习状态 | `backend/app/modules/agent/learning_snapshot.py` | `LearningSnapshotReader.read`、`LearningSnapshotReader._ensure_learning_state` | L280-L382、L384-L478 | 用户/线程归属已校验的 Snapshot、active topic、UserLearningMastery、LearningActivityEvent | 先复核已有快照项；没有初始化标记时复制最多 16 条 mastery 和 16 条 finding，并写策略版本标记。证据 source/error tag 只复制白名单字段；查询/flush 错误向 route 节点传播 | `learning_mastery`、`learning_weakness` Snapshot Item；同 Run 后续只读这些副本 | Router 的 `RouterDeps.learning_snapshot` |
| 掌握度与证据来源 | `backend/app/modules/agent/learning_snapshot.py` | `_build_mastery_signal` | L575-L669 | UserLearningMastery、知识点元数据、同用户活动事件、统一 UTC now | 保留 raw score，调用 `calculate_effective_mastery` 派生 effective score；同时回链 evidence ID、source、outcome、confidence、error tags、answer exposure 和衰减版本。讲解 exposure 的 `quality` 不转成 mastery source | 冻结的知识点级 mastery signal 和 recommended review reason | Tutor 选择 teaching mode / 下游 child workflow |
| 薄弱点投影 | `backend/app/modules/agent/weakness_projector.py` | `WeaknessFinding`、`WeaknessProjector.project`、`WeaknessProjector._project_group` | L32-L63、L85-L127、L144-L305 | 活动事件、LearningEvidence 或旧版兼容记录；verdict、error tags、coverage、迁移类型、发生时间 | 服务端按知识点/关键词分组；incorrect 形成 confirmed，后续 correct 只转 awaiting interval verification；exposure/observation/困惑假设只能形成 needs_diagnostic；错误标签决定复习理由，时间衰减只降低 severity，不删除历史 | 只读 `WeaknessFinding`，含 finding ID、证据来源、错误标签、TTL/复习时间；不写 ORM、不修改 mastery | Snapshot item、学习进度和 Weakness API |
| 用户端进度分层 | `backend/app/modules/learning/service.py` | `LearningProgressService.get`、`LearningProgressService._load_mastery_states` | L101-L179、L350-L426 | 用户活动事件、旧练习事实、UserLearningMastery、知识点和读取时点 | `topics`/`activity_retention` 只计算活动保持率；`mastery_evidence` 单独返回 effective/raw score、uncertainty、证据量和 source ID，避免把讲解 `quality=0.35` 显示成掌握度 | 兼容旧字段并新增两套明确的读取契约 | 用户学习进度页、Tutor Snapshot |
| 薄弱点 API 聚合 | `backend/app/modules/learning/weaknesses.py` | `WeaknessService.get` | L187-L266 | 当前用户的活动事件和未投影的旧练习答案 | 保留旧关键词 clusters/timeline，同时用 `WeaknessProjector` 生成 finding 统计；用户归属和历史去重仍由原查询边界保证 | `findings`、confirmed/diagnostic 计数和兼容旧响应 | 用户薄弱点页、只读工具 |

这条链路的错误传播是有意分层的：Snapshot/活动查询失败会让当前读取节点失败，避免把半截状态交给模型；单条旧活动无法解析时 Projector 跳过该记录并保留其余可验证事实；投影本身不执行数据库写入，权威 mastery 仍只能由评分事实和 `MasteryProjector` 更新。

## 已落库的记忆基础契约

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 记忆能力与分区命名 | `backend/app/modules/agent/memory_contracts.py` | `MemoryPartition`、`MemoryNeed`、`MemoryFactType`、`MEMORY_NEED_PARTITIONS` | 任务单中的分层记忆边界 | 固化十类分区、六类能力标签与五类事实事件类型，新增 `learning_weakness` 并明确能力声明不绑定 explain/validate/grade/plan 名称 | 稳定命名契约 | 快照选择器 / 完成事实投影 / workflow adapter |
| 记忆 ORM 基础表 | `backend/app/modules/agent/models.py` | `AgentThreadMemoryState`、`AgentMemoryEvent`、`AgentMemorySnapshot`、`AgentMemorySnapshotItem`、`AgentMemoryUpdateOutbox`、`UserLearningMastery`、`AgentConversationSummary`、`AgentMemoryItem` | L487-L837；其中 `UserLearningMastery` 为 L697-L755 | 线程、Run、用户和未来投影事件 | 定义热状态、事件、快照、Outbox、掌握度、对话摘要和长期记忆项的单表契约；掌握度同时保存兼容 score/count、alpha/beta、evidence mass、uncertainty、最近证据和 state version | Base metadata 中的记忆表结构 | Alembic 迁移 / 后续 selector 与 projector |
| 掌握度读时衰减 | `backend/app/modules/agent/mastery_decay.py`（L11-L62）；`backend/app/modules/agent/memory_selector.py`（L192-L239） | `MASTERY_DECAY_POLICY_VERSION`、`EffectiveMastery`、`calculate_effective_mastery`、`_mastery_signal`、`_load_frozen_mastery_signals`、`_freeze_mastery_signals` | 原始 `mastery_score`、evidence 时间、state model、统一 UTC now、同用户 Snapshot | `mastery-decay-v1` 按 90 天半衰期向不高于原分数的 0.2 地板衰减；优先从 `last_evidence_at` 取证据时间，未来时间钳制为 0 天，naive DATETIME 按 UTC；派生信号同时冻结 uncertainty/evidence mass/state model，首次选择锁 Snapshot、复核后追加含原始/有效分数、证据时间、策略版本的 Item | 可审计有效分数与 `learning_mastery` Snapshot Item；不覆盖累计分数或 Grade 事实，锁/查询错误向当前 workflow 传播 | PracticeBundle / PlanningBundle |
| PracticeBundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L648-L1032、L1239-L1259） | `_load_excluded_question_ids`、`_load_chapter_ids`、`_resolve_explicit_chapter_ids`、`_load_unique_weak_topic`、`load_practice_bundle`、`build_practice_query`、`build_practice_filters`、`_apply_explicit_question_repeat` | Validate child run、snapshot/items、近期 practice 事实、掌握度、显式章节/重复约束、UTC now | 校验归属并组装 `PracticeBundle`；无主题时用有效分数选唯一薄弱点并冻结题名/别名；显式章节只在唯一学科内解析；排除集只在重复约束和唯一 question 引用同时存在时覆盖本轮视图 | 含原始/有效掌握度、章节解析状态与本轮排除 ID 的 Bundle；同 Snapshot 不受来源改名或新证据影响 | `validate._load_learning_evidence_node` / `_question_discovery_node` |
| PlanningBundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L63-L84、L191-L511） | `PlanningTarget`、`PlanningBundle`、`_mastery_signal`、`_load_frozen_mastery_signals`、`_freeze_mastery_signals`、`load_planning_bundle` | Plan child run、同用户/线程 snapshot、最新 active `learning_goal`、真实评分掌握度、偏好 Bundle、UTC now | 装载当前主题、批准 goals、有效薄弱点和已决胜偏好；按标题去重并冻结掌握度，偏好选择由专用 selector 冻结 | 最小 PlanningBundle 含 targets、mastery 与 preferences；查询/锁/持久化错误向 Plan 聚合节点传播 | `plan._aggregate_learning_evidence_node` |
| EvaluationBundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L87-L123、L135-L162、L547-L763） | `EvaluationQuestion`、`EvaluationBundle`、`_extract_user_answer`、`load_evaluation_bundle` | Grade child run、同用户/线程 snapshot、快照 question 引用、题库标准答案与本轮原始输入 | 先校验 Run 与 snapshot 作用域，再要求唯一 question ID；只读取 active、未拒绝且 `answer_source` 非 none 的题目，开放题允许空标准答案交给 rubric gate；合并题目 JSON 与关系表知识点，提取显式答案/回答/解释句式，并冻结提示、答案暴露、生成题模型版本与答案可信度 | 最小 `EvaluationBundle`，含题面、可信标准答案/开放题待评估输入、知识点、来源 Artifact 和作答；不确定时无题面 Bundle | `grade._load_attempt_snapshot_node` |
| ConversationBundle 选择器 | `backend/app/modules/agent/memory_selector.py`（L1035-L1236） | `ConversationTurn`、`ConversationBundle.to_message_history`、`load_conversation_bundle` | Explain child run、同用户/线程 snapshot、冻结消息/摘要/Artifact ID、结构化理解 | 只复现 snapshot 选中的 visible completed 消息、公开 Artifact 和唯一 `historical_summaries` item；摘要额外复核源记录 user/thread/version，正文取 snapshot 副本而非当前版本；版本不符或重复条目安全降级为无摘要 | Pydantic AI history、冻结摘要、Artifact 摘要、结构化引用与确定性 query | `explain._load_scope_node` |
| 可信事实与 Outbox 生产 | `backend/app/modules/agent/memory_projection.py`（L27-L497） | `_ensure_memory_update_outbox`、`project_topic_confirmed_fact`、`project_completed_run_facts`、`_record_explanation_artifact_created`、`_record_plan_confirmed`、`_record_practice_artifact_created`、`_record_grade_result_confirmed` | snapshot 显式主题，或 completed run 的已持久化 Artifact | 写五类事实后在同一事务确保 pending Memory Outbox；Grade 在 L311-L497 先查证据幂等键，ungradable 只写活动，其余经过 EvidenceGate/WeightPolicy 并交接 MasteryProjector；新事实先 flush 取得 ID，重放已有事实会补建缺失任务；SAVEPOINT 收敛数据库唯一键并发冲突，不污染外层 Run 事务 | `agent_memory_events`、`agent_memory_update_outbox` 与 `user_learning_mastery` 原子可见；事件载荷只含脱敏证据快照/记忆 event ID；不满足事实条件时不创建掌握度 | 后续 Memory Outbox 消费者 / LearningSnapshot |
| 摘要与偏好任务生产 | `backend/app/modules/agent/worker.py`（L187-L229）；`backend/app/modules/agent/conversation_summary.py`（L38-L70）；`backend/app/modules/agent/preference_memory.py`（L122-L166） | `AgentWorker.process_run`、`enqueue_conversation_summary_maintenance`、`enqueue_preference_candidate_extraction` | workflow 返回 completed，Run、Artifact、最终消息和 `run.completed` 已写入当前事务 | 成功 Run 幂等写摘要任务；只有根 conversation 且存在原始触发消息时再写偏好候选任务。任务只携带来源标识，并发唯一键冲突由 SAVEPOINT 收敛 | Run 完成事实与 pending 派生任务原子可见；失败/waiting 不入队 | `MemoryOutboxConsumer.scan_and_process` |
| Memory Outbox 消费与运行时接入 | `backend/app/modules/agent/memory_outbox.py`（L45-L339）；`backend/app/modules/agent/worker.py`（L372-L396） | `MemoryOutboxStore.scan_due`、`MemoryOutboxStore.claim`、`MemoryOutboxStore.complete`、`MemoryOutboxStore.fail`、`MemoryOutboxConsumer.process_claimed`、`MemoryOutboxConsumer.scan_and_process`、`AgentWorker.start` | pending 或租约过期的 processing 事实/摘要/偏好/线程删除/向量任务 | Worker 条件 UPDATE 认领；SAVEPOINT 内按 task type 分派，完成/失败校验 worker 所有权 | 成功 completed；异常延迟重试/最终 failed，已完成 Run 不变 | 各 projector / lifecycle |
| 偏好候选抽取与来源审计 | `backend/app/modules/agent/model_runtime/preference_extractor.py`、`backend/app/modules/agent/preference_memory.py` | `PreferenceExtractionRuntime.extract`（L92-L144）、`PreferenceCandidateProjector.process_outbox`（L175-L244） | 已校验的根 conversation Run 与同作用域原始 user message | 模型仅返回最多五个结构化候选；重复 key 拒绝。projector 写 source kind/ID/version、scope、confidence、extractor/model 版本；所有候选保持 pending，来源已处理时不重复调用模型 | `agent_preference_candidates` 审计行；错误进入 Outbox 重试，不反向修改 Run | 用户候选治理 API |
| 候选批准、拒绝与长期项 | `backend/app/modules/agent/router.py`、`backend/app/modules/agent/preference_memory.py` | `get_preference_candidates`、`decide_user_preference_candidate`（L674-L710）、`decide_preference_candidate`、`_materialize_approved_preference`（L304-L399） | 当前认证用户、pending candidate、approved/rejected 决定 | 同用户/scope/key 行锁串行治理；批准才物化 active `user_preference` 并 supersede 同 key 旧项，拒绝保留 tombstone；重复同决定幂等，反向修改终态拒绝 | 候选治理状态与可审计长期项；跨用户无结果 | 偏好冲突选择器 / 线程删除治理 |
| 偏好三层冲突与冻结 | `backend/app/modules/agent/preference_memory.py` | `extract_explicit_preferences`、`_resolve_preference_sources`、`_load_frozen_preference_bundle`、`_freeze_preference_bundle`、`load_preference_bundle` | L95-L119、L422-L662 | 本轮原始输入、同用户候选、当前 thread、Snapshot/MemoryNeed | 确定性显式陈述优先于 approved/rejected 业务事件，业务事件优先于 pending 模型候选；同级按事件时间和稳定 ID。pending/rejected/冲突项只记录 dropped reason；锁 Snapshot 冻结选中、丢弃和空结果 marker | 可复现 `PreferenceBundle`；低置信和高置信 pending 都不进入 Plan/Router | `load_planning_bundle` / MEM-008 复现 |
| 可信事实派生记忆项 | `backend/app/modules/agent/memory_item_projection.py`（L15-L224） | `_upsert_memory_item`、`_enqueue_item_vector`、`_project_topic_context`、`_project_confirmed_plan_goal`、`project_trusted_memory_event` | 已通过 Outbox 归属校验的五类事实；Plan 额外读取同 Run Artifact | topic/plan 物化 active item，同时把同用户/线程/类型旧项标 superseded；按事实 ID 作为 source version 追加向量 upsert，并携带旧项删除列表。Explain/Practice/Grade 不复制正文 | 新旧 `agent_memory_items` 状态与 pending 向量任务同事务可见；格式/归属错误重试，不改 Run | PlanningBundle / `MemoryVectorLifecycle.process_outbox` |
| 历史消息增量摘要 | `backend/app/modules/agent/conversation_summary.py`（L91-L335） | `ConversationSummaryMaintainer.maintain`、`ConversationSummaryMaintainer._load_active_summary`、`ConversationSummaryMaintainer._load_raw_window_start`、`ConversationSummaryMaintainer._load_new_messages` | 已校验的 completed Run 摘要任务；同用户、同 active/archived 线程 | 保留最近 12 个用户轮次原文，按连续区间调用模型；锁线程复核后写新摘要、supersede 旧摘要，并追加以摘要 version 为来源版本的向量任务 | 新摘要、旧摘要状态与 pending 向量任务同事务可见；原消息不修改；模型/并发错误交给 Outbox 重试 | 历史摘要 Bundle / 向量消费者 |
| 向量生成、更新与删除 | `backend/app/modules/agent/memory_vector.py`（L58-L253） | `memory_item_vector_task_type`、`summary_vector_task_type`、`memory_vector_point_id`、`enqueue_memory_vector_task`、`MemoryVectorLifecycle._delete_sources`、`MemoryVectorLifecycle.delete_sources`、`MemoryVectorLifecycle.process_outbox` | active source/version、旧 source 列表或治理删除全集、Embedding 配置 | 稳定 UUID upsert；成功后删除旧点，collection 不存在幂等完成 | Qdrant 当前版本点；异常只重试 Outbox | `MemoryVectorLifecycle.recall` |
| 向量召回与 Snapshot 冻结 | `backend/app/modules/agent/memory_vector.py`（L255-L571） | `MemoryVectorLifecycle.recall`、`MemoryVectorLifecycle.recall_for_snapshot`、`MemoryVectorLifecycle._load_source`、`MemoryVectorLifecycle._hydrate_hit`、`MemoryVectorLifecycle._load_frozen_hits` | query、user/thread、允许分区、Snapshot/MemoryNeed | Qdrant 前置过滤后重读 MySQL 复核版本/status；首次命中冻结正文/source/score | 可复现 hits；失效来源即使向量暂未删也被丢弃 | 能力 selector / MEM-008 复现 |
| 线程删除分层失效 | `backend/app/modules/agent/thread_memory_deletion.py`、`backend/app/modules/agent/router.py` | `delete_thread_memory`、`ThreadMemoryDeletionProcessor.process_outbox`（L30-L196）、`delete_agent_thread`（L714-L726） | 用户归属 thread、热状态、摘要、候选、记忆项、向量 source | 锁线程并置 deleted；删除热状态；摘要用 self supersede tombstone；所有含 thread 来源的候选 invalidated，线程项和线程来源用户偏好 deleted；批准用户级 learning_goal 与 UserLearningMastery 不变；同事务写唯一 task-key Outbox | MySQL 立即安全失效，向量消费者失败可重试；跨用户无副作用 | 删除 API / Memory Outbox |

## 当前能力边界

1. 当前系统已经能选取近期消息、Artifact、待处理交互，并在 Router 前只读取确认后 6 个后续轮次内的 `active_topic`；过期主题不再静默影响新请求。
2. `MEM-003` 已闭环：conversation run 先做确定性理解；最新单题直接绑定，裸词“这个”或多题场景才进入候选受限的结构化模型。模型只能选择带 active 题面/Artifact 摘要的候选键，低置信度保持 unresolved，最终选择与审计一并冻结到 snapshot 并传给 child run。
3. `MEM-004` / `MEM-005` 的第二阶段已打通到过滤参数和首个澄清闭环：Validate 会从 snapshot 装载 `PracticeBundle`，继承主题、别名、难度约束、知识点 ID 和选中的 Artifact，并据此生成检索 query 与 retrieval filters；若缺少主题，会创建 `practice_topic` 输入项并在用户补充后从断点继续检索。
4. difficulty、chapter ordinal 与重复题标记都是当前轮约束：只从本轮 `raw_input` 生成并冻结在本轮 Snapshot，不进入 `active_topic_json`。后续轮次可继承主题，但新 Snapshot 与 PracticeBundle 不继承旧约束；旧 Snapshot、Artifact 和事实事件保持不变。
5. 真实排除集已闭环：Validate 完成时写 `practice_artifact_created` 事实事件，下一次练习默认排除近期已出过的题；用户明确要求重出唯一引用题时只覆盖当前读取视图，否定表达或歧义引用不放宽，历史事实不修改。
6. 掌握度已形成带时间衰减的真实读写闭环：Grade 原始累计与 evidence 永不被衰减覆盖；Practice/Planning 在统一 UTC 时点按 `mastery-decay-v1` 计算有效分数，选中时冻结 Snapshot Item。同一 Snapshot 重放保持原选择，新 Grade 证据只影响后续 Snapshot。主观题现在进入受 rubric 约束的 Assessor；低置信度、rubric 不完整或模型异常安全收敛为 ungradable，不写掌握度。
7. 本轮显式 `context_ref` 主题已在 Router 调用前写成 `topic_confirmed`；因此 Router/模型失败只会阻止 Agent 输出，不会丢失用户已表达的主题。继承的热状态主题不会重复产生确认事件。
8. Explain 成功产出 Artifact 时已写 `explanation_artifact_created`，包括零命中/检索异常后的无引用 fallback；事件不复制正文，也不修改掌握度。
9. Plan 只有在审批记录属于同一 Run、状态为 approved，且成功生成携带 approval ID 的 Artifact 后才写用户级 `plan_confirmed`；拒绝、pending、缺失审批或旁路恢复均不写长期目标。
10. PlanningBundle 已接入 Plan，EvaluationBundle 已接入 Grade，ConversationBundle 已接入 Explain；硬编码学习证据和固定批改反馈均已移除。Explain 的规划与生成模型使用 snapshot 冻结 history 和历史摘要，首次检索使用冻结题面/主题 query；结构化指代 unresolved 仍由 Router 决定是否澄清。
11. 历史摘要已形成“异步生成→预算选择→snapshot 冻结→Router/普通回答/Explain 消费”闭环；正文只作为动态 instructions 中的不可信数据，不伪装成 user history，也不进入公开 SSE。摘要和长期记忆项的 Embedding、版本替换、双层作用域复核及 Snapshot 召回冻结能力已经落地；具体 workflow 仍按能力显式选择，不在 Router 中隐式全量召回。
12. 偏好已形成“异步候选→用户治理→冲突决胜→Snapshot 冻结→Plan 消费”闭环。模型置信度不等于授权：0.95 与 0.42 候选都保持 pending；本轮明确时长可覆盖既有批准值但不改历史记录，旧 Snapshot 重放保持原结果。

## 现状问题与整改入口

| 问题 | 当前代码锚点 | 现状 | 任务单对应项 |
| --- | --- | --- | --- |
| 主题继承仍未消费掌握度等深层记忆 | `backend/app/modules/agent/context_builder.py` `ThreadContextBuilder.build` / `_active_topic_from_state`（L141-L276、L752-L772） | `active_topic` 已有 6 轮 TTL，历史摘要按预算选择；`user_learning_mastery` 仍由专用 Bundle 消费，未进入通用上下文 | `MEM-003`、`MEM-004`、`MEM-007` |
| Explain、Validate、Grade 与 Plan 已接入 bundle 化记忆 | `backend/app/modules/agent/memory_selector.py` `load_conversation_bundle` / `load_practice_bundle` / `load_evaluation_bundle` / `load_planning_bundle` | Router、普通回答与 Explain 已消费冻结摘要；Validate/Grade/Plan 继续按能力读取各自最小 Bundle，不跨能力复制摘要正文 | `MEM-004`、`MEM-005`、`MEM-007` |
| 客观/开放题掌握度闭环 | `backend/app/modules/agent/workflows/grade.py::_load_attempt_snapshot_node`（L81-L141）、`_objective_grade_node`（L144-L202）、`_open_answer_assessment_node`（L261-L345）、`_render_artifact_node`（L484-L522）；`backend/app/modules/agent/memory_projection.py::_record_grade_result_confirmed`（L311-L497） | 选择、填空、判断题仍用可信标准答案确定性产生 verdict；开放题使用冻结 rubric 的 Assessor，partial 按服务端权重投影，低置信度/ungradable 不写 mastery，全部结果都保留可回链 Artifact/活动事实 | `MEM-004`、`MEM-006` |
| 生命周期治理已闭环，管理观测待补 | `backend/app/modules/agent/thread_memory_deletion.py::delete_thread_memory` / `ThreadMemoryDeletionProcessor.process_outbox`（L30-L196） | 单轮约束、衰减、向量、偏好冲突和线程删除均已落地；下一步需要管理端 source 回查、Snapshot 复现与 Outbox 重放 | `MEM-008` |

## 设计约束

1. 原始消息和 Artifact 仍是事实源；未来长期记忆必须由它们和真实评分/审批事件投影而来。
2. Router 历史筛选使用 `token_budget=4096` 是“选择多少历史”的预算，不是模型最终输入加输出的全局上限。
3. 后续记忆闭环必须围绕事实类型和 `MemoryNeed` 稳定，而不是把 explain / validate / grade / plan 写死进存储结构。

## 下一步阅读

- 检索与 explain/validate 的现状，见 `implementation/rag-and-tools.md`。
- 模型调用预算、流式正文和 child run 继承模型配置，见 `implementation/model-runtime-streaming.md`。
