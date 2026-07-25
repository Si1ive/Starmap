# RAG、实体类型与工具活动

## 适用场景

本分卷记录 explain / validate 共用的 `retrieve_knowledge` 工具、底层检索服务、公开工具活动投影，以及
`2026-07-26-rag-explain-memory-remediation.md` 中 RAG 与 Explain 整改任务当前对应的真实代码位置。

## 当前检索主链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Explain/Validate 发起检索 | `backend/app/modules/agent/workflows/explain.py`、`validate.py` | `_evidence_loop_node`、`_question_discovery_node` | `explain.py` L40-L156；`validate.py` L33-L52 | query、范围、run ID、可选 `entity_type` | 由 workflow 统一调用 `retrieve_knowledge`，Explain 使用知识检索，Validate 强制 `entity_type="question"` | Tool 调用与内部结果 | `retrieve_knowledge` |
| 工具活动创建 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | L19-L75 | query、范围、run ID | 写 `tool.called`，公开检索标题、query 摘要、章节/实体类型等安全元数据 | running activity | 检索服务 |
| 检索结果与异常公开 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | L77-L181 | `RetrievalService` 返回结果或异常 | 正常结果精简为对 workflow 可消费的字段；零命中公开“没有检索到相关文档”；异常公开“暂时无法检索相关文档” | `tool.result` 事件与内部结果 | 时间线/工作流 |
| 大纲扩展与混合检索 | `backend/app/modules/retrieval/service.py` | `RetrievalService.search_with_outline_expansion` | L44-L107 | query、学科/章节过滤、`entity_type`、limit | 先做 canonical chapter 扩展，再组合 dense + sparse hybrid 检索 | `results`、`outline_expansion` | `search` |
| Collection 路由 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalSearchEngine.get_collections` | L105-L114 | `entity_type` | `knowledge_point` 和 `question` 进入不同 Qdrant collection；空类型时两者都查 | collection 列表 | `search` |
| 稀疏召回与命中合并 | `backend/app/modules/retrieval/search_engine.py` | `sparse_search`、`merge_hits` | L116-L194 | collection、query、filter | MySQL `sparse_text` 召回与 Qdrant dense 结果加权合并 | hit 列表 | `hydrate_results` |
| 命中内容回填 | `backend/app/modules/retrieval/search_engine.py` | `hydrate_results` | L197-L282 | hit 列表 | 按命中顺序从 `retrieval_segments` 和 `documents` 补齐正文、上下文、来源文档和页码 | `RetrievalResult` 列表 | `RetrievalResult.to_dict` |
| Agent DTO 出口 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalResult.to_dict` | L15-L62 | `RetrievalResult` | 统一输出 `entity_id`、`content_text`、`source`、`chapter_ids` 等字段 | Agent 工具与其他检索消费者的原始 DTO | `retrieve_knowledge` |

## 当前公开活动与用户端归并

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| Run 事件投影 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event`（tool 分支） | L162-L212 | 只转发显式 `public_metadata`，投影成 `workflow.activity.updated` |
| 时间线活动归并 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._activity_views` | L506-L538 | 按 `activity_id` 聚合 `tool.called` 与 `tool.result`；ID 不同就一定显示为多个活动 |
| 前端实时归并 | `frontend/src/features/agent/timeline-state.ts` | `applyWorkflowEvent` | L167-L224 | 以 activity ID 为键更新工作流活动状态 |
| 工作流卡片渲染 | `frontend/src/features/agent/InlineWorkflow.tsx` | `ActivityCard` / `InlineWorkflow` | L92-L133、L218-L242 | 渲染查询、命中数、资料列表和零命中/异常提示 |

## 当前已定位问题与代码锚点

| 任务 ID | 文件 | 符号 | 代码范围 | 当前问题 |
| --- | --- | --- | --- | --- |
| `ACT-001` | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | L19-L181 | 每次重试都随机生成新的 `activity_id`，用户端按不同活动展示多张卡片 |
| `RAG-001` | `backend/app/modules/retrieval/search_engine.py` | `hydrate_results` | L197-L282 | 命中后需要从 `documents` 回填来源信息；整改前曾因为访问不存在字段导致 Explain 真实命中却失败 |
| `RAG-002` | `backend/app/modules/retrieval/search_engine.py`、`backend/app/modules/agent/tools/retrieve_knowledge.py` | `RetrievalResult.to_dict`、`retrieve_knowledge` | `search_engine.py` L15-L62；`retrieve_knowledge.py` L77-L181 | 底层 DTO 与 Agent 简化字段之间存在语义压缩，Explain/Validate 需要稳定的实体类型和来源字段 |
| `EXP-001` | `backend/app/modules/agent/workflows/explain.py` | `_evidence_gate_node`、`_generate_explanation_node` | L159-L225 | 零命中仍允许进入模型生成，但必须区分正常空结果与服务异常，且不能伪造引用 |

## 现有测试入口

| 验证目标 | 文件 | 符号 | 代码范围 |
| --- | --- | --- | --- |
| 用户可读的零命中与异常提示 | `backend/tests/test_agent_retrieve_activity.py` | `test_retrieve_knowledge_explains_empty_result_without_internal_jargon` / `test_retrieve_knowledge_failure_hides_internal_degradation_wording` | L54-L107 |
| Explain 模型错误、零命中、首次强制检索和正文生成 | `backend/tests/test_agent_explain_workflow.py` | `test_evidence_loop_reports_model_failure_instead_of_false_completion` 至 `test_generate_explanation_uses_structured_runtime` | L42-L167 |
| 检索过滤、回填和服务委托 | `backend/tests/test_retrieval_service.py` | `test_hydrate_results_preserves_hit_order_and_adds_source_filename` 等 | L1-L176 |

## 下一步阅读

- 要看步骤、工具活动、错误投影和刷新恢复，转到 `implementation/events-timeline-errors.md`。
- 要看长期主题/记忆如何驱动后续 Validate，转到 `implementation/routing-context-memory.md` 与任务单的 `MEM-*` 部分。
