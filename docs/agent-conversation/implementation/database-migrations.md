# 数据库迁移与结构守卫

## 适用场景

本分卷面向维护者解释 Agent 对话模块为什么必须通过 Alembic 前向迁移推进结构、启动时如何阻断结构漂移，
以及当前 Agent 相关表的关键契约。

## 关键迁移与结构守卫

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 定义模型配置 | `backend/alembic/versions/20260723_agent_model_configs.py` | `upgrade` | L21-L90 | 旧库位于 `20260723_repair_agent_parent` | 创建配置表、唯一约束和索引，回填启用的旧配置 | `agent_model_configs` | 后续模型迁移 |
| 无限 Token 调整 | `backend/alembic/versions/20260724_agent_unlimited_tokens.py` | `upgrade` | L20-L27 | 已存在模型配置表 | 把 `max_tokens` 改为 nullable | 支持“不设上限” | schema guard |
| 时间线事件扩展 | `backend/alembic/versions/20260725_agent_activity.py` | `upgrade` | L34-L41 | 已存在 thread event ENUM | 加入 `workflow.activity.updated` | 工具活动可持久化 | Agent timeline |
| 建立记忆底座 | `backend/alembic/versions/20260726_agent_memory_foundation.py` | `upgrade` | L21-L325 | 已有 Agent 核心表 | 创建热状态、事实、Snapshot/Item、Memory Outbox、掌握度、摘要和长期记忆项 | 八张记忆表及索引/外键 | 幂等约束迁移 |
| Run/type 幂等约束 | `backend/alembic/versions/20260726_memory_outbox_unique.py` | `upgrade`、`downgrade` | L18-L34 | Memory Outbox 真表 | 添加或移除 `(run_id,event_type)` 唯一约束 | 阻止同事实类型并发重复任务 | 偏好候选迁移 |
| 偏好候选治理 | `backend/alembic/versions/20260727_preference_candidates.py` | `upgrade`、`downgrade` | L19-L82 | 唯一迁移 head | 创建带 source/version/status/决定审计的候选表 | `agent_preference_candidates` | 线程治理 Outbox |
| 线程治理任务 | `backend/alembic/versions/20260727_thread_memory_delete.py` | `upgrade`、`downgrade` | L19-L50 | Run/type Outbox | 允许 `run_id` 为空并添加唯一 `task_key`；降级先清治理任务 | 无 Run 的删除任务可幂等入队 | 失败摘要迁移 |
| Outbox 失败摘要 | `backend/alembic/versions/20260727_memory_outbox_error.py` | `upgrade`、`downgrade` | L19-L27 | 已支持治理 task key 的 Outbox | 添加或移除 nullable `last_error_message` | 失败详情可持久化 | ORM / Consumer |
| 记忆前后状态观测 | `backend/alembic/versions/20260727_memory_trace.py` | `upgrade`、`downgrade` | L20-L51 | 已存在 Agent Run/Thread 表 | 创建带 Run、事件序号和 before/after JSON 的不可变观测表及查询索引 | `agent_memory_traces`；保存关键事件与 Memory Outbox 边界 | 管理端记忆时间线 |
| 向量召回关联审计 | `backend/alembic/versions/20260728_vector_recall_trace.py` | `upgrade`、`downgrade` | L19-L35 | 已存在 `vector_recall_logs` 且迁移位于 `20260727_memory_trace` | 前向增加 trace/run/activity/attempt/phase/collection/query kind/raw query 八个 nullable 字段和 Trace/Run 时间索引，旧记录无需回填即可安全升级 | 新记录可还原一次 Agent 工具活动内的大纲和内容召回；降级仅移除新增审计字段 | `VectorRecallRecorder` / 管理端向量召回页 |
| Agent LLM 关联审计 | `backend/alembic/versions/20260728_agent_llm_audit.py` | `upgrade`、`downgrade` | L18-L29 | 已完成向量召回关联迁移 | 给 `llm_call_logs` 增加 nullable `trace_id`、`run_id` 及时间复合索引；旧日志保持可读，无需伪造关联 | 每个真实 Pydantic AI request 可关联模型会话和 Run | `AuditedOpenAIChatModel` / 管理端 LLM 调用页 |
| 用户私有语料所有权 | `backend/alembic/versions/20260728_user_private_corpus.py` | `upgrade`、`downgrade` | L19-L54 | 已完成 Agent LLM 关联审计迁移；既有语料均视作平台资料 | 给 `corpus_files` 增加 nullable UUID owner 外键和 owner/时间索引，把全局 SHA 唯一约束降为普通索引，使不同用户可各自上传相同文件；删除用户时级联删除个人语料 | `owner_user_id IS NULL` 表示平台资料，否则只属于一个学习用户；降级前若存在跨用户同 SHA 数据，恢复唯一约束会显式失败而不静默合并 | 用户资料 API / Agent 检索补全过滤 |
| 启动期门禁 | `backend/app/main.py` | `lifespan` | L91-L107 | 已连接 MySQL | 在 Worker 和调度器前调用 schema guard | 漂移时关闭连接并中止启动 | Worker 启动 |
| 版本与真结构校验 | `backend/app/modules/operations/schema_guard.py` | `AGENT_REQUIRED_TABLES`、`MEMORY_OUTBOX_REQUIRED_COLUMNS`、`verify_database_schema` | L13-L30、L45-L221 | Alembic revision 与 information_schema | 同时核对 head、Agent 表/列、Outbox 失败列和唯一索引、模型 nullable 约束 | 通过返回 revision；失败抛 `DatabaseSchemaError` | FastAPI lifespan |

## 当前 Agent 结构契约

| 数据类型 | 文件 | 符号 | 代码范围 | 入口条件与关键参数 | 数据库副作用与错误传播 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- |
| Run 事实 | `backend/app/modules/agent/models.py` | `AgentRun` | L87-L158 | Thread/user/workflow 与状态机字段 | 单一 Run 事实源；外键/唯一约束错误向事务传播 | Worker、timeline、管理端 |
| 线程时间线投影 | `backend/app/modules/agent/models.py` | `AgentThreadItem`、`AgentThreadEvent` | L202-L261 | thread sequence、visibility 与公开事件 | 单调序号唯一；刷新/SSE 只读这些公开投影 | 用户端与管理端 timeline |
| Step 与内部 Event | `backend/app/modules/agent/models.py` | `AgentStep`、`AgentEvent` | L264-L328 | Run ID、节点、事件序号和 payload | 保存内部执行顺序；同 Run sequence 冲突回滚 | Worker 恢复与管理审计 |
| Run Outbox | `backend/app/modules/agent/models.py` | `AgentRunOutbox` | L331-L355 | Run ID 与调度时间 | HTTP 事务入队，Worker 异步认领；错误保留 pending/failed | Agent Worker |
| Artifact / Input / Approval | `backend/app/modules/agent/models.py` | `AgentArtifact`、`AgentInput`、`AgentApproval` | L402-L484 | Run 产物、补充输入或审批动作 | 分别写业务产物与人工决策；状态错误由服务层阻断 | timeline 与管理端详情 |
| 记忆能力契约 | `backend/app/modules/agent/memory_contracts.py` | `MemoryPartition`、`MemoryNeed`、`MEMORY_NEED_PARTITIONS` | L8-L76 | workflow 声明稳定能力标签 | 无数据库写；非法枚举在构造阶段失败 | selector / workflow |
| 记忆 Snapshot、状态观测与 Outbox | `backend/app/modules/agent/models.py` | `AgentThreadMemoryState`、`AgentMemoryEvent`、`AgentMemorySnapshot`、`AgentMemorySnapshotItem`、`AgentMemoryTrace`、`AgentMemoryUpdateOutbox` | L487-L694 | user/thread/run/source/version、冻结 payload、before/after 状态副本与调度状态 | Snapshot 不可变追加；Trace 保存事件边界状态；Outbox 用 Run/type 或 task key 幂等，失败摘要只存脱敏文本 | Memory selector、Consumer、管理员运维 |
| 掌握度与长期项 | `backend/app/modules/agent/models.py` | `UserLearningMastery`、`AgentConversationSummary`、`AgentMemoryItem` | L697-L806 | 可信 Grade、消息序列范围、事实 source | 聚合分数、版本化摘要、active/superseded/deleted 长期项 | Validate / Plan / conversation |
| 偏好候选 | `backend/app/modules/agent/models.py` | `AgentPreferenceCandidate` | L807-L884 | user/source/key 与治理决定 | 同 source/key 唯一；拒绝和失效不能被重放复活 | preference selector 与用户治理 |

## 故障定位顺序

1. 先检查 `alembic_version` 是否等于当前 head `20260728_user_private_corpus`，禁止用 `alembic stamp head` 掩盖缺失迁移。
2. 若应用层已有字段但数据库报列不存在，执行 `alembic upgrade head`，再走 `verify_database_schema` 同时确认真列。
3. Memory Outbox 没有失败详情时，检查 `last_error_message` 真列以及 `MemoryOutboxStore.fail` 是否收到异常摘要。
4. 工具活动无法恢复时，确认 `workflow.activity.updated` 已进入数据库 ENUM。
5. 模型“无限输出 Token”不生效时，确认 `max_tokens` 允许 NULL，再核对 ORM `evaluates_none()`。
6. `agent_memory_update_outbox` 缺表的实际诊断和修复证据见 `../incidents/2026-07-27-memory-outbox-table-missing.md`。

## 下一步阅读

- 管理端如何筛选、查看和重放 Outbox：`admin-observability.md`。
- 记忆表的业务选择与冻结：`routing-context-memory.md`。
