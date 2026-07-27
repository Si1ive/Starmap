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
