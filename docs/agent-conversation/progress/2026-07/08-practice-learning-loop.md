# 2026-07 Agent 练习与学习闭环

## 2026-07-28：阶段一——对话出题落入真实练习

- 目标：让 Validate 的完成状态代表“已创建可练习草稿”，并提供对话内跳转、本会话练习轨道和管理端观测。
- 实现：新增 Session 原生题目 item/provenance、Agent Thread/Run 来源和 draft 状态；题库题重读完整实体，即时题冻结在 Session；Artifact 输出受控动作，练习页点击后才进入 active 会话。
- 管理端：Agent Runs 会话详情同步返回并展示关联练习、状态、题数、得分和来源 Run。
- 验证：`pytest` 覆盖 Validate、持久化、私有答案和 MySQL 外键索引替换顺序；用户端与管理端生产构建通过；真实 MySQL 从 `20260728_practice_hints` 前向升级到单 head `20260728_agent_practice_drafts`。首次升级暴露非事务 DDL 的索引依赖后，迁移改为先建替代索引并支持原地重入，全程未使用 stamp。
- 中文提交信息：`打通 Agent 出题与真实练习入口`。

## 2026-07-28：阶段二——统一学习活动与评价证据

- 目标：Agent 讲解和 Agent/普通练习都进入可回溯学习记录，同时禁止把“讨论过”误写成“已掌握”。
- 实现：新增 `learning_activity_events`；Explain 完成写无 verdict 的主题 exposure，练习交卷按 Session Item 写正确/错误评价事件；学习进度新事件优先、旧数据兼容且同源去重。
- 用户端：学习进度页新增最近学习记录，可回到 Agent 对话或练习结果；关键词轨迹标出 Agent 讲解、Agent 练习和普通作答来源。
- 管理端：Agent Runs 会话详情新增学习事件区，显示主题、事件类型、来源 Run 与“活动/正确/错误”证据层级。
- 验证：学习事件、Validate→Session→交卷整链、记忆投影、迁移图与 Schema Guard 测试通过；双前端生产构建通过；真实 MySQL 升至 `20260728_learning_activity`。
- 中文提交信息：`统一 Agent 学习活动与练习证据`。

## 2026-07-28：阶段三——统一 Agent 与练习薄弱点

- 目标：让对话内确定性批改和练习页交卷进入同一个薄弱点证据模型，并保留原始入口回链。
- 实现：Agent Grade 在掌握度门禁通过后写 `agent_grade_confirmed`；WeaknessService 新事件优先、历史 Session 兼容，将 Agent Grade、Agent 练习和普通练习按关键词重新投影；后续答对只标记待间隔验证。
- 用户端：错题页可从 Session 证据回练习结果，也可从对话评分证据回原 Thread，空态与说明覆盖两种来源。
- 管理端：Agent Runs 使用同一 projector 展示本会话薄弱点，不维护第二套统计口径。
- 验证：覆盖 Agent Grade 事件、Agent 错误→练习答对的跨入口验证、历史错题兼容和双前端生产构建。
- 中文提交信息：`统一 Agent 与练习薄弱点投影`。

## 2026-07-28：阶段四——受控 Capability/Tool Harness

- 目标：让 Router 明确看到服务端授权能力，让内部工具具备真实注册、工作流和参数门禁，同时不引入 MCP 或模型任意写库接口。
- 实现：新增版本化 Capability 目录；Router 注入最小能力 manifest，root/child Run 冻结审计快照；Explain/Validate 检索统一经过只读 Tool Registry，Run ID 只能由服务端注入。
- 事实边界：练习由领域服务幂等创建；学习活动由完成/评价事实投影；薄弱点只读聚合。三者均不暴露为模型写工具。
- 管理端：Agent Runs 每个运行入口显示选中 capability 与授权工具；完整响应沿用脱敏规则，旧 Run 保持空态。
- 验证：Capability 视图隔离、越权 workflow/未知参数拒绝、Router/child 快照、Explain/Validate 等聚焦回归 78 项及用户端/管理端生产构建通过；全量后端 890 项中 889 项通过，唯一失败是 `test_agent_workflow_engine.py::test_explain_workflow_keeps_artifact_through_render_and_completion` 仍按旧契约期待裸正文/字符串引用，而当前既有 Explain 契约会写知识库来源区块和结构化 citation，本阶段未回退正确产物。
- 中文提交信息：`建立受控 Agent 能力与工具层`。

## 2026-07-29：移除主动学习计时

- 目标：移除需要用户主动点击才会产生记录的专注/休息计时，避免把不完整的停留时长当作学习事实。
- 实现：删除练习库番茄钟、`/timers` API、`StudyTimerRecord` ORM、学习进度的时长汇总/周节奏和作答每题耗时；学习进度只保留真实作答、评分证据与最近活动。模拟考和刷题会话的服务器限时仍用于自动交卷，不作为学习时长统计。
- 数据库：新增 `backend/alembic/versions/20260729_remove_study_timing.py::upgrade`（L19-L22），前向删除计时表、计时索引和 `practice_answers.time_spent_seconds`，降级可恢复旧结构。
- 验证：迁移图、计时迁移 DDL、学习进度定向测试与用户端生产构建通过；提交前另行确认 `git diff --check`。
- 中文提交信息：`移除主动学习计时`。

## 2026-07-29：收紧 Agent 对话练习侧栏布局

- 目标：练习侧栏没有关联练习时不再显示空白占位或无效可访问内容；存在练习时保持对话流、输入区和侧栏边界对齐，并兼容窄屏布局。
- 实现：`frontend/src/pages/AgentPage.tsx::AgentPage`（L117-L125）继续在 Thread 或时间线 cursor 变化后读取练习列表，失败时回退为空列表；`frontend/src/features/agent/ConversationPracticeRail.tsx::ConversationPracticeRail`（L11-L55）将空列表收敛为隐藏的空侧栏，有数据时保留练习状态和练习/反馈页导航。`AgentPage`（L275-L320）在对话流和输入 dock 之间加入无障碍 spacer；`frontend/src/features/agent/agent-chat.css` 的 `.agent-practice-rail`、`.agent-practice-rail--empty`、`.agent-chat-rail-spacer`（L93-L111）统一桌面宽度，`@media (max-width: 900px)`（L1283-L1306）隐藏 spacer 并压缩空侧栏。
- 副作用与错误：本次没有新增 API、数据库写入或时间线状态；练习列表接口失败仍只影响侧栏并显示为空，不阻断对话；点击已有练习仍通过站内路由进入继续练习或反馈页。
- 验证：`cd frontend && npm run build` 通过；涉及 TS 文件的 `npx eslint src/features/agent/ConversationPracticeRail.tsx src/pages/AgentPage.tsx` 无错误，仅保留 `AgentPage.tsx:72` 原有非空断言警告；`git diff --check` 通过。
- 中文提交信息：`收紧 Agent 对话练习侧栏布局`。

## 2026-07-29：建立自适应学习 Agent 落实步骤

- 目标：在已完成的 Agent 练习、学习活动、掌握度和薄弱点闭环之上，规划 `ConversationTutorAgent`（合并 Router 与 Tutor）、异步 `LearningObserverAgent`、条件触发的开放题 Assessor，以及确定性掌握度/薄弱点 projector 的实施顺序。
- 关键设计：只问过或听过讲解只产生 exposure/hypothesis，不直接更新权威掌握度；RAG、学习状态和题目检索保持只读能力；题目创建、评分和学习事实写入继续由 workflow、领域服务和幂等投影完成；观察任务复用 silent Agent Run/Agent Run Outbox，不新增第二套模型任务队列。
- 文档：新增 `docs/agent-conversation/tasks/2026-07-29-adaptive-learning-agent.md`，记录当前代码锚点、目标数据流、七阶段实施步骤、迁移/测试/灰度验收和中文提交拆分；更新任务 README 路由。
- 验证：使用 `rg -n`、`nl -ba` 重新核对 Router、conversation、Tool Registry、Validate、Grade、学习事件、掌握度、Worker 和 Outbox 代码锚点；提交前运行 Markdown/链接检查、`git diff --check`。
- 中文提交信息：`建立自适应学习 Agent 落实步骤`。

## 2026-07-29：阶段一——冻结自适应学习证据契约与兼容边界

- 目标：先统一证据类型、结果、评价来源、错误标签和多知识点 coverage，固定模型不能直接写掌握度的边界。
- 关键实现：新增 `backend/app/modules/learning/contracts.py::EvidenceType`、`EvidenceOutcome`、`AssessmentSource`、`ErrorTag` 和 `LearningEvidence`；证据上下文强制携带答案来源、提示和答案暴露状态，校验 confidence/strength、重复知识点与 coverage 总和，并以 `is_mastery_evidence` 区分可投影候选。新增 `LearningEvidence.from_legacy_activity_event` 与 `LearningActivityEvent.to_learning_evidence`，只读兼容现有三类活动事件；历史讲解固定为 exposure/unknown/0，旧多知识点事件采用均分 coverage。
- 兼容边界：不修改 `learning_activity_events` 表、不改变 `quality`/`is_correct`/`error_types` 的旧读取语义，不新增迁移；未知历史活动降级为无 verdict 的 observation，模型附加 `mastery_score` 或未知字段直接失败。
- 验证：`backend/venv/bin/python -m pytest tests/test_learning_contracts.py tests/test_learning_activity_events.py tests/test_learning_weaknesses.py tests/test_learning_progress.py tests/test_agent_memory_projection.py tests/test_agent_grade_worker.py tests/test_agent_explain_worker.py -q`（34 passed）；`black --check`、`flake8 --max-line-length=88` 与 `git diff --check` 通过。
- 中文提交信息：`冻结自适应学习证据契约与兼容边界`。

## 2026-07-29：阶段二——合并 Router 与 Tutor 决策契约

- 目标：让在线入口一次模型调用同时产出业务 `action` 和 `teaching_mode`，并固定知识点目标、诊断需求、稳定原因代码与只读能力意图。
- 关键实现：新增兼容的 `ConversationDecision`/旧 `RouterDecision` 别名、`ConversationTutorRuntime`/旧 `RouterRuntime` 别名；`RouterDeps` 增加冻结学习快照摘要、三项只读能力 allowlist 和知识点目标范围。显式讲解、出题、批改、计划护栏仍在运行时生效，模型输出禁止掌握度写字段。
- 安全边界：`get_learning_snapshot`、`retrieve_knowledge`、`search_question_candidates` 只作为结构化 intent，真实执行继续由 ToolRegistry 和 workflow/参数/用户归属门禁负责；教学策略不进入学习证据投影。
- 验证：`backend/venv/bin/pytest tests/test_agent_router_runtime.py tests/test_agent_capability_harness.py -q`（25 passed）；对话 Worker 基线因测试 fixture 未加载 `users` 表而有既有 SQLite 外键建表错误，未归因于本次改动。
- 中文提交信息：`合并 Agent 路由与教学策略契约`。

## 2026-07-29：阶段二完成——冻结 Tutor 策略并交接 child workflow

- 目标：让 Router/Tutor 的单次决策进入真实 conversation Run 主链，保证同一份 LearningSnapshot、teaching policy 和 ConversationDecision 可被 direct answer 及 Explain/Validate/Grade child workflow 回放消费。
- 关键代码锚点：

  | 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
  | --- | --- | --- | --- | --- |
  | 快照读取 | `backend/app/modules/agent/learning_snapshot.py` | `LearningSnapshotSummary`、`LearningSnapshotReader.read`、`load_learning_snapshot_summary` | L39-L70、L280-L382、L705-L725 | 只读当前 Run 已冻结的 learning_mastery items，按用户/线程/快照校验并输出有限掌握度摘要；找不到快照不读取 live 状态 |
  | 路由主链 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | L54-L208 | 构建理解和 snapshot，注入 LearningSnapshot/只读 manifest，写 `conversation_decision`、兼容 `router_decision`、`teaching_policy_version` 与完整审计，决定 direct/clarify/child |
  | 策略冻结 | `backend/app/modules/agent/model_runtime/teaching_policy.py` | `FrozenTeachingPolicy.from_decision`、`load_frozen_teaching_policy`、`freeze_teaching_policy` | L19-L47、L67-L101、L104-L109 | 只复制 workflow action、教学模式、目标知识点、诊断需求、只读意图和理由码；child 缺策略时按 action 兼容默认，不重新路由 |
  | Child 交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata`、`_dispatch_workflow_node` | L275-L323、L326-L367 | 将策略和上下文审计冻结到 child metadata，并保持原有 child Run/时间线幂等副作用 |
  | Worker 恢复 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L105-L323 | 运行 workflow 前把 metadata 策略注入 ExecutionContext；Artifact 的私有 metadata 可记录策略，公开消息/SSE 不展示内部策略 |
  | 策略消费 | `backend/app/modules/agent/workflows/explain.py`、`validate.py`、`grade.py` | `_load_scope_node`、`_load_learning_evidence_node`、`_load_attempt_snapshot_node` | Explain L38-L59；Validate L51-L89；Grade L41-L86 | 分别读取冻结 `teaching_mode`；Explain 传给规划/生成 deps，Validate 写入学习证据上下文但不投影，Grade 保持确定性评分；策略不会选择 workflow 或直接更新掌握度 |

- 验证：`backend/venv/bin/pytest tests/test_agent_teaching_policy.py tests/test_agent_router_runtime.py tests/test_agent_capability_harness.py tests/test_agent_answer_runtime.py tests/test_agent_explain_workflow.py tests/test_agent_validate_workflow.py tests/test_agent_grade_worker.py -q`（53 passed，6 个既有 datetime 弃用告警）；`compileall`、Black 检查、Flake8（忽略 Black 与旧代码冲突的 E203/W503）和 `git diff --check` 通过。对话 Worker 整链仍受当前测试 fixture 未加载 `users` 表的既有 SQLite 外键建表问题影响。
- 中文提交信息：`冻结 Tutor 策略并交接 Agent 子工作流`。

## 2026-07-29：阶段三——升级学习证据与知识点掌握度模型

- 目标：在保留 `LearningActivityEvent`、`quality/is_correct` 和旧掌握度读取字段的前提下，补齐证据类型、结果、评价来源、证据强度、confidence、模型版本和多知识点 coverage，并把 Grade 的简单 verdict 平均值升级为可回放的加权 alpha/beta 状态。
- 关键实现：`backend/app/modules/learning/evidence.py::EvidenceGate.validate`（L59-L140）、`EvidenceWeightPolicy.calculate`（L164-L240）和 `build_assessment_evidence`（L243-L320）统一门禁/权重；`backend/app/modules/learning/events.py::record_practice_submission`（L44-L158）、`record_explanation_activity`（L161-L238）和 `record_agent_grade_activity`（L241-L371）写入结构化证据列与嵌套审计载荷，旧题目没有知识点映射时仍只记录事实、不进入 mastery。新增 `backend/app/modules/agent/mastery_projector.py::MasteryProjector.apply`（L35-L138），按 coverage 分摊强度，correct/incorrect 更新 alpha/beta，partial 按比例拆分，并维护 `evidence_mass`、`uncertainty`、`last_evidence_at` 和 `mastery-beta-v1`。
- 数据库：新增 `backend/alembic/versions/20260729_learning_evidence_model.py::upgrade`（L18-L167），按旧 `is_correct` 回填活动证据，讲解历史固定为 `exposure/unknown/0`；按 `mastery_score * evidence_count` 回填 alpha/beta，记录旧证据时间与状态版本。`backend/app/modules/operations/schema_guard.py::verify_database_schema`（L68-L293）同时校验新活动列和掌握度列，未迁移数据库拒绝启动。
- 读取兼容：学习进度、管理员 Thread 详情和 mastery Snapshot signal 继续提供旧字段，同时增加 evidence/uncertainty/state model 审计字段；读时衰减保留原 `mastery-decay-v1` 语义。
- 验证：受影响后端测试 `backend/venv/bin/python -m pytest tests/test_learning_evidence_model.py tests/test_agent_memory_projection.py tests/test_learning_activity_events.py tests/test_learning_contracts.py tests/test_agent_grade_worker.py tests/test_migrations.py tests/test_schema_guard.py tests/test_agent_mastery_decay.py -q`（67 passed，6 个既有 datetime 弃用告警）；全量后端为 922 passed、1 个阶段二 Explain 旧断言失败、3 deselected；前端 `npm run build`、新增文件 Black/Flake8、`compileall` 和 `git diff --check` 通过。新增证据门禁、提示/生成题/答案暴露降权、多知识点 coverage、partial、迁移回填和 schema guard 回归。
- 中文提交信息：`升级知识点掌握度证据模型`。

## 2026-07-29：阶段四——异步 LearningObserverAgent

- 目标：让每个已完成根 conversation 异步产生可回链的主题接触、行为信号和诊断需求，同时把模型结论严格限制在 exposure/hypothesis 层，不污染权威掌握度。
- 关键实现：`backend/app/modules/agent/learning_observer.py::schedule_learning_observation`（L72-L113）由 Worker 完成边界以 `observe:{source_run_id}:learning-observer-v1` 幂等创建 silent child；`build_observer_input_snapshot`（L133-L271）按 user/thread/root 过滤当前用户消息、原 Run 已选历史、相关 Artifact 摘要和数据库确认的知识点候选。`backend/app/modules/agent/model_runtime/observer.py::TurnObservation`、`TurnObservationOutput`、`LearningObserverRuntime.observe`（L37-L87、L131-L192）禁止 mastery/weight、correct/incorrect verdict 和越界知识点。
- 投影与消费：`backend/app/modules/agent/workflows/learning_observation.py::_prepare_observation_node`、`_observe_turn_node`、`_project_observation_node`（L34-L117）复用 WorkflowEngine/Step/Event/统一模型审计；`backend/app/modules/agent/learning_observer.py::record_turn_observation`（L301-L431）经 EvidenceGate 写 `agent_turn_observed`，固定 `unknown + strength=0` 且不调用 MasteryProjector。`backend/app/modules/agent/learning_snapshot.py::_freeze_diagnostic_hypotheses`、`LearningSnapshotReader.read`（L159-L248、L280-L382）把 14 天内诊断假设冻结成下一轮 `learning_hypothesis` Snapshot item。
- 错误与公开边界：助手 Artifact 只作 exposure/answer-leakage 上下文；Observer 不生成 Artifact/公开消息，也不递归派生摘要任务。模型、来源、知识点或落库失败只终止 silent child，来源 conversation 保持 completed，管理员仍可查看输入快照、结构化输出、模型调用和失败原因。
- 验证：`backend/venv/bin/pytest -q tests/test_agent_learning_observer.py tests/test_agent_conversation_workflow.py tests/test_agent_memory_projection.py tests/test_agent_grade_worker.py tests/test_learning_activity_events.py tests/test_learning_contracts.py tests/test_learning_evidence_model.py tests/test_agent_admin_router.py`（52 passed，23 个既有 datetime 弃用告警）；新增测试覆盖幂等 silent Run、困惑进入下一轮 Snapshot、零掌握度副作用、模型失败隔离和非法 mastery/verdict 拒绝。
- 中文提交信息：`实现异步学习观察闭环`。

## 2026-07-29：阶段五——开放回答评估与诊断题闭环

- 目标：把开放题/用户解释接入受冻结 rubric 约束的 Assessor，同时让 `explain_then_micro_check` 通过现有 Validate、Practice Session 和 Grade/学习活动链路完成诊断回链。
- Assessor：新增 `backend/app/modules/agent/model_runtime/assessor.py::OpenAnswerRubric`、`OpenAnswerAssessment`、`OpenAnswerAssessorRuntime.assess`（L43-L107、L172-L210、L219-L283）。模型只能输出 `correct/partial/incorrect/ungradable`、criterion scores、错误标签和 confidence；服务端重写 evidence ID、检查 rubric 覆盖和最低置信度，异常/低置信度反馈为 `ungradable`，不携带 mastery/delta。
- Grade 与证据：`backend/app/modules/agent/workflows/grade.py::_open_answer_assessment_node`、`_open_answer_grading_evidence`（L205-L345）加入开放题分支，partial 按冻结 rubric 权重计算；`backend/app/modules/learning/evidence.py::EvidenceWeightPolicy.calculate`（L164-L243）增加答案可信度降权；`_record_grade_result_confirmed`（L311-L497）对 ungradable 只记录活动、不创建掌握度事实。`record_agent_grade_activity`（L267-L429）保留 verdict、rubric、criterion/error tags 和诊断回链。
- 诊断闭环：`backend/app/modules/agent/diagnostic.py::schedule_diagnostic_check`（L40-L161）以版本化幂等键为合格解释 Run 创建 Validate child；`validate.py` 的 `_load_learning_evidence_node`、`_question_gate_node`、`_create_draft_node`、`_render_artifact_node`（L52-L119、L227-L264、L364-L397、L400-L502）把目标知识点和来源解释 Run/Artifact 固化到 Practice Session 快照；`PracticeService.create_agent_draft`（L21-L181）与 `record_practice_submission`（L48-L175）在交卷后保留回链，答对不删除历史错误。
- 生成题可信度：`GeneratedPracticeQuestion`（`backend/app/modules/agent/model_runtime/schema.py::GeneratedPracticeQuestion`，L207-L230）和 `PracticeGenerationRuntime.generate`（L41-L77）记录模型版本/答案可信度，事件层以 `assessment_source=generated_question` 和独立权重降级。
- 文档：同步更新 `architecture/conversation-mainline.md`、`architecture/workflow-branches.md`、`implementation/model-runtime-streaming.md`、`implementation/events-timeline-errors.md` 和本任务单的阶段状态；无数据库结构变化，无 Alembic 迁移。
- 验证：`backend/venv/bin/python -m pytest` 覆盖 Assessor、Grade、Observer、Validate、Practice、Memory Selector、学习证据/进度/薄弱点、迁移图和 Schema Guard（135 passed，91 个既有 datetime 弃用告警）；变更 Python 文件 Black/Flake8、`compileall` 和 `git diff --check` 通过。
- 中文提交信息：`增加开放回答评估与诊断题闭环`。

## 2026-07-29：阶段六前置——冻结 LearningSnapshot 与薄弱点 finding

- 目标：让 ConversationTutorAgent 在同一 memory snapshot 中读取知识点级 mastery、effective mastery、uncertainty、证据来源、错误标签、薄弱点和诊断需求，并把活动保持率与权威掌握度分成两个读取契约。
- 关键实现：新增 `backend/app/modules/agent/learning_snapshot.py::LearningSnapshotReader.read`（L280-L382）和 `_ensure_learning_state`（L384-L478），首次读取最多冻结 16 条 mastery/finding，复制 evidence source、error tag、衰减版本和推荐复习原因；`_build_mastery_signal`（L575-L669）保留 raw/effective 分数，不让 exposure quality 进入 mastery。`backend/app/modules/agent/weakness_projector.py::WeaknessProjector.project` / `_project_group`（L85-L127、L144-L305）按 verdict、error tag、迁移类型和 45 天衰减产出 `WeaknessFinding`，只问/观察进入 `needs_diagnostic`，后续答对进入 `awaiting_interval_verification`。
- 读取分层：`backend/app/modules/learning/service.py::LearningProgressService.get`（L101-L179）保留旧 `topics` 兼容入口并新增 `activity_retention`、`mastery_evidence`；`LearningProgressService._load_mastery_states`（L350-L426）只读取 UserLearningMastery 的权威证据。`WeaknessService.get`（L187-L266）保留旧 clusters/timeline，同时输出 finding 和 confirmed/diagnostic 统计。
- 验证：`backend/venv/bin/python -m pytest tests/test_agent_weakness_projector.py tests/test_agent_learning_observer.py tests/test_agent_capability_harness.py tests/test_agent_router_runtime.py tests/test_learning_progress.py tests/test_learning_weaknesses.py tests/test_agent_memory_contracts.py -q`（50 passed，1 个既有 datetime 弃用告警）；变更 Python 文件 Black/Flake8、`compileall` 通过。
- 中文提交信息：`冻结学习快照并投影薄弱点`。

## 2026-07-29：阶段六完成——接入自适应学习快照与只读工具

- 目标：把四项只读能力接入统一 ToolRegistry，保证 Tutor/Validate 读取的学习状态来自当前 Run 的冻结 Snapshot，并让管理端可以回放能力、版本、finding 和证据来源。
- 工具链：新增 `backend/app/modules/agent/tools/get_learning_snapshot.py::get_learning_snapshot`（L25-L57）、`get_weakness_findings.py::get_weakness_findings`（L11-L25）和 `search_question_candidates.py::search_question_candidates`（L15-L42）；模块注册函数（快照 L67-L78、薄弱点 L35-L46、题目 L66-L77）与既有 `retrieve_knowledge` 一起进入 `tool_registry`。快照/薄弱点工具只接受服务端注入 `run_id`，题目工具固定 `entity_type=question`，不注册 `record_evidence`、`update_mastery` 或 `set_weakness`；`WeaknessService.get` 同时保留 unknown/observation 活动，确保“只问过”能进入 `needs_diagnostic`。
- 门禁与审计：`ToolSpec`/`ToolRegistry.execute`（`backend/app/modules/agent/tools/registry.py` L17-L34、L76-L104）统一校验 workflow、read_only、未知参数和必需参数；`READ_ONLY_CAPABILITIES`（`backend/app/modules/agent/capabilities.py` L15-L36）与 `ReadToolIntent`（`backend/app/modules/agent/model_runtime/schema.py` L76-L81）扩展到四项，`admin_memory._serialize_snapshot_item`（L78-L106）能回看新增 Snapshot source kind。
- 验证：`backend/venv/bin/python -m pytest tests/test_agent_capability_harness.py tests/test_agent_router_runtime.py -q`（26 passed）；阶段六合并定向回归（含 Admin、Observer、LearningProgress、Weakness）60 passed，变更 Python 文件 Black/Flake8、`compileall`、`git diff --check` 通过。
- 中文提交信息：`接入自适应学习快照只读工具`。
