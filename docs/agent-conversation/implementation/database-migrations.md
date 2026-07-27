# 数据库迁移与结构守卫

## 适用场景

本分卷面向维护者解释 Agent 对话模块为什么必须通过 Alembic 前向迁移推进结构、启动时如何阻断结构漂移，
以及当前 Agent 相关表的关键契约。

## 关键迁移与结构守卫

| 执行阶段 | 文件 | 符号 | 职责 |
| --- | --- | --- | --- |
| 定义模型配置前向迁移 | `backend/alembic/versions/20260723_agent_model_configs.py` | `upgrade` | 创建 `agent_model_configs`，建立唯一约束和索引，并回填启用的旧模型配置 |
| 时间线事件枚举扩展 | `backend/alembic/versions/20260725_agent_activity.py` | `upgrade` | 给 thread event ENUM 增加 `workflow.activity.updated`，使工具活动能持久化 |
| 记忆基础表前向迁移 | `backend/alembic/versions/20260726_agent_memory_foundation.py` | `upgrade` | 创建线程热状态、记忆事件、快照、快照项、记忆 Outbox、掌握度、对话摘要和长期记忆项表，作为后续记忆读写的统一结构底座 |
| Memory Outbox 幂等约束 | `backend/alembic/versions/20260726_memory_outbox_unique.py` | `upgrade`（L18-L25）、`downgrade`（L28-L34） | 为 `agent_memory_update_outbox(run_id, event_type)` 增加 `uk_agent_memory_outbox_run_event`，由数据库阻止同一事实类型的并发重复任务；降级只移除该约束 |
| 无限 Token 结构调整 | `backend/alembic/versions/20260724_agent_unlimited_tokens.py` | `upgrade` | 把 `agent_model_configs.max_tokens` 改为 nullable，支持“不设上限” |
| 启动期结构校验 | `backend/app/main.py` | `lifespan` | FastAPI 启动时在 Worker、调度器之前执行 schema guard |
| 版本与真表校验 | `backend/app/modules/operations/schema_guard.py` | `AGENT_REQUIRED_TABLES`（L13-L25）、`verify_database_schema`（L43-L191） | 同时核对 Alembic head、`agent_runs` 必需列、模型配置表、八张记忆基础表、Memory Outbox 复合唯一索引和模型列约束；任一漂移都在 Worker 启动前抛 `DatabaseSchemaError` |

## 当前 Agent 结构契约

| 数据类型 | 文件 | 符号 | 契约 |
| --- | --- | --- | --- |
| Run / Step / Event / Artifact / Approval / Input | `backend/app/modules/agent/models.py` | `AgentRun` 至 `AgentApproval` 等模型 | 对话事实、执行状态、事件顺序、审批和 Artifact 都以数据库表为单一事实源 |
| 线程时间线项 | `backend/app/modules/agent/models.py` | `AgentThreadItem`、`AgentThreadEvent` | 用户端与管理端刷新时依赖这些投影恢复消息和工作流时间线 |
| 模型配置空值 | `backend/app/modules/agent/models.py` | `AgentModelConfigRecord.max_tokens` | 显式 `None` 必须保存为 SQL `NULL`，不能被 ORM 默认值覆盖 |
| Outbox | `backend/app/modules/agent/models.py` | `AgentOutbox` | HTTP 事务只负责入队，LLM 调用与 workflow 执行在 Worker 中异步完成 |
| 记忆分区与能力标签 | `backend/app/modules/agent/memory_contracts.py` | `MemoryPartition`、`MemoryNeed`、`MEMORY_NEED_PARTITIONS` | 长期记忆按事实分区建模，workflow 只声明能力标签，不把 explain/validate/grade/plan 名称写死进存储契约 |
| 记忆基础表 | `backend/app/modules/agent/models.py` | `AgentThreadMemoryState`、`AgentMemoryEvent`、`AgentMemorySnapshot`、`AgentMemorySnapshotItem`、`AgentMemoryUpdateOutbox`（L612-L650）、`UserLearningMastery`、`AgentConversationSummary`、`AgentMemoryItem` | 热状态、快照、Outbox、掌握度和长期记忆项具备明确表结构；Memory Outbox 已冻结每 Run/事件类型唯一约束，生产者重放由数据库兜底 |

## 故障定位顺序

1. 先检查 `alembic_version` 是否等于当前 head，禁止用 `alembic stamp head` 掩盖缺失迁移。
2. 若应用层提示字段存在但数据库报列不存在，优先跑 `verify_database_schema` 路径，确认是否漏跑迁移。
3. 如果是 Agent 事件或时间线恢复异常，确认 `workflow.activity.updated` 是否已在数据库枚举中存在。
4. 如果是模型“无限输出 Token”行为不生效，确认数据库列是否允许 `NULL`，再核对 ORM `evaluates_none()` 是否生效。
5. 如果是分层记忆功能启动失败，先确认已升级到当前 head `20260726_memory_outbox_unique`，再检查新增记忆表和 `uk_agent_memory_outbox_run_event` 是否存在；schema guard 会主动检查两者，禁止用 stamp 掩盖漏迁移。
6. `agent_memory_update_outbox` 缺表的实际诊断、升级证据和 Worker 重放结果见 `../incidents/2026-07-27-memory-outbox-table-missing.md`。

## 下一步阅读

- 要看管理端和模型配置如何消费这些结构，转到 `architecture/admin-and-model-config.md`。
- 要回查长期记忆新增表的任务边界，转到
  `../tasks/2026-07-26-rag-explain-memory-remediation-completed.md` 的 `MEM-002`。
