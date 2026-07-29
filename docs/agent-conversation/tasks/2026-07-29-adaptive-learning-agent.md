# 2026-07-29 自适应学习 Agent 与掌握度闭环落实步骤

## 任务定位

任务 ID：`LEARN-001`
状态：实施中（阶段一至阶段四已完成）
阶段状态：阶段一“冻结契约与兼容边界”、阶段二“合并 Router 与 Tutor 策略”、阶段三“学习证据与掌握度模型升级”和阶段四“异步 LearningObserverAgent”已完成；阶段五及后续阶段待实施。
目标：在现有 Agent 练习、评分、学习活动和薄弱点闭环之上，补齐“用户对话行为 → 结构化学习证据 → 掌握度/不确定性 → 下一步教学策略”的自适应学习链路。

本任务采用以下总体决策：

1. 在线只保留一个 `ConversationTutorAgent`，逻辑上合并当前 Router 与 Tutor 的职责；`workflow` 表示业务执行分支，`teaching_mode` 表示教学策略。
2. `LearningObserverAgent` 作为完成 Run 后的静默异步 workflow，负责从自然语言中抽取知识点、困惑和“需要诊断”的假设，不直接写权威掌握度。
3. 客观题继续由确定性 Grade workflow 判定；开放题或用户主动解释才触发受 rubric 约束的 `OpenAnswerAssessorAgent`。
4. `MasteryProjector` 和 `WeaknessProjector` 使用普通 Python 领域服务实现，模型不能直接设置掌握度、证据权重或薄弱项。
5. RAG、知识点/题目检索和学习状态读取是只读能力；出题、创建练习和评分通过现有 workflow/领域服务执行，不引入 MCP。
6. 首版使用可解释、可回放的加权证据模型；不在本任务中直接引入 DKT 等黑盒 Knowledge Tracing 模型。

## 不在本任务范围内

- 不替换现有 `WorkflowEngine`、Worker、Agent Run/Step/Event、Outbox 和 SSE 主链。
- 不把普通讲解、RAG 命中或用户自我声明直接当成掌握度 verdict。
- 不开放 `update_mastery`、`set_weakness` 等模型写工具。
- 不把模型生成题伪装成审核题；模型题必须保留来源可信度并使用独立证据权重。
- 不在同一次改动中重写用户端学习进度页面；只先稳定后端事件和读取契约。

## 当前实现基线与代码锚点

| 执行阶段 | 文件 | 符号 | 代码范围 | 入口条件 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 上下文与路由 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | L54-L208 | conversation Run 已创建 | 构建线程上下文、指代理解和 memory snapshot，读取同一 snapshot 的 LearningSnapshot 摘要，调用合并后的 ConversationTutorRuntime，冻结 capability/context/decision/teaching policy 元数据 | `AgentRunContext`、`ConversationDecision`、root Run metadata | direct/clarify 或 `_dispatch_workflow_node` |
| 路由模型 | `backend/app/modules/agent/model_runtime/router.py` | `conversation_tutor_agent` | L61-L80 | 已冻结的请求、历史摘要、LearningSnapshot 和能力清单 | 一次返回 `ConversationDecision` 的 workflow 与教学策略，不直接回答、不直接写学习事实；`router_agent` 仍为兼容别名 | action、teaching_mode、知识点目标、诊断标记、只读意图和理由代码 | `ConversationTutorRuntime.decide` |
| 路由护栏 | `backend/app/modules/agent/model_runtime/router.py` | `ConversationTutorRuntime.decide` | L233-L320 | 模型返回路由结果 | 校验 action/read intent/知识点范围；显式出题/批改/计划/讲解请求覆盖模型误判；clarify 必须有问题；旧输出补齐默认教学模式 | 受控 `ConversationDecision` | conversation workflow 分支 |
| Child workflow 交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata`、`_dispatch_workflow_node` | L275-L323、L326-L367 | action 为 explain/validate/grade/plan、冻结 teaching policy | 按 capability、Run/User 和父子关系幂等创建 child Run，冻结上下文、能力快照和 teaching policy；不再次调用 Router | child Run、AgentTimeline workflow item、Agent Run Outbox | Worker 执行 child workflow |
| 工具门禁 | `backend/app/modules/agent/tools/registry.py` | `ToolRegistry.execute` | L75-L103 | workflow 请求调用已注册工具 | 校验注册状态、workflow allowlist、只读属性、未知参数和必要参数 | 工具执行；异常传播至节点错误链 | `retrieve_knowledge` 或其他领域服务 |
| 知识库检索 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | L158-L386 | 有合法 Run、query 和范围过滤 | 由 Run 反查用户，执行混合检索，记录稳定 activity/attempt/trace，并过滤私有资料所有权 | 结构化 RAG 结果、`tool.called/result` 事件 | Explain/Validate 消费结果 |
| 练习候选 | `backend/app/modules/agent/workflows/validate.py` | `_question_discovery_node` | L81-L179 | Validate 已加载 PracticeBundle | 组装知识点/章节/难度/排除集过滤，通过 Tool Registry 检索题目；空命中进入生成分支 | candidates 或题库不足分支 | question gate/generate |
| 模型出题 | `backend/app/modules/agent/workflows/validate.py` | `_generate_question_node` | L207-L266 | 题库没有合格候选且主题明确 | 调用结构化 PracticeGenerationRuntime，生成带答案、解析、来源标识的单选题 | Agent 即时题候选；不进入公共题库 | composition/create draft |
| 题目生成运行时 | `backend/app/modules/agent/model_runtime/practice.py` | `PracticeGenerationRuntime.generate` | L37-L65 | Run 模型配置和主题/难度已冻结 | 使用 Pydantic AI `GeneratedPracticeQuestion` 输出并受 request limit 保护 | 结构化题面、选项、答案和解析 | Validate 继续执行 |
| 客观评分 | `backend/app/modules/agent/workflows/grade.py` | `_objective_grade_node` | L81-L129 | 题面、标准答案和用户答案均来自 EvaluationBundle | 归一化 choice/fill/judge 答案，确定性产生 correct/incorrect 和评分证据 | `objective_result`、`grading_evidence` | rubric/feedback/render |
| 练习活动事实 | `backend/app/modules/learning/events.py` | `record_practice_submission` | L44-L158 | Session 交卷且答案已判定 | 以 Session Item 幂等写 `practice_answer_graded`，保留题目快照、知识点和提示信息，并计算 evidence type/source/strength/coverage；旧题目没有服务端 knowledge point 时只记录活动事实，不进入 mastery | LearningActivityEvent | 学习进度/薄弱点读取或投影 |
| 讲解活动事实 | `backend/app/modules/learning/events.py` | `record_explanation_activity` | L161-L238 | Explain Artifact 完成且主题可信 | 写无 verdict 的主题 exposure；当前 `quality=0.35` 不代表掌握度贡献，同时固化 exposure/unknown/0 | `agent_explanation_completed` | 学习活动展示，不进入权威 mastery |
| Agent Grade 活动 | `backend/app/modules/learning/events.py` | `record_agent_grade_activity` | L241-L371 | Feedback Artifact 携带 confirmed verdict | 将对话评分映射到统一学习活动事件，经过 EvidenceGate/WeightPolicy 并回链 Run/Thread | `agent_grade_confirmed` | WeaknessService/学习进度 |
| 证据门禁与权重 | `backend/app/modules/learning/evidence.py` | `EvidenceGate.validate`、`EvidenceWeightPolicy.calculate` | L59-L140、L164-L240 | 服务端评分结果、来源用户/Run、冻结题面和 coverage | 校验用户/Run/题目/知识点/答案来源；按类型、提示、答案暴露、confidence 和题目可信度裁剪强度；练习兼容路径可显式仅记录无 coverage 事实 | `LearningEvidence`、`EvidenceWeight` | 活动事件或 `MasteryProjector.apply` |
| 掌握度投影 | `backend/app/modules/agent/memory_projection.py`、`mastery_projector.py` | `_record_grade_result_confirmed`、`MasteryProjector.apply` | memory L315-L484；projector L35-L138 | Feedback grading 含可信 verdict、题目和知识点 | 以 evidence ID 幂等写 memory fact；按 coverage 更新 alpha/beta、evidence mass、uncertainty 和兼容 score | mastery、AgentMemoryEvent、Memory Outbox | 长期记忆/后续选择 |
| 掌握度读时衰减 | `backend/app/modules/agent/mastery_decay.py` | `calculate_effective_mastery` | L28-L62 | 有原始分数、证据时间和读取时点 | 按固定策略计算 effective score，同时保留 state/policy version，不修改原始累计值 | `EffectiveMastery` | Practice/Plan/学习状态读取 |
| 掌握度模型 | `backend/app/modules/agent/models.py` | `UserLearningMastery` | L697-L755 | 已有可信评分证据 | 保存兼容 score/count、alpha/beta、evidence mass、uncertainty、最近证据时间和 state version | 用户级知识点掌握度表 | 新 `LearningSnapshot` 读取 |
| Run 完成交接 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L106-L331 | WorkflowEngine 返回 completed/waiting/failed | 先将 Run metadata 中已冻结的 teaching policy/decision/LearningSnapshot 注入 ExecutionContext，再持久化 Artifact、投影完成事实、写 Run 状态并投递摘要/偏好；根 conversation 同边界幂等调度 Observer，Observer 自身不递归派生摘要 | Run/Artifact/Event/Outbox/Observer child | 业务或 Observer Outbox |

## 目标执行链

```text
用户消息
  ↓
ConversationTutorAgent：workflow + teaching_mode + 只读查询
  ↓
现有 conversation workflow / child workflow
  ├─ direct_answer / explain / validate / grade / plan
  ├─ RAG 与题目检索
  └─ 练习 Artifact / Feedback Artifact
  ↓
完成 Run 后创建 silent learning_observation@v1 Run
  ↓
LearningObserverAgent：提取知识点、行为信号、错误标签、诊断需求
  ↓
EvidenceGate：校验来源、用户归属、知识点、评分来源和证据上限
  ├─ exposure / hypothesis：只写活动事实，不改变权威 mastery
  ├─ objective assessment：使用确定性 verdict
  └─ open response：调用 OpenAnswerAssessorAgent 或安全跳过
  ↓
LearningActivityEvent / 结构化学习证据
  ↓
MasteryProjector + WeaknessProjector
  ↓
下一轮 memory snapshot / LearningSnapshot
  ↓
ConversationTutorAgent 选择下一步教学动作
```

`learning_observation@v1` 使用现有 `AgentService.create_run` 和 `AgentRunOutbox`，Run 的 `presentation` 使用 `silent`，不新增第二套模型任务队列。观察失败只让静默 Run 重试或失败，不得回滚已经完成的用户回答、Artifact、SSE 和活动事实。

## 阶段一：冻结契约与兼容边界

实施状态：已完成（领域契约、旧事件只读适配和边界回归测试已提交）。

### 目标

先固定领域语言和不变量，再修改模型调用，避免 Router、学习记录、薄弱点和掌握度各自定义一套“正确/薄弱”。

### 实施内容

1. 定义 `EvidenceType`：`exposure`、`self_report`、`open_response`、`objective_assessment`、`hint_assisted`、`transfer`、`observation`。
2. 定义 `EvidenceOutcome`：`unknown`、`correct`、`partial`、`incorrect`、`ungradable`。
3. 定义 `AssessmentSource`：`deterministic`、`llm_rubric`、`user_report`、`question_bank`、`generated_question`。
4. 定义错误标签集合，并区分 `concept_gap`、`misconception`、`retrieval_gap`、`procedure_gap`、`transfer_gap`、`careless_error`。
5. 固定不变量：
   - RAG 命中和讲解完成不更新权威 mastery；
   - 用户自我声明不能产生强评分证据；
   - 模型不能提交任意 mastery 分数；
   - 同一 source/evidence ID 重放不得重复计数；
   - 多知识点题目必须使用 coverage 权重，不能对每个知识点完整计数；
   - 题目答案来源、提示和答案暴露状态必须进入证据上下文。

### 验收

- Pydantic schema 可以表达上述类型，未知枚举、越界 confidence 和缺少 source ID 会失败。
- 当前 `agent_explanation_completed`、`practice_answer_graded`、`agent_grade_confirmed` 的既有语义保持兼容。
- 为旧事件定义明确默认值，不把历史讲解事件回填成 mastery evidence。
## 阶段二：合并 Router 与 Tutor 策略

实施状态：已完成；ConversationDecision 契约、ConversationTutorRuntime 兼容别名、
只读能力 allowlist、LearningSnapshot 摘要、conversation/child Run 策略冻结以及
Explain/Validate/Grade 的策略读取均已落地。后续阶段再实现诊断题、Observer 和更完整
的学习状态模型。

### 目标

将当前只判断高层 action 的 Router 演进为一个在线 `ConversationTutorAgent`，一次模型调用同时返回业务 workflow 和教学策略；不改变 child workflow 的持久化职责。

### 实施内容

1. 扩展当前 `RouterDecision` 或重命名为兼容的 `ConversationDecision`，增加：
   - `teaching_mode`；
   - `target_knowledge_point_ids`；
   - `need_diagnostic_check`；
   - `read_tool_intents`；
   - 稳定 `reason_codes`。
2. `RouterDeps` 注入当前 Run 的只读 `LearningSnapshot` 摘要、能力 manifest、用户/线程/Run ID；不注入任意写库函数。
3. 保留 `_explicit_workflow_action` 确定性护栏，显式“出题/批改/计划/讲解”不得被模型改成普通回答。
4. 第一版只允许以下只读能力：`get_learning_snapshot`、`retrieve_knowledge`、`search_question_candidates`；工具仍通过 `ToolRegistry` 进行 workflow/参数/用户所有权校验。
5. `conversation._route_node` 写入完整的 `conversation_decision` 和 `teaching_policy_version`；`_dispatch_workflow_node` 将 teaching mode 冻结到 child Run metadata。
6. Explain/Validate/Grade workflow 读取冻结的 `teaching_mode`，不得重新让模型选择相同的业务 workflow。

### 错误传播与副作用

- Router 输出结构不合法、action 未授权或 clarify 缺少问题：当前 conversation Run 失败，不能创建 child Run。
- 只读 tool 检索失败：沿已有 tool/workflow 错误链处理；不能写学习证据。
- child Run 创建失败：父 Run 保留可审计错误；不产生孤立的 mastery 或 weakness。
- `teaching_mode` 只是策略事实，不是学习证据，不直接更新掌握度。

### 验收

- 同一请求不再出现“Router 选择 validate、Tutor 再次选择 validate”的重复决策。
- 现有显式路由护栏、capability snapshot、child Run 幂等和 direct/explain/validate/grade 回归保持通过。
- 能验证三种核心输出：只回答、解释后建议诊断、根据薄弱项进入练习。
## 阶段三：学习证据与掌握度模型升级

实施状态：已完成；活动事实已增加结构化证据字段，Grade 已接入 EvidenceGate、EvidenceWeightPolicy
和 MasteryProjector，Alembic 前向迁移、旧数据回填、schema guard、学习进度/管理端读取和回放回归均已落地。

### 目标

保留当前 `LearningActivityEvent` 作为可回链活动事实，增加明确的证据字段；将当前简单 verdict 平均值升级为带证据强度和不确定性的可解释模型。

### 数据库与迁移

通过 Alembic 前向迁移新增或规范化以下字段，不能只修改 ORM：

`learning_activity_events`：

- `evidence_type`；
- `evidence_outcome`；
- `assessment_source`；
- `evidence_strength`；
- `assessment_confidence`；
- `model_version`；
- `knowledge_point_coverage_json`。

`user_learning_mastery`：

- `mastery_alpha`、`mastery_beta` 或等价的加权证据参数；
- `evidence_mass`；
- `uncertainty`；
- `last_evidence_at`；
- `state_model_version`。

保留 `mastery_score`、`evidence_count`、`correct_count`、`incorrect_count` 作为兼容读取字段；迁移回填必须记录 `state_model_version`，便于回放和回退。历史只有 `quality` 而没有 verdict 的讲解事件，回填为 `evidence_type=exposure`、`evidence_outcome=unknown`、`evidence_strength=0`。

### 领域服务

1. 新增 `EvidenceGate`：校验 source Run/User、题目/知识点归属、答案来源、模型版本、提示和幂等键。
2. 新增 `EvidenceWeightPolicy`：根据证据类型、题目可信度、提示、答案暴露和知识点覆盖计算服务端权重；模型提出的 suggested weight 只能被裁剪，不能越过策略上限。
3. 将 `_record_grade_result_confirmed` 中的直接平均值更新抽成 `MasteryProjector.apply`；原函数只负责读取可信 grading、写 memory fact、调用 projector 和 Outbox。
4. 先使用加权 Beta/证据模型：`correct` 增加 alpha，`incorrect` 增加 beta，`partial` 按比例拆分；exposure 和 unknown 不进入 alpha/beta。
5. `calculate_effective_mastery` 继续作为读时衰减边界，增加 state model/policy version，不在本阶段修改原有衰减语义。

### 验收

- “只问过”不会改变权威 mastery；“做错”会增加负向证据；“提示后做对”权重低于独立做对。
- 同一 evidence ID 重放一次或多次都只更新一次。
- 多知识点题目按 coverage 权重更新，重复知识点 ID 不重复计数。
- 旧数据迁移后学习进度、管理端详情和现有掌握度测试仍可读取。

### 本阶段落点

- `learning_activity_events` 的旧 `quality/is_correct` 保留为兼容读取字段；新增列和 payload 中的证据快照以 `LearningActivityEvent.to_learning_evidence` 统一读取。
- `UserLearningMastery` 由 `MasteryProjector.apply` 维护 alpha/beta 和 uncertainty；`memory_projection._record_grade_result_confirmed` 只负责读取可信 grading、幂等写事实并交接 projector/Outbox。
- 迁移 head 为 `20260729_learning_evidence_model`；未执行 `alembic upgrade head` 或缺少新列时，`verify_database_schema` 在应用启动阶段失败，不允许以 `alembic stamp head` 绕过。
## 阶段四：异步 LearningObserverAgent

实施状态：已完成；根 conversation 完成后的幂等 silent child Run、受控输入快照、结构化
TurnObservation、零强度活动事实、14 天诊断 hypothesis 冻结、模型审计和失败隔离均已落地。

### 目标

对每个完成的用户 conversation turn 生成“知识点/行为/诊断需求”观察，但将模型结论限制在 hypothesis/exposure 层，避免自然语言分析污染权威掌握度。

### 实施内容

1. 新增内部 `learning_observation@v1` workflow，使用现有 Worker、Run、Step、Event、Outbox 和 Pydantic AI model audit。
2. 在根 conversation Run 完成并完成已有事实投影后，以 `observe:{source_run_id}:{observer_version}` 创建 silent child Run；只观察 root conversation，避免 Explain/Grade child Run 重复分析同一用户消息。
3. Observer 输入包括：当前 user message、服务端筛选的 conversation snapshot、active topic、相关 Artifact 摘要和可选知识点候选；助手讲解只作为 exposure/answer-leakage 上下文，不能当成用户回答。
4. Observer 输出结构化 `TurnObservation`：知识点 ID、signal、outcome、error tags、model confidence、diagnostic need、source message ID、observer version。
5. `EvidenceGate` 将 observation 映射为：
   - `exposure`：只进入学习活动和用户可见轨迹；
   - `hypothesis`：供下一轮策略选择，带 TTL，不进入 authoritative mastery；
   - `open_response`：只有有明确用户回答时才转入 Assessor。
6. Observer 模型失败、知识点无法解析或输入越权：静默 Run 失败/重试并记录错误；不影响原 conversation Run 的 completed 状态。

### 验收

- 用户仅提问或听完讲解时，生成可回链 observation，但 `UserLearningMastery` 不变化。
- 明确表达困惑时，下一轮 `LearningSnapshot` 能看到 `diagnostic_need`。
- 同一 source Run 和 observer version 不会创建重复 observation。
- 管理端能按 source Run 查看 Observer 的模型调用、输入快照、结构化输出和失败原因；用户端不展示内部推理文本。

### 本阶段落点

- `AgentWorker.process_run` 在 Artifact/事实投影、`run.completed`、摘要和偏好任务之后调用
  `schedule_learning_observation`；后者只接受根 `conversation`，用
  `observe:{source_run_id}:learning-observer-v1` 创建一个 `presentation=silent` child Run。
- `learning_observation@v1` 依次执行输入冻结、模型观察和活动投影。输入只包含当前用户消息、原 Run
  已选历史、同 root 已完成公开 Artifact 摘要、active topic 和数据库确认存在的知识点候选；助手内容被显式标记为
  context-only。模型输出禁止 mastery/weight 和 correct/incorrect verdict，并由运行时复核 message/知识点范围。
- `record_turn_observation` 把同一 source Run/version 收敛为一条 `agent_turn_observed`，经
  `EvidenceGate` 写 `observation|exposure + unknown + strength=0`，不调用 `MasteryProjector`。
  困惑、错误假设、开放回答候选或显式诊断需求保留 14 天 TTL。
- 下一轮 `load_learning_snapshot_summary` 把未过期 hypothesis 复制到本轮
  `AgentMemorySnapshotItem(memory_partition=learning_hypothesis)`；同一 Run 后续只读冻结副本，过期项不再进入 Tutor。
- Observer 的输入快照、结构化输出、模型配置/调用引用和错误保存在 silent Run/Step/Event/metadata 既有审计链；
  Observer 失败只终止 child Run，来源 conversation 保持 completed，且 Observer 不再派生对话摘要任务。
## 阶段五：开放题 Assessor 与诊断题闭环

### 目标

将“用户主动解释/开放回答”转成受 rubric 约束的中等强度证据；将 `need_diagnostic_check` 接入现有 Validate/Practice/Grade 链路。

### 实施内容

1. 客观题路径不改为 LLM 评分，继续使用 `_objective_grade_node`。
2. 为开放回答新增受控 Assessor 运行时或 `grade_open@v1` workflow，输入冻结题面、rubric、用户回答、知识点和提示/答案暴露信息。
3. Assessor 输出 `correct/partial/incorrect/ungradable`、criterion scores、error tags、assessment confidence、evidence ID；低置信度或 rubric 不完整直接 `ungradable`，不更新 mastery。
4. `record_agent_grade_activity` 和 `MasteryProjector` 接受 `partial`、rubric 来源和 evidence strength，但不得接受模型直接提交的 mastery delta。
5. 第一版诊断题复用现有 Validate 创建一题的机制和 Practice Session 快照，不引入新的内联答案协议；`teaching_mode=explain_then_micro_check` 先生成受控入口，用户作答后沿 Grade 既有链路返回。
6. 模型生成题必须在 evidence 中记录 `assessment_source=generated_question`、题目生成模型版本和答案可信度；未经验证的模型题不得与审核题同权重。

### 验收

- 开放题无法评分时，反馈可以展示“需要更明确回答”，但不产生错误掌握度。
- partial 不被强行折算为 correct/incorrect；权重由服务端 policy 统一计算。
- 诊断题答错后能回链到触发它的解释 Run 和目标知识点，并形成薄弱项候选。
- 诊断题答对后不会删除历史错误，只会进入“待迁移/间隔验证”状态。
## 阶段六：LearningSnapshot、薄弱点与工具接入

### 目标

让 ConversationTutorAgent 每轮读取同一份冻结的掌握度、证据、薄弱项和诊断需求，保证决策可复现。

### 实施内容

1. 扩展 memory selector 或新增只读 `LearningSnapshotReader`，返回知识点级 mastery、effective mastery、uncertainty、证据来源、错误标签、hypothesis TTL 和推荐复习原因。
2. `WeaknessProjector` 从 verdict、错误标签、迁移结果和时间衰减派生 `WeaknessFinding`；“只问过”只能产生 `unknown/needs_diagnostic`，不能产生 confirmed weakness。
3. `LearningProgressService` 区分“活动保持率轨迹”和“掌握度证据”，避免把讲解 exposure 的 `quality` 误显示为 mastery。
4. 将 `get_learning_snapshot`、`get_weakness_findings`、`retrieve_knowledge`、`search_question_candidates` 注册为只读能力；所有工具继续经过 workflow/参数/用户所有权门禁。
5. 不注册 `record_evidence` 的任意写版本，不注册 `update_mastery`、`set_weakness`；写入只能由完成/评分事实和 projector 触发。

### 验收

- 同一 Run 使用同一 memory snapshot，来源改名或新证据不会改变已冻结 child Run 的输入。
- 下一轮 Tutor 能区分：低掌握度、高不确定性、仅有 exposure、明确 misconception、已过期复习。
- RAG 只返回当前用户有权访问的资料；RAG 结果不会进入用户 mastery。
- 管理端能看到所选 `teaching_mode`、读取的 snapshot 版本、tool activity 和最终证据 ID。
## 阶段七：灰度、评估与权重校准

### 灰度策略

1. 先以 shadow mode 运行 Observer，只记录 observation，不改变任何掌握度或用户回答。
2. 比较 Observer 与人工标注的知识点映射、行为分类、错误标签和诊断建议。
3. 通过 feature flag 分开启用：`conversation_decision_v2`、`learning_observer_v1`、`open_answer_assessor_v1`、`mastery_model_v2`。
4. 每个事件和 `UserLearningMastery` 保存模型/策略版本，支持按版本回放。

### 必测场景

- 只问知识点：有 exposure，无 mastery 更新。
- 讲解后没有作答：仍为 unknown，需要诊断。
- 客观题做错：负向证据和错误类型可回链。
- 客观题做对：正向证据，但单题不能直接变成高掌握。
- 使用提示后做对：中等证据。
- 原题做对、变式题做错：生成 transfer weakness。
- 开放题低置信度：返回 ungradable，不更新 mastery。
- 多知识点题目：按 coverage 分摊，不重复计数。
- Observer/Assessor 重试：事件和 mastery 幂等。
- RAG 越权、未知参数、私有资料候选：工具门禁拒绝。

### 评估指标

- `topic_resolution_accuracy`：用户表达映射到知识点的准确率；
- `observation_classification_precision`：问过/作答/自我陈述/困惑分类精度；
- `assessment_agreement`：开放题评分与人工 rubric 一致率；
- `diagnostic_trigger_precision`：需要诊断的判断是否过度触发；
- `next_question_prediction`：掌握度对后续题目结果的预测能力；
- `weakness_recovery_rate`：薄弱项经过干预后被变式题验证修复的比例；
- `tool_policy_violation_count`：越权工具调用和任意写入次数，目标为 0。

## 提交拆分与完成条件

按照仓库规则，每个可独立验证阶段单独提交，提交信息使用中文：

1. `建立自适应学习证据契约`：schema、枚举、门禁和兼容测试。
2. `合并 Agent 路由与教学策略`：ConversationDecision、Router/Tutor 合并、教学模式冻结。
3. `升级知识点掌握度证据模型`：Alembic、MasteryProjector、旧数据回填和回放测试。
4. `增加异步学习观察 Agent`：silent Run、Observer workflow、观察事实和失败隔离。
5. `增加开放回答评估与诊断题闭环`：Assessor、rubric、诊断题回链和证据权重。
6. `接入自适应学习快照与只读工具`：WeaknessFinding、LearningSnapshot 和 capability harness。
7. `完成自适应学习 Agent 灰度评估`：feature flag、Pydantic Evals、指标和运维说明。

每个提交前必须执行与范围匹配的后端测试、迁移图/Schema Guard、`git diff --check`；涉及前端契约时补充前端构建。代码提交时同步更新对应 `implementation/` 分卷和本月 `progress/2026-07/08-practice-learning-loop.md`，本任务单只维护跨提交状态和验收入口。

## 参考资料

- [Pydantic AI Agents](https://pydantic.dev/docs/ai/core-concepts/agent/)
- [Pydantic AI Dependencies](https://pydantic.dev/docs/ai/core-concepts/dependencies/)
- [Pydantic AI Function Tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/)
- [Pydantic AI Output](https://pydantic.dev/docs/ai/core-concepts/output/)
- [Pydantic AI Testing](https://pydantic.dev/docs/ai/guides/testing/)
- [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/)
