# 2026-07 Validate 记忆消费闭环进展

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
