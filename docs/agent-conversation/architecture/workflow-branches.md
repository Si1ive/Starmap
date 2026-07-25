# Agent 工作流分支

## 适用场景

本分卷描述 conversation Router 之后 explain / validate / grade / plan 四类业务 child workflow 的入口、关键节点、
工具调用和最终落点。定位“Router 明明分到了某个 workflow，但用户端没有看到正确产物”时，应从这里开始。

## Router 到 child Run 的公共链路

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata` | L163-L186 | 受控上下文与父 Run `model_config_id` | 复制上下文审计和模型配置 ID，不复制 API Key | child run metadata | `_dispatch_workflow_node` |
| 2 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | L189-L234 | Router action、parent/root run、触发消息 | 幂等创建 compact child run 和对应 workflow timeline item | 队列中的 child run | `AgentWorker.process_run` |
| 3 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（进入 running） | L127-L138 | queued child run | 提交 running 状态和 `run.status_changed`，让用户端先看到真实执行中 | running child run | `WorkflowEngine.execute` |
| 4 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | L61-L212 | workflow 定义与 child run | 每个节点开始/完成/失败分别写 step 事件，并把 `artifact` 收进 `ExecutionContext.artifacts` | 可持久化步骤链和最终产物 | 具体 workflow 节点 |

## Explain：资料探索到讲解产物

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 资料范围加载 | `backend/app/modules/agent/workflows/explain.py` | `_load_scope_node` | L26-L37 | child run context | 读取允许学科与章节范围并写入上下文 | `scope` | `_evidence_loop_node` |
| 有界资料探索 | `backend/app/modules/agent/workflows/explain.py` | `_evidence_loop_node` | L40-L156 | 用户问题、预算和 child run ID | 首次无论模型是否想结束都至少检索一次；只把成功且非空结果记为 evidence；每轮决策和 observation 写 `agent_loop_turns` | 有效 evidence、`retrieval_attempted` | `ExplanationRuntime.decide` / `retrieve_knowledge` |
| 检索工具 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `_logical_activity_id`、`_next_attempt_number`、`retrieve_knowledge` | L77-L313 | explain/validate 的 query、范围、run ID | 检索前写 `tool.called`，同一逻辑检索的重试复用稳定 `activity_id`，后台额外保留 `attempt_id` / `attempt_no`；完成后统一返回带 `entity`/`question_meta`/`knowledge_point_meta` 的 Agent DTO，并公开零命中或异常的安全提示 | 公开活动 + 内部检索结果 | `RetrievalService.search_with_outline_expansion` |
| 零证据门禁 | `backend/app/modules/agent/workflows/explain.py` | `_evidence_gate_node` | L159-L175 | 已筛选 evidence | 非空资料直接通过；零命中记录“没有检索到相关文档”，但继续生成通用知识回答 | `gate_passed` 与原因 | `_generate_explanation_node` |
| 结构化讲解生成 | `backend/app/modules/agent/workflows/explain.py` | `_generate_explanation_node` | L178-L230 | 用户问题和证据列表 | 截断证据正文并保留 `entity_title`、`entity_type`、`source`；无资料时明确禁止伪造引用；调用结构化讲解运行时 | `ExplanationOutput` | `_citation_gate_node` |
| 正文/引用校验 | `backend/app/modules/agent/workflows/explain.py` | `_citation_gate_node` | L233-L245 | 结构化讲解结果 | 只要正文非空即通过，引用列表可为空 | 可渲染 explanation | `_render_artifact_node` |
| Artifact 渲染与结束 | `backend/app/modules/agent/workflows/explain.py` | `_render_artifact_node`、`_completed_node` | L248-L275 | outline、body、citations、summary | 组装 explanation artifact，并把最终 artifact 挂到 NodeResult 和上下文 | `agent_artifacts`、completed run | `AgentWorker.process_run` |

## Validate：候选题检索到练习产物

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 学习证据读取 | `backend/app/modules/agent/workflows/validate.py` | `_load_learning_evidence_node` | L38-L49 | user/context | 读取弱项、强项和近期主题，并写入 `learning_evidence` | 学习证据 | `_question_discovery_node` |
| 候选题检索 | `backend/app/modules/agent/workflows/validate.py` | `_question_discovery_node` | L52-L73 | `weak_areas` 与 run ID | 拼查询词并调用 `retrieve_knowledge(entity_type="question")`，直接拿到题目实体元数据 | `candidates` | `_question_gate_node` |
| 题目资格门 | `backend/app/modules/agent/workflows/validate.py` | `_question_is_eligible`、`_question_gate_node` | L20-L35、L76-L89 | 候选题列表 | 校验实体类型、审核/状态、题型、难度和真实来源字段；不再依赖虚构的 `source_type` | `valid_questions` | `_composition_gate_node` |
| 组合校验 | `backend/app/modules/agent/workflows/validate.py` | `_composition_gate_node` | L92-L116 | 有效题目 | 汇总 `question_meta.question_type`、`question_meta.difficulty` 和 `subject_id`，供后续产物使用 | `composition` | `_create_draft_node` |
| 练习草稿与 Artifact | `backend/app/modules/agent/workflows/validate.py` | `_create_draft_node`、`_render_artifact_node` | L119-L161 | 有效题目与组合信息 | 生成 practice draft，再渲染 practice artifact | `agent_artifacts` 与 completed run | `_completed_node` |

## Grade：作答快照到反馈产物

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 作答快照 | `backend/app/modules/agent/workflows/grade.py` | `_load_attempt_snapshot_node` | L18-L32 | `question_id`、`user_answer` | 冻结题目 ID、作答正文和提交时间 | `attempt` | `_objective_grade_node` |
| 客观判定与 rubric | `backend/app/modules/agent/workflows/grade.py` | `_objective_grade_node`、`_rubric_gate_node` | L35-L63 | 尝试快照 | 先做确定性判定，再组装 rubric | `objective_result`、`rubric` | `_generate_feedback_node` |
| 主观反馈生成 | `backend/app/modules/agent/workflows/grade.py` | `_generate_feedback_node`、`_feedback_gate_node` | L66-L98 | attempt 和 rubric | 生成 strengths / weaknesses / suggestions，并校验整体反馈非空 | `feedback` | `_render_artifact_node` |
| 反馈 Artifact | `backend/app/modules/agent/workflows/grade.py` | `_render_artifact_node`、`_completed_node` | L101-L132 | 反馈内容 | 组装 feedback artifact | `agent_artifacts` 与 completed run | worker 完成分支 |

## Plan：计划草案、审批与恢复执行

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 学习证据聚合 | `backend/app/modules/agent/workflows/plan.py` | `_aggregate_learning_evidence_node` | L25-L41 | user_id | 聚合薄弱项、强项、连续学习天数和每日目标 | `learning_evidence` | `_planning_precondition_gate_node` |
| 计划草案生成 | `backend/app/modules/agent/workflows/plan.py` | `_planning_precondition_gate_node`、`_propose_plan_delta_node`、`_plan_quality_gate_node` | L44-L88 | 学习证据 | 校验薄弱项非空后生成 7 天计划草案，并做质量门禁 | `plan_draft` | `_create_approval_node` |
| 审批请求 | `backend/app/modules/agent/workflows/plan.py` | `_create_approval_node` | L91-L141 | 计划草案 | 调用 `AgentService.create_approval` 创建真实审批记录，保留 diff 内容 | `approval_data` | `_wait_for_approval_node` |
| WAITING 断点 | `backend/app/modules/agent/workflows/plan.py` | `_wait_for_approval_node` | L144-L148 | 当前 run | 返回 `NodeResult.waiting(next_node="apply_plan_change")` | checkpoint 与待审批状态 | 用户审批 API |
| 恢复应用与 Artifact | `backend/app/modules/agent/workflows/plan.py` | `_apply_plan_change_node`、`_render_plan_result_node` | L151-L186 | 审批通过后的 checkpoint | 应用最终计划，并渲染 plan artifact | `agent_artifacts` 与 completed run | `_completed_node` |

## 旁路：等待用户输入与审批

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责与最终落点 |
| --- | --- | --- | --- | --- |
| 用户补充输入 | `frontend/src/store/agent-context.tsx` | `AgentProvider.answerWorkflowInput` | L457-L464 | 提交等待中的工作流输入，成功后刷新 thread 时间线 |
| 后端接收输入 | `backend/app/modules/agent/router.py` | `submit_input_answer` | L547-L568 | 校验等待项归属，保存用户答案并重新投递 Run |
| 用户审批 | `frontend/src/store/agent-context.tsx` | `AgentProvider.decideWorkflowApproval` | L466-L480 | 调用批准/拒绝 API，成功后刷新时间线 |
| 后端审批 | `backend/app/modules/agent/router.py` | `approve_approval`、`reject_approval` | L607-L622、L626-L641 | 更新审批事实，并恢复或终止相应 workflow |

## 下一步阅读

- 需要看检索、DTO、工具活动与 Explain 无资料策略，转到 `implementation/rag-and-tools.md`。
- 需要看上下文选择和 Router 当前记忆边界，转到 `implementation/routing-context-memory.md`。
