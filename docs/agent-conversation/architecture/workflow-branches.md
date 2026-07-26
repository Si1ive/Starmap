# Agent 工作流分支

## 适用场景

本分卷描述 conversation Router 之后 explain / validate / grade / plan 四类业务 child workflow 的入口、关键节点、
工具调用和最终落点。定位“Router 明明分到了某个 workflow，但用户端没有看到正确产物”时，应从这里开始。

## Router 到 child Run 的公共链路

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | L46-L121 | conversation run 与当前消息 | 调用上下文构建、确定性理解和 snapshot，再用独立请求调用 Router；找不到 run 时返回失败，Router 异常交给 engine | `agent_run_context`、RouterDecision 或失败 | `build_turn_understanding` / `ensure_turn_memory_snapshot` |
| 2 | `backend/app/modules/agent/turn_understanding.py`、`backend/app/modules/agent/memory_projection.py` | `build_turn_understanding`、`ensure_turn_memory_snapshot`、`project_topic_confirmed_fact` | L105-L157、L161-L246；L67-L122 | 当前输入、context refs、线程 `active_topic` | 生成确定性理解、创建不可变 snapshot 并更新热状态；首个主题来自显式 context ref 时，在 Router 模型调用前按 Run 幂等写 `topic_confirmed`，继承主题不重复写 | `standalone_request`、snapshot、`active_topic`、主题事实与 pending Memory Outbox；Router 后续失败不回滚已表达主题 | `_route_node` 的 Router 调用 |
| 3 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | L183-L209 | 受控上下文、独立请求、snapshot ID 与父 Run `model_config_id` | 复制上下文审计、`active_topic`、`standalone_request`、`memory_snapshot_id` 和模型配置 ID，不复制 API Key | child run metadata | `_dispatch_workflow_node` |
| 4 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | L212-L261 | Router action、parent/root run、独立请求 | 幂等创建 compact child run 和对应 workflow timeline item；child `input_message` 使用 `standalone_request` | 队列中的 child run | `AgentWorker.process_run` |
| 5 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（进入 running） | L128-L178 | queued child run | 提交 running 状态和 `run.status_changed`，让用户端先看到真实执行中 | running child run | `WorkflowEngine.execute` |
| 6 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | L27-L209 | workflow 定义与 child run | 每个节点开始/完成/失败分别写 step 事件并提交真实边界；异常节点提交已有 snapshot/主题事实与 step.failed，再返回失败 | 可恢复步骤链、最终产物或失败结果 | 具体 workflow 节点 / worker 终态投影 |

## Explain：资料探索到讲解产物

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 资料范围加载 | `backend/app/modules/agent/workflows/explain.py` | `_load_scope_node` | child run context | 读取允许学科与章节范围并写入上下文 | `scope` | `_evidence_loop_node` |
| 有界资料探索 | `backend/app/modules/agent/workflows/explain.py` | `_evidence_loop_node` | 用户问题、预算和 child run ID | 首次无论模型是否想结束都至少检索一次；只把成功且非空结果记为 evidence；同时记录 `retrieval_outcome=evidence|empty|error`；每轮决策和 observation 写 `agent_loop_turns` | 有效 evidence、`retrieval_attempted`、`retrieval_outcome` | `ExplanationRuntime.decide` / `retrieve_knowledge` |
| 检索工具 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `_logical_activity_id`、`_next_attempt_number`、`retrieve_knowledge` | explain/validate 的 query、范围、run ID | 检索前写 `tool.called`，同一逻辑检索的重试复用稳定 `activity_id`，后台额外保留 `attempt_id` / `attempt_no`；完成后统一返回带 `entity`/`question_meta`/`knowledge_point_meta` 的 Agent DTO，并公开零命中或异常的安全提示 | 公开活动 + 内部检索结果 | `RetrievalService.search_with_outline_expansion` |
| 零证据门禁 | `backend/app/modules/agent/workflows/explain.py` | `_evidence_gate_node` | 已筛选 evidence 与 `retrieval_outcome` | 非空资料直接通过；零命中记录“没有检索到相关文档”，检索异常记录“暂时无法检索相关文档”，但两者都继续生成通用知识回答 | `gate_passed` 与原因 | `_generate_explanation_node` |
| 结构化讲解生成 | `backend/app/modules/agent/workflows/explain.py` | `_fallback_evidence_text`、`_generate_explanation_node` | 用户问题、证据列表和 `retrieval_outcome` | 截断证据正文并保留 `entity_title`、`entity_type`、`source`；无资料时按零命中/异常选择不同 fallback 文案；调用结构化讲解运行时后清空无资料场景的 citations | `ExplanationOutput` | `_citation_gate_node` |
| 正文/引用校验 | `backend/app/modules/agent/workflows/explain.py` | `_citation_gate_node` | 结构化讲解结果 | 只要正文非空即通过，引用列表在无资料场景下已被上游清空 | 可渲染 explanation | `_render_artifact_node` |
| Artifact 渲染与结束 | `backend/app/modules/agent/workflows/explain.py` | `_render_artifact_node`、`_completed_node`（L279-L306） | outline、body、citations、summary | 组装 explanation artifact，并把最终 artifact 挂到 NodeResult 和上下文 | `agent_artifacts`、completed run | `AgentWorker.process_run` |
| 讲解事实投影 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/agent/memory_item_projection.py` | `project_completed_run_facts`、`_record_explanation_artifact_created`（L125-L182）；`project_trusted_memory_event`（L153-L165） | worker 已持久化的 explanation Artifact | 按 Run 幂等写讲解事实并确保 pending Outbox；异步消费者确认可信类型但不复制正文、不提高掌握度 | `explanation_artifact_created`、completed Outbox；正文仍以 Artifact 为权威 | 后续摘要 projector |

## Validate：候选题检索到练习产物

| 执行阶段 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| PracticeBundle 选择 | `backend/app/modules/agent/memory_selector.py` | `load_practice_bundle` | child run `run_id` / `user_id`、`memory_snapshot_id`、selected snapshot items | 校验 run 与 snapshot 权限，从 `agent_memory_snapshots`、`agent_memory_snapshot_items` 和 `selection_metadata_json` 读取主题、aliases、difficulty 约束、knowledge point IDs 与选中的 Artifact | `PracticeBundle` | `_load_learning_evidence_node` |
| 学习证据读取 | `backend/app/modules/agent/workflows/validate.py` | `_load_learning_evidence_node` | `PracticeBundle`、当前上下文 | 优先用 bundle topic 填充 `weak_areas` / `recent_topics`，并把序列化后的 bundle 写回 `ExecutionContext` 供后续节点继续消费 | `learning_evidence`、`practice_bundle` | `_question_discovery_node` |
| 候选题检索 / 缺主题澄清 | `backend/app/modules/agent/memory_selector.py`、`backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/agent/service.py` | `build_practice_query`、`build_practice_filters`、`_question_discovery_node`、`create_input` | `practice_bundle`、`weak_areas`、run ID | 用 bundle topic title + aliases 确定性生成 query；若无主题且无 fallback terms，则先查找已回答的 `practice_topic` 输入；仍缺主题时创建 `AgentInput`、投影 `workflow.input.required` 并返回 `NodeResult.waiting(next_node="question_discovery")`；有主题后调用 `retrieve_knowledge(entity_type="question")`，同时下发 `knowledge_point_ids`、`difficulty` 和排除题 ID | `candidates` 或等待中的 pending input + checkpoint | `_question_gate_node` / 用户补充输入 |
| 澄清恢复执行 | `backend/app/modules/agent/service.py` | `submit_input_answer` | waiting run、`practice_topic` 用户答案 | 校验 run 和输入归属，把输入记为 answered，恢复 run 到 running 并重新投递 outbox | answered input、恢复后的 run | `AgentWorker.process_run` -> `_question_discovery_node` |
| 题目资格门 | `backend/app/modules/agent/workflows/validate.py` | `_question_is_eligible`、`_question_gate_node` | 候选题列表 | 校验实体类型、审核/状态、题型、难度和真实来源字段；不再依赖虚构的 `source_type` | `valid_questions` | `_composition_gate_node` |
| 组合校验 | `backend/app/modules/agent/workflows/validate.py` | `_composition_gate_node` | 有效题目 | 汇总 `question_meta.question_type`、`question_meta.difficulty` 和 `subject_id`，供后续产物使用 | `composition` | `_create_draft_node` |
| 练习草稿与 Artifact | `backend/app/modules/agent/workflows/validate.py` | `_create_draft_node`、`_render_artifact_node` | 有效题目与组合信息 | 生成 practice draft，再渲染 practice artifact | `agent_artifacts` 与 completed run | `_completed_node` |

## Grade：作答快照到反馈产物

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 作答快照 | `backend/app/modules/agent/workflows/grade.py` | `_load_attempt_snapshot_node` | L20-L31 | `question_id`、`user_answer` | 冻结题目 ID、作答正文和提交时间；当前 worker 只注入 `input_message`，因此 P1 尚无真实题面/答案 Bundle | `attempt` | `_objective_grade_node` |
| 客观判定与 rubric | `backend/app/modules/agent/workflows/grade.py` | `_objective_grade_node`、`_rubric_gate_node` | L34-L67 | 尝试快照 | 当前 P1 不读取标准答案，所有作答都标为非客观题，再组装完整度 rubric；这里不会产生 `grading_evidence` | `objective_result`、`rubric` | `_generate_feedback_node` |
| 主观反馈生成 | `backend/app/modules/agent/workflows/grade.py` | `_generate_feedback_node`、`_feedback_gate_node` | L70-L105 | attempt 和 rubric | 生成固定 strengths / weaknesses / suggestions，并校验整体反馈非空 | `feedback`；反馈为空时返回失败并由 worker 投影 `run.failed` | `_render_artifact_node` |
| 反馈 Artifact | `backend/app/modules/agent/workflows/grade.py` | `_render_artifact_node`、`_completed_node` | L108-L142 | 反馈内容、可选的内部 `grading_evidence` | 组装 feedback artifact；只有已有显式 verdict 时才把完整证据放入 `content.grading`，固定反馈不伪造评分 | `agent_artifacts` 与 completed run | `AgentWorker.process_run` |
| 完成事实交接 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L183-L224 | completed 结果与 Feedback Artifact | 先持久化 Artifact，再在同一完成事务调用事实投影，最后写 `run.completed` | Artifact、内部记忆事实或无副作用跳过 | `project_completed_run_facts` |
| 评分事实与掌握度 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/agent/memory_item_projection.py` | `project_completed_run_facts`、`_record_grade_result_confirmed`、`project_trusted_memory_event` | L125-L140、L308-L413；L153-L165 | Feedback Artifact 的 `content.grading` | 校验证据、去重知识点，写幂等事实、同步更新掌握度并确保 pending Outbox；异步消费不复制评分正文；证据不完整安全跳过 | 事实、掌握度与 completed Outbox | 后续练习/摘要或 Embedding 扩展 |

## Plan：计划草案、审批与恢复执行

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 学习证据聚合 | `backend/app/modules/agent/workflows/plan.py` | `_aggregate_learning_evidence_node` | L25-L42 | user_id | 聚合薄弱项、强项、连续学习天数和每日目标 | `learning_evidence` | `_planning_precondition_gate_node` |
| 计划草案生成 | `backend/app/modules/agent/workflows/plan.py` | `_planning_precondition_gate_node`、`_propose_plan_delta_node`、`_plan_quality_gate_node` | L45-L99 | 学习证据 | 校验薄弱项非空后生成 7 天计划草案，并做质量门禁 | `plan_draft` | `_create_approval_node` |
| 审批请求 | `backend/app/modules/agent/workflows/plan.py` | `_create_approval_node` | L102-L155 | 计划草案 | 调用 `AgentService.create_approval` 创建真实审批记录，保留 diff 内容 | `approval_data` | `_wait_for_approval_node` |
| WAITING 断点 | `backend/app/modules/agent/workflows/plan.py` | `_wait_for_approval_node` | L158-L162 | 当前 run | 返回 `NodeResult.waiting(next_node="apply_plan_change")` | checkpoint 与待审批状态 | 用户审批 API |
| 审批决定分流 | `backend/app/modules/agent/service.py` | `AgentService.decide_approval` | L424-L476 | waiting run、pending approval、用户决定 | approved 恢复 running 并投递；rejected 转 failed、删除 checkpoint、不投递；错误状态或跨用户无副作用返回 | approved run 或 rejected 终态 | `AgentWorker.process_run` / timeline |
| 恢复应用与 Artifact | `backend/app/modules/agent/workflows/plan.py` | `_apply_plan_change_node`、`_render_plan_result_node`、`_completed_node` | L165-L220 | 审批通过后的 checkpoint | 应用节点复核 approval=approved；渲染时把 approval ID 放入 Plan Artifact，未批准返回失败 | 携带审批来源的 Artifact 与 completed run，或无 Artifact 的 failed run | worker 完成分支 |
| 确认计划事实与目标物化 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/agent/memory_item_projection.py` | `project_completed_run_facts`、`_record_plan_confirmed`、`_project_confirmed_plan_goal` | L125-L140、L185-L251；L108-L150 | 已持久化 Plan Artifact、approval ID | 同步投影再查 approved 审批并写事实/Outbox；异步投影复核同 Run Plan Artifact 与 approval ID，按事实键 upsert 用户级目标摘要；未批准跳过 | `plan_confirmed`、`learning_goal` 与 completed Outbox | 未来 PlanningBundle |

## 旁路：等待用户输入与审批

| 执行阶段 | 文件 | 符号 | 职责与最终落点 |
| --- | --- | --- | --- |
| 用户补充输入 | `frontend/src/store/agent-context.tsx` | `AgentProvider.answerWorkflowInput` | 提交等待中的工作流输入，成功后刷新 thread 时间线 |
| 后端接收输入 | `backend/app/modules/agent/router.py`、`backend/app/modules/agent/service.py` | `submit_input_answer`、`submit_input_answer` | 校验等待项归属，保存用户答案并重新投递 Run |
| 用户审批 | `frontend/src/store/agent-context.tsx` | `AgentProvider.decideWorkflowApproval` | 调用批准/拒绝 API，成功后刷新时间线 |
| 后端审批 | `backend/app/modules/agent/router.py` | `approve_approval`、`reject_approval` | 更新审批事实，并恢复或终止相应 workflow |

## 下一步阅读

- 需要看检索、DTO、工具活动与 Explain 无资料策略，转到 `implementation/rag-and-tools.md`。
- 需要看上下文选择和 Router 当前记忆边界，转到 `implementation/routing-context-memory.md`。
