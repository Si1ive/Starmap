# 2026-07 Agent 对话模块进展

## 2026-07-26：冻结 Memory Outbox 数据库幂等键

### 目标

在接入 Memory Outbox 生产者前先建立数据库级并发幂等约束，避免同一 Run 的同类事实在并发重放时产生重复异步任务。

### 实现

- 在 `backend/app/modules/agent/models.py::AgentMemoryUpdateOutbox`（L612-L650）增加 `(run_id, event_type)` 唯一约束 `uk_agent_memory_outbox_run_event`。
- 新增前向迁移 `backend/alembic/versions/20260726_memory_outbox_unique.py::upgrade`（L18-L26），并提供 `downgrade`（L28-L34）；当前表尚无生产者，因此升级不会遇到历史重复任务。
- 更新 `backend/tests/test_migrations.py::test_migration_graph_has_single_head`（L28-L34）到新 head，并新增 `test_memory_outbox_idempotency_migration_renders_mysql_ddl`（L238-L262）验证 MySQL ALTER TABLE DDL。
- 同步更新数据库迁移分卷和 `MEM-006` 状态；本提交只冻结可靠生产契约，不宣称生产者或消费者已完成。

### 验证

- `cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_migrations.py tests/test_agent_memory_contracts.py` 通过（15 passed）。
- `git diff --check` 通过。

### 提交信息

`冻结 Memory Outbox 数据库幂等键`

## 2026-07-26：只为经批准的 Plan 写长期目标事实

### 目标

完成 `MEM-006` 的 `plan_confirmed` 同步事实边界：只有用户批准、应用成功并生成 Artifact 的计划才能成为长期目标；拒绝、pending、缺审批和旁路恢复均不得写记忆。

### 实现

- 在 `backend/app/modules/agent/workflows/plan.py::_render_plan_result_node`（L192-L215）把已通过守卫的 approval ID 写入 Plan Artifact，使事实投影可以回查真实批准来源。
- 扩展 `backend/app/modules/agent/memory_projection.py::project_completed_run_facts`（L82-L97），由 `_record_plan_confirmed`（L141-L206）校验 approval ID、同 Run 归属和数据库 approved 状态，再按 approval ID 幂等写用户级 `plan_confirmed`。
- 事件只保存 Artifact、approval 和可选 snapshot ID，计划正文仍以 `agent_artifacts` 为权威来源；拒绝与未批准路径维持零 Artifact、零长期事实。
- 扩展 `backend/tests/test_agent_plan_worker.py`（L92-L200），覆盖拒绝/旁路不写事实、批准后 Artifact 携带审批来源、事实载荷和重放幂等。
- 同步更新记忆实现分卷、Plan 执行全景和任务单，并修正 `memory_projection.py` 插入 Plan 投影后受影响的主题、Explain 与 Grade 锚点。

### 验证

- `cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_plan_worker.py tests/test_agent_memory_projection.py` 通过（9 passed）。
- `git diff --check` 通过。

### 提交信息

`只为经批准的 Plan 写长期目标事实`

## 2026-07-26：阻止被拒绝的 Plan 继续应用

### 目标

在写入 `plan_confirmed` 前先修复审批边界：用户拒绝计划时必须终止 Run，不能恢复 checkpoint、重新投递
或生成 Plan Artifact；即使外部错误地恢复 Run，应用节点也必须复核数据库中的真实审批状态。

### 实现

- 修改 `backend/app/modules/agent/service.py::AgentService.decide_approval`（L424-L476）：只接受 approved/rejected；批准时恢复 running 并写 Run Outbox，拒绝时转 failed、记录用户拒绝原因、删除 checkpoint 且不投递，二者统一投影 `run.status_changed`。
- 在 `backend/app/modules/agent/workflows/plan.py::_apply_plan_change_node`（L165-L189）增加纵深守卫，从数据库重读 checkpoint 携带的 approval ID，只有状态为 approved 才应用草案；pending、rejected 或缺失均失败且不生成 Artifact。
- 新增 `backend/tests/test_agent_plan_worker.py::test_rejected_plan_stops_without_outbox_or_artifact`（L92-L128）、`test_plan_apply_node_rejects_unapproved_checkpoint`（L132-L147）和 `test_approved_plan_resumes_and_creates_artifact`（L151-L200），同时锁定拒绝、旁路恢复和正常批准三条链路。
- 同步更新事件/错误实现分卷、Plan 执行全景和 `MEM-006` 任务状态，为下一提交的 `plan_confirmed` 事实投影建立可信前置条件。

### 验证

- `cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_plan_worker.py tests/test_agent_timeline_service.py::test_workflow_interactions_require_owned_run_in_matching_wait_state tests/test_agent_worker_waiting.py` 通过（6 passed）。
- `git diff --check` 通过。

### 提交信息

`阻止被拒绝的 Plan 继续应用`

## 2026-07-26：记录 Explain 成功讲解产物事实

### 目标

继续推进 `MEM-006`，让 Explain 成功完成后留下可追溯、可重放的讲解 Artifact 事实，同时确保零命中
fallback 也属于成功讲解，且讲解行为不会被误当成学习掌握度证据。

### 实现

- 在 `backend/app/modules/agent/memory_projection.py::project_completed_run_facts`（L82-L97）增加 explanation Artifact 分派，并由 `_record_explanation_artifact_created`（L100-L138）按 Run 幂等写线程级 `explanation_artifact_created`。
- 事件载荷只保留 `artifact_id` 与可选 `memory_snapshot_id`，正文、outline 和 citations 继续以 `agent_artifacts` 为唯一权威位置，不复制进长期事件或公开 SSE。
- 扩展 `backend/tests/test_agent_explain_worker.py::test_worker_persists_zero_hit_fallback_answer_without_citations`（L129-L227），覆盖零命中 fallback 仍写事实、重放不重复、引用为空且 `user_learning_mastery` 不产生记录。
- 同步更新 Router/记忆实现分卷、Explain 工作流执行全景和任务单，并修正 `memory_projection.py` 插入新函数后受影响的 Grade 代码锚点。

### 验证

- `cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_explain_worker.py tests/test_agent_memory_projection.py` 通过（8 passed）。
- `git diff --check` 通过。

### 提交信息

`记录 Explain 成功讲解产物事实`

## 2026-07-26：在 Router 失败前保留用户确认主题事实

### 目标

继续推进 `MEM-006`，把本轮用户显式选择的主题在 Router/模型调用前沉淀为可追溯事实，确保后续
模型配置或执行失败不会连同用户输入事实一起丢失，同时避免把继承的热状态重复记成用户确认。

### 实现

- 新增 `backend/app/modules/agent/memory_projection.py::project_topic_confirmed_fact`（L25-L79），仅接受 `source=context_ref` 的首个类型化主题，以 `topic_confirmed:{run_id}` 幂等写线程级事件，并记录 snapshot、状态版本和来源消息。
- 在 `backend/app/modules/agent/turn_understanding.py::ensure_turn_memory_snapshot`（L161-L246）创建或复用 snapshot 时调用主题投影；写入发生在 `_route_node` 的 Router 调用之前，继承自 `thread_memory` 的主题会无副作用跳过。
- 更新 `backend/tests/test_agent_conversation_workflow.py::test_model_configuration_failure_creates_visible_failed_message`（L603-L666），证明 Router 模型不可用时显式二分查找主题仍存在；`test_follow_up_validate_request_uses_active_topic_snapshot_for_child_run`（L443-L521）证明继承主题不新增确认事件。
- 新增 `backend/tests/test_agent_memory_projection.py::test_topic_confirmed_projection_is_idempotent_and_skips_inherited_topic`（L131-L179），覆盖同一 Run 重放与继承来源跳过。

### 验证

- `cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_memory_projection.py tests/test_agent_conversation_workflow.py` 通过（17 passed）。
- `git diff --check` 通过。

### 提交信息

`在 Router 失败前保留用户确认主题事实`

## 2026-07-26：建立真实评分事实到掌握度的安全投影边界

### 目标

继续推进任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 的 `MEM-006`，让未来真实评分
能够以事实事件幂等更新掌握度，同时确保当前只有固定反馈的 P1 Grade 不会污染学习画像。

### 实现

- 在 `backend/app/modules/agent/memory_projection.py::_record_grade_result_confirmed`（L262-L366）校验 Feedback Artifact 的结构化评分证据，按用户 + evidence ID 写 `grade_result_confirmed`，并按知识点增量更新 `user_learning_mastery`；重复知识点先去重，重放同一证据无副作用。
- 在 `backend/app/modules/agent/workflows/grade.py::_render_artifact_node`（L108-L137）建立可选 `grading_evidence -> content.grading` 交接；当前 `_objective_grade_node`（L34-L51）仍不生产 verdict，因此固定反馈不会触发掌握度写入。
- 新增 `backend/tests/test_agent_memory_projection.py::test_grade_projection_updates_mastery_and_replays_idempotently`（L183-L252）等五个回归场景，覆盖增量公式、用户隔离、知识点去重、证据契约、缺证据跳过和 P1 worker 端到端无污染语义。
- 同步更新 `implementation/routing-context-memory.md`、`architecture/workflow-branches.md` 和任务单，明确本次只完成安全投影边界；真实题面、标准答案与评分证据生产者仍是后续 `EvaluationBundle` / Grade 接入范围。

### 验证

- `cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_memory_projection.py tests/test_agent_memory_selector.py tests/test_agent_validate_worker.py` 通过（11 passed）。
- `git diff --check` 通过。

### 提交信息

`建立真实评分事实到掌握度的安全投影边界`

## 2026-07-26：让 Validate 在缺主题时进入澄清并可恢复执行

### 目标

继续推进任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `MEM-005`，
把 Validate “拿不到主题就失败”的临时行为收口成显式澄清闭环，让缺主题的出题请求进入 waiting，
并在用户补充练习范围后从 checkpoint 恢复同一轮检索。

### 实现

- 在 `backend/app/modules/agent/workflows/validate.py` 中新增 `practice_topic` 澄清路径：`_question_discovery_node()` 会先尝试读取已回答输入，若仍无主题则调用 `AgentService.create_input()` 创建待补充项，并返回 `NodeResult.waiting(next_node="question_discovery")`。
- 复用 `backend/app/modules/agent/service.py` 现有 `create_input()` / `submit_input_answer()` 事实链，把待输入项写入 `agent_inputs`，投影 `workflow.input.required`，并在用户回答后恢复 run 到 `running` 继续执行。
- Validate 恢复执行后会把已回答的 `practice_topic` 作为 fallback query，直接继续调用 `retrieve_knowledge()`，不再把这类请求终止成失败。
- 新增 `backend/tests/test_agent_validate_worker.py`，并更新 `backend/tests/test_agent_validate_workflow.py`，覆盖缺主题进入 waiting、时间线 `workflow.pending_input` 展示，以及用户回答后从 checkpoint 恢复检索并产出 practice artifact。
- 同步更新 `implementation/routing-context-memory.md`、`implementation/rag-and-tools.md`、`architecture/workflow-branches.md` 与任务单中的 `MEM-005` 状态、代码锚点和剩余缺口。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_validate_workflow.py tests/test_agent_validate_worker.py tests/test_agent_worker_waiting.py tests/test_agent_timeline_service.py -q` 通过。
- `cd backend && python3 -m py_compile app/modules/agent/workflows/validate.py tests/test_agent_validate_workflow.py tests/test_agent_validate_worker.py` 通过。
- `git diff --check` 通过。

### 提交信息

`让 Validate 在缺主题时进入澄清并可恢复执行`

## 2026-07-26：让 Validate 继承知识点与难度过滤条件

### 目标

继续推进任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `MEM-005`，
让 Validate 不只根据主题别名拼 query，还能把 snapshot 中的知识点 ID、难度约束和排除题参数继续下发到检索层，进一步缩小“讲解后出题”的候选范围。

### 实现

- 在 `backend/app/modules/agent/turn_understanding.py` 中补充确定性约束抽取，支持从“难一点 / 简单点 / 难度适中”这类输入生成 `difficulty:hard|easy|medium`，并顺手把“出一道题”纳入 practice 意图识别。
- 在 `backend/app/modules/agent/memory_selector.py` 扩展 `PracticeBundle`，新增 `difficulty`、`knowledge_point_ids` 和 `build_practice_filters()`，把 snapshot 的 topic、aliases 和约束进一步转换成 Validate 可直接消费的结构化过滤条件。
- 在 `backend/app/modules/agent/workflows/validate.py` 的 `_question_discovery_node()` 中继续下发 `knowledge_point_ids`、`filters` 与 `exclude_entity_ids` 给 `retrieve_knowledge()`，不再只靠自由文本 query 收窄候选。
- 在 `backend/app/modules/agent/tools/retrieve_knowledge.py`、`backend/app/modules/retrieval/service.py` 与 `backend/app/modules/retrieval/search_engine.py` 中补齐知识点过滤、difficulty 过滤和排除实体 ID 的参数透传，让 Qdrant filter、MySQL sparse 条件和公开活动元数据保持一致。
- 新增 `backend/tests/test_agent_turn_understanding.py`，并扩充 `backend/tests/test_agent_memory_selector.py`、`backend/tests/test_agent_validate_workflow.py`、`backend/tests/test_retrieval_service.py`，覆盖约束抽取、PracticeBundle 组装、Validate 检索参数透传，以及 Qdrant / sparse 过滤维度对齐。
- 同步更新 `implementation/routing-context-memory.md`、`implementation/rag-and-tools.md`、`architecture/workflow-branches.md` 与任务单中的 `MEM-003` / `MEM-004` / `MEM-005` 状态、代码锚点和剩余缺口。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_turn_understanding.py tests/test_agent_memory_selector.py tests/test_agent_validate_workflow.py tests/test_retrieval_service.py tests/test_agent_retrieve_activity.py tests/test_agent_conversation_workflow.py tests/test_agent_context_builder.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`让 Validate 继承知识点与难度过滤条件`

## 2026-07-26：让 Validate 消费记忆快照 Bundle 并停止静默默认出题

### 目标

推进任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `MEM-004` 和 `MEM-005` 的第一阶段，
让 Validate 不再只收到 `memory_snapshot_id`，而是真正从 snapshot 组装 `PracticeBundle`，用当前主题和 aliases 生成题目检索 query，并去掉没有主题时的静默默认出题。

### 实现

- 新增 `backend/app/modules/agent/memory_selector.py`，定义 `TopicBundle` / `PracticeBundle`，并在 `load_practice_bundle()` 中按 `run_id + user_id` 读取 `agent_memory_snapshots`、选中的 `agent_memory_snapshot_items` 与 `selection_metadata_json`，组装主题、aliases、约束和 selected artifacts。
- 在 `backend/app/modules/agent/turn_understanding.py` 为 `TopicEntity` 增加 `aliases`，保证“二分查找 / 折半查找”这类主题别名能够进入 snapshot，并被后续 bundle 消费。
- 在 `backend/app/modules/agent/workflows/validate.py` 中装载 `PracticeBundle`，优先用 bundle topic 填充 `weak_areas` / `recent_topics`，再通过 `build_practice_query()` 生成题目检索 query；若既没有 topic 也没有 fallback terms，则直接失败，不再静默默认“数据结构/操作系统”。
- 新增 `backend/tests/test_agent_memory_selector.py`，并扩充 `backend/tests/test_agent_validate_workflow.py`，覆盖 snapshot topic aliases、selected artifacts、Validate 使用 bundle topic 查询，以及缺少主题时不会继续随机检索的回归场景。
- 同步更新 `implementation/routing-context-memory.md`、`implementation/rag-and-tools.md`、`architecture/workflow-branches.md` 与任务单中的 `MEM-003` / `MEM-004` / `MEM-005` 状态、代码锚点和剩余缺口。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_memory_selector.py tests/test_agent_validate_workflow.py tests/test_agent_conversation_workflow.py tests/test_agent_context_builder.py tests/test_agent_router_runtime.py tests/test_agent_retrieve_activity.py -q` 通过。
- `python3 -m py_compile backend/app/modules/agent/memory_selector.py backend/app/modules/agent/workflows/validate.py backend/app/modules/agent/turn_understanding.py` 通过。
- `git diff --check` 通过。

### 提交信息

`让 Validate 消费记忆快照 Bundle 并停止静默默认出题`

## 2026-07-26：打通 TurnUnderstanding、独立请求与 snapshot 传递

### 目标

推进任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `MEM-003` 的第一阶段，
让 conversation run 能在 Router 前读取线程热状态、生成确定性 `TurnUnderstanding`、创建 snapshot，并把 `standalone_request` 与 `memory_snapshot_id` 传给 child run。

### 实现

- 在 `backend/app/modules/agent/context_builder.py` 为 `AgentRunContext` 增加 `active_topic`、`memory_state_version`、`standalone_request` 和 `memory_snapshot_id`，并在 `ThreadContextBuilder.build()` 中读取 `agent_thread_memory_states`。
- 新增 `backend/app/modules/agent/turn_understanding.py`，用确定性规则把 `context_refs` 或线程 `active_topic` 补全为 `TurnUnderstanding`；对“给我出道题”这类短句可生成独立请求，例如“给用户出一道关于二分查找的练习题”。
- 在 `backend/app/modules/agent/workflows/conversation.py` 中先创建 `agent_memory_snapshots` / `agent_memory_snapshot_items`，再把 `standalone_request` 交给 Router；child run 的 `input_message` 和 metadata 也同步继承 `standalone_request`、`active_topic` 与 `memory_snapshot_id`。
- 扩充 `backend/tests/test_agent_context_builder.py` 与 `backend/tests/test_agent_conversation_workflow.py`，覆盖 Router 前读取热状态，以及 Validate follow-up 场景下 snapshot 和独立请求透传到 child run。
- 同步更新 `implementation/routing-context-memory.md`、`architecture/workflow-branches.md` 与任务单中的 `MEM-003` 状态、代码锚点和剩余未完成项。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_conversation_workflow.py tests/test_agent_context_builder.py tests/test_agent_router_runtime.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`打通 Agent 独立请求与记忆快照主链`

## 2026-07-26：落地 Agent 分层记忆的首批契约与基础表

### 目标

推进任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `MEM-001` 和 `MEM-002`，
先把分层记忆的稳定命名契约、ORM 基础表和 Alembic 前向迁移落库，为后续 `MEM-003` 之后的 selector / projector 实现提供结构底座。

### 实现

- 新增 `backend/app/modules/agent/memory_contracts.py`，定义 `MemoryPartition`、`MemoryNeed` 和 `MEMORY_NEED_PARTITIONS`，把记忆分区与能力标签固定为 workflow-neutral 的稳定契约。
- 在 `backend/app/modules/agent/models.py` 增加 `AgentThreadMemoryState`、`AgentMemoryEvent`、`AgentMemorySnapshot`、`AgentMemorySnapshotItem`、`AgentMemoryUpdateOutbox`、`UserLearningMastery`、`AgentConversationSummary`、`AgentMemoryItem` 八张基础表的 ORM 模型。
- 新增 Alembic 迁移 `backend/alembic/versions/20260726_agent_memory_foundation.py`，创建上述记忆表及其唯一约束、索引和外键；同步更新 `backend/tests/test_migrations.py` 的 head 断言，并新增迁移 DDL 回归测试。
- 新增 `backend/tests/test_agent_memory_contracts.py`，验证分区全集、能力标签全集，以及能力标签不混入 explain / validate / grade / plan 这类 workflow 名称。
- 同步更新 `implementation/routing-context-memory.md`、`implementation/database-migrations.md` 与任务单中的 `MEM-001` / `MEM-002` 状态和代码锚点。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_memory_contracts.py tests/test_migrations.py -q` 通过。
- `python3 -m py_compile backend/app/modules/agent/models.py backend/app/modules/agent/memory_contracts.py backend/alembic/versions/20260726_agent_memory_foundation.py` 通过。
- `git diff --check` 通过。

### 提交信息

`落地 Agent 分层记忆契约与基础表`
