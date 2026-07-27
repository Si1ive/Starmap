# MEM-007：记忆生命周期与治理

## 状态与设计边界

状态：进行中。增量摘要、Snapshot 冻结消费、明确重复题覆盖当前排除视图、线程主题六轮 TTL 和临时
练习约束单轮失效已完成；掌握度衰减、Embedding 生命周期、偏好候选冲突治理和线程删除仍待实现。

稳定边界是事实模型、作用域、版本和选择协议，不是 Explain/Validate/Grade/Plan 的工作流名称。原始消息、
Artifact、Grade 证据和业务审批保持不可变；排除集、薄弱点、有效掌握度和召回结果均在读取时派生。

## 已完成链路的准确锚点

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理与副作用 | 下游消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 生成当前轮临时约束 | `backend/app/modules/agent/turn_understanding.py` | `_derive_constraints` | L139-L152 | 当前轮原始输入 | 只从本轮文本解析 difficulty、chapter ordinal 与明确重复题意图；随后冻结进本轮理解 | `ensure_turn_memory_snapshot` 创建本轮 Snapshot |
| 重复题意图识别 | `backend/app/modules/agent/turn_understanding.py` | `requests_question_repeat` | L518-L536 | 当前轮原始输入 | 排除“不要/别/不想/无需”等否定表达；无数据库写入 | PracticeBundle 决定是否覆盖排除视图 |
| 主题确认版本写入 | `backend/app/modules/agent/turn_understanding.py` | `_topic_state_payload` | L539-L554 | 线程状态与解析主题 | 显式主题重置确认版本，继承主题保留原版本；更新既有 JSON 热状态 | 下一轮上下文构建读取 TTL |
| 主题 TTL 读取 | `backend/app/modules/agent/context_builder.py` | `_active_topic_from_state` | L752-L772 | 同用户线程热状态 | 版本差不超过 6 时返回去除内部标记的主题；非法或超期数据安全失效 | Router 前的 `AgentRunContext.active_topic` |
| Practice 记忆组装 | `backend/app/modules/agent/memory_selector.py` | `load_practice_bundle` | L638-L762 | run ID、user ID、Snapshot 与可信事实 | 校验作用域，优先 Snapshot 主题，读取章节、当前轮约束、掌握度与排除事实；只返回派生视图 | Validate 检索 query 与 filters |
| 唯一重复题覆盖 | `backend/app/modules/agent/memory_selector.py` | `_apply_explicit_question_repeat` | L1004-L1024 | 当前排除 ID 与本轮理解 | 仅在唯一结构化题目引用时从当前视图移除该 ID；不删除事实 | `PracticeBundle.excluded_question_ids` |
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

## 下一单元：UserLearningMastery 时间衰减

目标：保留原始累计分数和 Grade evidence 审计，同时为消费者提供由同一时钟确定性计算的有效掌握度。

待冻结并实现的契约：

- 时间基准使用数据库 UTC 时间；naive 时间按 UTC 解释，测试必须注入或冻结 `now`，禁止依赖本机时区。
- 原始 `mastery_score`、`evidence_count`、`last_evidence_id` 与事实事件不可被定时任务覆盖。
- 衰减只作用于读模型；需要定义半衰期/保留地板、未来时间和无证据的安全行为，并在 Snapshot 中冻结
  消费时的有效分数、原始分数、证据时间与策略版本。
- Practice 的唯一薄弱点回退和 Planning 的学习目标必须消费相同有效分数，避免两个工作流对同一画像
  给出不同结论；新 Grade 证据更新原始聚合后，从新的证据时间重新计算。
- 覆盖近期、过期、新证据、无证据、用户隔离、边界时间和时区回归。

## Embedding 与向量生命周期

目标：只为可治理的摘要和长期记忆项生成向量，并让每个向量都能回到不可变来源版本。

验收边界：

1. Memory Outbox 为合格 source 生成 Embedding；幂等键至少包含 source kind、source ID、source version
   和用户作用域，重复消费执行 upsert 而不是创建重复点。
2. 向量 payload 保存 user ID、可选 thread ID、memory partition、source kind/ID/version 和状态，不保存
   密钥；召回先做 user/thread/scope/version 过滤，再返回候选。
3. 精确实体 ID 查询优先，向量只用于没有结构化实体 ID 的旧摘要/情景记忆；选择结果和丢弃原因冻结
   进 Snapshot，后续 source 更新不能改变旧 Run 的复现内容。
4. 新版本 upsert 成功后删除或失效旧版本向量；source 被 supersede、拒绝或线程删除时通过 Outbox
   幂等删除，删除失败可重试。
5. 向量服务失败只影响 Memory Outbox 状态，不反向失败已完成 Run；正文不得进入公开 SSE。

## 偏好候选与完整冲突优先级

模型抽取只能产生 candidate，不能直接成为 trusted memory。每个候选至少记录 source ID/source kind、
用户与可选线程作用域、结构化 preference key/value、confidence、status、extractor/model version 和时间。

完整优先级固定为：

```text
用户本轮明确陈述
  > 真实业务事件（含用户批准/拒绝）
  > 模型抽取候选
```

同 key 冲突时，高优先级来源覆盖当前读取视图但不删除低优先级审计记录；同优先级按可信事件时间与稳定
ID 决胜。低置信候选保持 pending，不进入 Router/Bundle；达到阈值仍须进入批准流程后才能 active。
用户拒绝产生可信 rejection/tombstone，后续同 source 重放不得复活；跨用户或跨线程候选不得参与冲突。

## 删除线程

删除线程的业务事务必须标记线程级热状态、对话摘要和线程级记忆项失效，并写唯一删除 Outbox；消费者
按 thread/user/source version 删除所有线程向量。重放删除应幂等，即使部分 source 或向量已经不存在也
视为成功。线程删除失败不得留下可被下一轮召回的半活跃记忆。

用户级 `UserLearningMastery` 和已经独立批准、明确标记为用户级的学习目标不随线程删除；任何包含
`thread_id` 的候选、摘要或记忆项都必须删除/失效。测试必须覆盖跨用户同线程样式 ID、重复删除、向量
服务暂时失败后重试，以及用户级画像保留。

## 设计基线

本任务吸收 Codex Memories、Claude Code Memory 与 Hermes Memory 的共同边界：常驻状态小而可信，
大型历史按需选择，派生与工作流解耦。教育域额外需要评分证据、用户作用域和 Snapshot 审计，因此不
直接照搬纯 Markdown 记忆，也不为“排除集”“薄弱点”等场景视图建立专用事实表。
