# 2026-07 管理端记忆可观测进展

## 2026-07-28：重构会话记忆模块并修复 Token 估算

- 目标：把每轮六域纵向同时展开改为“总上下文 + 横向模块轨道 + 单一详情面板”，并修复非 Snapshot 域内容大幅变化时 Token 始终显示 0 的误导。
- 根因与后端：`backend/app/modules/agent/admin_memory.py::_section_token_total`、`_conversation_section_states`（L383-L424）原先主动忽略五个非 Snapshot 域；现在 Snapshot 继续累计已选 Item 的持久化估算，其余非空域稳定序列化脱敏 JSON 后复用 `ThreadContextBuilder.estimate_tokens`，空字典/数组仍为 0。`get_conversation_memory_observability`（L427-L528）汇总相同口径，但 `changed` 仍由前后值独立比较，因此等体量重写会标记内容变化而 Token 持平。
- 界面：`frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::MemorySectionPanel`、`TurnMemoryChange`、`RunMemoryDrawer`（L147-L346）让每轮第一行展示总上下文、第二行横排六模块，点击一个模块后只在下方展开该域 before/after，再次点击收起；`frontend-admin/src/pages/agent-observability/agent-observability.css`（L701-L1003、L1257-L1281）定义横向滚动、选中态、键盘焦点、移动端单栏和 reduced-motion。
- 回归：`backend/tests/test_agent_admin_memory.py::test_conversation_section_states_estimate_changed_non_snapshot_content`、`test_conversation_section_states_keep_empty_domains_at_zero_tokens`（L427-L466）覆盖非 Snapshot 正文扩张与空域归零；Snapshot selected token 既有行为继续由 `test_conversation_section_states_include_selected_snapshot_token_delta`（L401-L424）保护。
- 验证：`cd backend && venv/bin/pytest tests/test_agent_admin_memory.py -q` 通过（10 passed）；`cd frontend-admin && npm run lint`、`npm run build` 通过（仅保留既有 chunk size 提示）；`git diff --check` 通过。
- 提交信息：`重构会话记忆模块并修复 Token 估算`

## 2026-07-28：完善上下文记忆全量对比与索引解析

- 目标：修正记忆抽屉只展示变化域的误导性表达；每轮固定展示六个域，变化时高亮、未变化时低对比，并展示真实 Snapshot Token 总量变化和 source 索引所指向的数据库内容。
- 后端：该提交当时只累计 `selected=true` Snapshot Item 的持久化 `token_estimate`，非 Snapshot 域保持 0；此历史口径已由本卷顶部“重构会话记忆模块并修复 Token 估算”替代，当前权威实现见 `backend/app/modules/agent/admin_memory.py::_section_token_total`、`_conversation_section_states`（L383-L424）。
- 索引隔离：`backend/app/modules/agent/admin_memory.py::get_snapshot_item_source`、`_load_current_source`（L552-L603、L606-L752）沿用 Run/Snapshot/Item 与 user/thread 绑定，按白名单 source kind 回查真实表；删除、跨作用域和版本漂移继续统一返回 404。`frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::MemoryIndexResolver`（L76-L145）在 Snapshot 内并列展示本轮冻结值与当前数据库值。
- 界面：该提交当时以 `MemorySection` 纵向固定渲染六域；该交互已由本卷顶部提交替代，当前权威入口为 `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::MemorySectionPanel`、`TurnMemoryChange`（L147-L266）。
- 验证：`cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_admin_memory.py` 通过（8 passed）；`cd frontend-admin && npm run build` 与目标文件 ESLint 通过（仅保留既有 chunk size 提示）；`git diff --check` 通过。
- 提交信息：`完善上下文记忆全量对比与索引解析`

## 2026-07-28：合并 Agent Runs 记忆入口并修复无变化时间线

- 目标：保留“会话与 Run”的整体结构，移除“记忆派生任务”子页和全部页面回放入口；把根/子 Run 的多个记忆入口收敛为会话唯一入口，并按轮次只展示上下文记忆变化。
- 根因：`backend/app/modules/agent/events.py::EventStore.append`（L29-L112）采样的是单个事件写入前后状态，而事件写入本身通常不修改记忆，所以底层 Trace 的 `changed=false` 是正确采样结果；旧页面错误地把它解释为整轮“长期记忆无变化”，同时按 Run 切碎了同一轮的 root/child 数据。
- 修复：当前实现由 `backend/app/modules/agent/admin_memory.py::_conversation_memory_state`、`_changed_memory_sections`（L363-L380）排除步骤上下文和 Outbox 状态；`get_conversation_memory_observability`（L427-L528）按 Thread、root Run 和轮次归并 root/child Trace，并以前一轮最终状态连续比较当前轮最终状态。即使每条事件 Trace 自身均为无变化，相邻轮状态 v7→v8 仍会正确报告线程热状态变化。
- 界面：`frontend-admin/src/pages/AgentRunsPage.tsx::AgentRunsPage`（L56-L306）移除双标签页；`frontend-admin/src/pages/AgentRunDetailPage.tsx::RunLane`、`TurnFlow`、`AgentRunDetailPage`（L260-L304、L306-L384、L386-L514）移除 Run 级记忆/回放按钮，只在会话工具栏保留一个入口；`frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::TurnMemoryChange`、`RunMemoryDrawer`（L39-L93、L95-L179）只显示每轮 before/after 与变化域，不再展示运行上下文轨迹、工具/模型审计或派生任务。
- 验证：`cd backend && PYTHONPATH=. venv/bin/pytest -q tests/test_agent_admin_memory.py` 通过（7 passed）；`cd frontend-admin && npm run build` 通过（TypeScript + Vite，仅保留既有 chunk size 提示）；`git diff --check` 通过。
- 提交信息：`合并会话记忆监控并修复变化时间线`

## 2026-07-28：把 Agent Runs 重构为执行流程图

- 目标：让管理员一眼看出用户输入经过哪些根/子 Run、当前卡在哪个步骤、为什么降级或失败，并就地查看每步传入参数、输出、工具调用和记忆入口。
- 流程图：`frontend-admin/src/pages/AgentRunDetailPage.tsx::buildFlowSteps`（L118-L178）按 `step_id` 配对事件并把步骤内事件归组；`StepNode`（L194-L256）区分完成、执行中、等待、降级和真实失败；`RunLane`、`TurnFlow`（L259-L419）用纵向信号轨道串联用户输入、根 Run、child Run 和最终回复。RAG 空命中使用“已降级继续”的琥珀提示，只有 failed 使用红色。
- 记忆语义：当时的界面曾区分“本轮记忆选择→运行上下文→可信事实→长期记忆变化/记忆派生任务”；该 Run 级抽屉与任务子页已由本卷顶部“合并 Agent Runs 记忆入口”提交移除，当前权威入口为 `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::RunMemoryDrawer`（L95-L179）。
- 设计与适配：`frontend-admin/src/pages/agent-observability/agent-observability.css`（L14-L420、L727-L817）定义流程轨道、状态颜色、证据双栏和移动端收敛；真实失败与可恢复降级使用不同语义色，保留键盘可展开和纯文本 JSON。
- 验证：管理端 TypeScript/Vite 构建与 ESLint 通过；无头 Chrome 在 1440×1000 和 390×844 下完成流程图、抽屉和派生任务视觉回归，均无横向溢出、页面异常或未受信任 HTML 执行。
- 提交信息：`将 Agent Runs 重构为执行流程图`

## 2026-07-28：同步结构守卫迁移头验收

- 目标：修正全量回归中仍把 `20260727_memory_trace` 写死为项目 head 的旧测试期望，确保启动结构守卫验收与向量/LLM 审计前向迁移一致。
- 实现：`backend/tests/test_schema_guard.py::test_schema_guard_reads_the_project_migration_heads`（L237-L238）改为断言 `20260728_agent_llm_audit`；生产 `get_expected_revisions` 仍从 Alembic 脚本目录动态读取，没有硬编码或 stamp 旁路。
- 验证：结构守卫定向测试与后端全量测试通过；Alembic current/head 均为 `20260728_agent_llm_audit`，`git diff --check` 通过。
- 提交信息：`同步数据库结构守卫迁移头验收`

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
- 后端：`backend/app/modules/agent/admin_memory.py::_runtime_context_trace`（L141-L190）按执行顺序比较相邻 `AgentStep.input_data.variables`，返回每步执行前上下文、节点输出、下一步输入以及 added/removed/changed keys；`get_run_memory_observability`（L193-L350）把它作为独立 `runtime_context_trace` 返回，仍对所有嵌套正文脱敏。数据库只读，无模型、工具或记忆写入副作用。
- 前端：该提交当时曾在 Run 抽屉并排展示步骤前、输出和下一步输入；这部分重复信息已由本卷顶部“合并 Agent Runs 记忆入口”提交移除，当前步骤参数只在 `frontend-admin/src/pages/AgentRunDetailPage.tsx::StepNode`（L192-L257）消费，记忆抽屉只显示轮次差异。
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
- 实现：`backend/app/modules/agent/admin_memory.py::get_run_memory_observability`（L193-L350）按 Run 的
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
- 实现：该提交当时在每个 Run 卡增加记忆观测入口，并提供 Run→Snapshot→Outbox 轨迹、选择账本、source 对比与任务筛选；这些历史 UI 已由本卷顶部“合并 Agent Runs 记忆入口”提交删除，当前实现只保留 `frontend-admin/src/pages/AgentRunDetailPage.tsx::AgentRunDetailPage`（L386-L514）的会话唯一入口和 `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::RunMemoryDrawer`（L95-L179）的轮次变化视图。
- 安全补全：`backend/app/modules/agent/admin_memory.py::get_run_memory_observability`（L193-L350）把 Outbox
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
- 实现：`backend/app/modules/agent/memory_observability.py::capture_memory_state`（L130-L304）只读汇总线程热状态、Snapshot、事实事件、长期记忆项、掌握度、摘要和 Outbox；`record_memory_trace`（L307-L331）写前后副本。`backend/app/modules/agent/events.py::EventStore.append`（L29-L112）记录关键事件前后，`backend/app/modules/agent/memory_outbox.py::MemoryOutboxConsumer.process_claimed`（L231-L366）记录投影成功/失败边界；`backend/app/modules/agent/admin_memory.py::get_run_memory_observability`（L193-L350）返回脱敏 `memory_trace`。
- 管理端：该提交最初以事件级卡片展示前/后 JSON，并允许从任务列表返回 Run；这些历史组件现已移除。底层 Trace 仍由上述后端锚点保存，当前由 `backend/app/modules/agent/admin_memory.py::get_conversation_memory_observability`（L427-L528）按会话轮次连续比较后交给前端消费。
- 验证：事件序列/记忆 trace、管理观测、迁移 DDL、schema guard 和相关 Outbox/工作流回归通过（56 passed）；前端 `npm run lint && npm run build`、Python 编译检查与 `git diff --check` 均通过。
- 提交信息：`建立 Agent 记忆前后状态观测链`

## 2026-07-28：补齐管理工作台功能页图标

- 目标：让管理侧栏每个功能切换入口都有可辨识图标，重点补齐系统监控“概览”。
- 实现：`frontend-admin/src/components/Sider/index.tsx::menuItems`（L40-L95）为数据采集的任务、数据源、定时任务、日志，以及系统监控概览和基础配置补齐语义图标；路由、权限与选中逻辑不变。
- 验证：`cd frontend-admin && npm run lint && npm run build` 通过；`git diff --check` 通过。
- 提交信息：`补齐管理工作台功能页图标`
