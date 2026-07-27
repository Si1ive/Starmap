# 2026-07 管理端记忆可观测进展

## 2026-07-28：加固监控采集器自身可靠性

- 目标：修复“监控看起来正常但自身已丢日志/丢 API 统计”的盲区，并让进程资源值覆盖实际子进程负载。
- 服务日志：`backend/app/modules/monitoring/log_sink.py::queue_log`（L36-L48）在队列满时真正淘汰最旧事件并保留最新事件；`_flush_batch`、`_worker_loop`（L124-L202）在数据库失败时累计安全错误并把原批次重新入队。`get_sink_health`（L237-L248）把队列、丢弃、失败和 worker 状态交给管理 API。
- API 统计：`backend/app/modules/monitoring/api_stats.py::_flush_to_db`（L105-L188）写库失败后把快照与并发新数据合并回内存，避免先 clear 后永久丢批；`get_api_stats_health`（L191-L197）公开 pending buckets、失败次数和最后错误。
- 资源采样：`backend/app/modules/monitoring/system_metrics.py::_safe_psutil_sample`（L25-L83）汇总当前进程及递归 children 的 RSS/CPU，单个退出或无权限子进程不会清空整次采样。
- 管理端：`frontend-admin/src/pages/Monitor/Api.tsx::ApiMonitor`（L11-L229）与 `frontend-admin/src/pages/Monitor/Errors.tsx::MonitorErrors`（L28-L261）分别显示指标重试和日志丢弃/flush 告警。
- 验证：监控可靠性、延迟直方图和数据库监控 8 项通过；Python 编译、管理端 lint/build 与 `git diff --check` 通过。
- 提交信息：`加固后台监控采集可靠性`

## 2026-07-28：拆分运行上下文与持久化记忆观测

- 目标：修复 Memory 抽屉把 `changed=false` 误解成“整个工作流上下文没变化”的问题，同时避免为了可见性把关键词、大纲候选和 RAG 证据错误写入长期记忆。
- 后端：`backend/app/modules/agent/admin_memory.py::_runtime_context_trace`（L137-L169）按执行顺序比较相邻 `AgentStep.input_data.variables`，返回每步执行前上下文、节点输出、下一步输入以及 added/removed/changed keys；`get_run_memory_observability`（L172-L327）把它作为独立 `runtime_context_trace` 返回，仍对所有嵌套正文脱敏。数据库只读，无模型、工具或记忆写入副作用。
- 前端：`frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::RuntimeContextCard`（L156-L187）并排展示步骤前、输出和下一步输入；`RunMemoryDrawer`（L189-L598）改名为“Run 上下文与记忆观测”，增加临时运行上下文专区，并把旧时间线明确命名为“持久化记忆变化时间线”。
- 语义：检索焦点、候选章节、RAG 证据和节点中间结果留在 Run/Step 审计；只有线程热状态、Snapshot、长期项、掌握度、摘要或 Outbox 前后不同，持久化 Memory 才标记变化。
- 验证：后端管理观测、路由和工作流引擎 11 项通过；Python 编译、管理端 lint/build 与 `git diff --check` 通过。
- 提交信息：`拆分 Agent 运行上下文与记忆观测`

## 2026-07-28：补齐 Agent Pydantic AI 实际调用审计

- 目标：修复 Run metadata 只能证明打开过模型会话、LLM 调用页却漏掉 Router、指代、Explain、直接回答、摘要和偏好提取真实请求的问题，并完整记录流式正文与结构化重试。
- 实现：`backend/app/modules/agent/model_runtime/config.py::AuditedOpenAIChatModel`（L82-L144）覆盖非流式和流式 request 边界；每次实际 request 用同一 `model_call_*` Trace 记录序列化消息、模型参数、完整响应正文、单次 Token、耗时和异常。流式请求在消费结束后读取 `stream.get()`；结构化输出重试会形成同 Trace 下的多条请求记录。
- 用途：`open_agent_model`（L251-L327）接收显式 purpose；Router、指代消解、证据决策、讲解生成、直接回答、对话摘要和偏好候选提取分别传入稳定用途，Run metadata 与 `llm_call_logs` 可按 Trace 对齐。
- 迁移与管理端：`backend/alembic/versions/20260728_agent_llm_audit.py::upgrade`（L18-L22）为旧日志表安全增加 nullable Trace/Run 字段与索引；管理 API 支持 Trace/Run 过滤，LLM 详情页展示两种关联 ID。
- 验证：66 个模型运行时、流式/非流式审计和迁移回归通过；Python 编译、Alembic 单 head、管理端 lint/build、`git diff --check` 通过。真实 MySQL 已用 `alembic upgrade head` 前向升级到 `20260728_agent_llm_audit`。
- 提交信息：`补齐 Agent LLM 实际调用审计`

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

## 2026-07-27：完成管理端记忆观测与 Outbox 运维界面

- 目标：完成 `MEM-008` 最后一阶段，让管理员在既有 Agent Runs 监控中使用冻结记忆飞行记录器和
  Memory Outbox 运维面，同时保留原有评测重放入口。
- 实现：`frontend-admin/src/pages/AgentRunDetailPage.tsx::TurnDetail`（L98-L278）在每个 Run 卡增加记忆观测入口；
  `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::RunMemoryDrawer`（L85-L420）展示
  Run→Snapshot→Outbox 轨迹、理解/预算、选择账本、模型/工具/派生事实，并只在显式操作后以纯文本显示冻结
  正文或当前 source。`frontend-admin/src/pages/agent-observability/MemoryOutboxPanel.tsx::MemoryOutboxPanel`
  （L38-L396）提供 event/status/run/thread/source/time 组合筛选、失败详情、重放资格和原任务确认重放。
- 安全补全：`backend/app/modules/agent/admin_memory.py::get_run_memory_observability`（L135-L258）把 Outbox
  最后错误经 `safe_error_summary` 后加入 Run 摘要；前端没有 HTML/Markdown 执行器，也不提供强制成功、
  跳过版本校验或直接写派生记忆入口。
- 验证：管理端观测/Outbox/路由后端回归 14 项通过；前端 ESLint 和生产构建通过。无头 Chrome 模拟真实管理
  API 验证桌面 Outbox、桌面/390px Run 抽屉均无横向页面溢出或运行时异常，恶意 HTML 样例未生成 DOM 图片。
- 提交信息：`完成管理端记忆观测与 Outbox 运维界面`

## 2026-07-27：补充工作流节点输入审计

- 目标：让管理员在事件流中同时看到节点开始前收到的上下文，而不是只能从 `step.completed.output` 反推。
- 实现：`backend/app/modules/agent/workflows/contracts.py::ExecutionContext.audit_input` 将运行输入、上下文 key 和变量递归收敛为有上限的 JSON；`backend/app/modules/agent/workflows/engine.py::WorkflowEngine.execute` 在创建 `AgentStep` 和追加 `step.started` 时复用同一快照，因而 `generate_explanation` 等 action 的输入与完成输出可以按 `step_id` 配对。
- 验证：`backend/tests/test_agent_workflow_engine.py::test_engine_persists_public_step_for_timeline_snapshot` 校验事件与数据库步骤输入一致；相关工作流回归通过。
- 提交信息：`补充 Agent 工作流节点输入审计`

## 2026-07-27：建立记忆前后状态观测链

- 目标：回答“这一事件发生前后，Agent 的上下文和长期记忆到底变了什么”，并让 Memory Outbox 页面能回到产生任务的 Run。
- 迁移：`backend/alembic/versions/20260727_memory_trace.py::upgrade`（L20-L45）新增 `agent_memory_traces`，以 Run、事件序号和 before/after JSON 保存不可变观测边界；`backend/app/modules/operations/schema_guard.py::AGENT_REQUIRED_TABLES`（L13-L26）与 `verify_database_schema`（L46-L223）将新表纳入启动结构门禁。
- 实现：`backend/app/modules/agent/memory_observability.py::capture_memory_state`（L130-L304）只读汇总线程热状态、Snapshot、事实事件、长期记忆项、掌握度、摘要和 Outbox；`record_memory_trace`（L307-L331）写前后副本。`backend/app/modules/agent/events.py::EventStore.append`（L29-L112）记录关键事件前后，`backend/app/modules/agent/memory_outbox.py::MemoryOutboxConsumer.process_claimed`（L231-L366）记录投影成功/失败边界；`backend/app/modules/agent/admin_memory.py::get_run_memory_observability`（L136-L281）返回脱敏 `memory_trace`。
- 管理端：`frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::MemoryTraceCard`（L108-L153）展示事件前/后 JSON 与 `changed`；`RunMemoryDrawer`（L155-L520）组织时间线；`frontend-admin/src/pages/agent-observability/MemoryOutboxPanel.tsx::MemoryOutboxPanel`（L45-L423）的带 Run 任务可直接打开该抽屉，并在页首说明“事实→Outbox→Worker→长期记忆”的关系。
- 验证：事件序列/记忆 trace、管理观测、迁移 DDL、schema guard 和相关 Outbox/工作流回归通过（56 passed）；前端 `npm run lint && npm run build`、Python 编译检查与 `git diff --check` 均通过。
- 提交信息：`建立 Agent 记忆前后状态观测链`
