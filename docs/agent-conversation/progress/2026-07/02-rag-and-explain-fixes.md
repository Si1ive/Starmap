# 2026-07 RAG、Explain 与故障修复进展

## 2026-07-26：补齐二分查找题进入 Validate 候选集的整体验收

### 目标

完成未来任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中问题 5 的剩余验收，
确认 `RAG-001 + RAG-002` 修复后，真实二分查找题能够穿过来源回填、Agent DTO 和 Validate 资格门，进入候选集。

### 实现

- 扩充 `backend/tests/test_agent_validate_workflow.py`，新增 `test_validate_binary_search_question_survives_retrieval_dto_and_gate`，从 `load_learning_evidence -> question_discovery -> question_gate -> composition_gate` 真实执行 Validate 的检索与筛选主链。
- 测试中使用 `RetrievalResult.to_dict()` 构造二分查找题的底层检索结果，再通过真实 `retrieve_knowledge()` 工具归一化，校验 `source.filename`、`question_meta.paper_name`、题目审核状态和实体类型都能进入 `candidates`、`valid_questions` 与最终 `composition`。
- 同步更新 `implementation/rag-and-tools.md` 与任务单，把问题 5 状态改为已完成，并记录新的验收入口与验证命令。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_validate_workflow.py tests/test_agent_retrieve_activity.py tests/test_retrieval_service.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`补齐二分查找题进入 Validate 候选集的验收`

## 2026-07-26：补齐 Explain 无资料回退的端到端验收

### 目标

完成未来任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `EXP-001` 的最终验收，
确认 Explain 在零命中和检索异常两条无资料路径下都能通过 worker 持久化链落库，并在刷新后恢复最终正文与空引用。

### 实现

- 新增 `backend/tests/test_agent_explain_worker.py`，真实执行 `AgentWorker.process_run()`，覆盖零命中与检索异常两条回退路径在 completed 分支中的 Artifact 持久化、`message.completed` 投影和线程刷新恢复。
- 测试中 patch `RetrievalService.search_with_outline_expansion()` 而不是直接替换 `retrieve_knowledge()`，保留 `tool.called` / `tool.result` 事件链，顺带校验公开活动卡片在时间线中的 detail、status 与 artifact 引用都符合预期。
- 同步更新 `implementation/rag-and-tools.md`、`implementation/events-timeline-errors.md` 与任务单 `EXP-001` 状态，补齐 worker、timeline 和新测试文件的代码锚点。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_explain_worker.py tests/test_agent_explain_workflow.py tests/test_agent_retrieve_activity.py tests/test_agent_timeline_service.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`补齐 Explain 无资料回退的端到端验收`

## 2026-07-25：固化 Explain 无资料时的 fallback 语义

### 目标

推进未来任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `EXP-001` 的代码整改，
让 Explain 在零命中与检索异常两种无资料场景下都能继续回答，同时不给出伪造引用。

### 实现

- 在 `backend/app/modules/agent/workflows/explain.py` 增加 `_fallback_evidence_text()`，按 `retrieval_outcome=empty|error` 生成不同 fallback 文案。
- 在 `_evidence_loop_node()` 中记录 `retrieval_outcome`，让 `_evidence_gate_node()` 区分“没有检索到相关文档”和“暂时无法检索相关文档”两类原因，但两者都继续进入 `generate_explanation`。
- 在 `_generate_explanation_node()` 中对无资料场景强制清空 `citations`，避免模型把通用知识回答伪装成有来源答案。
- 扩充 `backend/tests/test_agent_explain_workflow.py`，覆盖零命中、检索异常区分和无资料引用清理；同步更新 `implementation/rag-and-tools.md`、`architecture/workflow-branches.md` 与未来任务单 `EXP-001` 的状态、代码锚点和剩余验收项。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_explain_workflow.py tests/test_agent_retrieve_activity.py tests/test_agent_timeline_service.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`固化 Explain 无资料时的回退回答`

## 2026-07-25：折叠检索重试的公开活动卡片

### 目标

完成未来任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `ACT-001` 的实现，
让同一逻辑检索的多次 attempt 在后台完整保留，同时用户端只看到一个持续更新的检索活动卡片。

### 实现

- 在 `backend/app/modules/agent/tools/retrieve_knowledge.py` 增加稳定 `logical_activity_id` 计算和 `_next_attempt_number()`，按 run/query/scope/entity_type 复用公开 `activity_id`，并为每次真实调用保留独立 `attempt_id`、`attempt_no`。
- 保持零命中和异常的公开提示语义不变，但在后台 run 事件中额外记录失败 attempt 的原始错误；前端与时间线继续按 `activity_id` 聚合，因此重试只会更新同一张活动卡片。
- 扩充 `backend/tests/test_agent_retrieve_activity.py`，覆盖同一 query 的重试会复用逻辑活动 ID；新增 `backend/tests/test_agent_timeline_service.py::test_timeline_merges_retry_attempts_into_single_public_activity`，覆盖线程时间线对多次 attempt 的单卡片归并。
- 同步更新 `implementation/rag-and-tools.md`、`architecture/workflow-branches.md` 与未来任务单 `ACT-001` 的状态、代码锚点和验证记录。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_retrieve_activity.py tests/test_agent_timeline_service.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`折叠 Agent 检索重试的公开活动`

## 2026-07-25：统一 Agent 检索结果 DTO 并修正 Validate 资格门

### 目标

完成未来任务单 `tasks/2026-07-26-rag-explain-memory-remediation.md` 中 `RAG-002` 的代码整改，
把题目/知识点检索结果收敛为稳定 DTO，并让 Explain、Validate 消费真实实体元数据而不是猜测字段。

### 实现

- 在 `backend/app/modules/retrieval/search_engine.py` 扩展 `RetrievalResult`，统一输出 `entity`、`source`、`question_meta`、`knowledge_point_meta`、学科章节和正文字段，并在 `hydrate_results()` 中从 `questions` / `knowledge_points` 补齐标题、审核状态和元数据。
- 在 `backend/app/modules/agent/tools/retrieve_knowledge.py` 新增 Agent 侧归一化与排序逻辑，删除旧的 `id/title/content/source_type` 猜测映射；Explain 混合结果默认把知识点排在题目前，Validate 继续强制题目检索。
- 在 `backend/app/modules/agent/workflows/explain.py` 改用新 DTO 的 `entity_title`、`content_text` 和 `source` 组织证据；在 `backend/app/modules/agent/workflows/validate.py` 改用 `question_meta` 与实体审核/状态字段做资格门和组合门统计。
- 新增 `backend/tests/test_agent_validate_workflow.py`，并扩充 `backend/tests/test_retrieval_service.py`、`backend/tests/test_agent_retrieve_activity.py`，覆盖题目/知识点元数据回传、Explain 混合结果排序以及 Validate 不再依赖 `source_type` 的回归场景。
- 同步更新 `implementation/rag-and-tools.md`、`architecture/workflow-branches.md` 与任务单中的 `RAG-002` 状态、代码锚点和验证记录。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_retrieval_service.py tests/test_agent_retrieve_activity.py tests/test_agent_validate_workflow.py tests/test_agent_explain_workflow.py tests/test_relation_expansion.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`统一 Agent 检索结果 DTO 并修正 Validate 资格门`

## 2026-07-25：修复检索来源信息回填

### 目标

修复 `RetrievalSearchEngine.hydrate_results()` 在 Explain/Validate 命中真实文档后仍访问不存在的
`Document.filename` 字段，导致检索结果在 MySQL 回填阶段失败的问题。

### 实现

- 在 `backend/app/modules/retrieval/search_engine.py` 增加 `_document_source_name()`，统一使用 `source_label -> title -> None` 回退链生成来源展示名。
- 保持 `RetrievalResult` 现有 `source.filename` 对外字段不变，仅修正其内部填充值，避免在 `RAG-002` 前扩大接口改动面。
- 扩充 `backend/tests/test_retrieval_service.py`，覆盖展示来源优先级、标题回退和没有来源文档三种情况。
- 同步更新 `implementation/rag-and-tools.md` 与任务单 `RAG-001` 状态、代码锚点和验证说明。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_retrieval_service.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`修复 Agent 检索来源信息回填`

## 2026-07-25：修复工作流最终 Artifact 契约

### 目标

修复 Explain 等 workflow 在 `render_artifact` 节点已生成正文但最终因 `NodeResult.success()` 不接受
`artifact` 参数而失败的问题，并补一条真正跑到最终渲染节点的回归测试。

### 实现

- 扩展 `backend/app/modules/agent/workflows/contracts.py` 中 `NodeResult.success()` 的签名，使其可统一承载 `output`、`next_node` 和 `artifact`。
- 保持 Explain / Validate / Grade / Plan 现有 render 节点调用方式不变，直接复用统一工厂方法传递最终 Artifact。
- 在 `backend/tests/test_agent_workflow_engine.py` 新增 explain workflow 回归测试，真实执行 `load_scope -> ... -> render_artifact -> completed`，确认最终 Artifact 不再丢失。
- 同步更新任务单 `FLOW-001` 状态和 `implementation/events-timeline-errors.md` 中的产物持久化说明与测试锚点。

### 验证

- `cd backend && ./venv/bin/pytest tests/test_agent_workflow_engine.py tests/test_agent_explain_workflow.py -q` 通过。
- `git diff --check` 通过。

### 提交信息

`修复 Agent 工作流最终 Artifact 契约`
