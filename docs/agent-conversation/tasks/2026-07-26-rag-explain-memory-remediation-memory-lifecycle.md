# MEM-007：记忆生命周期与治理

## 状态与设计边界

状态：已完成。增量摘要、Snapshot 冻结、单轮约束、主题 TTL、掌握度衰减、向量生命周期、偏好冲突
与线程删除治理均已实现并验证。

稳定边界是事实模型、作用域、版本和选择协议，不是 Explain/Validate/Grade/Plan 的工作流名称。原始消息、
Artifact、Grade 证据和业务审批保持不可变；排除集、薄弱点、有效掌握度和召回结果均在读取时派生。

## 已完成链路的准确锚点

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理与副作用 | 下游消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 生成当前轮临时约束 | `backend/app/modules/agent/turn_understanding.py` | `_derive_constraints` | L139-L152 | 当前轮原始输入 | 只从本轮文本解析 difficulty、chapter ordinal 与明确重复题意图；随后冻结进本轮理解 | `ensure_turn_memory_snapshot` 创建本轮 Snapshot |
| 重复题意图识别 | `backend/app/modules/agent/turn_understanding.py` | `requests_question_repeat` | L518-L536 | 当前轮原始输入 | 排除“不要/别/不想/无需”等否定表达；无数据库写入 | PracticeBundle 决定是否覆盖排除视图 |
| 主题确认版本写入 | `backend/app/modules/agent/turn_understanding.py` | `_topic_state_payload` | L539-L554 | 线程状态与解析主题 | 显式主题重置确认版本，继承主题保留原版本；更新既有 JSON 热状态 | 下一轮上下文构建读取 TTL |
| 主题 TTL 读取 | `backend/app/modules/agent/context_builder.py` | `_active_topic_from_state` | L752-L772 | 同用户线程热状态 | 版本差不超过 6 时返回去除内部标记的主题；非法或超期数据安全失效 | Router 前的 `AgentRunContext.active_topic` |
| Practice 记忆组装 | `backend/app/modules/agent/memory_selector.py` | `load_practice_bundle` | L857-L997 | run ID、user ID、同线程 Snapshot 与可信事实 | 校验作用域，优先 Snapshot 主题；无主题时读取或冻结有效掌握度与题名/别名，再组装章节、当前轮约束与排除视图 | Validate 检索 query 与 filters |
| 唯一重复题覆盖 | `backend/app/modules/agent/memory_selector.py` | `_apply_explicit_question_repeat` | L1239-L1259 | 当前排除 ID 与本轮理解 | 仅在唯一结构化题目引用时从当前视图移除该 ID；不删除事实 | `PracticeBundle.excluded_question_ids` |
| 对话摘要选择 | `backend/app/modules/agent/context_builder.py` | `ThreadContextBuilder._load_conversation_summary` | L533-L569 | user、thread、原始历史边界与剩余 Token | 只选范围不重叠、未 supersede 且预算可容纳的唯一摘要；双活直接报完整性错误 | Turn Snapshot 冻结内容与版本 |

## 已完成：临时练习约束单轮失效

已把“只从当前原始输入解析”的行为固化为端到端契约，没有新增持久化字段。

验收：同一线程 Turn A 明确要求 `difficulty:hard` 和 `chapter_ordinal:N`，其 Snapshot 与 PracticeBundle
必须包含这两个约束；Turn B 不再出现难度和章节表达时，新 Snapshot、子 Run 的 PracticeBundle 与最终
工具参数均不得继承旧值。线程 `active_topic_json` 只允许保存主题及确认版本，不保存 difficulty、chapter
或 repeat 约束；Turn A 的 Snapshot、Artifact 和可信事实保持不变。

`backend/tests/test_agent_conversation_workflow.py::test_practice_constraints_expire_after_the_current_turn`
（L894-L1078）从显式 `context_ref` 创建 Turn A，经过 Router、不可变 Snapshot 和 Validate child Run 装载
PracticeBundle；Turn B 再从 `active_topic` 继承主题。回归证明 Turn B 的 constraints、difficulty、chapter
和 filters 均为空，线程热状态不含临时约束，Turn A Snapshot、唯一主题事实和 Artifact 集合保持不变。

## 已完成：UserLearningMastery 时间衰减

已保留原始累计分数和 Grade evidence 审计，同时为消费者提供由同一时钟确定性计算的有效掌握度。

- `backend/app/modules/agent/mastery_decay.py::calculate_effective_mastery`（L26-L58）固定
  `mastery-decay-v1`：90 天半衰期，向不高于原分数的 0.2 地板衰减；低分不会被抬高，未来证据年龄钳制
  为 0，naive DATETIME 按 UTC。
- `backend/app/modules/agent/memory_selector.py::_mastery_signal`、`_load_frozen_mastery_signals`、
  `_freeze_mastery_signals`（L191-L303）保留 raw/effective score、证据 ID/时间、年龄和策略版本；锁定 Snapshot
  并在锁内复核后追加 `learning_mastery` Item，同 Snapshot 重放读取副本，不覆盖原始聚合或事实。
- `load_planning_bundle`（L306-L511）与 `_load_unique_weak_topic` / `load_practice_bundle`（L762-L997）
  都以 effective score `< 0.6` 选择薄弱点；新 Grade 更新 `last_graded_at` 后只影响后续 Snapshot。
- `backend/tests/test_agent_mastery_decay.py`（L1-L65）、
  `backend/tests/test_agent_memory_selector.py::test_practice_uses_decayed_mastery_and_freezes_it_per_snapshot`
  （L1174-L1335）和 `test_planning_uses_the_same_effective_mastery_policy`（L1339-L1429）覆盖近期/过期、
  新证据、无证据、用户隔离、来源改名、Snapshot 重放、未来时间与时区边界。

## 已完成：Embedding 与向量生命周期

已只为可治理的增量摘要、显式主题和批准目标建立版本化向量，并保留 workflow 显式选择能力的边界，
没有让 Router 隐式读取全部长期记忆。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理与副作用 | 下游消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 生成版本化任务 | `backend/app/modules/agent/conversation_summary.py`、`backend/app/modules/agent/memory_item_projection.py` | `ConversationSummaryMaintainer.maintain`、`_enqueue_item_vector` | L91-L231、L76-L113 | 新 active source、同作用域旧版本、completed Run | 摘要或记忆项与 pending Outbox 同事务可见；任务只携带 source kind/ID/version 与待删旧 source，不携带正文 | `MemoryOutboxConsumer.process_claimed` |
| 生成与删除向量 | `backend/app/modules/agent/memory_vector.py` | `memory_vector_point_id`、`enqueue_memory_vector_task`、`MemoryVectorLifecycle._delete_sources`、`MemoryVectorLifecycle.process_outbox` | L86-L253 | 版本化任务、当前 MySQL source、Embedding 配置 | 稳定 UUID upsert，成功后删旧点；失效 source 只删点 | Qdrant 当前版本点 |
| 双层过滤召回 | `backend/app/modules/agent/memory_vector.py` | `MemoryVectorLifecycle.recall`、`MemoryVectorLifecycle._hydrate_hit` | L255-L303、L448-L523 | query、user/thread、允许分区、Qdrant 候选 | Qdrant 过滤后重读 MySQL 复核 version/status | `recall_for_snapshot` |
| 冻结与重放 | `backend/app/modules/agent/memory_vector.py` | `MemoryVectorLifecycle.recall_for_snapshot`、`MemoryVectorLifecycle._load_frozen_hits` | L306-L379、L526-L571 | Snapshot/MemoryNeed | 锁 Snapshot 冻结正文/source/score；重放不查当前 source | MEM-008 复现 |

`backend/tests/test_agent_memory_vector.py` 的五项回归（L122-L427）覆盖摘要 upsert 后删除旧点、双层作用域与
版本复核、Snapshot 重放、主题 supersede、向量故障只重试 Outbox，以及 collection 已不存在时删除幂等完成。
向量 payload 不含正文或密钥，公开 SSE 契约未改变。

## 已完成：偏好候选与完整冲突优先级

模型抽取只能产生 candidate，不能直接成为 trusted memory。高、低置信度候选都保持 pending，用户通过
独立治理接口批准后才物化 active `user_preference`，拒绝则形成同 source 重放不可复活的 tombstone。

完整优先级固定为：

```text
用户本轮明确陈述
  > 真实业务事件（含用户批准/拒绝）
  > 模型抽取候选
```

同 key 冲突时，高优先级来源覆盖当前读取视图但不删除低优先级审计记录；同优先级按可信事件时间与稳定
ID 决胜。低置信候选保持 pending，不进入 Router/Bundle；达到阈值仍须进入批准流程后才能 active。
用户拒绝产生可信 rejection/tombstone，后续同 source 重放不得复活；跨用户或跨线程候选不得参与冲突。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理与副作用 | 下游消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 异步抽取 | `backend/app/modules/agent/model_runtime/preference_extractor.py`、`backend/app/modules/agent/preference_memory.py` | `PreferenceExtractionRuntime.extract`、`PreferenceCandidateProjector.process_outbox` | L92-L144、L175-L244 | 根 conversation 的原始 user message、Run 模型配置 | 受控模型最多返回五个结构化候选；重复 key 或非法值失败，Outbox 写完整 source/confidence/scope/extractor/model 审计且统一 pending | 候选治理接口 |
| 用户治理 | `backend/app/modules/agent/router.py`、`backend/app/modules/agent/preference_memory.py` | `get_preference_candidates`、`decide_user_preference_candidate`、`decide_preference_candidate`、`_materialize_approved_preference` | L674-L710、L304-L399 | 当前认证用户、pending candidate、决定 | 同 key 行锁串行；approved 物化长期项并 supersede 旧 active 项，rejected 保留 tombstone；跨用户和终态反向修改无结果 | 偏好冲突选择器 |
| 三层决胜与冻结 | `backend/app/modules/agent/preference_memory.py` | `extract_explicit_preferences`、`_resolve_preference_sources`、`_freeze_preference_bundle`、`load_preference_bundle` | L95-L119、L422-L662 | 本轮明确陈述、批准/拒绝事件、pending 候选、user/thread/Snapshot | 按固定优先级和事件时间/稳定 ID 决胜；selected、dropped reason 与空结果 marker 锁内冻结，同 Snapshot 重放不读新决定 | PlanningBundle / MEM-008 复现 |
| Plan 消费 | `backend/app/modules/agent/memory_selector.py`、`backend/app/modules/agent/workflows/plan.py` | `load_planning_bundle`、`_aggregate_learning_evidence_node`、`_propose_plan_delta_node` | L306-L511、L26-L103 | 冻结偏好、目标、掌握度 | 把选中偏好及 source 加入 PlanningBundle；目标自身分钟数优先，其次使用 `daily_study_minutes`，最后才回退 30 | Plan 草案与审批 Artifact |

`backend/tests/test_agent_preference_memory.py`（L142-L521）、
`backend/tests/test_agent_preference_extractor_runtime.py`（L17-L88）和
`backend/tests/test_agent_plan_worker.py::test_plan_consumes_approved_daily_minutes_preference`（L287-L334）覆盖
完整来源、0.95/0.42 均 pending、批准/拒绝、跨用户/线程隔离、三层冲突、重放冻结与最终 Plan 参数。

## 已完成：删除线程

`backend/app/modules/agent/thread_memory_deletion.py::delete_thread_memory`（L30-L161）在用户归属锁内软删线程，
删除热状态，用 self-supersede tombstone 失效全部摘要，将所有含该 thread 来源的候选置 invalidated，并把线程
项及线程来源用户偏好置 deleted；独立批准的用户级 learning_goal 和 `UserLearningMastery` 明确保留。事务同时
以 `task_key=thread_memory_delete:{user}:{thread}` 写唯一治理 Outbox，payload 冻结所有摘要/记忆项 source version。

`ThreadMemoryDeletionProcessor.process_outbox`（L171-L196）复核 task key、user/thread 和 deleted 状态后调用
`MemoryVectorLifecycle.delete_sources`（L194-L196）。Qdrant 暂时失败只使 Outbox pending/failed；MySQL 来源已先
失效，所以残留向量也会被召回二次复核丢弃。重复删除、向量不存在和 collection 不存在均幂等。

`backend/tests/test_agent_thread_memory_deletion.py`（L220-L350）覆盖跨用户拒绝、重复删除、热状态/摘要/候选/
线程项失效、线程来源用户偏好删除、用户目标与掌握度保留，以及 Qdrant 失败后重试删除稳定点 ID。

## 设计基线

本任务吸收 Codex Memories、Claude Code Memory 与 Hermes Memory 的共同边界：常驻状态小而可信，
大型历史按需选择，派生与工作流解耦。教育域额外需要评分证据、用户作用域和 Snapshot 审计，因此不
直接照搬纯 Markdown 记忆，也不为“排除集”“薄弱点”等场景视图建立专用事实表。
