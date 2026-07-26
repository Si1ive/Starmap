# RAG、实体类型与工具活动

## 适用场景

本分卷记录 explain / validate 共用的 `retrieve_knowledge` 工具、底层检索服务、公开工具活动投影，以及
`2026-07-26-rag-explain-memory-remediation.md` 中 RAG 与 Explain 整改任务当前对应的真实代码位置。

## 当前检索主链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Explain/Validate 发起检索 | `backend/app/modules/agent/workflows/explain.py`、`backend/app/modules/agent/memory_selector.py`、`validate.py` | `_evidence_loop_node`、`build_practice_query`、`build_practice_filters`、`_question_discovery_node` | `explain.py` L49-L176；`memory_selector.py` L161-L193；`validate.py` L78-L146 | query 或 `PracticeBundle`、范围、run ID、可选 `entity_type` | 由 workflow 统一调用 `retrieve_knowledge`；Explain 使用混合知识检索并记录 `retrieval_outcome`；Validate 先按 `PracticeBundle` 中的 topic title + aliases 生成 query，再把 `knowledge_point_ids`、`difficulty` 和排除题 ID 作为过滤条件传给检索；若没有主题且没有 fallback terms，则先读取或创建 `practice_topic` 输入项，等待用户补充后从断点恢复并继续检索，而不是静默默认主题或直接失败 | Tool 调用、等待用户输入，或内部检索结果 | `retrieve_knowledge` / waiting checkpoint |
| Agent 结果归一化 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `_agent_result_title`、`_normalize_agent_result`、`_sort_agent_results`、`_logical_activity_id`、`_next_attempt_number` | L24-L127 | `RetrievalResult.to_dict()` 输出、run/query 范围、结构化过滤参数 | 把底层 DTO 统一为 Agent 可直接消费的 `entity`/`question_meta`/`knowledge_point_meta` 结构；Explain 混合查询时把知识点排在题目前面；同一逻辑检索基于 run/query/scope/knowledge_point_ids/filters/exclude IDs 计算稳定活动 ID，并统计 attempt 序号 | 稳定 Agent DTO 与逻辑活动 ID | `retrieve_knowledge` |
| 工具活动创建 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | L130-L227 | query、范围、run ID、知识点/过滤参数 | 写 `tool.called`，公开检索标题、query 摘要、章节/实体类型，以及知识点 ID、difficulty、排除题等安全元数据；同一逻辑检索的重试复用 `activity_id`，并单独记录 `attempt_id` / `attempt_no` | running activity | 检索服务 |
| 检索结果与异常公开 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | L228-L337 | `RetrievalService` 返回结果或异常 | 正常结果保留实体标题、正文、来源和题目/知识点元数据；零命中公开“没有检索到相关文档”；异常公开“暂时无法检索相关文档”；后台事件保留每次 attempt 的原始失败信息 | `tool.result` 事件与内部结果 | 时间线/工作流 |
| 大纲扩展与混合检索 | `backend/app/modules/retrieval/service.py` | `RetrievalService.search_with_outline_expansion`、`search` | L44-L111、L204-L301 | query、学科/章节过滤、知识点过滤、排除题、`entity_type`、limit | 先做 canonical chapter 扩展，再把 `knowledge_point_ids`、`difficulty`、排除题等过滤条件同时下发到 dense 和 sparse 路径，组合 dense + sparse hybrid 检索 | `results`、`outline_expansion` | `search_engine` |
| Collection 路由 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalSearchEngine.get_collections` | L171-L181 | `entity_type` | `knowledge_point` 和 `question` 进入不同 Qdrant collection；空类型时两者都查 | collection 列表 | `search` |
| 稀疏召回与命中合并 | `backend/app/modules/retrieval/search_engine.py` | `sparse_search`、`merge_hits` | L183-L277 | collection、query、filter | MySQL `sparse_text` 召回与 Qdrant dense 结果加权合并；同时与 Qdrant 保持 `knowledge_point_ids`、difficulty 和排除题过滤维度一致 | hit 列表 | `hydrate_results` |
| 命中内容回填 | `backend/app/modules/retrieval/search_engine.py` | `hydrate_results`、`_document_source_name`、`_load_knowledge_point_details`、`_load_question_details`、`_question_title` | L279-L447 | hit 列表 | 按命中顺序从 `retrieval_segments`、`documents`、`knowledge_points` 和 `questions` 补齐正文、上下文、展示来源、实体标题、审核状态与题目/知识点元数据 | `RetrievalResult` 列表 | `RetrievalResult.to_dict` |
| Agent DTO 出口 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalResult.to_dict` | L20-L95 | `RetrievalResult` | 统一输出 `entity`、`source`、`question_meta`、`knowledge_point_meta`、学科章节和正文字段，供 Agent 工具、聊天检索上下文和管理调试共用 | Agent 工具与其他检索消费者的原始 DTO | `retrieve_knowledge` |

## 当前公开活动与用户端归并

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| Run 事件投影 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event`（tool 分支） | L162-L212 | 只转发显式 `public_metadata`，投影成 `workflow.activity.updated` |
| 时间线活动归并 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._activity_views` | L506-L538 | 按 `activity_id` 聚合 `tool.called` 与 `tool.result`；同一逻辑检索复用稳定 ID 后，重试只会更新同一活动卡片 |
| 前端实时归并 | `frontend/src/features/agent/timeline-state.ts` | `applyWorkflowEvent` | L167-L224 | 以 activity ID 为键更新工作流活动状态；相同 ID 的后续 attempt 会覆盖旧状态而不是新增卡片 |
| 工作流卡片渲染 | `frontend/src/features/agent/InlineWorkflow.tsx` | `ActivityCard` / `InlineWorkflow` | L92-L133、L218-L242 | 渲染查询、命中数、资料列表和零命中/异常提示 |

## 当前任务锚点

| 任务 ID | 文件 | 符号 | 代码范围 | 当前问题 |
| --- | --- | --- | --- | --- |
| `ACT-001` | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `_logical_activity_id`、`_next_attempt_number`、`retrieve_knowledge` | L77-L337 | 已完成：同一逻辑检索复用稳定 `activity_id`，后台事件额外保留 `attempt_id`、`attempt_no` 和失败明细，用户端只显示一个持续更新的活动 |
| `RAG-001` | `backend/app/modules/retrieval/search_engine.py` | `hydrate_results`、`_document_source_name` | L279-L376 | 已改为 `source_label -> title -> None` 回退链，不再访问不存在的 `Document.filename`；二分查找题的来源展示名已由 Validate 检索链回归覆盖 |
| `RAG-002` | `backend/app/modules/retrieval/search_engine.py`、`backend/app/modules/agent/tools/retrieve_knowledge.py`、`backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/agent/workflows/explain.py` | `RetrievalResult.to_dict`、`retrieve_knowledge`、`_question_is_eligible`、`_generate_explanation_node` | `search_engine.py` L20-L95、L279-L440；`retrieve_knowledge.py` L24-L337；`validate.py` L25-L149；`explain.py` L206-L261 | 已完成：统一类型化 DTO，Explain 混合结果优先知识点，Validate 改读 `question_meta` 和实体状态字段，不再依赖虚构的 `source_type`；二分查找题进入候选集的整体验收已补齐 |
| `EXP-001` | `backend/app/modules/agent/workflows/explain.py`、`backend/app/modules/agent/worker.py` | `_fallback_evidence_text`、`_evidence_loop_node`、`_evidence_gate_node`、`_generate_explanation_node`、`AgentWorker.process_run` | `explain.py` L26-L261；`worker.py` L100-L251 | 已完成：零命中与检索异常会进入不同 fallback 文案；无资料时强制清空 citations；worker 会把最终 artifact 和 message 持久化，刷新后仍能恢复 |
| `MEM-005` | `backend/app/modules/agent/memory_selector.py`、`backend/app/modules/agent/tools/retrieve_knowledge.py`、`backend/app/modules/agent/workflows/validate.py`、`backend/app/modules/retrieval/search_engine.py`、`backend/app/modules/agent/service.py` | `load_practice_bundle`、`build_practice_filters`、`retrieve_knowledge`、`_question_discovery_node`、`build_filter`、`create_input`、`submit_input_answer` | `memory_selector.py` L81-L193；`retrieve_knowledge.py` L130-L337；`validate.py` L47-L146；`search_engine.py` L104-L169、L449-L530；`service.py` L279-L362 | 进行中：Validate 已开始消费 `PracticeBundle`，会用 snapshot topic aliases 构造 `query="二分查找 折半查找"`，把 `knowledge_point_ids`、`difficulty` 和排除题 ID 下发到检索层，并在缺主题时创建 `practice_topic` 等待输入后恢复执行；掌握度、真实排除集和唯一高优先级薄弱点回退仍待补齐 |

## 现有测试入口

| 验证目标 | 文件 | 符号 | 代码范围 |
| --- | --- | --- | --- |
| 用户可读的零命中与异常提示、Explain 混合结果优先知识点，以及重试复用逻辑活动 ID | `backend/tests/test_agent_retrieve_activity.py` | `test_retrieve_knowledge_explains_empty_result_without_internal_jargon`、`test_retrieve_knowledge_failure_hides_internal_degradation_wording`、`test_retrieve_knowledge_prefers_knowledge_points_for_mixed_explain_results`、`test_retrieve_knowledge_reuses_logical_activity_id_across_retries` | L84-L276 |
| Explain 模型错误、零命中、检索异常区分、首次强制检索和无资料引用清理 | `backend/tests/test_agent_explain_workflow.py` | `test_evidence_loop_reports_model_failure_instead_of_false_completion`、`test_evidence_loop_keeps_zero_hits_out_of_valid_evidence`、`test_evidence_gate_distinguishes_retrieval_error_from_zero_hits`、`test_generate_explanation_clears_citations_when_no_evidence` 等 | L47-L236 |
| Explain 无资料回答经 worker 持久化后仍可刷新恢复，且 citations 始终为空 | `backend/tests/test_agent_explain_worker.py` | `test_worker_persists_zero_hit_fallback_answer_without_citations`、`test_worker_persists_retrieval_error_fallback_answer_without_citations` | L123-L264 |
| 检索过滤、知识点 / 排除题条件对齐、回填、题目/知识点元数据回传和服务委托 | `backend/tests/test_retrieval_service.py` | `test_build_filter_keeps_qdrant_and_sparse_filter_dimensions_aligned`、`test_hydrate_results_preserves_hit_order_and_adds_source_display_name` 等 | L14-L80、L67-L267 |
| Validate 题目资格门读取真实 DTO 元数据，二分查找题能经检索 DTO 进入候选集，并优先使用 snapshot topic aliases、knowledge point / difficulty 过滤；缺主题时进入等待输入而非直接失败 | `backend/tests/test_agent_validate_workflow.py`、`backend/tests/test_agent_validate_worker.py` | `test_question_gate_accepts_rich_question_metadata_without_source_type`、`test_question_gate_filters_deleted_or_source_less_questions`、`test_validate_binary_search_question_survives_retrieval_dto_and_gate`、`test_validate_uses_practice_bundle_topic_for_query`、`test_validate_stops_when_no_topic_or_fallback_terms`、`test_validate_waits_for_topic_clarification_and_resumes_with_answer` | `test_agent_validate_workflow.py` L18-L255；`test_agent_validate_worker.py` L98-L172 |
| `PracticeBundle` 会从 snapshot、selected items 和 selection metadata 组装主题、约束、difficulty、knowledge point 与 Artifact 选择 | `backend/tests/test_agent_memory_selector.py` | `test_load_practice_bundle_uses_snapshot_topic_and_context_metadata` | L46-L132 |
| `TurnUnderstanding` 会保留 topic aliases，并把“难一点”等输入抽成稳定 `difficulty:*` 约束 | `backend/tests/test_agent_turn_understanding.py` | `test_build_turn_understanding_preserves_topic_aliases_and_difficulty_constraint` | L1-L43 |
| 时间线把多次 attempt 归并成一个公开活动 | `backend/tests/test_agent_timeline_service.py` | `test_timeline_merges_retry_attempts_into_single_public_activity` | L346-L491 |

## 下一步阅读

- 要看步骤、工具活动、错误投影和刷新恢复，转到 `implementation/events-timeline-errors.md`。
- 要看长期主题/记忆如何驱动后续 Validate，转到 `implementation/routing-context-memory.md` 与任务单的 `MEM-*` 部分。
