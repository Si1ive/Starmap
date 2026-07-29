# Run/Thread 事件、时间线与错误投影

## 适用场景

本分卷说明内部 Run 事件如何投影到 thread 时间线，为什么刷新后仍能恢复消息、工作流步骤和工具活动，以及
失败错误如何既保留管理端审计信息，又向用户公开安全提示。

## 跨域学习活动事件

| 阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理与错误传播 | 输出/消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 练习评分投影 | `backend/app/modules/practice/router.py`、`backend/app/modules/learning/events.py` | `_submit`（L106-L145）、`record_practice_submission`（L48-L175） | Session 行锁、冻结题目、PracticeAnswer、可选 diagnostic context | 先确定性判分，再以 `session:item` 查询/写唯一事件；诊断 Session 将来源解释 Run/Artifact 和目标知识点保留在 snapshot/payload；旧题目无知识点映射时仍可记录事实但不进入 mastery；任何数据库错误阻止同事务交卷，重试不会重复写 | `learning_activity_events`；学习进度与薄弱点消费 |
| Agent 讲解投影 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/learning/events.py` | `_record_explanation_artifact_created`（L147-L190）、`record_explanation_activity`（L161-L238） | completed Explain Artifact、Run context snapshot | 只接受冻结 active topic；缺主题安全跳过；事件与 Agent Memory fact 同事务，错误沿 Worker 失败链传播 | 无 verdict 的 exposure；学习记录和 Agent Runs 消费 |
| Agent Grade 投影 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/learning/events.py` | `_record_grade_result_confirmed`（L315-L526）、`record_agent_grade_activity`（L277-L440） | 已通过 rubric 的 grading、Feedback Artifact、冻结 topic 和 mastery flag | correct/partial/incorrect 先经过证据门禁和权重策略；authoritative treatment 才更新掌握度，并按 evidence ID 写统一评价事件；ungradable/灰度保护只记录活动事实；topic 缺失时从知识点水合，仍缺失则不虚构薄弱点 | `agent_grade_confirmed`；学习进度、薄弱点、掌握度和版本回放消费 |

`learning_activity_events` 是用户学习记录的可信事实层，不替代 `AgentEvent` 时间线。前者跨普通练习和 Agent 对话，
后者描述单次 Run 的执行过程；管理端在 Thread 详情中并排展示两者，便于判断 workflow 完成是否真正形成学习事实。

## 阶段一：自适应学习证据契约与兼容边界

自适应学习的第一阶段只冻结领域语言，不新增数据库列，也不改变现有 Worker、掌握度写入或学习进度读取。
原因是 `quality`、`is_correct` 和 `error_types` 目前服务于不同的旧页面和投影，直接重命名会让历史事件无法回放。
新的 Pydantic 契约先作为归一化边界，后续 EvidenceGate 和 Projector 只能消费归一化结果。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 领域枚举 | `backend/app/modules/learning/contracts.py` | `EvidenceType`、`EvidenceOutcome`、`AssessmentSource`、`ErrorTag` | L24-L68 | Observer、Grade 或旧活动事件提供的字符串 | Pydantic Enum 只接受冻结的证据类型、结果、评价来源和六类错误标签；未知值直接抛 `ValidationError` | 不写库；为所有后续 workflow 提供一个权威值集合 | `LearningEvidence` |
| 证据上下文 | `backend/app/modules/learning/contracts.py` | `EvidenceContext.validate_hint_levels` | L123-L134 | 题目 ID、答案来源、提示级别、答案暴露状态 | 拒绝空/重复提示，并显式区分 `not_applicable` 与 `unknown`；不从 `quality` 猜答案来源 | 结构化 `EvidenceContext`；验证失败在模型输出边界传播 | `LearningEvidence.validate_contract` |
| 证据字段与模型护栏 | `backend/app/modules/learning/contracts.py` | `LearningEvidence` | L137-L184 | `source_id`、证据类型/结果、confidence、强度、知识点和上下文 | `extra=forbid` 固定输入面；枚举和 confidence/strength 字段由 Pydantic 约束，模型没有 `mastery_score` 写入字段 | 只产生结构化证据对象；未知字段或缺少 source ID 在构造阶段失败 | `LearningEvidence.validate_contract` |
| 知识点字段校验 | `backend/app/modules/learning/contracts.py` | `LearningEvidence.validate_knowledge_point_ids`、`LearningEvidence.validate_coverage_values` | L196-L220 | 知识点 ID 列表和 coverage 映射 | 去重检查、拒绝空 ID 和越界/非正权重，为多知识点总和校验准备规范化输入 | 规范化知识点集合；错误阻止证据继续流转 | `LearningEvidence.validate_contract` |
| 证据结构校验 | `backend/app/modules/learning/contracts.py` | `LearningEvidence.validate_contract` | L223-L296 | 已通过字段校验的证据对象 | 多知识点必须逐项 coverage 且总和为 1；exposure/observation 强制 `unknown + strength=0`；self-report 只能是低强度 unknown/ungradable；带 verdict 必须声明评价来源 | 只产生不可直接写掌握度的领域对象；结构错误阻止后续投影 | `LearningEvidence.is_mastery_evidence` |
| 掌握度资格护栏 | `backend/app/modules/learning/contracts.py` | `LearningEvidence.is_mastery_evidence` | L310-L330 | 已通过结构校验的证据对象 | 仅把有 verdict、可信评价来源、正强度和知识点 coverage 的 objective/open/hint/transfer 证据标为候选；不计算分数、不写数据库 | 布尔资格结果；EvidenceGate/`MasteryProjector` 后续继续做来源归属和幂等校验 | 后续阶段的 EvidenceGate/Projector |
| 旧事件归一化 | `backend/app/modules/learning/contracts.py` | `LearningEvidence.from_legacy_activity_event` | L338-L471 | 当前 `agent_explanation_completed`、`practice_answer_graded`、`agent_grade_confirmed` 行，及其旧 `payload_json` 或新证据列 | 讲解固定映射为 exposure/unknown/0；评分保留 correct/incorrect，提示后改为 hint_assisted；新列优先、旧多知识点缺 coverage 时均分；未知事件降级为 observation/unknown | 只读生成归一化对象，不更新历史行、掌握度、薄弱点或 Outbox；缺少 source ID 由同一 Pydantic 边界拒绝 | `learning_evidence_from_activity_event` |
| 旧事件模块入口 | `backend/app/modules/learning/contracts.py` | `learning_evidence_from_activity_event` | L481-L486 | 任意 ORM/Mapping 形式的旧活动事实 | 统一转调 `LearningEvidence.from_legacy_activity_event`，避免各读取方复制默认值 | 返回同一 Pydantic 契约或传播 `ValidationError` | `LearningActivityEvent.to_learning_evidence` |
| ORM 兼容入口 | `backend/app/modules/learning/models.py` | `LearningActivityEvent.to_learning_evidence` | L22-L100 | 已从数据库加载的活动事实 | 调用同一个旧事件适配器，保持现有 `event_type`、`quality`、`is_correct` 和唯一约束不变，同时读取新证据字段 | 只读 `LearningEvidence`；异常向调用方传播，不产生数据库副作用 | 需要证据语义的读取服务 |

### 兼容规则

- `agent_explanation_completed` 的旧 `quality=0.35` 仍可供学习轨迹使用，但归一化后
  `evidence_type=exposure`、`evidence_outcome=unknown`、`evidence_strength=0`，因此不会进入权威 `UserLearningMastery`。
- `practice_answer_graded` 和 `agent_grade_confirmed` 继续按现有 `is_correct` 保留正确/错误语义；
  `source_id` 仍是旧事件的用户内幂等身份，`evidence_id` 缺省沿用它。提示级别、答案来源和答案暴露状态进入嵌套上下文。
- 旧事件没有 coverage 列时，适配器只使用去重后的知识点并按 `1 / knowledge_point_count` 均分；
  它不会把一条多知识点题复制成多条完整证据。后续迁移可在新 JSON 字段存在时优先读取显式 coverage。
- 适配器不会把旧 `answer_mismatch` 等技术诊断字符串冒充六类学习错误标签，原始活动 payload 仍由现有学习进度和薄弱点代码消费。

### 失败传播与消费边界

模型输出缺少 `source_id`、携带未知枚举、越界 confidence/strength、重复知识点或任意 `mastery_score`
时，`LearningEvidence` 构造失败；调用方应让当前观察/评分链失败或安全跳过，不能创建掌握度副作用。
归一化本身只读数据库对象，最终结果由后续 EvidenceGate、掌握度投影和薄弱点投影消费；阶段一不新增 Alembic
迁移，避免 ORM 先于真实数据库结构上线。

## 阶段三：证据门禁、权重与掌握度状态模型

阶段一的契约只回答“这是什么证据”，阶段三才允许它进入权威掌握度。入口事实仍然是
`LearningActivityEvent` 或 completed Grade Artifact；模型不能直接传入 `mastery_score`、delta
或未经策略裁剪的权重。服务端先从已验证的题面/评分快照构造 `LearningEvidence`，再由门禁确认
用户、Run、题目和知识点范围，最后把每个 verdict 按证据强度和 coverage 投影到
`UserLearningMastery`。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 评分证据构造 | `backend/app/modules/learning/evidence.py` | `build_assessment_evidence` | L246-L327 | 服务端 grading、题目 ID、知识点、答案来源、提示/答案暴露、评分/答案 confidence | 去重知识点并补均分 coverage；把 verdict、答案来源和已知错误标签归一化为唯一 Pydantic 契约；忽略未知技术标签，不接受 mastery 字段 | `LearningEvidence`，尚未写库 | `EvidenceGate.validate` |
| 来源与归属门禁 | `backend/app/modules/learning/evidence.py` | `EvidenceGate.validate` | L59-L140 | 当前 Session/Run 用户、来源用户/Run、冻结题面题目 ID、已验证知识点集合 | 拒绝跨用户、无稳定 evidence ID、Agent 无来源 Run、题目不一致、题面未验证的知识点和不可信答案来源；默认要求 mastery coverage，练习兼容路径可显式关闭；失败抛 `EvidenceGateError` | 通过则原样返回证据；Grade 门禁失败只跳过 mastery，练习交卷门禁失败沿事务错误传播 | `finalize_evidence_weight` |
| 服务端权重 | `backend/app/modules/learning/evidence.py` | `EvidenceWeightPolicy.calculate` | L164-L243 | evidence type、assessment source、评分/答案 confidence、提示、答案暴露、题目审核状态和可选 suggested weight | 按类型/来源设上限；提示、答案暴露、模型答案和低 confidence 只会降权；生成题答案 confidence 再乘独立可信度因子；suggested weight 先裁剪到 `[0,1]` 再取策略上限；按 coverage 生成每个知识点的分摊强度 | `EvidenceWeight`（policy version、总强度、point strength、原因码） | `MasteryProjector.apply` 或活动事实列 |
| 活动事实落库 | `backend/app/modules/learning/events.py` | `record_practice_submission`、`record_explanation_activity`、`record_agent_grade_activity` | L51-L181、L184-L273、L277-L440 | 已确定性判分的 PracticeAnswer、Explain Artifact、Grade Feedback Artifact | 在旧 `quality/is_correct` 之外写 evidence type/outcome/source/strength/confidence/model/coverage，并把完整证据和 flag policy version 放入 payload；ungradable/灰度保护只写活动；沿原 `(user,event_type,source_id)` 唯一约束幂等 | `learning_activity_events` 新列和旧兼容列；管理员/学习进度/评估回放读取新字段 | 事件读取或 Agent Grade 掌握度投影 |
| Grade 事实与幂等 | `backend/app/modules/agent/memory_projection.py` | `_record_grade_result_confirmed` | L315-L526 | completed feedback 的 grading、evidence ID、题目、知识点和 mastery flag | 先按 `(user,evidence_id)` 查 `AgentMemoryEvent`；ungradable 或非 authoritative treatment 只回链活动事件并返回，其余经过门禁和权重后写 memory fact，再逐知识点调用 projector；重复 Run 只补 Outbox，不重新累计 | `AgentMemoryEvent`、`AgentMemoryUpdateOutbox`、`UserLearningMastery` 与 rollout snapshot 同事务更新；门禁失败不创建掌握度副作用 | `record_agent_grade_activity` 与管理端/学习记录 |
| 加权掌握度投影 | `backend/app/modules/agent/mastery_projector.py` | `MasteryProjector.apply` | L35-L138 | 一个知识点行、LearningEvidence、coverage 分摊权重、partial credit、证据时间 | correct 增加 alpha，incorrect 增加 beta，partial 按比例拆分；`mastery_score=alpha/(alpha+beta)` 保持旧读取字段，`evidence_mass` 累加实际强度，`uncertainty` 随证据质量下降；exposure/unknown/ungradable 直接返回 | 更新 alpha/beta、score、兼容次数、last evidence、state model version 和审计 metadata；不接受模型 delta | `mastery_decay` / `memory_selector` 冻结到下一轮 Snapshot |
| 读时衰减与选择 | `backend/app/modules/agent/mastery_decay.py`、`memory_selector.py` | `calculate_effective_mastery`、`_mastery_signal` | decay L28-L62；selector L192-L239 | 原始 mastery score、last evidence time、state/policy version | 保留原 90 天半衰期语义，优先使用 `last_evidence_at` 并把 state model/policy version、uncertainty、evidence mass 一并放入派生信号；不修改数据库累计值 | 可回放的 effective mastery signal | Planning/Practice Bundle 和 Conversation Tutor |

### 阶段三的不变量和错误传播

- Explain 只写 `exposure + unknown + strength=0`；其旧 `quality=0.35` 仍服务于活动轨迹，不能进入
  alpha/beta。用户自我声明仍不会得到评分 verdict。
- 同一证据在活动层由 `uk_learning_activity_source` 去重，在 Agent Grade 掌握度层由
  `grade_result_confirmed:{user}:{evidence_id}` 去重；重试不增加 evidence count、alpha 或 beta。
- 多知识点题目在契约层必须 coverage 总和为 1，projector 每次只消费一个知识点对应的
  `point_strength`，所以不会把同一题完整计入每个知识点。
- `_record_grade_result_confirmed` 只捕获来源门禁错误并安全跳过掌握度；数据库唯一键、flush 和
  Outbox 错误继续向 Worker 事务错误链传播。普通练习交卷的证据门禁发生在 `_submit` 的同一事务内，
  门禁失败会阻止不完整学习事实与交卷状态一起提交。
- `learning_progress` 和管理员 Thread 详情只读旧列与新列的并存结果；管理员还可以从
  `user_learning_mastery` Snapshot item 看到 alpha/beta、uncertainty 和 state model version，
  用户端不展示模型内部推理文本。

## 阶段四：静默 LearningObserver 与诊断 hypothesis

Observer 复用 Agent Run 主链，但它是来源 conversation 的异步派生事实，不是第二条用户回答。来源 Run
先完成 Artifact 和既有学习事实投影，再创建 silent child；因此观察失败不能回滚用户已经看到的正文，且
`thread_events` 会按既有 silent 规则拒绝公开 Observer 的 step、错误和内部结构化输出。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 完成交接 | `backend/app/modules/agent/worker.py`、`backend/app/modules/agent/learning_observer.py` | `AgentWorker.process_run`、`schedule_learning_observation` | worker L212-L281；observer L76-L124 | completed Run、来源 message、parent/root、observer version 和稳定分桶 | Worker 先落 Artifact、调用 `project_completed_run_facts`、写 `run.completed`，再按 flag 只为根 conversation 入桶用户以稳定 key 创建 silent child；Observer workflow 自身不触发摘要维护 | `agent_runs`、`agent_events`、`agent_run_outbox`；来源 Run 保持 completed，flag snapshot 可回放 | `learning_observation@v1` |
| 输入权限与冻结 | `backend/app/modules/agent/learning_observer.py`、`backend/app/modules/agent/workflows/learning_observation.py` | `build_observer_input_snapshot`、`_prepare_observation_node` | observer L133-L271；workflow L34-L49 | source Run/message ID、user/thread/root、原 context audit 与相关 Artifact | 逐项复核来源归属，只复制原 Run 已选消息、同 root 已完成非 silent Artifact 摘要、active topic 和数据库存在的知识点；文本截断，助手内容标为 context-only，越权或缺来源抛错 | 冻结 `observer_input_snapshot` 写 Run metadata 和下一节点上下文 | `_observe_turn_node` |
| 模型结构护栏 | `backend/app/modules/agent/model_runtime/observer.py`、`backend/app/modules/agent/workflows/learning_observation.py` | `TurnObservation`、`TurnObservationOutput`、`LearningObserverRuntime.observe`、`_observe_turn_node` | runtime L37-L87、L131-L192；workflow L52-L88 | 冻结输入、source message ID、允许知识点 ID、一次调用预算 | Pydantic AI 只允许 exposure/confusion/hypothesis/self-report/open-response-candidate，outcome 限 unknown/ungradable；禁止额外 mastery/weight 字段，再复核模型返回的 message 和知识点范围 | 结构化输出写 Run metadata、Step output 和统一 LLM audit；模型错误进入 silent Run 失败链 | `_project_observation_node` |
| 非掌握度活动投影 | `backend/app/modules/agent/learning_observer.py`、`backend/app/modules/agent/workflows/learning_observation.py` | `record_turn_observation`、`_project_observation_node` | observer L301-L431；workflow L91-L117 | 结构化 observations、source Run/version、知识点候选 | 以 source Run/version 查询唯一事件，经 EvidenceGate 校验归属和范围；统一写 `unknown + strength=0`，exposure 与 observation 均不调用 MasteryProjector；困惑/假设/开放回答候选带 14 天 expiry | `agent_turn_observed` 和可回链 payload；`UserLearningMastery` 不变化 | 下一轮 LearningSnapshot / 学习活动 / 管理端 |
| 下一轮冻结消费 | `backend/app/modules/agent/learning_snapshot.py` | `_freeze_diagnostic_hypotheses`、`load_learning_snapshot_summary` | L128-L218、L221-L291 | 当前用户 Snapshot、14 天内 Observer 活动及 payload expiry | 优先读取本 snapshot 已冻结项；首次读取时复制未过期 hypothesis 为 `learning_hypothesis` item，过滤过期/非法 payload，非 UUID 兼容标识安全空读 | `diagnostic_hypotheses`、source item IDs；原活动和 mastery 不修改 | ConversationTutorAgent |

错误传播分三层：模型或结构验证失败由 WorkflowEngine 写 `step.failed`，Worker 只把 Observer child 标记 failed；
来源越权/知识点越界同样失败且不写活动；活动唯一键或数据库失败沿 Observer 事务传播并由 Outbox 重试。
由于来源 conversation 在调度前已经 completed，以上失败都不会覆盖来源 Artifact、SSE、活动事实或 mastery。

## 阶段五：开放回答评估与诊断题闭环

开放题沿 Grade 的现有 Run/Step/Event/Artifact 主链增加一个受控 Assessor 分支；客观题仍由服务端确定性
比较。解释后诊断题不新增协议或表，而是通过 Worker 创建 Validate child，复用 Practice Session 快照，
交卷后仍由既有确定性 `_submit` 和学习活动投影完成。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Assessor 结构护栏 | `backend/app/modules/agent/model_runtime/assessor.py` | `OpenAnswerRubric`、`OpenAnswerAssessment`、`normalize_open_answer_assessment` | L43-L107、L172-L210 | 冻结标准答案/解析、criterion 权重、模型结构化输出 | `extra=forbid`，服务端校验 criterion 覆盖和最小置信度；服务端重写 evidence ID；低置信度、不完整 rubric、模型 `ungradable` 或异常只形成 ungradable，不进入掌握度 | 受控 Assessment 与安全 feedback reason | Grade `_open_answer_assessment_node` |
| Grade 分支与反馈 | `backend/app/modules/agent/workflows/grade.py` | `_load_attempt_snapshot_node`、`_open_answer_assessment_node`、`_open_answer_grading_evidence`、`_generate_feedback_node`、`_render_artifact_node` | L86-L145、L210-L377、L417-L499、L516-L550 | EvaluationBundle、开放题用户回答、提示/答案暴露、目标知识点和 Assessor flag | 只把冻结题面/知识点交给 Assessor；关闭/shadow 安全收敛，partial 按服务端 rubric 权重算分，四种 verdict 保持原语义；反馈与 Artifact 只保存结构化证据，不接受模型 mastery/delta | Feedback Artifact 的 `grading`；ungradable 可完成并显示“需要更明确回答” | Worker 完成交接 |
| 证据权重与掌握度 | `backend/app/modules/learning/evidence.py`、`backend/app/modules/agent/memory_projection.py`、`backend/app/modules/learning/events.py` | `EvidenceWeightPolicy.calculate`、`_record_grade_result_confirmed`、`record_agent_grade_activity` | evidence L164-L327；projection L315-L526；events L277-L440 | grading verdict、assessment source、model/answer confidence、coverage、错误标签和灰度处理 | LLM rubric 受 open-response/source cap；生成题额外乘答案可信度；partial 传入 `partial_credit`；ungradable/关闭/shadow 只写零强度活动或跳过 authoritative mastery | `LearningEvidence`、`agent_grade_confirmed`、必要时 mastery/Outbox；错误标签和版本供 Weakness/评估读取 | LearningProgress/Weakness |
| 诊断入口与回链 | `backend/app/modules/agent/diagnostic.py`、`backend/app/modules/agent/workflows/validate.py` | `schedule_diagnostic_check`、`_load_learning_evidence_node`、`_question_gate_node`、`_create_draft_node`、`_render_artifact_node` | diagnostic L40-L161；validate L52-L119、L227-L264、L364-L397、L400-L502 | 已完成 explain/direct answer Run、冻结 teaching policy、目标 KP/主题 | 以版本化 idempotency key 创建 Validate child；子 Run 只复用冻结 context/目标，题目快照写来源解释 Run/Artifact/KP；Validate 不会递归触发诊断 | compact Validate Run、Practice Session/Artifact 和安全 diagnostic payload | Practice `_submit` -> `record_practice_submission` |

失败边界也分开：Assessor 模型/结构错误在 Grade 节点收敛为 `ungradable`，仍可产出反馈但不更新 mastery；
EvidenceGate/数据库错误仍沿原 Worker 事务失败链传播。诊断 child 创建失败不改变已完成解释 Run，诊断题答对
不会删除历史错误，答错则以 `diagnostic_context` 回链来源解释 Run、目标知识点和后续 Weakness 输入。

## 事件写入与公开投影

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 内部事件追加 | `backend/app/modules/agent/events.py` | `EventStore.append`（L29-L112） | run 事件类型和 payload | 分配 run 内 sequence，写入 `agent_events`，触发 thread 投影；对可诊断事件读取并持久化记忆前后状态 | 内部事件事实与 `agent_memory_traces` | `ThreadEventStore.project_run_event` / 管理端记忆时间线 |
| Thread 投影总入口 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event` | `run.status_changed`、`step.*`、`tool.*`、`message.*`、`run.failed` | 把内部事件映射成统一的公开 thread 事件，并保持 cursor 单调递增 | `agent_thread_events` | SSE / 时间线刷新 |
| 消息投影 | `backend/app/modules/agent/thread_events.py` | `_project_message_event` | `message.delta`、`message.completed`、`message.failed` | 第一个 delta 创建 assistant item，后续 delta 追加正文；completed/failed 收敛状态 | 可恢复消息事实 | `AgentTimelineService.get_timeline` |
| 审批终态分流 | `backend/app/modules/agent/service.py` | `AgentService.decide_approval`（L424-L476） | waiting run、pending approval、用户 approve/reject | 先校验用户、状态、审批归属和 decision；批准时恢复 running 并投递 Outbox，拒绝时转 failed、删除 checkpoint 且不投递，二者都写 `run.status_changed` | 可恢复执行的 approved run，或不会再执行的 rejected run | `AgentWorker.process_run` / timeline |
| 时间线快照构建 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService.get_timeline`、`message_view`、`_build_workflow_views` | Thread 下消息、Run、步骤、事件、Artifact、审批 | 按 root run 聚合并重建消息、工作流步骤、活动与 Artifact | 刷新可恢复的 timeline snapshot | HTTP / 前端刷新 |
| SSE 消费 | `frontend/src/store/agent-context.tsx` | `AgentProvider.connectThreadStream` | thread ID、cursor | 连接 EventSource，实时归并消息/工作流事件，必要时回拉快照 | 浏览器状态 | `timeline-state` reducer |

## 失败错误如何公开且不覆盖正文

| 执行阶段 | 文件 | 符号 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 错误分类 | `backend/app/modules/agent/public_errors.py` | `classify_agent_error` / `public_error_message` | worker 得到异常或刷新时重建错误文案 | 生成稳定 `error_code` 与安全中文提示，不暴露供应商敏感原文 | Worker / timeline 刷新 |
| 失败持久化 | `backend/app/modules/agent/worker.py` | `AgentWorker._record_failure` | Run 执行失败 | `run.error_message` 保留原始错误；metadata 和事件写稳定码与公开消息 | 管理端审计 + 用户端安全错误 |
| 失败消息投影 | `backend/app/modules/agent/thread_events.py` | `_project_message_event`（failed 分支） | 失败前已有 partial 正文 | 不再把失败文案写进 `content_text`，只更新状态和错误字段 | 刷新后仍保留 partial 正文 |
| 刷新恢复 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService.message_view` | 页面刷新读取 `AgentMessage` | 用持久化的 `error_code` 重建 `error_message`，无需新增列 | `TimelineResponse` |
| 前端失败归并 | `frontend/src/features/agent/timeline-state.ts` | `applyMessageEvent`（failed 分支） | 实时 `message.failed` | 同时保留 content、error_code、error_message | React 消息状态 |
| 前端失败显示 | `frontend/src/features/agent/ConversationStream.tsx` | `TimelineItemView`（failed 分支） | assistant status 为 failed | 有正文时正文与红字原因分开显示；无正文只显示一次原因 | 用户对话页面 |

## 工作流步骤与活动为什么刷新后不丢

| 执行阶段 | 文件 | 符号 | 职责 |
| --- | --- | --- | --- |
| Artifact 工厂契约 | `backend/app/modules/agent/workflows/contracts.py` | `NodeResult.success` | render 节点可通过统一工厂方法同时返回 `output`、`next_node` 和最终 `artifact`，避免 completed 之前丢失产物 |
| 节点输入审计 | `backend/app/modules/agent/workflows/contracts.py`、`backend/app/modules/agent/workflows/engine.py` | `ExecutionContext.audit_input`、`WorkflowEngine.execute` | 节点开始前把 `input_message`、上下文 key 和递归收敛后的变量快照写入 `AgentStep.input_data` 与 `step.started.input`；模型/工具输出仍写在完成事件中，管理端可把输入和输出配对定位 |
| 节点进度持久化 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | 每个 step 的开始、完成、失败都写 `agent_steps` 和 `agent_events`，并在关键边界 commit |
| 当前公开步骤 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | run 进入 running 和完成时维护 `current_public_step`、最终 artifact 和消息完成事件 |
| 最终正文与产物落库 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | workflow 返回 completed 后创建 `AgentArtifact`、写 `artifact.rendered` / `message.completed` / `run.completed`，让刷新可恢复最终正文和 artifact |
| Plan 恢复审批守卫 | `backend/app/modules/agent/workflows/plan.py` | `_apply_plan_change_node`（L184-L208） | checkpoint 中的 approval ID 与 plan draft | 从数据库重读审批，只有真实状态为 approved 才设置 final plan；pending/rejected/缺失均返回失败，阻止绕过服务层恢复 | approved 计划或失败结果，不会产生未授权 Artifact |
| 时间线步骤重建 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._build_workflow_views` | 按 root run 聚合 child runs、steps、tool events、pending input 和 approvals |
| 活动按 ID 归并 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._activity_views` | `tool.called` + `tool.result` 共享同一 `activity_id` 时可在刷新后重建成一个活动 |
| 记忆变化观测 | `backend/app/modules/agent/memory_observability.py` | `capture_memory_state`（L130-L304）、`record_memory_trace`（L307-L331） | 事件或 Memory Outbox 边界前后的 Run | 只读收集线程热状态、Snapshot、事实事件、长期记忆项、掌握度、摘要和派生任务；保存前后副本并标记 `changed` | `agent_memory_traces`；不参与业务决策 | `get_run_memory_observability` |

## 阶段七：学习事实的版本审计与灰度保护

灰度开关不新增第二套事件表。现有 `LearningActivityEvent` 的 payload 追加
`adaptive_learning_flag_policy_version`，有 Run 归属的讲解/Grade 还复制本轮
`adaptive_learning_flags`；Grade 的 `AgentMemoryEvent` 同时保存 mastery rollout
决策。`UserLearningMastery.metadata_json` 保存实际投影时的 flag snapshot，
而 `state_model_version` 继续标识掌握度状态算法。这样事件、掌握度和下一轮
Snapshot 可以按版本回放，关闭新模型时也不会删除已经产生的评分活动。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 活动版本载荷 | `backend/app/modules/learning/events.py` | `record_practice_submission`、`record_explanation_activity`、`record_agent_grade_activity` | L51-L181、L184-L273、L277-L440 | 交卷/Artifact/Grade 事实、weight policy、Run metadata | 保留旧列和统一 `learning_evidence`，追加 flag policy version；有 Run 的事件携带用户当时的 flag snapshot | `learning_activity_events.payload_json`；同源唯一键继续幂等 | 学习进度/Weakness/评估回放 |
| Observer 版本载荷 | `backend/app/modules/agent/learning_observer.py` | `record_turn_observation` | L315-L445 | silent Run metadata、结构化观察、来源消息 | 将 Observer version、flag snapshot、hypothesis TTL 和零强度 evidence 一起写入活动 payload；不调用 projector | `agent_turn_observed`；来源 conversation 不被修改 | LearningSnapshot |
| Mastery 灰度保护 | `backend/app/modules/agent/memory_projection.py` | `_record_grade_result_confirmed` | L315-L526 | 可信 Grade、EvidenceWeight、`mastery_model_v2` decision | 先写可回链 memory fact 和活动；只有 `decision.is_authoritative` 才逐知识点调用 `MasteryProjector`，并在新行/旧行 metadata 固化 flag snapshot | 评分活动可存在而 `UserLearningMastery` 不变；Outbox 仍按事实幂等 | 后续 Snapshot/离线回放 |

模型失败、配置关闭、shadow 保护和 EvidenceGate 拒绝都不删除原始回答或已完成
Run；只有真正通过门禁且进入 authoritative treatment 的证据才产生掌握度副作用。

## 回归测试入口

| 验证目标 | 文件 | 符号 | 覆盖内容 |
| --- | --- | --- | --- |
| 工作流公开步骤与输入持久化 | `backend/tests/test_agent_workflow_engine.py` | `test_engine_persists_public_step_for_timeline_snapshot` | 校验 step.started / step.completed 真实提交后，时间线刷新仍能恢复当前步骤，并且事件与 `AgentStep.input_data` 保存同一份节点输入 |
| Explain 最终 Artifact 不再丢失 | `backend/tests/test_agent_workflow_engine.py` | `test_explain_workflow_keeps_artifact_through_render_and_completion` | 真正执行 explain workflow 到 `render_artifact -> completed`，确认 `NodeResult.success(..., artifact=...)` 可把 artifact 保留到最终结果 |
| Explain 无资料回退在 worker 持久化后仍可刷新恢复 | `backend/tests/test_agent_explain_worker.py` | `test_worker_persists_zero_hit_fallback_answer_without_citations`、`test_worker_persists_retrieval_error_fallback_answer_without_citations` | 真实执行 `AgentWorker.process_run`，覆盖零命中和检索异常两条路径的活动卡片、artifact、最终消息与线程刷新恢复 |
| Plan 拒绝与恢复守卫 | `backend/tests/test_agent_plan_worker.py` | `test_rejected_plan_stops_without_outbox_or_artifact`（L165-L201）、`test_plan_apply_node_rejects_unapproved_checkpoint`（L205-L220）、`test_approved_plan_resumes_and_creates_artifact`（L224-L283） | 覆盖拒绝不重投递/不产物/不写记忆、错误恢复仍被节点拒绝，以及批准后生成计划并幂等写确认事实 |
| LearningObserver 隔离与下一轮消费 | `backend/tests/test_agent_learning_observer.py` | `test_completed_root_conversation_creates_one_silent_observer_run`、`test_observer_confusion_is_zero_strength_and_visible_in_next_snapshot`、`test_observer_failure_does_not_change_completed_source_run` | 覆盖 source/version 幂等 silent child、零强度活动且不写 mastery、14 天 hypothesis 冻结到下一轮 Snapshot，以及模型失败不改变来源 Run |

## 当前整改关注点

1. `FLOW-001` 已在 2026-07-25 完成：workflow 最终 Artifact 通过 `NodeResult.success(..., artifact=...)` 进入 `context.artifacts`，Explain 渲染链已补回归测试。
2. `ACT-001` 要稳定逻辑 `activity_id`，否则即便后端只是在重试，时间线刷新和 SSE 都会显示成多张活动卡片。
3. `EXP-001` 已在 2026-07-26 补齐 worker 级验收：零命中和工具异常两条公开路径都会保留正确活动语义，且最终正文、artifact 与空 citations 均可在刷新后恢复。
4. 人工输入恢复入口由 `backend/app/modules/agent/service.py::AgentService.get_input`（L315-L327）同时接受稳定 `input_key` 与兼容 `input_id`；`AgentService.submit_input_answer`（L329-L350）仍校验 run 所有权、等待状态、pending 状态与过期时间，失败继续安全返回 404，成功才恢复 run 并入队。
4. Plan 审批已按决定分流：拒绝是用户终止计划变更，不再恢复 checkpoint 或生成 Artifact；应用节点还会从数据库复核 approved 状态，避免任何旁路绕过审批。

## 下一步阅读

- 检索和工具当前实现，见 `implementation/rag-and-tools.md`。
- 管理端如何读取这些事实并按 Thread/turn 展示，见 `implementation/admin-observability.md`。
