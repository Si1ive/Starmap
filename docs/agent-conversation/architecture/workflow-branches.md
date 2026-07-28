# Agent 工作流分支

## 适用场景

本分卷描述 conversation Router 之后 explain / validate / grade / plan 四类业务 child workflow 的入口、关键节点、
工具调用和最终落点。定位“Router 明明分到了某个 workflow，但用户端没有看到正确产物”时，应从这里开始。

## Router 到 child Run 的公共链路

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/context_builder.py`、`backend/app/modules/agent/workflows/conversation.py` | `_active_topic_from_state`、`_route_node` | L752-L772；L50-L155 | conversation run、当前消息与线程热状态 | 构建近期原文与预算内 active 摘要；显式主题最多继承 6 个后续轮次，版本差超过阈值或标记非法时不交给 Router；仅在真实歧义时调用指代模型，再冻结 snapshot | `agent_run_context`、RouterDecision 或失败 | `build_turn_understanding` / `ensure_turn_memory_snapshot` |
| 2 | `backend/app/modules/agent/turn_understanding.py` | `_derive_constraints`、`_resolve_question_artifact_reference`、`build_ambiguous_referent_candidates`、`hydrate_referent_candidate_labels`、`build_turn_understanding`、`requests_question_repeat` | L213-L226、L229-L258、L261-L338、L341-L375、L421-L481、L602-L620 | 当前输入、context refs、近期 Artifact 结构化引用、线程 `active_topic`、题库 active 题面 | 先确定性抽取当前显式练习主题、difficulty/章节和唯一 question 指代；“再出一遍上次那道题”等肯定表达额外冻结 `repeat_referenced_question`，常见否定表达不冻结；仍歧义时构造候选，并为 question 水合真实题面、过滤缺失或失效实体 | 确定性理解或带语义标签的候选白名单 | `ReferentRuntime.resolve` / `apply_referent_resolution` |
| 3 | `backend/app/modules/agent/model_runtime/referent.py`、`backend/app/modules/agent/turn_understanding.py` | `ReferentRuntime.resolve`、`apply_referent_resolution` | L79-L148；L378-L418 | 原始输入、近期消息、带标签候选、Run 模型配置 | 结构化返回 resolved/unresolved；resolved 键必须属于候选且置信度至少 0.8，否则报错或降级。合法选择和候选审计写回理解 | 含 `reference_sources` / `reference_resolution` 的 TurnUnderstanding | `ensure_turn_memory_snapshot` |
| 4 | `backend/app/modules/agent/turn_understanding.py`、`backend/app/modules/agent/memory_projection.py` | `ensure_turn_memory_snapshot`、`project_topic_confirmed_fact` | L489-L599；L67-L122 | 完整理解、当前 Run、线程热状态与可选摘要 | 创建不可变 snapshot；摘要作为 `historical_summaries` item 保存正文副本、来源 ID、版本和范围；显式主题仍在 Router 前幂等写事实 | 可复现 snapshot、热状态、主题事实与 pending Outbox | `_route_node` 的 Router 调用 |
| 5 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | L217-L246 | 受控上下文、独立请求、snapshot ID 与父 Run `model_config_id` | 复制摘要 ID 等上下文审计、`active_topic`、`standalone_request`、`memory_snapshot_id` 和模型配置 ID，不复制摘要正文或 API Key | child run metadata | `_dispatch_workflow_node` |
| 6 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | L249-L298 | Router action、parent/root run、独立请求 | 幂等创建 compact child run 和对应 workflow timeline item；child `input_message` 使用 `standalone_request` | 队列中的 child run | `AgentWorker.process_run` |
| 7 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（进入 running） | L122-L180 | queued child run | 提交 running 状态和 `run.status_changed`，让用户端先看到真实执行中，再恢复 checkpoint 并调用引擎 | running child run 与节点结果 | completed / waiting / failed 分支 |
| 8 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | L27-L209 | workflow 定义与 child run | 每个节点开始/完成/失败分别写 step 事件并提交真实边界；异常节点提交已有 snapshot/主题事实与 step.failed，再返回失败 | 可恢复步骤链、最终产物或失败结果 | 具体 workflow 节点 / worker 终态投影 |

## Explain：资料探索到讲解产物

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 对话连续性选择 | `backend/app/modules/agent/memory_selector.py`、`backend/app/modules/agent/workflows/explain.py` | `load_conversation_bundle`（L1067-L1236）、`_load_scope_node`（L36-L47） | child run、同用户/线程 snapshot、冻结消息/摘要/Artifact ID | 复现 snapshot 当时的 visible completed 消息、唯一摘要副本和公开 Artifact；摘要源记录需匹配 user/thread/version，重复或版本不符时不注入摘要 | `conversation_bundle`、`scope.mode=snapshot` | `_evidence_loop_node` |
| 有界资料探索 | `backend/app/modules/agent/workflows/explain.py` | `_conversation_inputs`、`_evidence_loop_node`（L50-L206） | ConversationBundle、预算和 child run ID | 把原始消息转 history、摘要转不可信 deps；首次仍强制使用唯一题面、topic aliases 或 standalone request 的冻结 query | 有效 evidence、`retrieval_attempted`、`retrieval_outcome` | `ExplanationRuntime.decide` / `retrieve_knowledge` |
| 检索工具 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `_logical_activity_id`、`_next_attempt_number`、`retrieve_knowledge` | explain/validate 的 query、范围、run ID | 检索前写 `tool.called`，同一逻辑检索的重试复用稳定 `activity_id`，后台额外保留 `attempt_id` / `attempt_no`；完成后统一返回带 `entity`/`question_meta`/`knowledge_point_meta` 的 Agent DTO，并公开零命中或异常的安全提示 | 公开活动 + 内部检索结果 | `RetrievalService.search_with_outline_expansion` |
| 零证据门禁 | `backend/app/modules/agent/workflows/explain.py` | `_evidence_gate_node` | 已筛选 evidence 与 `retrieval_outcome` | 非空资料直接通过；零命中记录“没有检索到相关文档”，检索异常记录“暂时无法检索相关文档”，但两者都继续生成通用知识回答 | `gate_passed` 与原因 | `_generate_explanation_node` |
| 结构化讲解生成 | `backend/app/modules/agent/workflows/explain.py` | `_fallback_evidence_text`、`_generate_explanation_node`（L236-L289） | standalone question、ConversationBundle history/摘要、证据列表和 `retrieval_outcome` | 规划和正文模型复用同一份冻结 history、摘要、主题、Artifact 摘要与引用 ID；无资料时使用 fallback 并清空 citations | `ExplanationOutput` | `_citation_gate_node` |
| 正文/引用校验 | `backend/app/modules/agent/workflows/explain.py` | `_citation_gate_node` | 结构化讲解结果 | 只要正文非空即通过，引用列表在无资料场景下已被上游清空 | 可渲染 explanation | `_render_artifact_node` |
| Artifact 渲染与结束 | `backend/app/modules/agent/workflows/explain.py` | `_render_artifact_node`、`_completed_node`（L307-L333） | outline、body、citations、summary | 组装 explanation artifact，并把最终 artifact 挂到 NodeResult 和上下文 | `agent_artifacts`、completed run | `AgentWorker.process_run` |
| 讲解事实投影 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/agent/memory_item_projection.py` | `project_completed_run_facts`、`_record_explanation_artifact_created`（L125-L182）；`project_trusted_memory_event`（L212-L224） | worker 已持久化的 explanation Artifact | 按 Run 幂等写讲解事实并确保 pending Outbox；异步消费者确认可信类型但不复制正文、不提高掌握度 | `explanation_artifact_created`、completed Outbox；正文仍以 Artifact 为权威 | 后续摘要 projector |

## Validate：候选题检索到练习产物

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| PracticeBundle 选择 | `backend/app/modules/agent/memory_selector.py` | `_resolve_explicit_chapter_ids`、`_load_unique_weak_topic`、`load_practice_bundle`、`_apply_explicit_question_repeat`（L708-L854、L857-L997、L1239-L1259） | child run、snapshot/items、知识点与章节约束、近期练习事实、UTC 读取时点 | 校验权限；显式章节序号在唯一学科内解析；无主题时按统一衰减策略选择唯一有效薄弱点并冻结题名/别名与分数 Snapshot Item；排除集仅在明确重复唯一题时覆盖本轮视图 | 含章节来源、有效掌握度审计和本轮排除视图的 `PracticeBundle`；同 Snapshot 不受来源改名或新证据影响，原掌握度/事实不修改 | `_load_learning_evidence_node` |
| 学习证据读取 | `backend/app/modules/agent/workflows/validate.py` | `_load_learning_evidence_node` | `PracticeBundle`、当前上下文 | 优先用 bundle topic 填充 `weak_areas` / `recent_topics`，并把序列化后的 bundle 写回 `ExecutionContext` 供后续节点继续消费 | `learning_evidence`、`practice_bundle` | `_question_discovery_node` |
| 候选题检索 / 严格范围 / 缺主题澄清 | `backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/agent/tools/retrieve_knowledge.py`、`backend/app/modules/retrieval/service.py`、`backend/app/modules/agent/service.py` | `_question_discovery_node`（L79-L172）、`retrieve_knowledge`（L144-L357）、`RetrievalService.search_with_outline_expansion`（L44-L120）、`AgentService.create_input` | `practice_bundle`、`weak_areas`、run ID | unresolved 显式章节先失败；resolved 显式章节下发 strict；无主题时创建/读取 `practice_topic` 等待恢复；检索零命中直接记录中性提示并绕过题目资格门 | candidates、pending input，或 `fallback=llm_generation` | `_question_gate_node` / `_generate_question_node` / 用户补充输入 |
| 澄清恢复执行 | `backend/app/modules/agent/service.py` | `submit_input_answer` | waiting run、`practice_topic` 用户答案 | 校验 run 和输入归属，把输入记为 answered，恢复 run 到 running 并重新投递 outbox | answered input、恢复后的 run | `AgentWorker.process_run` -> `_question_discovery_node` |
| 题目资格门 | `backend/app/modules/agent/workflows/validate.py` | `_question_is_eligible`、`_question_gate_node`（L29-L42、L175-L197） | 非空候选题列表 | 校验实体类型、审核/状态、题型、难度和真实来源字段；全部不合格时记为可恢复的题库不足，不把 Run 标成失败 | `valid_questions`，或中性降级原因 | `_composition_gate_node` / `_generate_question_node` |
| 模型兜底出题 | `backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/agent/model_runtime/practice.py` | `_generate_question_node`（L200-L258）、`PracticeGenerationRuntime.generate`（L41-L65） | 冻结主题、难度、Run 模型配置和剩余模型预算 | 生成结构化单选题；答案必须属于唯一选项集合；标记为“Agent 模型即时生成”，不伪装真题 | `valid_questions` 中的瞬时生成题 | `_composition_gate_node` |
| 组合校验 | `backend/app/modules/agent/workflows/validate.py` | `_composition_gate_node` | 有效题目 | 汇总 `question_meta.question_type`、`question_meta.difficulty` 和 `subject_id`，供后续产物使用 | `composition` | `_create_draft_node` |
| 练习草稿与 Artifact | `backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/agent/worker.py` | `_create_draft_node`、`_render_artifact_node`（L286-L363）、`AgentWorker.process_run`（L185-L210） | 有效题目与组合信息 | 生成 practice draft 和用户可展开的题面 Markdown；模型题答案/解析通过 `_private_metadata` 交给 Worker 写入 `AgentArtifact.metadata_json`，不进入公开 content，也不写入全局题库 | 公开题面、私有批改元数据与 completed run | `_completed_node` / 后续 Grade |

## Grade：作答快照到反馈产物

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 评分记忆选择 | `backend/app/modules/agent/memory_selector.py` | `EvaluationQuestion`、`EvaluationBundle`、`_extract_user_answer`、`load_evaluation_bundle` | L86-L144、L514-L645 | Grade run/user、同线程 snapshot、唯一 question 引用、题库与原始输入 | 校验 run/snapshot 作用域，重读 active 且未拒绝的题面、标准答案来源和知识点；只从显式答案句式提取作答。缺快照、跨作用域、多题、失效题或缺可信答案返回稳定 reason | `EvaluationBundle` 或 unresolved reason | `_load_attempt_snapshot_node` |
| 作答快照 | `backend/app/modules/agent/workflows/grade.py` | `_load_attempt_snapshot_node` | L40-L78 | `EvaluationBundle` | 把题型、题面、标准答案、答案来源、知识点、来源 Artifact 与用户作答冻结进 ExecutionContext；bundle 不完整时返回失败 | `attempt`；失败由 Worker 写 `run.failed`，无 Artifact/掌握度 | `_objective_grade_node` |
| 客观判定与证据门禁 | `backend/app/modules/agent/workflows/grade.py` | `_normalize_answer`、`_objective_grade_node`、`_rubric_gate_node` | L25-L37、L81-L147 | attempt | 仅支持 choice/fill/judge；按题型归一化后确定性比较，生成 correct/incorrect、分数和 answer_mismatch，再复核作答完整、判定确定、答案来源可信。主观题直接失败 | `objective_result`、`grading_evidence`、`rubric` | `_generate_feedback_node` |
| 证据反馈与 Artifact | `backend/app/modules/agent/workflows/grade.py` | `_generate_feedback_node`、`_feedback_gate_node`、`_render_artifact_node`、`_completed_node` | L150-L223 | 确定性结果、标准答案和可选解析 | 正确时说明一致；错误时展示用户答案、标准答案与解析；反馈门通过后把完整 `grading_evidence` 放入 Feedback Artifact | `agent_artifacts` 与 completed run；错误证据携带 `answer_mismatch` | `AgentWorker.process_run` |
| 完成事实与摘要任务交接 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L185-L227 | completed 结果与 Feedback Artifact | 先持久化 Artifact并调用事实投影，再写 `run.completed` 和幂等摘要维护 Outbox | Artifact、内部记忆事实、摘要任务或无副作用跳过 | `project_completed_run_facts` / `enqueue_conversation_summary_maintenance` |
| 评分事实与掌握度 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/agent/memory_item_projection.py` | `project_completed_run_facts`、`_record_grade_result_confirmed`、`project_trusted_memory_event` | L125-L140、L308-L413；L212-L224 | Feedback Artifact 的 `content.grading` | 校验证据、去重知识点，写幂等事实、同步更新掌握度并确保 pending Outbox；异步消费不复制评分正文；证据不完整安全跳过 | 事实、掌握度与 completed Outbox | PlanningBundle / 后续练习或摘要 |

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
