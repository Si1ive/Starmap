# Agent 工作流分支

## 适用场景

本分卷描述 conversation Router 之后 explain / validate / grade / plan 四类业务 child workflow 的入口、关键节点、
工具调用和最终落点。定位“Router 明明分到了某个 workflow，但用户端没有看到正确产物”时，应从这里开始。

## Router 到 child Run 的公共链路

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/context_builder.py`、`backend/app/modules/agent/workflows/conversation.py`、`backend/app/modules/agent/capabilities.py` | `_active_topic_from_state`、`_route_node`、`CapabilityRegistry.model_manifest` | L752-L772；L45-L157；L62-L67 | conversation run、当前消息与线程热状态 | 构建近期原文与预算内 active 摘要；显式主题最多继承 6 个后续轮次，版本差超过阈值或标记非法时不交给 Router；仅在真实歧义时调用指代模型，再冻结 snapshot，并注入本轮获授权的最小能力清单 | `agent_run_context`、RouterDecision、`capability_snapshot` 或失败 | `build_turn_understanding` / `ensure_turn_memory_snapshot` |
| 2 | `backend/app/modules/agent/turn_understanding.py` | `_derive_constraints`、`_resolve_question_artifact_reference`、`build_ambiguous_referent_candidates`、`hydrate_referent_candidate_labels`、`build_turn_understanding`、`requests_question_repeat` | L213-L226、L229-L258、L261-L338、L341-L375、L421-L481、L602-L620 | 当前输入、context refs、近期 Artifact 结构化引用、线程 `active_topic`、题库 active 题面 | 先确定性抽取当前显式练习主题、difficulty/章节和唯一 question 指代；“再出一遍上次那道题”等肯定表达额外冻结 `repeat_referenced_question`，常见否定表达不冻结；仍歧义时构造候选，并为 question 水合真实题面、过滤缺失或失效实体 | 确定性理解或带语义标签的候选白名单 | `ReferentRuntime.resolve` / `apply_referent_resolution` |
| 3 | `backend/app/modules/agent/model_runtime/referent.py`、`backend/app/modules/agent/turn_understanding.py` | `ReferentRuntime.resolve`、`apply_referent_resolution` | L79-L148；L378-L418 | 原始输入、近期消息、带标签候选、Run 模型配置 | 结构化返回 resolved/unresolved；resolved 键必须属于候选且置信度至少 0.8，否则报错或降级。合法选择和候选审计写回理解 | 含 `reference_sources` / `reference_resolution` 的 TurnUnderstanding | `ensure_turn_memory_snapshot` |
| 4 | `backend/app/modules/agent/turn_understanding.py`、`backend/app/modules/agent/memory_projection.py` | `ensure_turn_memory_snapshot`、`project_topic_confirmed_fact` | L489-L599；L67-L122 | 完整理解、当前 Run、线程热状态与可选摘要 | 创建不可变 snapshot；摘要作为 `historical_summaries` item 保存正文副本、来源 ID、版本和范围；显式主题仍在 Router 前幂等写事实 | 可复现 snapshot、热状态、主题事实与 pending Outbox | `_route_node` 的 Router 调用 |
| 5 | `backend/app/modules/agent/workflows/conversation.py`、`backend/app/modules/agent/model_runtime/teaching_policy.py` | `_child_context_metadata`、`freeze_teaching_policy` | L275-L323；L104-L109 | 受控上下文、独立请求、snapshot ID、选中 capability、父 Run `model_config_id` 与 ConversationDecision | 复制摘要 ID 等上下文审计、`active_topic`、`standalone_request`、`memory_snapshot_id`、模型配置，并把 teaching_mode/目标知识点/诊断需求/只读意图冻结为 child metadata；不复制摘要正文、函数或 API Key | child run metadata | `_dispatch_workflow_node` |
| 6 | `backend/app/modules/agent/workflows/conversation.py`、`backend/app/modules/agent/capabilities.py` | `_dispatch_workflow_node`（L326-L367）、`CapabilityRegistry.require`（L74-L78） | Tutor action、parent/root run、独立请求与 FrozenTeachingPolicy | action 必须命中能力目录和业务 workflow 白名单；随后幂等创建 compact child run，标题来自能力定义，`input_message` 使用 `standalone_request`，策略只读冻结不重新路由 | 队列中的 child run、冻结 capability snapshot 和 teaching policy | `AgentWorker.process_run` |
| 7 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（进入 running） | L122-L180 | queued child run | 提交 running 状态和 `run.status_changed`，让用户端先看到真实执行中，再恢复 checkpoint 并调用引擎 | running child run 与节点结果 | completed / waiting / failed 分支 |
| 8 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | L27-L209 | workflow 定义与 child run | 每个节点开始/完成/失败分别写 step 事件并提交真实边界；异常节点提交已有 snapshot/主题事实与 step.failed，再返回失败 | 可恢复步骤链、最终产物或失败结果 | 具体 workflow 节点 / worker 终态投影 |

## Explain：资料探索到讲解产物

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 对话连续性选择 | `backend/app/modules/agent/memory_selector.py`、`backend/app/modules/agent/workflows/explain.py` | `load_conversation_bundle`（L1122-L1294）、`_load_scope_node`（L38-L59） | child run、同用户/线程 snapshot、冻结消息/摘要/Artifact ID 与 teaching policy | 复现 snapshot 当时的 visible completed 消息、唯一摘要副本和公开 Artifact；摘要源记录需匹配 user/thread/version，重复或版本不符时不注入摘要；读取 FrozenTeachingPolicy 作为讲解策略，不再重新选择业务 workflow | `conversation_bundle`、`scope.mode=snapshot`、teaching_mode | `_evidence_loop_node` |
| 有界资料探索 | `backend/app/modules/agent/workflows/explain.py` | `_conversation_inputs`、`_evidence_loop_node`（L50-L206） | ConversationBundle、预算和 child run ID | 把原始消息转 history、摘要转不可信 deps；首次仍强制使用唯一题面、topic aliases 或 standalone request 的冻结 query | 有效 evidence、`retrieval_attempted`、`retrieval_outcome` | `ExplanationRuntime.decide` / `retrieve_knowledge` |
| 检索工具 | `backend/app/modules/agent/tools/registry.py`、`backend/app/modules/agent/tools/retrieve_knowledge.py`、`backend/app/modules/agent/workflows/explain.py` | `ToolRegistry.execute`（L75-L103）、`register_retrieve_knowledge`（L438-L450）、`_evidence_loop_node`（工具调用 L133-L148） | explain/validate 的 query、范围、服务端注入 run ID | 先校验工具已注册、调用 workflow 在 allowlist、工具只读、参数已声明；通过后检索并写原有 `tool.called/result`。同一逻辑检索重试复用 `activity_id`，未知参数或越权 workflow 直接传播失败 | 公开活动 + 内部检索结果；无任意写库工具 | `retrieve_knowledge` / `RetrievalService.search_with_outline_expansion` |
| 零证据门禁 | `backend/app/modules/agent/workflows/explain.py` | `_evidence_gate_node` | 已筛选 evidence 与 `retrieval_outcome` | 非空资料直接通过；零命中记录“没有检索到相关文档”，检索异常记录“暂时无法检索相关文档”，但两者都继续生成通用知识回答 | `gate_passed` 与原因 | `_generate_explanation_node` |
| 结构化讲解生成 | `backend/app/modules/agent/workflows/explain.py` | `_fallback_evidence_text`、`_generate_explanation_node`（L236-L289） | standalone question、ConversationBundle history/摘要、证据列表和 `retrieval_outcome` | 规划和正文模型复用同一份冻结 history、摘要、主题、Artifact 摘要与引用 ID；无资料时使用 fallback 并清空 citations | `ExplanationOutput` | `_citation_gate_node` |
| 正文/引用校验 | `backend/app/modules/agent/workflows/explain.py` | `_citation_gate_node` | 结构化讲解结果 | 只要正文非空即通过，引用列表在无资料场景下已被上游清空 | 可渲染 explanation | `_render_artifact_node` |
| Artifact 渲染与结束 | `backend/app/modules/agent/workflows/explain.py` | `_render_artifact_node`、`_completed_node`（L307-L333） | outline、body、citations、summary | 组装 explanation artifact，并把最终 artifact 挂到 NodeResult 和上下文 | `agent_artifacts`、completed run | `AgentWorker.process_run` |
| 讲解事实与学习活动投影 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/learning/events.py`、`backend/app/modules/agent/memory_item_projection.py` | `project_completed_run_facts`（L129-L145）、`_record_explanation_artifact_created`（L147-L190）；`record_explanation_activity`（L161-L238）；`project_trusted_memory_event`（L212-L224） | worker 已持久化的 explanation Artifact、冻结 active topic | 按 Run 幂等写讲解记忆事实与 `exposure/unknown/0` 学习活动，经过来源门禁后确保 pending Outbox；活动不复制正文、不提高掌握度 | `explanation_artifact_created`、带结构化 evidence 的 `agent_explanation_completed`、completed Outbox | 学习进度 / 后续摘要 projector |

## Validate：候选题检索到练习产物

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| PracticeBundle 选择 | `backend/app/modules/agent/memory_selector.py` | `_resolve_explicit_chapter_ids`、`_load_unique_weak_topic`、`load_practice_bundle`、`_apply_explicit_question_repeat`（L708-L854、L857-L997、L1239-L1259） | child run、snapshot/items、知识点与章节约束、近期练习事实、UTC 读取时点 | 校验权限；显式章节序号在唯一学科内解析；无主题时按统一衰减策略选择唯一有效薄弱点并冻结题名/别名与分数 Snapshot Item；排除集仅在明确重复唯一题时覆盖本轮视图 | 含章节来源、有效掌握度审计和本轮排除视图的 `PracticeBundle`；同 Snapshot 不受来源改名或新证据影响，原掌握度/事实不修改 | `_load_learning_evidence_node` |
| 学习证据读取 | `backend/app/modules/agent/workflows/validate.py` | `_load_learning_evidence_node`（L52-L119） | `PracticeBundle`、Worker 注入的 FrozenTeachingPolicy、可选 `diagnostic_context` | 读取并冻结 `teaching_mode`、目标知识点和诊断标记；诊断子 Run 将来源解释 Run 的目标知识点/主题覆盖到 PracticeBundle，并保留安全回链，不写学习事实 | `learning_evidence`、`practice_bundle`、diagnostic context | `_question_discovery_node` |
| 候选题检索 / 严格范围 / 缺主题澄清 | `backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/agent/tools/retrieve_knowledge.py`、`backend/app/modules/retrieval/service.py`、`backend/app/modules/agent/service.py` | `_question_discovery_node`（L79-L172）、`retrieve_knowledge`（L144-L357）、`RetrievalService.search_with_outline_expansion`（L44-L120）、`AgentService.create_input` | `practice_bundle`、`weak_areas`、run ID | unresolved 显式章节先失败；resolved 显式章节下发 strict；无主题时创建/读取 `practice_topic` 等待恢复；检索零命中直接记录中性提示并绕过题目资格门 | candidates、pending input，或 `fallback=llm_generation` | `_question_gate_node` / `_generate_question_node` / 用户补充输入 |
| 澄清恢复执行 | `backend/app/modules/agent/service.py` | `submit_input_answer` | waiting run、`practice_topic` 用户答案 | 校验 run 和输入归属，把输入记为 answered，恢复 run 到 running 并重新投递 outbox | answered input、恢复后的 run | `AgentWorker.process_run` -> `_question_discovery_node` |
| 题目资格门 | `backend/app/modules/agent/workflows/validate.py` | `_question_is_eligible`、`_question_gate_node`（L34-L49、L227-L264） | 非空候选题列表、可选诊断目标知识点 | 校验实体类型、审核/状态、题型、难度和真实来源字段；诊断模式把候选知识点冻结到目标 ID 并只保留一题；全部不合格时记为可恢复的题库不足 | `valid_questions`，或中性降级原因 | `_composition_gate_node` / `_generate_question_node` |
| 模型兜底出题 | `backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/agent/model_runtime/practice.py` | `_generate_question_node`（L267-L330）、`PracticeGenerationRuntime.generate`（L41-L77） | 冻结主题、难度、目标知识点、Run 模型配置和剩余模型预算 | 生成结构化单选题，并把生成模型版本/答案可信度写入私有元数据；答案必须属于唯一选项集合，不伪装真题 | `valid_questions` 中的瞬时生成题及可信度审计 | `_composition_gate_node` |
| 组合校验 | `backend/app/modules/agent/workflows/validate.py` | `_composition_gate_node` | 有效题目 | 汇总 `question_meta.question_type`、`question_meta.difficulty` 和 `subject_id`，供后续产物使用 | `composition` | `_create_draft_node` |
| 练习草稿持久化 | `backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/practice/service.py` | `_create_draft_node`（L364-L397）、`PracticeService.create_agent_draft`（L21-L181） | 有效题目、PracticeBundle、Run/User、可选 diagnostic context | 用 Run 做幂等键创建 draft Session；题库题重读完整 Question，模型题写 Session 原生快照；诊断来源、目标知识点、生成模型版本和答案可信度进入快照；Run/所有权错误沿 WorkflowEngine 失败链传播 | `practice_sessions`、`practice_session_questions`、session ID | `_render_artifact_node` |
| Artifact 动作与结束 | `backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/agent/worker.py` | `_render_artifact_node`（L400-L502）、`AgentWorker.process_run`（L215-L289） | Session ID、题面与组合信息、可选诊断回链 | 公开题面携带受控 `open_practice` 动作；模型答案/解析继续通过 `_private_metadata` 写入 Artifact 私有元数据，诊断信息只输出安全的来源 Run/Artifact/目标 ID | 可跳转 Practice Artifact、私有批改元数据与 completed run | 用户练习页 / `_submit` |

## 解释后诊断题：来源回链到 Practice/Grade

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 诊断 child 调度 | `backend/app/modules/agent/worker.py`、`backend/app/modules/agent/diagnostic.py` | `AgentWorker.process_run`（L265-L289）、`schedule_diagnostic_check`（L40-L161） | 已完成 conversation direct answer 或 explain Run、冻结 teaching policy、解释 Artifact | 只接受 `explain_then_micro_check` 且有目标知识点的来源 Run；用 `diagnostic:{source_run}:{version}` 幂等创建 Validate child，复制 context snapshot/模型配置并写入来源 Run、Artifact、目标知识点；Validate/Grade/Observer 不递归触发 | compact Validate child、Run Outbox、Thread workflow item；来源 Run 保持 completed | `AgentWorker.process_run` -> Validate `_load_learning_evidence_node` |
| 诊断题快照 | `backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/practice/service.py` | `_load_learning_evidence_node`（L52-L119）、`_question_gate_node`（L227-L264）、`_create_draft_node`（L364-L397）、`PracticeService.create_agent_draft`（L21-L181） | child Run metadata、候选题、冻结目标知识点 | 将来源目标知识点写入 PracticeBundle，候选题只保留一题并在 Session snapshot 中保留 `diagnostic_context`；不把诊断题答案写入公开 Artifact | Draft PracticeSession/Question snapshot、诊断来源与目标 ID | Practice `_submit` |
| 诊断作答事实 | `backend/app/modules/practice/router.py`、`backend/app/modules/learning/events.py` | `_submit`（L106-L145）、`record_practice_submission`（L48-L175） | 用户答案、Session snapshot、诊断 context | 复用既有确定性判分；以 Session Item 幂等写活动事件，将来源解释 Run/Artifact 和目标知识点放入 payload/evidence，错误保留为后续 Weakness 输入，正确不删除旧事实 | `practice_answer_graded`、`LearningEvidence`、薄弱项读取所需回链 | 学习进度 / WeaknessProjector |

## Grade：作答快照到反馈产物

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 评分记忆选择 | `backend/app/modules/agent/memory_selector.py` | `EvaluationQuestion`、`EvaluationBundle`、`_extract_user_answer`、`load_evaluation_bundle` | L87-L123、L135-L162、L547-L763 | Grade run/user、同线程 snapshot、唯一 question 引用、题库与原始输入 | 校验 run/snapshot 作用域，重读 active 且未拒绝的题面、标准答案来源和知识点；开放题允许空标准答案进入 rubric gate；同时冻结提示级别、答案暴露、生成题模型版本/答案可信度；缺快照、跨作用域、多题、失效题或缺可信答案返回稳定 reason | `EvaluationBundle` 或 unresolved reason | `_load_attempt_snapshot_node` |
| 作答快照与分支 | `backend/app/modules/agent/workflows/grade.py` | `_load_attempt_snapshot_node`（L81-L141） | `EvaluationBundle`、Worker 注入的 FrozenTeachingPolicy | 读取并校验 `grade` 教学策略，把题型、题面、标准答案、答案来源、知识点、提示/答案暴露、来源 Artifact 与用户作答冻结进 ExecutionContext；客观题进入确定性节点，开放题进入 Assessor | `attempt`、私有策略上下文；数据不完整时 Worker 写 `run.failed`，不产生 Artifact/掌握度 | `_objective_grade_node` / `_open_answer_assessment_node` |
| 客观判定 | `backend/app/modules/agent/workflows/grade.py` | `_normalize_answer`、`_objective_grade_node` | L66-L79、L144-L202 | objective attempt | choice/fill/judge 仍由服务端归一化比较，生成 correct/incorrect 和结构化评分证据；生成题额外携带 generated source、模型版本和答案可信度 | `objective_result`、`grading_evidence` | `_rubric_gate_node` |
| 开放题 Assessor 与证据 | `backend/app/modules/agent/workflows/grade.py`、`backend/app/modules/agent/model_runtime/assessor.py` | `_build_open_answer_rubric`、`_open_answer_assessment_node`、`_open_answer_grading_evidence`（L38-L63、L205-L258、L261-L345）；`normalize_open_answer_assessment`、`OpenAnswerAssessorRuntime.assess`（L172-L210、L219-L283） | 冻结开放题、rubric、用户回答、知识点、提示/答案暴露、Run/User | Assessor 只返回 verdict/criterion/error/confidence；服务端重写 evidence ID，校验完整 rubric/criterion 覆盖/最低置信度，低置信度或模型异常收敛为 ungradable；partial score 按 rubric 权重计算，不接受 mastery/delta | `open_assessment`、`grading_evidence`、Assessor LLM 审计；失败仍可完成“需要更明确回答” | `_rubric_gate_node` |
| 反馈与 Artifact | `backend/app/modules/agent/workflows/grade.py` | `_rubric_gate_node`、`_generate_feedback_node`、`_feedback_gate_node`、`_render_artifact_node`、`_completed_node` | L345-L379、L382-L464、L470-L522 | 客观判定或 Assessor 结构化结果 | 四种开放题 verdict 均通过受控 gate；ungradable 展示“需要更明确回答”，partial 展示部分覆盖但不改写为正确/错误；Artifact 只写服务端 grading evidence | `agent_artifacts` 与 completed run；ungradable 不进入 mastery，其他结果进入投影 | `AgentWorker.process_run` |
| 完成事实、权重与掌握度 | `backend/app/modules/agent/worker.py`、`backend/app/modules/agent/memory_projection.py`、`backend/app/modules/learning/events.py`、`backend/app/modules/learning/evidence.py` | `AgentWorker.process_run`（L215-L289）、`_record_grade_result_confirmed`（L311-L497）、`record_agent_grade_activity`（L267-L429）、`EvidenceGate.validate`（L59-L140）、`EvidenceWeightPolicy.calculate`（L164-L243）、`MasteryProjector.apply`（L35-L138） | completed Feedback Artifact、冻结 topic、题目/知识点与答案来源 | ungradable 只记录零强度活动事实并返回；其余 verdict 经过来源/题面/知识点门禁和开放题/生成题权重，再按 coverage 调用 projector；任何模型 mastery/delta 均不会进入证据契约 | `agent_grade_confirmed`、必要时 `AgentMemoryEvent/UserLearningMastery`、Outbox；错误证据保留供 Weakness 消费 | PlanningBundle / Weakness / 后续摘要 |

## Plan：计划草案、审批与恢复执行

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 规划记忆选择 | `backend/app/modules/agent/memory_selector.py`、`backend/app/modules/agent/preference_memory.py` | `PlanningTarget`、`PlanningBundle`、`load_planning_bundle`、`load_preference_bundle` | L63-L84、L306-L511；L605-L662 | Plan run/user、同线程 snapshot、最新批准目标、真实掌握度、本轮明确和已治理偏好 | 校验作用域，按当前主题→批准 goals→有效薄弱点组装，并取得三层冲突已决胜偏好；掌握度与偏好选择分别锁 Snapshot 冻结 | 最小 PlanningBundle 与可复现 mastery/preferences；pending 候选不进入，来源更新不改变同 Snapshot | `_aggregate_learning_evidence_node` |
| 学习证据聚合 | `backend/app/modules/agent/workflows/plan.py` | `_aggregate_learning_evidence_node` | L26-L53 | PlanningBundle | 把真实 targets、周期、目标项 ID、掌握度及已决胜偏好写入 ExecutionContext；不再注入默认学科或 60 分钟 | `planning_bundle`、`learning_evidence` | `_planning_precondition_gate_node` |
| 计划草案生成 | `backend/app/modules/agent/workflows/plan.py` | `_planning_precondition_gate_node`、`_propose_plan_delta_node`、`_plan_quality_gate_node` | L56-L118 | 真实规划 targets 与选中偏好 | targets 为空直接失败且不创建审批；非空时最多取三个目标，目标自身 daily_minutes 优先，其次使用批准/本轮明确时长，最后回退规则模板 30 分钟 | 带 source/source_id 的 `plan_draft` | `_create_approval_node` |
| 审批请求 | `backend/app/modules/agent/workflows/plan.py` | `_create_approval_node` | L121-L174 | 计划草案 | 调用 `AgentService.create_approval` 创建真实审批记录，保留 diff 内容 | `approval_data` | `_wait_for_approval_node` |
| WAITING 断点 | `backend/app/modules/agent/workflows/plan.py` | `_wait_for_approval_node` | L177-L181 | 当前 run | 返回 `NodeResult.waiting(next_node="apply_plan_change")` | checkpoint 与待审批状态 | 用户审批 API |
| 审批决定分流 | `backend/app/modules/agent/service.py` | `AgentService.decide_approval` | L424-L476 | waiting run、pending approval、用户决定 | approved 恢复 running 并投递；rejected 转 failed、删除 checkpoint、不投递；错误状态或跨用户无副作用返回 | approved run 或 rejected 终态 | `AgentWorker.process_run` / timeline |
| 恢复应用与 Artifact | `backend/app/modules/agent/workflows/plan.py` | `_apply_plan_change_node`、`_render_plan_result_node`、`_completed_node` | L184-L239 | 审批通过后的 checkpoint | 应用节点复核 approval=approved；渲染时把 approval ID 和真实来源目标放入 Plan Artifact，未批准返回失败 | 携带审批来源的 Artifact 与 completed run，或无 Artifact 的 failed run | worker 完成分支 |
| 确认计划事实与目标物化 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/agent/memory_item_projection.py` | `project_completed_run_facts`、`_record_plan_confirmed`、`_project_confirmed_plan_goal` | L125-L140、L185-L251；L165-L209 | 已持久化 Plan Artifact、approval ID | 同步投影再查 approved 审批并写事实/Outbox；异步投影复核 Artifact/approval，物化新用户目标、supersede 旧目标并追加版本化向量任务；未批准跳过 | active `learning_goal`、旧项 superseded、pending 向量任务与 completed 事实 Outbox | 后续 Plan / 向量召回 / 冲突治理 |

## 旁路：等待用户输入与审批

| 执行阶段 | 文件 | 符号 | 职责与最终落点 |
| --- | --- | --- | --- |
| 用户补充输入 | `frontend/src/store/agent-context.tsx` | `AgentProvider.answerWorkflowInput` | 提交等待中的工作流输入，成功后刷新 thread 时间线 |
| 后端接收输入 | `backend/app/modules/agent/router.py`、`backend/app/modules/agent/service.py` | `submit_input_answer`、`submit_input_answer` | 校验等待项归属，保存用户答案并重新投递 Run |
| 用户审批 | `frontend/src/store/agent-context.tsx` | `AgentProvider.decideWorkflowApproval` | 调用批准/拒绝 API，成功后刷新时间线 |
| 后端审批 | `backend/app/modules/agent/router.py` | `approve_approval`、`reject_approval` | 更新审批事实，并恢复或终止相应 workflow |
| 偏好候选列表与决定 | `backend/app/modules/agent/router.py` | `get_preference_candidates`、`decide_user_preference_candidate`（L674-L710） | 只列出当前用户候选；pending 可批准或拒绝，重复同决定幂等，跨用户或终态反向修改返回无结果 |

## 下一步阅读

- 需要看检索、DTO、工具活动与 Explain 无资料策略，转到 `implementation/rag-and-tools.md`。
- 需要看上下文选择和 Router 当前记忆边界，转到 `implementation/routing-context-memory.md`。
