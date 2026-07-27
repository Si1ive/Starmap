# 2026-07 管理端记忆可观测进展

## 2026-07-27：实现 Run/Snapshot/source 只读观测与复现

- 目标：推进 `MEM-008` 第一阶段，让管理员从具体 Run 查看当前轮理解、冻结 Snapshot、selected/dropped、
  Token 预算、模型调用 ID、实际工具参数和派生任务，并安全对比 source 当前状态。
- 实现：`backend/app/modules/agent/admin_memory.py::get_run_memory_observability`（L135-L257）按 Run 的
  user/thread 作用域聚合直接或 child 绑定的冻结事实；`replay_run_memory_snapshot`（L260-L278）按原 Item 顺序只读复现；
  `get_snapshot_item_source` 与 `_load_current_source`（L281-L449）通过 Item 绑定回查 source，统一隐藏缺失、
  越权和版本漂移。`redact_admin_value`（L44-L65）递归遮蔽凭证。
- 模型审计：`backend/app/modules/agent/model_runtime/config.py::open_agent_model`（L168-L235）为每次生产模型
  会话生成 `model_call_*` ID，并只把不含密钥的模型标识写入 Run metadata。
- 验证：Run 观测、冻结复现、source supersede、跨 Run/版本 404、递归脱敏、既有 Agent 管理路由和模型配置
  回归共 56 项通过；Python 编译与 `git diff --check` 通过。
- 提交信息：`实现管理端记忆快照观测与复现`

## 2026-07-27：实现 Memory Outbox 失败观测与幂等重放

- 目标：推进 `MEM-008` 第二阶段，为管理员提供 Outbox 组合筛选、失败详情和不克隆任务的安全重放。
- 迁移：`backend/alembic/versions/20260727_memory_outbox_error.py::upgrade`（L19-L23）从
  `20260727_thread_memory_delete` 前向添加 nullable `last_error_message`；
  `backend/app/modules/operations/schema_guard.py::verify_database_schema`（L45-L221）同时检查迁移 head 和真列。
- 实现：`backend/app/modules/agent/memory_outbox.py::MemoryOutboxStore.fail`（L160-L195）持久化安全错误；
  `backend/app/modules/agent/admin_memory_outbox.py::list_memory_outbox`（L59-L132）支持 event/status/run/thread/
  source/time 筛选，`get_memory_outbox_detail`（L135-L146）返回脱敏详情，`replay_memory_outbox`（L149-L204）
  锁定原行并写 `audit_logs`，重复请求始终沿用同一个 Outbox ID 和唯一幂等身份。
- 安全：completed 和有效 processing 租约返回 409；过期 processing 可恢复，Consumer 后续仍复核
  user/thread/run/source version；接口没有强制成功、跳过版本或直接写派生记忆旁路。
- 验证：Outbox 筛选/详情/状态门/重复重放/审计、Consumer 失败摘要、迁移图、DDL、schema guard 和路由回归
  共 68 项通过；Python 编译、Alembic 单 head 与 `git diff --check` 通过；真实 MySQL 已从
  `20260727_thread_memory_delete` 前向升级到 `20260727_memory_outbox_error (head)`。
- 提交信息：`实现 Memory Outbox 观测与幂等重放`
