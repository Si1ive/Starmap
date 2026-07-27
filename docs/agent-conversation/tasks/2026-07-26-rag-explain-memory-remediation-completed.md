# 已完成整改与分层记忆基础

## 分卷职责

本分卷保存原任务单中已经闭环的故障整改和 MEM-001～006 状态，供回查依赖与验证入口使用；当前待做
项统一从[记忆生命周期分卷](./2026-07-26-rag-explain-memory-remediation-memory-lifecycle.md)和
[管理端可观测性分卷](./2026-07-26-rag-explain-memory-remediation-observability.md)继续。

## `run_5c6c46d3` 故障整改

`run_5c6c46d3111c495c831a` 的失败链已经全部解除：检索来源回填不再读取不存在的
`Document.filename`，题目/知识点共享类型化 DTO，Explain 无资料时清空引用并继续生成，最终
Artifact 可穿过 `NodeResult.success()` 交给 Worker 持久化。同一逻辑检索的多次 attempt 在后台保留，
用户时间线按稳定活动 ID 归并。

| 任务 | 完成结果 | 回归文件与完整符号 | 代码范围 | 中文提交线索 |
| --- | --- | --- | --- | --- |
| FLOW-001 | Artifact 契约穿过 Explain/Validate/Grade/Plan | `backend/tests/test_agent_workflow_engine.py::test_explain_workflow_keeps_artifact_through_render_and_completion` | L159-L257 | 修复 Agent 工作流 Artifact 成功结果契约 |
| RAG-001 | MySQL 命中来源安全回填 | `backend/tests/test_retrieval_service.py::test_hydrate_results_preserves_hit_order_and_adds_source_display_name`；`backend/tests/test_retrieval_service.py::test_hydrate_results_falls_back_to_title_and_handles_missing_source` | L102-L180；L185-L277 | 修复检索命中来源回填 |
| RAG-002 | 题目/知识点类型、来源、状态与元数据统一 | `backend/tests/test_agent_validate_workflow.py::test_validate_binary_search_question_survives_retrieval_dto_and_gate` | L90-L174 | 统一 Agent 检索结果契约 |
| ACT-001 | 一次逻辑活动、多次后台 attempt | `backend/tests/test_agent_timeline_service.py::test_timeline_merges_retry_attempts_into_single_public_activity` | L347-L492 | 折叠 Agent 用户端检索重试活动 |
| EXP-001 | 零命中与异常均产生无伪造引用的可恢复正文 | `backend/tests/test_agent_explain_worker.py::test_worker_persists_zero_hit_fallback_answer_without_citations`；`backend/tests/test_agent_explain_worker.py::test_worker_persists_retrieval_error_fallback_answer_without_citations` | L134-L243；L247-L311 | 固化 Explain 无资料回答 |

完整线上数据库漏迁移证据及前向升级过程见
[`2026-07-27-memory-outbox-table-missing.md`](../incidents/2026-07-27-memory-outbox-table-missing.md)。

## MEM-001～005

- MEM-001 已冻结 workflow-neutral 的 `MemoryPartition`、`MemoryNeed` 与能力到分区映射。
- MEM-002 已通过 Alembic 建立线程热状态、追加事实、不可变 Snapshot、Memory Outbox、学习掌握度、
  对话摘要和通用记忆项；启动结构守卫会在 Worker 扫描前阻断缺表或索引漂移。
- MEM-003 已在 Router 前形成确定性 `TurnUnderstanding` 和不可变 Snapshot，并把独立请求、结构化引用
  与 Snapshot ID 交给子 Run；没有可信唯一候选时不猜测。
- MEM-004 已让 Conversation、Practice、Evaluation、Planning 四类能力 Bundle 从真实 Snapshot/事实
  读取最小上下文，Router、Explain、Validate、Grade、Plan 不再依赖硬编码主题或计划。
- MEM-005 已打通 Validate 的主题、难度、章节、题目排除、唯一薄弱点与缺主题澄清恢复链。

这些行为的权威教学说明位于
[`routing-context-memory.md`](../implementation/routing-context-memory.md)与
[`rag-and-tools.md`](../implementation/rag-and-tools.md)；逐提交验证记录位于
[`01-memory-foundation-and-outbox.md`](../progress/2026-07/01-memory-foundation-and-outbox.md)和
[`04-validate-memory-consumption.md`](../progress/2026-07/04-validate-memory-consumption.md)。

## MEM-006 已完成边界

可信事实只由确定性来源产生：显式主题、公开 Explanation/Practice Artifact、真实批准的计划以及 Grade
客观判定。Run 完成事务写事实与 Outbox，派生消费者独立认领、租约、重试；派生失败不会污染已完成
Run。当前已经物化显式主题、批准目标和增量对话摘要，Explain/Validate 不提高掌握度，只有可信 Grade
证据可以幂等更新 `UserLearningMastery`。

Embedding 与偏好候选尚未完成，因同时涉及冲突、版本和删除治理，统一在 MEM-007 分卷继续，不把它们
误标为 MEM-006 已完成。

## 已覆盖的端到端场景

1. Explain 零命中或检索异常仍可完成、无引用并在刷新后恢复。
2. 检索重试在用户端只出现一个活动，后台仍能审计各次 attempt。
3. 二分查找真实题可穿过 MySQL/Qdrant、来源回填、DTO 和 Validate 资格门。
4. “讲解二分查找”后“给我出道题”会使用 Snapshot 主题；缺主题且无唯一薄弱点时进入澄清。
5. Grade 对唯一可信客观题产生可重放掌握度证据；主观题、缺标准答案或跨作用域输入安全失败。
6. 13 轮以上线程按连续序列增量摘要，保留近期 12 个用户轮次，旧摘要被新版本 supersede。
