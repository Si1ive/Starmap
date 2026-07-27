# 2026-07 记忆基础、可信事实与 Outbox 进展

## 2026-07-27：让 Explain 消费 snapshot 冻结摘要

- 目标：补齐历史摘要的首个 child workflow 消费者，保证 Explain 使用父 Run snapshot 的内容副本而不是执行时的最新摘要。
- 实现：`backend/app/modules/agent/memory_selector.py::load_conversation_bundle`（L1055-L1224）要求唯一 snapshot item 并复核源摘要 user/thread/version 后读取冻结正文；版本不符或重复条目不注入摘要。`_conversation_inputs`（L50-L66）把摘要交给 `ExplanationDeps`，模型通过 `_controlled_context`（L57-L73）将其作为不可信数据。
- 测试：Memory selector、Explain workflow/runtime/Worker 聚焦回归 23 项通过；全部 Agent 回归 195 passed、75 warnings，Python 编译与 `git diff --check` 通过。
- 提交信息：`让 Explain 消费 snapshot 冻结摘要`

## 2026-07-27：让 Router 与普通回答消费冻结历史摘要

- 目标：继续 `MEM-007`，把已生成摘要接入通用 conversation 上下文，同时保证近期原文优先、范围不重叠、预算可控和 snapshot 可复现。
- 实现：`backend/app/modules/agent/context_builder.py::ThreadContextBuilder._load_conversation_summary`（L533-L569）只选同用户/线程、唯一 active、早于近期原文且适配剩余预算的摘要；`backend/app/modules/agent/turn_understanding.py::ensure_turn_memory_snapshot`（L405-L515）冻结正文副本、来源 ID、版本和 sequence 范围；`RouterDeps` / `DirectAnswerDeps` 只把正文放入标记为不可信数据的动态 instructions。child metadata 只携带摘要 ID，公开 SSE 不携带正文。
- 测试：`backend/tests/test_agent_context_builder.py::test_context_selects_only_active_summary_that_fits_remaining_budget`（L319-L384）覆盖预算命中/丢弃和 snapshot item；Answer/Router runtime 回归覆盖依赖透传与不把摘要当授权。
- 验证：全部 Agent 回归通过（195 passed，75 warnings）；Python 编译与 `git diff --check` 通过。
- 提交信息：`让通用对话消费冻结历史摘要`

## 2026-07-27：按连续消息区间增量生成历史摘要

- 目标：推进 `MEM-007` 的首个可独立验证单元，在不阻塞成功 Run、不覆盖原消息的前提下，把最近 12 个用户轮次之前的历史按稳定 sequence 区间滚动压缩。
- 实现：`backend/app/modules/agent/conversation_summary.py::enqueue_conversation_summary_maintenance`（L37-L69）让每个成功 Run 同事务幂等写摘要维护 Outbox；`ConversationSummaryMaintainer.maintain`（L90-L211）按 run/thread/user 复核作用域，只选择活跃摘要末尾到近期窗口之前最多 24 条 visible completed user/assistant 消息，模型返回后锁线程复核活跃版本，生成新版本后以 `superseded_by_id` 失效旧摘要。`backend/app/modules/agent/model_runtime/conversation_summary.py::ConversationSummaryRuntime.summarize`（L65-L117）使用触发 Run 绑定模型，把旧摘要和消息都按不可信数据处理。
- 异步边界：`backend/app/modules/agent/memory_outbox.py::MemoryOutboxConsumer.process_claimed`（L202-L276）识别摘要任务并在 SAVEPOINT 内调用 maintainer；模型或持久化失败只让 Outbox 延迟重试，原 completed Run、原始消息和公开 SSE 均不改变。
- 测试：`backend/tests/test_agent_conversation_summary.py`（L169-L436）覆盖近期窗口、隐藏/失败/system 消息排除、重放幂等、增量合并与 supersede、并发版本变化重试、跨用户/线程隔离和失败隔离；`backend/tests/test_agent_conversation_summary_runtime.py`（L42-L86）覆盖结构化输出与触发 Run 模型配置；Explain Worker 回归证明完成链真实入队。
- 验证：全部 Agent 回归通过（192 passed，75 warnings）；Python 编译通过，`git diff --check` 通过。
- 提交信息：`按连续消息区间增量生成对话摘要`

## 2026-07-27：让 Explain 消费 ConversationBundle 冻结上下文

- 目标：完成 `MEM-004`，让 Explain 真正消费 Router 前按权限和 Token 预算筛选并冻结到 snapshot 的消息、Artifact、主题与引用，移除无实际约束的全学科固定 scope。
- 实现：`backend/app/modules/agent/memory_selector.py::load_conversation_bundle`（当前 L1055-L1224）按 snapshot ID 复现同用户/线程的上下文和首次 query；`_evidence_loop_node`（当前 L69-L206）与 `_generate_explanation_node`（当前 L236-L289）向规划/生成模型传入同一 history。
- 测试：`backend/tests/test_agent_memory_selector.py::test_load_conversation_bundle_replays_only_snapshot_selected_visible_context`（当前 L341-L526）覆盖冻结选择、摘要副本、版本/重复保护、hidden 丢弃、Artifact 和 aliases query；`backend/tests/test_agent_explain_workflow.py::test_explain_uses_conversation_bundle_history_and_frozen_topic_query`（当前 L145-L203）覆盖冻结检索与摘要依赖；`backend/tests/test_agent_explain_worker.py::test_explain_worker_replays_snapshot_selected_history`（L314-L441）覆盖 Worker 端到端重放。
- 验证：全部 Agent 回归通过（185 passed，75 warnings）；Python 编译和 `git diff --check` 通过，旧状态/旧锚点扫描未发现残留。
- 提交信息：`让 Explain 消费冻结的 ConversationBundle`

## 2026-07-27：让 Grade 以 EvaluationBundle 产生真实客观题证据

- 目标：推进 `MEM-004` / `MEM-006`，删除 Grade 的固定反馈和伪 attempt，让真实客观题、标准答案与显式作答形成可审计掌握度证据。
- 实现：`backend/app/modules/agent/memory_selector.py::load_evaluation_bundle`（L502-L633）按 run/user/thread 校验 snapshot，要求唯一 question 引用并重读 active、未拒绝、答案来源可信的题面；`backend/app/modules/agent/workflows/grade.py::_load_attempt_snapshot_node`（L40-L78）装载 bundle，`_objective_grade_node`（L81-L129）只对 choice/fill/judge 确定性比较并生成 verdict/score/error type，`_render_artifact_node`（L191-L218）交给既有事实投影。主观题或不可信/歧义输入在 Artifact 前失败。
- 测试：`backend/tests/test_agent_memory_selector.py`（L189-L337）覆盖真实题面装载、Artifact 来源、跨用户和多题歧义；`backend/tests/test_agent_grade_worker.py`（L153-L243）覆盖正确/错误 verdict 到 `grade_result_confirmed` / `user_learning_mastery`、主观题零副作用拒绝与判断题否定表达；`test_grade_run_without_snapshot_fails_without_touching_mastery`（L398-L415）覆盖缺快照守卫。
- 验证：全部 Agent 回归通过（182 passed，75 warnings）；Python 编译、`git diff --check` 与旧状态/旧锚点扫描通过。
- 提交信息：`让 Grade 消费真实 EvaluationBundle`

## 2026-07-27：让 Plan 消费真实 PlanningBundle

- 目标：推进 `MEM-004`，移除 Plan 固定注入的学科、强弱项和 60 分钟目标，只允许真实记忆产生审批草案。
- 实现：`backend/app/modules/agent/memory_selector.py::load_planning_bundle`（L303-L499）按用户/线程校验 Run/snapshot，选择当前主题、最新 active 已批准 goals 和按统一策略衰减后的有效薄弱点，按标题去重并冻结题名/别名、分数与证据版本；`backend/app/modules/agent/workflows/plan.py::_aggregate_learning_evidence_node`（L26-L49）接入 bundle，targets 为空时由前置门失败且不创建审批。
- 测试：`backend/tests/test_agent_memory_selector.py::test_load_planning_bundle_uses_approved_goals_and_real_weak_mastery`（L66-L155）覆盖用户隔离、批准目标、周期和真实薄弱点；`backend/tests/test_agent_plan_worker.py::test_plan_without_real_memory_fails_before_creating_approval`（L142-L156）与 `test_approved_plan_resumes_and_creates_artifact`（L219-L278）覆盖无证据零审批和真实目标 Artifact。
- 验证：Memory selector、Plan Worker、Memory Outbox、Validate 与 Conversation 组合回归通过（36 passed，53 warnings）；Python 编译与 `git diff --check` 通过。
- 提交信息：`让 Plan 只消费真实 PlanningBundle`

## 2026-07-27：修复运行库缺失 Memory Outbox 真表

- 目标：消除 Worker 扫描 `agent_memory_update_outbox` 时的 MySQL 1146，并让同类结构漂移在 Worker 启动前失败。
- 根因与修复：代码 head 为 `20260726_memory_outbox_unique`，实际 `starmap` 仅到 `20260725_agent_activity`；执行 `alembic upgrade head` 后创建八张记忆表并添加 `(run_id,event_type)` 唯一约束。`backend/app/modules/operations/schema_guard.py::verify_database_schema`（L43-L191）进一步校验全部记忆真表和 `uk_agent_memory_outbox_run_event`，不再只相信 revision。
- 验证：真实数据库 current=head、真表/两列复合索引存在；回滚事务重放 `MemoryOutboxStore.scan_due` 成功且 `due_count=0`；真实 schema guard 通过。迁移、Outbox 与 guard 回归共 26 项通过，`git diff --check` 通过。
- 故障单：`incidents/2026-07-27-memory-outbox-table-missing.md`。
- 提交信息：`在启动前阻断 Memory Outbox 结构漂移`

## 2026-07-26：仅在真实歧义时调用结构化指代模型

- 目标：完成 `MEM-003`，让裸词“这个”和最新 practice 多题等真正歧义进入受约束模型，同时保证确定性单题、显式引用和无候选场景不增加调用。
- 实现：`backend/app/modules/agent/turn_understanding.py::build_ambiguous_referent_candidates`（L187-L264）构造候选，`hydrate_referent_candidate_labels`（L267-L301）用 active 题面水合并过滤失效题；`backend/app/modules/agent/model_runtime/referent.py::ReferentRuntime.resolve`（L79-L148）只允许选择候选键，低置信度降级 unresolved；`backend/app/modules/agent/workflows/conversation.py::_route_node`（L50-L155）在 snapshot 前按需调用并记录 `reference_resolution`。总调用预算提高到 3，覆盖可选消歧、Router 和 direct answer。
- 安全边界：题目 ID 不作为语义证据，候选缺少真实题面时禁止调用；Artifact 摘要和题面均按不可信数据处理；模型不能生成实体 ID，非法键使本轮失败而不是写入 snapshot。
- 测试：`backend/tests/test_agent_referent_runtime.py`（L1-L128）覆盖白名单、伪造键、低置信度和缺标签；`backend/tests/test_agent_conversation_workflow.py::test_ambiguous_previous_question_uses_structured_resolver_before_snapshot`（L569-L680）覆盖题面水合、按需调用、snapshot 审计和三次调用预算。
- 验证：指代、理解、上下文、conversation、memory selector 与 Router 组合回归通过（49 passed，47 warnings）；Python 编译与 `git diff --check` 通过。
- 提交信息：`仅在真实歧义时调用结构化指代模型`

## 2026-07-26：让上一道题绑定结构化 Artifact 引用

- 目标：继续推进 `MEM-003`，让“上一道题 / 这道题”在无显式引用时使用可信 question ID，同时禁止根据 Artifact 标题或摘要猜题。
- 实现：`backend/app/modules/agent/context_builder.py::ThreadContextBuilder._load_artifacts`（L395-L463）调用 `_extract_artifact_reference_entities`（L713-L746），只从 practice `content.question_ids` 生成带 Artifact ID 的 question 引用；`backend/app/modules/agent/turn_understanding.py::_resolve_question_artifact_reference`（L155-L184）只解析最新 practice 的唯一题目，多题或缺 ID 保持歧义且不回退旧产物，结果由 `build_turn_understanding`（L347-L403）进入不可变 snapshot。
- 测试：`backend/tests/test_agent_context_builder.py::test_context_exposes_structured_question_references_from_practice_artifact`（L521-L576）覆盖真实持久化结构读取；`backend/tests/test_agent_turn_understanding.py::test_build_turn_understanding_resolves_previous_single_question_from_latest_artifact`（L104-L131）及 L133-L179 的三个边界测试覆盖单题解析、多题歧义、不回退和不读摘要。
- 验证：上下文、理解、conversation snapshot 与 memory selector 组合回归通过（30 passed，43 warnings）；Python 编译与 `git diff --check` 通过。
- 提交信息：`让上一道题绑定结构化 Artifact 引用`

## 2026-07-26：启用可信事实异步派生

- 目标：让 Memory Outbox 产生真实长期记忆落点并进入后台循环，而不是空消费任务。
- 实现：`memory_item_projection.py::project_trusted_memory_event`（L154-L166）按事实分派，线程主题与批准计划分别物化 `topic_context` / `learning_goal`；`AgentWorker.start`（L370-L394）在 Run 批次后消费记忆任务，异常仍只重试 Outbox。
- 验证：记忆/迁移组 32 项、workflow/Worker 组 22 项通过；Python 编译与 `git diff --check` 通过。
- 提交信息：`启用可信事实异步派生`

## 2026-07-26：建立 Memory Outbox 消费状态机

- 目标：让记忆任务具备可竞争认领、崩溃恢复、延迟重试和失败隔离能力。
- 实现：新增 `backend/app/modules/agent/memory_outbox.py::MemoryOutboxStore`（当前 L30-L177）与 `MemoryOutboxConsumer`（当前 L180-L308）；processing 复用 `scheduled_at` 作为租约截止，状态更新校验 worker 所有权，投影异常由 SAVEPOINT 隔离，耗尽预算进入 failed。
- 边界：该提交的默认 projector 只验证可信事实且未接入 Agent Worker；实际派生与运行时启用由后续 `启用可信事实异步派生` 提交完成。
- 验证：`cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_memory_outbox.py` 通过（4 passed）；Python 编译与 `git diff --check` 通过。
- 提交信息：`建立 Memory Outbox 消费状态机`

## 2026-07-26：同事务生产 Memory Outbox 任务

### 目标

让五类可信记忆事实在同一事务可靠产生 pending Memory Outbox，并让已有事实重放能够补建迁移前缺失任务；并发重复不能污染成功 Run。

### 实现

- 新增 `backend/app/modules/agent/memory_projection.py::_ensure_memory_update_outbox`（L27-L64）：按 Run/事实类型查询，写入只包含 memory event ID 和 fact type 的 pending 任务。
- 五类事实投影在新事件 flush 后调用 ensure；发现已有事件时不再直接返回，而是补建缺失 Outbox。
- 使用嵌套事务 SAVEPOINT 捕获数据库唯一键冲突，只回滚并发重复任务，不反向破坏外层 Run、Artifact 和事实事务。
- 为 conversation、Explain、Validate、Plan 和投影测试补齐 Memory Outbox 测试表；`backend/tests/test_agent_memory_projection.py::test_topic_confirmed_projection_is_idempotent_and_skips_inherited_topic`（L133-L208）覆盖新建、重放和删除后补建。

### 验证

- `cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_memory_projection.py tests/test_agent_conversation_workflow.py tests/test_agent_explain_worker.py tests/test_agent_plan_worker.py tests/test_agent_validate_worker.py` 通过（24 passed）。
- `git diff --check` 通过。

### 提交信息

`同事务生产 Memory Outbox 任务`

## 2026-07-26：冻结 Memory Outbox 数据库幂等键

### 目标

在接入 Memory Outbox 生产者前先建立数据库级并发幂等约束，避免同一 Run 的同类事实在并发重放时产生重复异步任务。

### 实现

- 在 `backend/app/modules/agent/models.py::AgentMemoryUpdateOutbox`（L612-L650）增加 `(run_id, event_type)` 唯一约束 `uk_agent_memory_outbox_run_event`。
- 新增前向迁移 `backend/alembic/versions/20260726_memory_outbox_unique.py::upgrade`（L18-L25），并提供 `downgrade`（L28-L34）；当前表尚无生产者，因此升级不会遇到历史重复任务。
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

- 在 `backend/app/modules/agent/workflows/plan.py::_render_plan_result_node`（L198-L221）把已通过守卫的 approval ID 写入 Plan Artifact，使事实投影可以回查真实批准来源。
- 扩展 `backend/app/modules/agent/memory_projection.py::project_completed_run_facts`（L125-L140），由 `_record_plan_confirmed`（L185-L251）校验 approval ID、同 Run 归属和数据库 approved 状态，再按 approval ID 幂等写用户级 `plan_confirmed`。
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
- 在 `backend/app/modules/agent/workflows/plan.py::_apply_plan_change_node`（L171-L195）增加纵深守卫，从数据库重读 checkpoint 携带的 approval ID，只有状态为 approved 才应用草案；pending、rejected 或缺失均失败且不生成 Artifact。
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

- 在 `backend/app/modules/agent/memory_projection.py::project_completed_run_facts`（L125-L140）增加 explanation Artifact 分派，并由 `_record_explanation_artifact_created`（L143-L182）按 Run 幂等写线程级 `explanation_artifact_created`。
- 事件载荷只保留 `artifact_id` 与可选 `memory_snapshot_id`，正文、outline 和 citations 继续以 `agent_artifacts` 为唯一权威位置，不复制进长期事件或公开 SSE。
- 扩展 `backend/tests/test_agent_explain_worker.py::test_worker_persists_zero_hit_fallback_answer_without_citations`（当前 L134-L243），覆盖零命中 fallback 仍写事实、重放不重复、引用为空且 `user_learning_mastery` 不产生记录。
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

- 新增 `backend/app/modules/agent/memory_projection.py::project_topic_confirmed_fact`（L67-L122），仅接受 `source=context_ref` 的首个类型化主题，以 `topic_confirmed:{run_id}` 幂等写线程级事件，并记录 snapshot、状态版本和来源消息。
- 在 `backend/app/modules/agent/turn_understanding.py::ensure_turn_memory_snapshot`（L405-L515）创建或复用 snapshot 时调用主题投影；写入发生在 `_route_node` 的 Router 调用之前，继承自 `thread_memory` 的主题会无副作用跳过。
- 更新 `backend/tests/test_agent_conversation_workflow.py::test_model_configuration_failure_creates_visible_failed_message`（L761-L825），证明 Router 模型不可用时显式二分查找主题仍存在；`test_follow_up_validate_request_uses_active_topic_snapshot_for_child_run`（L487-L566）证明继承主题不新增确认事件。
- 新增 `backend/tests/test_agent_memory_projection.py::test_topic_confirmed_projection_is_idempotent_and_skips_inherited_topic`（L133-L208），覆盖同一 Run 重放、继承跳过与 Outbox 补建。

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

- 在 `backend/app/modules/agent/memory_projection.py::_record_grade_result_confirmed`（L308-L413）校验 Feedback Artifact 的结构化评分证据，按用户 + evidence ID 写 `grade_result_confirmed`，并按知识点增量更新 `user_learning_mastery`；重复知识点先去重，重放同一证据无副作用。
- 在 `backend/app/modules/agent/workflows/grade.py::_render_artifact_node`（当前 L191-L218）建立可选 `grading_evidence -> content.grading` 交接；该提交当时的 `_objective_grade_node` 尚不生产 verdict，因此固定反馈不会触发掌握度写入。2026-07-27 已由本卷顶部的 EvaluationBundle 提交补齐真实客观题证据生产者。
- 新增 `backend/tests/test_agent_memory_projection.py::test_grade_projection_updates_mastery_and_replays_idempotently`（L212-L281）等五个回归场景，覆盖增量公式、用户隔离、知识点去重、证据契约、缺证据跳过和 P1 worker 端到端无污染语义。
- 同步更新 `implementation/routing-context-memory.md`、`architecture/workflow-branches.md` 和任务单，明确本次只完成安全投影边界；真实题面、标准答案与评分证据生产者仍是后续 `EvaluationBundle` / Grade 接入范围。

### 验证


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
