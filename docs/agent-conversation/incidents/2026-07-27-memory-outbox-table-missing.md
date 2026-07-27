# Memory Outbox 真表缺失导致 Worker 循环扫描失败

## 现象

2026-07-26 运行中的 Agent Worker 在扫描记忆任务时反复收到 MySQL 1146：

```text
Table 'starmap.agent_memory_update_outbox' doesn't exist
```

失败 SQL 来自 `MemoryOutboxStore._expire_exhausted_processing`，因此每轮 Worker 扫描都会先回滚事务，
再由 `AgentWorker.start` 记录“Worker 扫描异常”。Run Outbox 与 Memory Outbox 共用后台循环，持续报错会让
记忆事实无法异步派生。

## 根因证据

| 检查 | 实际结果 | 结论 |
| --- | --- | --- |
| `alembic heads` | `20260726_memory_outbox_unique` | 代码要求已经包含记忆基础表和唯一约束 |
| `alembic current -v` | `20260725_agent_activity` | 应用连接的 `localhost:3306/starmap` 漏跑两份迁移 |
| Worker 报错表 | `agent_memory_update_outbox` | 正是 `20260726_agent_memory_foundation` 创建的表 |

根因是代码更新后没有对同一数据库执行 `alembic upgrade head`，不是 Outbox SQL 或状态机错误，也不是
Alembic 已到 head 后的真表漂移。

## 修复与执行链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 错误传播/消费位置 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 创建 Outbox 表 | `backend/alembic/versions/20260726_agent_memory_foundation.py` | `upgrade` | L152-L192 | revision `20260725_agent_activity` | 创建 `agent_memory_update_outbox`、外键及扫描索引 | MySQL 新增真表 | DDL 失败会中止 upgrade，禁止 stamp |
| 冻结幂等键 | `backend/alembic/versions/20260726_memory_outbox_unique.py` | `upgrade` | L18-L25 | 已存在的 Outbox 表 | 添加 `(run_id,event_type)` 唯一约束 | `uk_agent_memory_outbox_run_event` | DDL 失败保留完整迁移错误 |
| 启动期真表门禁 | `backend/app/modules/operations/schema_guard.py` | `verify_database_schema` | L43-L191 | Alembic revision、information_schema 表/列/索引 | 校验九张 Agent 必需表、Memory Outbox 复合唯一索引和模型列约束 | 校验通过才允许启动 Worker | 缺表/缺索引抛 `DatabaseSchemaError`，由 FastAPI lifespan 中止启动 |
| Worker 原始复现 | `backend/app/modules/agent/memory_outbox.py` | `MemoryOutboxStore._expire_exhausted_processing`、`MemoryOutboxStore.scan_due` | L51-L91 | 到期 processing/pending 任务 | 先把耗尽重试的任务置 failed，再查询可认领任务 | due 任务列表 | 数据库错误向 Worker 扫描循环传播 |

实际执行 `alembic upgrade head` 后，数据库依次升级到记忆基础迁移和唯一约束迁移。随后确认：

- `alembic current -v` 为 `20260726_memory_outbox_unique (head)`；
- 真表 `agent_memory_update_outbox` 存在；
- `uk_agent_memory_outbox_run_event` 包含 `run_id`、`event_type` 两列；
- 在回滚诊断事务中重放 `MemoryOutboxStore.scan_due` 成功，`due_count=0`；
- 增强后的真实数据库 schema guard 返回 `schema_guard_ok=20260726_memory_outbox_unique`。

## 防止复发

启动门禁现在不再只相信 revision 和 `agent_model_configs`：即使数据库被错误 stamp、从旧备份恢复或有人
手工删除记忆表，应用也会在 Worker 启动前失败，并明确列出缺失表或唯一约束。标准发布仍必须先运行
`alembic upgrade head`；门禁是漂移检测，不替代迁移。
