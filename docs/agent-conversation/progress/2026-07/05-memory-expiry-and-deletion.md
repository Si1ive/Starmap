# 2026-07 记忆失效与删除治理进展

## 2026-07-27：建立受治理的偏好候选与冲突优先级

- 目标：完成 `MEM-007` 的偏好候选来源、置信度、审批状态和完整冲突优先级，确保模型推测永远不能直接成为 trusted memory。
- 实现：`backend/app/modules/agent/model_runtime/preference_extractor.py::PreferenceExtractionRuntime.extract`（L92-L144）把根 conversation 原始消息限制为最多五个结构化提案；`backend/app/modules/agent/preference_memory.py::PreferenceCandidateProjector.process_outbox`（L175-L244）通过 Memory Outbox 写 source kind/ID/version、user/thread scope、confidence、extractor/model 版本并统一保持 pending。`decide_preference_candidate` / `_materialize_approved_preference`（L304-L399）只允许归属用户批准或拒绝，批准物化 active 项，拒绝形成 tombstone。`extract_explicit_preferences`、`_resolve_preference_sources`、`_freeze_preference_bundle` 与 `load_preference_bundle`（L95-L119、L422-L662）执行“本轮明确陈述 > 真实批准/拒绝事件 > 模型候选”，冻结 selected、dropped reason 和空结果 marker；PlanningBundle 把已决胜 `daily_study_minutes` 传给 Plan 草案。
- 迁移：`backend/alembic/versions/20260727_preference_candidates.py::upgrade`（L19-L70）从唯一 head 前向创建 `agent_preference_candidates`；`backend/app/modules/operations/schema_guard.py::verify_database_schema`（L44-L193）把真表纳入启动门禁。已对当前 MySQL 实际执行 `venv/bin/alembic upgrade head` 升至 `20260727_preference_candidates`，未使用 stamp。
- 验证：偏好、模型运行时、迁移、schema guard、Memory Outbox、MemorySelector 与 Plan 聚焦回归 53 项通过；全部 Agent 回归 224 passed、101 warnings，Python 编译、五个新增文件的 Black 检查和 `git diff --check` 通过。
- 提交信息：`建立受治理的 Agent 偏好候选`

## 2026-07-27：打通 Agent 记忆向量生命周期

- 目标：完成 `MEM-007` 的 Embedding、向量召回、来源版本更新与删除，让摘要和长期记忆项可以被治理且可回查。
- 实现：`backend/app/modules/agent/memory_vector.py::enqueue_memory_vector_task`、`memory_vector_point_id` 与 `MemoryVectorLifecycle.process_outbox`（L86-L249）用 source kind/ID/version 形成稳定点 ID，重读 MySQL active source 后生成 Embedding 并幂等 upsert，新版本成功后删除旧点；collection 已不存在时删除幂等完成，服务故障交给 Memory Outbox 重试。`MemoryVectorLifecycle.recall`、`MemoryVectorLifecycle.recall_for_snapshot`、`MemoryVectorLifecycle._hydrate_hit` 与 `MemoryVectorLifecycle._load_frozen_hits`（L251-L567）执行 Qdrant 与 MySQL 双层作用域/版本复核，首次选择冻结正文副本和 score，同 Snapshot 重放不访问当前 source。摘要和主题/批准目标的生产入口分别位于 `backend/app/modules/agent/conversation_summary.py::ConversationSummaryMaintainer.maintain`（L91-L231）和 `backend/app/modules/agent/memory_item_projection.py::_enqueue_item_vector`（L76-L113）。
- 验证：向量、Outbox、摘要、事实投影与 Plan 聚焦回归 25 项通过；全部 Agent 回归 215 passed、101 warnings，Python 编译、两个新增文件的 Black 检查和 `git diff --check` 通过。
- 提交信息：`打通 Agent 记忆向量生命周期`

## 2026-07-27：让学习掌握度按证据时间衰减

- 目标：完成 `MEM-007` 的学习画像时间治理，保留 Grade 原始聚合与事实审计，同时让 Practice 和 Planning 使用同一可复现有效分数。
- 实现：`backend/app/modules/agent/mastery_decay.py::calculate_effective_mastery`（L26-L58）固定 `mastery-decay-v1` 的 90 天半衰期和不抬高低分的 0.2 地板；`backend/app/modules/agent/memory_selector.py::_mastery_signal`、`_load_frozen_mastery_signals`、`_freeze_mastery_signals`（L191-L303）统一 UTC、版本化审计和 Snapshot 锁内幂等冻结。`load_planning_bundle`（L306-L511）与 `_load_unique_weak_topic` / `load_practice_bundle`（L762-L997）都按 effective score 选取，并冻结题名/别名，原始 score/evidence 不修改。
- 验证：纯函数与 selector/Grade/Plan/Validate 聚焦回归 43 项通过；全部 Agent 回归 210 passed、101 warnings，Python 编译与 `git diff --check` 通过。
- 提交信息：`让学习掌握度按证据时间衰减`

## 2026-07-27：固化临时练习约束的单轮失效边界

- 目标：完成 `MEM-007` 的临时约束收口，证明 difficulty、chapter ordinal 和派生检索参数不会随线程主题继承到下一轮。
- 实现：不新增状态字段；`backend/tests/test_agent_conversation_workflow.py::test_practice_constraints_expire_after_the_current_turn`（L894-L1078）连续执行两个同线程 conversation Run。Turn A 从显式知识点引用生成 hard + 第三章 Snapshot/PracticeBundle，Turn B 只继承主题，新 Snapshot/PracticeBundle/filter 不含旧约束；线程热状态只保留主题确认版本，旧 Snapshot、主题事实与 Artifact 集合不变。
- 验证：TurnUnderstanding、MemorySelector、Conversation workflow 与 Validate 聚焦回归 39 项通过；全部 Agent 回归 203 passed、87 warnings，Python 编译与 `git diff --check` 通过。
- 提交信息：`固化临时练习约束的单轮失效边界`

## 2026-07-27：让线程主题在六个后续轮次后失效

- 目标：推进 `MEM-007`，避免一次旧主题永久控制后续无关请求，同时兼容已经落库但没有确认版本的热状态 JSON。
- 实现：`backend/app/modules/agent/turn_understanding.py::_topic_state_payload`（L539-L554）在显式主题写当前确认版本，继承时保留原版本；`backend/app/modules/agent/context_builder.py::_active_topic_from_state`（L752-L772）在 Router 前只暴露版本差不超过 6 的主题，第 7 轮开始失效，缺标记的旧数据首次兼容，非法标记安全失效。
- 验证：ContextBuilder、Conversation workflow、TurnUnderstanding 聚焦回归 32 项通过；全部 Agent 回归 202 passed、75 warnings，Python 编译与 `git diff --check` 通过。
- 提交信息：`让线程主题按轮次自动失效`
