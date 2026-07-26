# RAG、Explain 与分层记忆整改计划

## 文档目的

本任务单用于持续追踪 `run_5c6c46d3` 暴露的检索、工作流产物、用户端活动投影问题，以及后续分层
长期记忆建设。它是待做任务的权威清单，不表示列出的代码修复已经完成；实施时按任务 ID 更新状态、
验证结果和对应提交，不依赖历史对话恢复上下文。

实施前置已在 2026-07-25 完成：`docs/agent-conversation/` 已从旧大文件拆分为 `architecture/`、
`implementation/`、`tasks/` 和 `progress/` 分卷，后续每个 Agent 提交直接更新最小相关分卷。

状态含义：`已定位` 表示根因已有证据但代码尚未修复；`待设计` 表示仍需冻结契约；`待实现` 表示
方案已明确；`已完成` 必须同时满足代码、迁移、测试、教学文档和提交要求。

## 用户问题覆盖矩阵

| 原问题 | 任务 ID | 当前结论 | 状态 | 完成条件 |
| --- | --- | --- | --- | --- |
| 1. 工具重试三次，用户端也展示三次 | ACT-001 | 已为同一逻辑检索复用稳定 `activity_id`，后台额外保留 `attempt_id` / `attempt_no`，时间线与前端按同一 ID 归并成单个活动 | 已完成 | 后台保留每次 attempt；用户端以稳定逻辑活动 ID 只展示一个持续更新的活动 |
| 2. Explain 无资料时由 LLM 回答 | EXP-001 | 已完成代码修复与 worker 级验收：零命中和检索异常均走不同 fallback 文案，最终 artifact、message 与空 citations 都能持久化并在刷新后恢复 | 已完成 | 正常零命中和检索异常均可按策略继续回答；无伪造引用；最终内容成功展示 |
| 3. LLM 已生成长回答但最终显示失败 | FLOW-001 | `NodeResult.success()` 已支持 `artifact`，Explain 渲染链已补最终节点回归测试 | 已完成 | Explain/Validate/Grade/Plan 均可创建 Artifact；失败回归测试覆盖最终节点 |
| 4. 题目和知识点看似走同一路检索 | RAG-002 | 已统一题目/知识点 DTO，Explain 混合结果优先知识点，Validate 改读 `question_meta` 与实体状态字段 | 已完成 | 统一类型化 DTO；Explain 与 Validate 使用明确实体类型、字段和用户可见名称 |
| 5. 二分查找题明明存在却未检索到 | RAG-001、RAG-002 | 已完成代码修复与整体验收：来源回填、DTO 和 Validate 资格门已经打通，真实二分查找题可进入 Validate 候选集 | 已完成 | 修复来源字段和 DTO；真实二分查找题通过混合检索进入 Validate 候选集 |

结论：五个问题均已登记，没有遗漏；其中 `ACT-001`、`EXP-001`、`FLOW-001`、`RAG-001 + RAG-002` 均已完成代码与验收闭环。

## `run_5c6c46d3` 已确认故障链

完整子 Run 为 `run_5c6c46d3111c495c831a`，父 conversation Run 为
`run_379058566cb4408892e3`。实际执行顺序如下：

```text
load_scope completed
  → retrieve_knowledge 连续执行三次
  → 每次均在命中后的文档信息回填处抛出 Document.filename 不存在
  → evidence_count=0
  → evidence_gate 允许继续
  → generate_explanation 成功生成完整二分查找正文
  → citation_gate 通过
  → render_artifact 调用 NodeResult.success(artifact=...)
  → TypeError
  → run.failed
  → 用户端未收到最终 Artifact，只显示回复生成失败
```

二分查找检索分层探测结果：

| 探测层 | 结果 | 证据 |
| --- | --- | --- |
| MySQL `questions` | 命中 | 题目 ID `7d600b0198a3425bbe202986885bc877` |
| MySQL `retrieval_segments` | 命中 | Segment ID `91b0a7f197d44ded848b4a58d6fe8e02` |
| MySQL 稀疏检索 | 命中 | 查询“二分查找”返回 1 条，分数 `1.0` |
| Qdrant 题目 Collection | 命中 | 排名第一，分数 `0.6684933` |
| MySQL 来源信息回填 | 失败 | `'Document' object has no attribute 'filename'` |
| Agent 工具字段转换 | 不兼容 | 底层返回 `entity_id/content_text/source`，工具读取 `id/content/source_type` |

## 当前代码锚点

| 执行阶段 | 文件 | 符号 | 代码范围 | 当前职责与问题 |
| --- | --- | --- | --- | --- |
| 工具活动创建 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `_logical_activity_id`、`_next_attempt_number`、`retrieve_knowledge` | L77-L227 | 已为同一逻辑检索生成稳定 `activity_id`，并在 `tool.called` 中追加 `attempt_id` / `attempt_no`，同时把 `knowledge_point_ids`、difficulty 和排除题参数公开到安全活动元数据，供后台保留每次 attempt |
| 工具结果与异常 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `_normalize_agent_result`、`_sort_agent_results`、`retrieve_knowledge` | L24-L74、L228-L337 | 已统一 Agent DTO，公开零命中和异常结果；Explain 混合检索默认把知识点排在题目前面；失败 attempt 的原始错误保留在后台事件中 |
| 用户活动归并 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._activity_views` | L506-L538 | 按 `activity_id` 聚合；不同 ID 必然生成不同活动 |
| 检索结果契约 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalResult.to_dict` | L20-L95 | 已统一输出 `entity`、`source`、`question_meta`、`knowledge_point_meta` 与学科章节字段，供 Agent 与检索调试共用 |
| Collection 路由 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalSearchEngine.get_collections` | L171-L181 | `knowledge_point` 和 `question` 分别进入不同 Qdrant Collection；空类型同时查两者 |
| 命中内容回填 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalSearchEngine.hydrate_results`、`RetrievalSearchEngine._document_source_name`、`RetrievalSearchEngine._load_knowledge_point_details`、`RetrievalSearchEngine._load_question_details`、`RetrievalSearchEngine._question_title` | L279-L447 | 已从 MySQL 同步补全文档来源、实体标题、审核状态和题目/知识点元数据，消除 `source_type` 猜测映射 |
| 无证据生成 | `backend/app/modules/agent/workflows/explain.py` | `_fallback_evidence_text`、`_evidence_loop_node`、`_evidence_gate_node`、`_generate_explanation_node` | L26-L261 | 无证据仍进入模型生成；零命中与检索异常会走不同 fallback 文案；无资料时强制清空 citations，避免伪造引用 |
| Explain 产物渲染 | `backend/app/modules/agent/workflows/explain.py` | `_render_artifact_node`、`_completed_node` | L279-L306 | 已通过统一 `artifact` 契约把成功正文挂回上下文并交给 worker 持久化 |
| Explain 持久化与刷新恢复 | `backend/app/modules/agent/worker.py`、`backend/app/modules/agent/timeline.py` | `AgentWorker.process_run`、`AgentTimelineService.get_timeline`、`AgentTimelineService._activity_views`、`AgentTimelineService.message_view` | `worker.py` L100-L251；`timeline.py` L320-L360、L399-L538、L554-L572 | worker 在 completed 分支创建 artifact、写 `message.completed` / `run.completed`；时间线刷新时按 root run 重建活动、artifact 和最终正文 |
| 节点结果契约 | `backend/app/modules/agent/workflows/contracts.py` | `NodeResult.success` | L27-L48 | 已支持 `artifact` 参数，render 节点可通过统一工厂方法把最终产物传给引擎与 worker |
| Validate 检索与首个记忆消费 | `backend/app/modules/agent/memory_selector.py`、`backend/app/modules/agent/workflows/validate.py` | `load_practice_bundle`、`build_practice_query`、`build_practice_filters`、`_question_is_eligible`、`_load_learning_evidence_node`、`_question_discovery_node`、`_question_gate_node`、`_composition_gate_node` | `memory_selector.py` L81-L193；`validate.py` L25-L149 | Validate 已开始按 `PracticeBundle` 消费 snapshot topic、aliases、difficulty、knowledge point IDs 和选中的 Artifact，并把它们转换成题目检索 query 与过滤条件；题目资格门与组合门继续读取真实 DTO。掌握度、真实排除集和澄清闭环仍待补齐 |
| 当前上下文构建 | `backend/app/modules/agent/context_builder.py` | `AgentRunContext`、`ThreadContextBuilder.build`、`_load_thread_memory_state` | L82-L121、L138-L256、L489-L501 | 已能选择近期消息、Artifact、待处理交互，并读取线程 `active_topic` / `memory_state_version`；仍未按 `MemoryNeed` 选择掌握度、摘要和排除集 |
| Router 与子 Run 交接 | `backend/app/modules/agent/workflows/conversation.py`、`backend/app/modules/agent/turn_understanding.py` | `_route_node`、`_child_context_metadata`、`_dispatch_workflow_node`、`build_turn_understanding`、`ensure_turn_memory_snapshot` | `conversation.py` L46-L260；`turn_understanding.py` L105-L227 | Router 已先生成 `TurnUnderstanding` 并创建 snapshot，再使用 `standalone_request` 路由；topic aliases、`memory_snapshot_id`、独立请求和 `difficulty:*` 约束都会传给 child run，Validate 已开始消费这些 snapshot 内容 |
| Run 最终持久化 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L150-L222 | 执行工作流并创建 Artifact/最终消息；未来在完成事务中写记忆更新 Outbox |

## 第一组：立即解除现有故障

### FLOW-001 修复工作流 Artifact 契约

- 状态：已完成（2026-07-25）。
- 已扩展 `NodeResult.success()`，接收并传递 `artifact`，Explain / Validate / Grade / Plan 现可继续复用统一工厂方法。
- 已补 `backend/tests/test_agent_workflow_engine.py::test_explain_workflow_keeps_artifact_through_render_and_completion`，真正执行 explain workflow 到 `render_artifact -> completed`，覆盖此前的 TypeError 回归点。
- 验证：`./venv/bin/pytest tests/test_agent_workflow_engine.py tests/test_agent_explain_workflow.py -q` 通过。

### RAG-001 修复命中后的来源信息回填

- 状态：已完成（2026-07-25）。
- 已使用当前 `Document.source_label` / `title` 契约替代不存在的 `filename`，空来源明确回退为 `None`。
- 已增加“Qdrant 命中且存在展示来源”和“只有标题或完全没有来源文档”的回填测试。
- 验证：`cd backend && ./venv/bin/pytest tests/test_retrieval_service.py -q` 通过。

### RAG-002 统一题目/知识点检索 DTO

- 状态：已完成（2026-07-25）。
- 已在 `RetrievalResult.to_dict()` 中统一输出 `entity`、`source`、`question_meta`、`knowledge_point_meta`、学科章节和正文字段，并在 `hydrate_results()` 阶段从 `questions` / `knowledge_points` 补齐标题、审核状态和题目元数据。
- 已删除 Agent 工具中的 `id/title/content/source_type` 猜测式映射，改为统一归一化 DTO；Explain 混合检索结果默认把知识点排在题目前面，Validate 继续强制 `entity_type="question"`。
- 已修改 Validate 资格门与组合门，改读 DTO 中真实的题目来源、审核状态、题型、难度和学科字段，不再依赖空 `source_type`。
- 验证：`cd backend && ./venv/bin/pytest tests/test_retrieval_service.py tests/test_agent_retrieve_activity.py tests/test_agent_validate_workflow.py tests/test_agent_explain_workflow.py tests/test_relation_expansion.py -q` 通过。

### RAG-001 + RAG-002 验收：二分查找题进入 Validate 候选集

- 状态：已完成（2026-07-26 完成整体验收）。
- 已新增 `backend/tests/test_agent_validate_workflow.py::test_validate_binary_search_question_survives_retrieval_dto_and_gate`，从 `load_learning_evidence -> question_discovery -> question_gate -> composition_gate` 真实走过 Validate 检索链。
- 测试使用 `RetrievalResult.to_dict()` 构造二分查找题的底层检索结果，再通过真实 `retrieve_knowledge()` 工具归一化为 Agent DTO，确认 `source.filename`、`question_meta.paper_name` 与题目实体状态都能穿过装配层进入 `candidates` 和 `valid_questions`。
- 同时校验 Validate 对二分查找的检索参数仍是 `query="二分查找"` 且 `entity_type="question"`，确保该题不会在混合检索装配、DTO 转换或资格门阶段再次丢失。
- 验证：`cd backend && ./venv/bin/pytest tests/test_agent_validate_workflow.py tests/test_agent_retrieve_activity.py tests/test_retrieval_service.py -q` 通过。

### ACT-001 折叠用户端工具重试

- 状态：已完成（2026-07-25）。
- 已在 `retrieve_knowledge()` 中按 run/query/scope/entity_type 生成稳定 `logical_activity_id`，并让公开 `activity_id` 复用该逻辑 ID；每次真实调用仍保留独立 `attempt_id` 与 `attempt_no`。
- 已保持 `tool.called` / `tool.result` 的公开提示语义不变：零命中仍显示“没有检索到相关文档”，异常仍显示“暂时无法检索相关文档”；同一逻辑检索的后续 attempt 只会更新同一张活动卡片。
- 已补 `backend/tests/test_agent_retrieve_activity.py::test_retrieve_knowledge_reuses_logical_activity_id_across_retries` 与 `backend/tests/test_agent_timeline_service.py::test_timeline_merges_retry_attempts_into_single_public_activity`，分别覆盖后台事件 attempt 信息和线程时间线单卡片归并。
- 验证：`cd backend && ./venv/bin/pytest tests/test_agent_retrieve_activity.py tests/test_agent_timeline_service.py -q` 通过。

### EXP-001 固化 Explain 无资料回答

- 状态：已完成（2026-07-26 完成完整验收）。
- 已保留无证据进入 `generate_explanation` 的行为，并在 `evidence_loop -> evidence_gate` 之间区分 `retrieval_outcome=empty|error`；零命中继续提示“没有检索到相关文档”，检索异常则提示“暂时无法检索相关文档”。
- 已在 `_fallback_evidence_text()` 中为零命中和检索异常生成不同 fallback 文案，并在无资料场景下强制清空 `citations`，避免模型把通用知识回答伪装成有来源答案。
- 已补 `backend/tests/test_agent_explain_workflow.py::test_evidence_gate_distinguishes_retrieval_error_from_zero_hits` 与 `test_generate_explanation_clears_citations_when_no_evidence`，覆盖两类 fallback 和无资料引用清理。
- 已新增 `backend/tests/test_agent_explain_worker.py::test_worker_persists_zero_hit_fallback_answer_without_citations` 与 `test_worker_persists_retrieval_error_fallback_answer_without_citations`，通过 patch `RetrievalService.search_with_outline_expansion()` 让真实 `retrieve_knowledge()` 工具链继续产生活动事件，再走完整 `AgentWorker.process_run()` 持久化链，覆盖 artifact、最终消息和线程刷新恢复。
- 验证：`cd backend && ./venv/bin/pytest tests/test_agent_explain_worker.py tests/test_agent_explain_workflow.py tests/test_agent_retrieve_activity.py tests/test_agent_timeline_service.py -q` 通过。

## 第二组：分层长期记忆最小闭环

### MEM-001 冻结记忆分区和事实边界

- 状态：已完成（2026-07-26，契约已落库）。
记忆分区固定为：当前轮理解、线程主题状态、近期原始对话、历史主题摘要、用户学习画像、Artifact/任务、
待处理交互、用户明确偏好与目标。原始消息和 Artifact 继续作为事实源；流式 delta、失败输出和 LLM 猜测
不得直接成为长期用户记忆。
- 已在 `backend/app/modules/agent/memory_contracts.py` 定义 `MemoryPartition`、`MemoryNeed` 和 `MEMORY_NEED_PARTITIONS`，把分区与能力标签固化为 workflow-neutral 的稳定命名契约。
- 已新增 `backend/tests/test_agent_memory_contracts.py`，覆盖分区全集、能力标签全集，以及“能力标签不出现 explain / validate / grade / plan 等工作流名称”的约束。

### MEM-002 建立热状态、事件、快照和专业画像存储

- 状态：已完成（2026-07-26，迁移与 ORM 已落库）。
通过 Alembic 前向迁移逐步增加：

- `agent_thread_memory_states`：小型结构化活跃主题、主题栈、活跃任务和指代对象；
- `agent_memory_events`：追加式增量来源和幂等审计；
- `agent_memory_snapshots`/`agent_memory_snapshot_items`：冻结 Run 实际使用的记忆版本；
- `agent_memory_update_outbox`：完成事件的可靠异步投影；
- `user_learning_mastery`：按知识点保存掌握度和真实答题/Grade 证据；
- `agent_conversation_summaries`：按消息序列范围增量压缩旧对话；
- `agent_memory_items`：偏好、目标和主题情景摘要，不承载专业学习掌握度。
- 已在 `backend/app/modules/agent/models.py` 新增上述八张表的 ORM 模型，并通过 `backend/alembic/versions/20260726_agent_memory_foundation.py` 创建对应前向迁移。
- 已补 `backend/tests/test_migrations.py::test_agent_memory_foundation_migration_renders_mysql_ddl`，验证迁移会创建全部记忆基础表、关键唯一约束和索引；同时更新 Alembic head 断言。
- 当前仍未接入这些表的实际 selector / projector，后续消费逻辑继续按 `MEM-003` 到 `MEM-006` 推进。

### MEM-003 新输入的增量处理

- 状态：进行中（2026-07-26 已完成确定性独立请求与 snapshot 第一阶段）。
1. HTTP 事务只原子保存用户消息、根 Run、时间线和 Run Outbox，不调用 LLM。
2. Worker 在 Router 前读取热状态、少量近期消息、显式引用和待处理交互。
3. 确定性解析优先；只有“这个、上一道、难一点”等仍有歧义时调用结构化指代消解模型。
4. 生成 `TurnUnderstanding`：原始输入、独立请求、意图提示、主题实体、约束和引用来源。
5. 创建不可变 Turn Memory Snapshot，并以版本号更新线程热状态。
6. Router 使用独立请求；子 Run 接收 snapshot ID，不再只传消息 ID。

- 已在 `backend/app/modules/agent/context_builder.py` 为 `AgentRunContext` 增加 `active_topic`、`memory_state_version`、`standalone_request` 和 `memory_snapshot_id`，并在 `ThreadContextBuilder.build()` 中读取 `agent_thread_memory_states`。
- 已新增 `backend/app/modules/agent/turn_understanding.py`，用确定性规则把 `context_refs` 或线程 `active_topic` 补全为 `TurnUnderstanding`；例如当前活跃主题是“二分查找”且输入“给我出一道难一点的题”时，会生成 `standalone_request="给用户出一道关于二分查找的练习题"`，并补 `constraints=["difficulty:hard"]`。
- 已在 `backend/app/modules/agent/workflows/conversation.py` 的 `_route_node()` 中创建不可变 snapshot，并把 `memory_snapshot_id`、`turn_understanding` 写入父 run metadata；Router 改为消费 `standalone_request`，child run 也改为继承 `standalone_request` 和 `memory_snapshot_id`。
- 已补 `backend/tests/test_agent_context_builder.py::test_context_loads_active_topic_from_thread_memory_state` 与 `backend/tests/test_agent_conversation_workflow.py::test_follow_up_validate_request_uses_active_topic_snapshot_for_child_run`，覆盖“Router 前读取热状态”和“子 Run 继承 snapshot ID + standalone_request”的第一阶段闭环。
- 尚未完成项：歧义输入的结构化指代消解模型、更多 bundle 类型和更多 workflow consumer，以及掌握度/排除集/澄清闭环，继续留在后续 `MEM-003` / `MEM-004` / `MEM-005`。

冲突优先级固定为：当前输入明确主题 > 显式引用/附件 > 待处理任务 > 最近活跃主题 > 唯一高优先级
学习薄弱点 > 请求用户澄清。禁止静默使用“数据结构 操作系统”作为默认主题。

### MEM-004 按能力声明选择最小记忆

- 状态：进行中（2026-07-26 已落地 `PracticeBundle` 首个 selector）。
- 已新增 `backend/app/modules/agent/memory_selector.py`，定义 workflow-neutral 的 `TopicBundle` / `PracticeBundle`，并通过 `load_practice_bundle()` 按 `run_id + user_id` 校验 run/snapshot 归属，从 `agent_memory_snapshots`、`agent_memory_snapshot_items` 与 `selection_metadata_json` 读取主题、aliases、约束、difficulty、knowledge point IDs 和已选 Artifact。
- 已在 `build_practice_query()` 与 `build_practice_filters()` 中把 bundle topic title + aliases、difficulty 确定性转成 query 与 retrieval filters；当既没有 bundle topic 也没有 fallback terms 时返回空 query，避免静默默认“数据结构/操作系统”。
- 已补 `backend/tests/test_agent_memory_selector.py::test_load_practice_bundle_uses_snapshot_topic_and_context_metadata`，覆盖 snapshot topic aliases、约束、difficulty、knowledge point IDs 和 selected artifacts 都能被组装进 `PracticeBundle`。
- 当前仍未完成：`ConversationBundle` / `EvaluationBundle` / `PlanningBundle` 等更多 selector，掌握度与真实排除集的结构化选择，以及 explain / grade / plan 的 bundle 接入。

- 定义类型化 `MemoryNeed`，把消费能力固定为 `conversation_continuity`、`topic_focus`、`practice_generation`、
  `grading_evidence`、`planning_goal`、`pending_interaction` 等稳定标签；当前 Router/Explain/Validate/Grade/Plan
  只是这些能力的第一批消费者，不是记忆表结构边界。
- Bundle 命名按能力而不是按 workflow：`ConversationBundle`、`TopicBundle`、`PracticeBundle`、
  `EvaluationBundle`、`PlanningBundle`。未来新增或重排 workflow 时，只声明需要哪些能力，不改底层存储。
- 先做权限和作用域过滤，再按实体 ID 精确查询；只有旧情景摘要缺少实体 ID 时才做向量检索。
- `message_history` 只承担近期对话连续性；主题、学习画像和 Artifact 使用结构化 Bundle。
- 快照记录每条选中记忆的来源、版本、选择原因、内容副本、估算 Token 和被丢弃原因。

### MEM-005 先用 Validate 打穿首个消费闭环

- 状态：进行中（2026-07-26 已让 Validate 使用 `PracticeBundle` 生成题目检索 query 与过滤条件）。
- 已在 `backend/app/modules/agent/turn_understanding.py` 为 `TopicEntity` 增加 `aliases`，并为“难一点 / 简单点 / 难度适中”这类输入补 `difficulty:*` 约束，让 snapshot topic 与难度条件都能进入后续 bundle。
- 已在 `backend/app/modules/agent/workflows/validate.py` 的 `_load_learning_evidence_node()` 中装载 `PracticeBundle`，优先使用 bundle topic 填充 `weak_areas` / `recent_topics`，并把 bundle 本身写回 `ExecutionContext`。
- 已在 `_question_discovery_node()` 中通过 `build_practice_query()` 构造 query，并把 `knowledge_point_ids`、`difficulty` 与 `exclude_entity_ids` 下发到 `retrieve_knowledge()`；当 bundle topic 存在时会发起 `query="二分查找 折半查找"` 的题目检索，当 topic 与 fallback terms 都为空时直接失败，不再静默随机出题。
- 已补 `backend/tests/test_agent_validate_workflow.py::test_validate_uses_practice_bundle_topic_for_query` 与 `test_validate_stops_when_no_topic_or_fallback_terms`，分别覆盖 topic aliases + knowledge point + difficulty 过滤，以及“缺少主题即失败”的行为；并新增 `backend/tests/test_agent_turn_understanding.py::test_build_turn_understanding_preserves_topic_aliases_and_difficulty_constraint`，覆盖约束抽取。
- 当前仍未完成：`chapter_ids` 的稳定来源、真实 `exclude_ids` 回写、唯一高优先级薄弱点回退，以及失败后主动进入澄清而不是直接终止。

`validate` 是首个落地消费者，因为当前“讲解后出题”的痛点最集中、验证成本最低；它只是样板，不是
记忆内核对 workflow 的硬编码。后续若把 `validate` 拆成新的 workflow，或新增 `drill`、`quiz`、`review`
之类分支，只要复用 `practice_generation`/`topic_focus` 能力和同一套快照、回写协议即可。

首个目标链路：

```text
“讲解二分查找”完成
  → 热状态 active_topic=二分查找
  → 用户输入“给我出道题”
  → standalone_request=“给用户出一道关于二分查找的练习题”
  → Router=validate
  → PracticeBundle 读取主题、掌握度、出题约束、近期题目排除集
  → 确定性构造 query="二分查找 折半查找"
  → retrieve_knowledge(entity_type="question", knowledge_point_ids=["kp_binary_search"], filters={"difficulty":"hard"}, exclude_ids)
```

没有明确主题时：先使用活跃主题；再考虑唯一高优先级薄弱点；当前实现已移除静默默认主题，若仍拿不到主题则直接失败，后续再补“请求用户澄清”的显式闭环。

### MEM-006 按事实事件回写，而不是按 workflow 名写库

- 不把 `message.delta` 写长期记忆，只在 `message.completed`/`artifact.rendered`/`run.completed` 后投影。
- Run 完成事务同步更新下一轮马上需要的热状态，并写 Memory Outbox。
- 异步投影历史摘要、Embedding、偏好候选和长期事件，失败可重放且不反向把成功 Run 改成失败。
- 领域事件固定为“主题被确认”“讲解 Artifact 产生”“练习 Artifact 产生”“评分结果确认”“计划被用户确认”
  等事实事件；Explain/Validate/Grade/Plan 只是当前这些事件的来源。
- Explain 只更新主题和讲解 Artifact，不提高掌握度；Validate 创建练习和排除集，也不提高掌握度。
- Grade 的真实得分/错误类型才更新 `user_learning_mastery`；Plan 只有经用户确认后才成为长期目标。
- `run.failed` 不写 Agent 输出记忆，用户已表达的输入主题仍保留为事实。

### MEM-007 压缩、冲突、失效与删除

- 最近 6～12 轮保留原始消息；更旧消息按连续 sequence 区间增量摘要，不整线程重复总结。
- 摘要不覆盖原消息，旧摘要被合并后标记 `superseded` 并保留来源范围和版本。
- 用户明确陈述和真实业务事件优先于模型抽取；低置信度候选不能覆盖高置信度活跃记忆。
- 线程主题按轮次衰减；临时约束随 Turn/Practice 结束；学习画像长期保存并按时间衰减。
- 删除线程时失效线程记忆并通过 Outbox 删除向量；用户级学习画像单独控制。

### MEM-008 记忆可观测性与安全

- Agent Runs 展示原始输入、独立请求、主题来源、快照版本、选中/丢弃记忆、Token 和最终工具参数。
- 记忆正文不塞入公开 SSE；事件只保存快照/调用 ID 和安全摘要。
- 所有读取校验 `user_id`、`thread_id` 和 Artifact 权限；记忆文本按不可信数据渲染，不能成为系统指令。
- 支持按 source ID 回查、幂等重放、快照复现和投影失败重试。

## 外部基线与设计校正

本轮审计结论：对“现有方案是否过度绑定当前 workflow”的担忧是合理的。当前任务单里稳定的部分是
MEM-001/002/003/007/008；风险主要在 MEM-004/005/006 的原始表述，它们容易让维护者误以为
Validate/Explain/Grade/Plan 是记忆内核的天然边界。这里把设计口径校正为：稳定的是事实模型、快照、
选择协议和事件回写；可变的是 workflow 对这些能力的装配方式。

| 方案 | 公开设计 | 为什么稳定 | 为什么不直接照搬 | 本任务单吸收后的落点 |
| --- | --- | --- | --- | --- |
| [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[Memories](https://learn.chatgpt.com/docs/customization/memories?surface=app)、[Skills](https://learn.chatgpt.com/docs/build-skills)、[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) | `AGENTS.md` 负责持久规则，Memories 在后台把旧会话沉淀为本地记忆，Skills 按需加载，Subagents 把噪声工作移出主线程 | 规则、记忆、执行技能三层分离；会话空闲后异步生成记忆，技能只在命中时加载，workflow 变化不会倒逼底层记忆重建 | Codex 主要服务工程协作，缺少“学习掌握度、题目排除集、评分证据”这类教育域结构化状态；它的 durable recall 更偏通用提示与历史上下文 | 采纳“三层分离”：记忆底座只存事实和结构化状态，workflow 只声明 `MemoryNeed`；不把 `validate`、`grade` 名称写进存储契约 |
| [Claude Code Memory](https://code.claude.com/docs/en/memory)、[Skills](https://code.claude.com/docs/en/skills)、[Context Windows](https://platform.claude.com/docs/en/build-with-claude/context-windows) | `CLAUDE.md` 与 auto memory 在每次会话启动时加载，长流程靠 compaction 管理上下文，技能正文只在使用时注入 | 作用域和加载时机清晰：事实/规则常驻，流程说明按需注入；官方明确把“procedure”从常驻记忆里拆到 skills，避免上下文腐烂 | Claude Code 的 memory 更像“项目说明 + 偏好 + 调试经验”，不是我们要长期审计的业务事实账本；auto memory 也不提供我们需要的用户级学习画像和快照复现 | 采纳“事实常驻、流程按需加载”的边界：主题状态、掌握度、摘要常驻； Explain/Validate/Grade 的步骤说明放在 workflow adapter，不进入核心记忆 schema |
| [Hermes Memory](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory.md)、[Memory Providers](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory-providers.md)、[Context Engine Plugins](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/context-engine-plugin.md) | 小而常驻的 `MEMORY.md`/`USER.md` 负责有界记忆，外部 provider 做跨会话召回，context engine 可替换压缩/上下文管理策略 | 内建记忆、外部记忆、上下文管理彼此解耦；即使改检索或压缩引擎，也不必改 agent core 和 memory surface | Hermes 的 Markdown 记忆非常轻量，适合个人 agent，不足以承载我们需要的权限校验、评分证据、用户级 mastery 和可追溯快照；它也公开暴露单用户污染风险 | 采纳“有界常驻 + 外部检索 + 可替换上下文引擎”的思想：线程热状态要小，历史摘要/向量检索走异步通道，记忆选择器与具体 workflow 解耦 |

三类成熟方案虽然实现不同，但共同点很一致：

1. 记忆底座独立于 workflow。稳定的是记忆面、作用域和加载协议，不是某条业务流程图。
2. 常驻记忆必须小而可信。大型步骤说明、长参考资料、工具细节都按需加载，不能长期塞在主上下文。
3. 长期记忆只接收确认后的事实，不接收流式中间态和临时推理。
4. 复杂流程靠技能、子代理、上下文压缩去适配，而不是频繁改底层记忆 schema。

因此，本任务单的最终口径应当是：

- 当前设计的大方向没有错：分层记忆、快照、事件回写、热状态与长期画像分离，这些都比“把全部历史直接塞回模型”更稳。
- 需要修正的是表达和边界：记忆核心必须围绕事实类型与能力标签稳定，workflow 只做薄适配层。
- `validate` 仍然应该作为第一条打通链路，因为它最能暴露主题继承、题目检索和排除集是否好用；但它只是验收样例，不是架构中心。

## 实施顺序与依赖

```text
文档分卷迁移
  → FLOW-001
  → RAG-001
  → RAG-002
  → ACT-001 + EXP-001
  → MEM-001/002（契约与迁移）
  → MEM-003/004（输入解析、快照、选择）
  → MEM-005（Validate 最小闭环）
  → MEM-006（完成事件增量回写）
  → MEM-007（摘要、冲突、失效）
  → MEM-008（完整可观测与治理）
```

记忆接入 Validate 前必须先完成 FLOW-001、RAG-001 和 RAG-002，否则即使主题选择正确，检索结果仍可能
在回填/DTO 层丢失，最终 Practice Artifact 也可能无法持久化。

## 端到端验收场景

1. Explain 检索零命中：用户看到一个检索活动和通用知识回答，引用为空，刷新后正文仍在；已由 `backend/tests/test_agent_explain_worker.py::test_worker_persists_zero_hit_fallback_answer_without_citations` 覆盖。
2. Explain 检索连续失败三次：后台显示三次 attempt，用户端只有一个活动，LLM 回答仍正常完成；公开活动折叠由 `test_timeline_merges_retry_attempts_into_single_public_activity` 覆盖，单次失败回退持久化由 `test_worker_persists_retrieval_error_fallback_answer_without_citations` 覆盖。
3. 二分查找真实题：MySQL 稀疏和 Qdrant 向量候选经过回填、DTO 和资格门后进入 Practice；已由 `backend/tests/test_agent_validate_workflow.py::test_validate_binary_search_question_survives_retrieval_dto_and_gate` 覆盖。
4. 上下文继承：“讲解二分查找”后说“给我出道题”，工具查询必须包含二分查找且类型为 question。
5. 明确覆盖：“不要二分查找，出红黑树题”，当前输入覆盖旧主题。
6. 无法消解：没有主题和唯一薄弱点时进入澄清，不使用硬编码默认主题。
7. 增量回写：Explain/Validate 不提高掌握度；Grade 完成后以证据 ID 幂等更新掌握度。
8. 失败隔离：流式中途失败不写长期 Agent 输出记忆；重放 Outbox 不产生重复记忆。

## 任务维护规则

- 每个独立修复使用中文 Git 提交，并在实现提交中把对应任务状态和验证证据更新到本文件。
- 代码或符号行号发生变化时，同一提交重新使用 `rg -n`、`nl -ba` 核对本文件代码锚点。
- 复杂实现细节写入对应 `implementation/` 分卷；本文件只保留待做状态、依赖、关键决策和验收入口。
- 单项只有在代码、迁移、测试、文档和提交全部完成后才能标记 `已完成`。
