# Agent Runs、记忆与模型调用审计

## 适用场景

本分卷描述管理员如何从 Thread 级列表进入多轮问答详情，并查看 Run 的事件、审批、产物，以及
整个会话按轮次连续变化的上下文记忆。所有入口继承 `/api/v1/admin` 的管理员认证；记忆正文只在
管理端按不可信纯文本展示，不能进入公共 SSE。

## 会话列表与单轮归并

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 会话状态统计 | `backend/app/modules/agent/admin_router.py` | `get_run_stats` | L251-L287 | Agent Thread 与 root Run | 用窗口函数取每个 Thread 最新 root Run 并按状态聚合 | 会话状态计数；只读数据库 | `AgentRunsPage.fetchStats` |
| 会话分页 | `backend/app/modules/agent/admin_router.py` | `list_all_runs` | L291-L387 | 页码、状态、workflow、用户与时间范围 | 先分页 Thread，再批量聚合 run/turn/event 数 | Thread 级 `items[]`；只读数据库 | `AgentRunsPage.fetchSessions` |
| 管理端契约 | `frontend-admin/src/api/agentRuns.ts` | `AdminAgentSession`、`AdminAgentTurn`、`AdminAgentSessionDetail` | L12-L113 | 后端 Thread/turn JSON | 约束会话摘要、多轮问答和单轮内嵌事实结构 | TypeScript 类型 | 管理端列表与详情页 |
| 旧链接兼容 | `backend/app/modules/agent/admin_router.py` | `_resolve_thread` | L234-L247 | Thread ID 或旧 Run ID | 统一解析为 Thread | Thread；不存在返回 `None` | `get_run_detail` |
| 按轮归并 | `backend/app/modules/agent/admin_router.py` | `_build_turns` | L141-L231 | messages、runs、events、approvals、artifacts | 以 root Run 为边界把 child Run 和事实归入同一轮 | `turns[]`；只读 | `get_run_detail` |
| 会话详情 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L477-L542 | 已解析 Thread | 一次读取五类事实并调用 `_build_turns` | 完整会话详情；不存在传播安全 404 | `AgentRunDetailPage` |
| 前端列表 | `frontend-admin/src/pages/AgentRunsPage.tsx` | `AgentRunsPage` | L56-L306 | 分页会话与统计 | 保留原“会话与 Run”统计、筛选、分页和 Thread 详情入口，不再建立记忆派生任务子页 | 单一会话监控表 | 管理员进入会话详情 |
| 前端执行流程图 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `buildFlowSteps`、`StepNode`、`RunLane`、`TurnFlow`、`AgentRunDetailPage` | L116-L176、L192-L257、L260-L304、L306-L384、L386-L514 | `session.turns` 中的 Run、按 Run 排序的事件、审批与产物 | 用 `step_id` 配对 started/completed/failed，把步骤期间的工具/交互/落库事件挂到节点；根 Run 与 child Run 用交接线串联。节点内折叠展示执行前 `input`、完成 `output` 和调用证据；会话工具栏提供唯一记忆入口，Run 卡片不再各自提供入口或回放 | 可直接定位停点和分支原因的纵向流程图；无 API 或数据库副作用 | 管理员展开执行证据，或打开会话记忆抽屉 |

## 会话级上下文记忆变化

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 会话记忆 API | `backend/app/modules/agent/admin_router.py` | `get_conversation_memory_admin` | L455-L462 | 管理员认证后的 Thread ID | 把请求交给会话记忆聚合服务 | `data` 或安全 404；只读数据库，不运行 workflow | `getConversationMemory` |
| 记忆域过滤 | `backend/app/modules/agent/admin_memory.py` | `_conversation_memory_state`、`_changed_memory_sections` | L351-L378 | 任意事件采样状态 | 固定投影线程热状态、Snapshot、可信事实、长期记忆项、掌握度和摘要，并按顶层记忆域计算差异；Outbox 状态、步骤参数和模型输出不算记忆变化 | 六域稳定状态与变化域列表 | Token 统计与会话轮次聚合 |
| 分域与总 Token | `backend/app/modules/agent/admin_memory.py` | `_section_token_total`、`_conversation_section_states` | L383-L424 | 一轮开始前与结束后的六域状态 | 对每个域生成独立的 `changed/before/after`；Snapshot 累计 `selected=true` Item 的持久化 `token_estimate`，其余非空域把脱敏 JSON 按稳定键序列化后复用 `ThreadContextBuilder.estimate_tokens`，空域保持 0 | 固定六条 `sections` 与每域 before/after/delta；只读、无模型 usage 写入 | 按轮连续比较 |
| 按轮连续比较 | `backend/app/modules/agent/admin_memory.py` | `get_conversation_memory_observability` | L427-L528 | Thread ID | 校验 Thread 后按 root Run 建立轮次，把 root/child 的 Trace 归入同一轮；第一轮从空记忆基线建立状态，后续轮次以前一轮最终状态比较当前轮最终状态，并汇总六域估算 Token | 每轮固定六域、`token_totals.before/after/delta`、总变化轮数；无写库、模型或工具副作用 | 会话记忆抽屉 |
| 事件前后记忆记录 | `backend/app/modules/agent/events.py`、`backend/app/modules/agent/memory_observability.py` | `EventStore.append`、`capture_memory_state`、`record_memory_trace` | L29-L112；L130-L331 | 可诊断 Agent 事件；跳过 `message.delta` | 事件写入前后读取当前分层记忆，按同一 `event_id/event_sequence` 保存 before/after；快照记录失败只记 debug，不阻断对话事件 | `agent_memory_traces`，`changed` 表示前后状态是否不同 | `RunMemoryDrawer` 的记忆变化时间线 |
| 响应脱敏 | `backend/app/modules/agent/admin_memory.py` | `redact_admin_value`、`safe_error_summary` | L48-L69、L72-L75 | 任意嵌套管理 DTO 或错误摘要 | 递归移除凭证字段并遮蔽 Bearer、带密码 URL、OpenAI 风格 Key 和 traceback | 脱敏副本；不修改数据库原值 | 所有 Agent 管理响应 |
| 模型调用标识与实际请求 | `backend/app/modules/agent/model_runtime/config.py`、`backend/app/modules/monitoring/llm_calls.py` | `AgentModelSession`、`AuditedOpenAIChatModel`、`open_agent_model`（L59-L144、L251-L327）、`LLMCallRecorder.record_pydantic_response`（L205-L224） | Run ID、调用用途、最终模型配置和每次 Pydantic AI request | 模型会话生成 `model_call_*` Trace 并写无密钥 Run metadata；非流式、流式和结构化重试分别记录真实请求/完整响应/单次 Token/耗时/错误，日志独立事务失败不阻断 Agent | 可按 Run/Trace 关联的 `llm_call_logs` 和模型会话序列 | Run 记忆观测模型区、管理端 LLM 调用页 |
| source 受控回查 | `backend/app/modules/agent/admin_router.py`、`backend/app/modules/agent/admin_memory.py` | `get_run_memory_source_admin`、`get_snapshot_item_source`、`_load_current_source` | L470-L483；L552-L603、L606-L752 | 当前轮 root Run ID 与该 Snapshot Item ID | 先以 Run/Snapshot/Item 联合绑定 user/thread，再按受支持的 `source_kind` 查询对应业务表并脱敏；缺失、越权、版本漂移统一 404 | 本轮冻结副本与当前数据库值；只读数据库 | `MemoryIndexResolver` |
| 前端管理契约 | `frontend-admin/src/api/agentRuns.ts` | `AdminConversationMemoryTurn`、`AdminConversationMemorySection`、`AdminConversationMemory`、`AdminMemorySourceComparison`、`getConversationMemory`、`getAgentRunMemorySource` | L221-L283、L344-L359 | 会话记忆 JSON、Thread ID、Run ID 与 Item ID | 约束固定分域、Token 总量和 source 对比 DTO，并发送管理员认证请求 | 类型化 DTO；不执行正文 | `RunMemoryDrawer` |
| source 索引解析 | `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx` | `snapshotItems`、`MemoryIndexResolver` | L66-L145 | Snapshot `after.items`、root Run ID | 只从快照枚举有 source 绑定且类型受支持的 Item；按钮按 Item 调用受控回查，分别展示冻结值和数据库当前值，404 只显示统一不可用提示 | 纯文本 source 对照；无写库副作用 | 管理员判断索引实际指向内容 |
| 六域记忆抽屉 | `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx` | `MemorySectionPanel`、`TurnMemoryChange`、`RunMemoryDrawer` | L147-L346 | Thread ID 与会话记忆响应 | 展开轮次后第一行显示总上下文 before/after/delta，第二行横排六个模块；模块按钮用 `aria-expanded` 单选或收起，下方面板只展示当前模块的前后纯文本。`changed` 与 token delta 分开表达，正文变化但体量持平时明确提示 | 无模型、工具或写库副作用；Snapshot 面板继续把 after 交给 `MemoryIndexResolver` | 管理员按模块核对上下文变化 |
| 记忆视觉语义 | `frontend-admin/src/pages/agent-observability/agent-observability.css` | `.conversation-memory-turn`、`.conversation-memory-total`、`.conversation-memory-module-rail`、`.conversation-memory-panel` | L701-L1003、L1257-L1281 | 轮次、总量、六域模块和选中面板 DOM | 墨色承载正文、琥珀只表示内容变化、玉色底线只表示当前选择；六模块形成可横向滚动轨道，面板桌面双栏、窄屏单栏，并保留键盘焦点与 reduced-motion | 响应式记忆工作台 | 管理员视觉核对 |
| 不可信纯文本 | `frontend-admin/src/pages/agent-observability/PlainDataBlock.tsx` | `PlainDataBlock` | L7-L15 | 任意脱敏 JSON | 只经 `JSON.stringify` 写入 React 文本节点，不解析 Markdown/HTML | 可滚动、可聚焦的纯文本块 | Snapshot/source/Outbox 审计视图 |

底层单 Run/Snapshot 观测接口仍可用于自动化诊断，但 Agent Runs 页面不再暴露 Run、Snapshot 或
Memory Outbox 回放入口；面向管理员的默认阅读路径只有“会话详情 → 查看上下文记忆变化”。这里的
Token 是排障用的确定性估算而非模型供应商 usage：Snapshot 使用实际冻结选择时保存的估算，其他域使用
与 Context Builder 相同的四字符口径估算脱敏 JSON。内容是否变化始终由前后值比较决定，不能用净 Token
增减替代；等体量重写会显示“内容变化 · token 持平”。

## Memory Outbox 列表、失败详情与幂等重放

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 失败摘要落库 | `backend/app/modules/agent/memory_outbox.py` | `MemoryOutboxStore.fail`、`MemoryOutboxConsumer.process_claimed` | L160-L195、L230-L310 | 已认领 Outbox 与投影异常 | SAVEPOINT 回滚派生写后，把递归脱敏且截断的错误写到同一 Outbox；预算内 pending，耗尽 failed | 原 Run 保持 completed；Outbox 重试或终态 | 管理列表 |
| 列表筛选 | `backend/app/modules/agent/admin_memory_outbox.py` | `list_memory_outbox` | L59-L132 | event/status/run/thread/source/time 与分页 | 组合 SQL 条件；source 仅检查约定 payload ID 字段 | 分页 DTO，不返回原始异常 | 管理端 Outbox 表 |
| 详情序列化 | `backend/app/modules/agent/admin_memory_outbox.py` | `serialize_memory_outbox`、`get_memory_outbox_detail` | L29-L56、L135-L146 | Outbox ID | 二次脱敏 payload/error，计算重放资格和阻断原因 | 单条详情或 404；只读 | 详情抽屉 |
| 重放状态门 | `backend/app/modules/agent/admin_memory_outbox.py` | `_replay_state` | L19-L26 | 当前状态、租约到期时间与 now | 禁止 completed 和有效 processing 租约；允许 failed/pending/过期 processing | allowed + block reason | `replay_memory_outbox` |
| 原记录重放 | `backend/app/modules/agent/admin_memory_outbox.py` | `replay_memory_outbox` | L149-L204 | Outbox ID、管理员、IP、User-Agent | `FOR UPDATE` 锁原行，保留 Run/type 或 task key，重置为立即 pending，并追加 `audit_logs` | 不克隆任务；冲突 409；同事务审计 | Worker 再次认领 |
| 运维 HTTP 入口 | `backend/app/modules/agent/admin_router.py` | `list_memory_outbox_admin`、`get_memory_outbox_detail_admin`、`replay_memory_outbox_admin` | L391-L445 | 管理员认证与查询/路径参数 | 转换时间过滤；重放显式解析当前管理员 | 列表、详情、重放 DTO | 管理端页面 |

重放不是“强制成功”：接口不会调用 projector、修改 derived memory 或绕过 source version 校验；它只恢复原
Outbox 的调度状态。Worker 后续仍走 `MemoryOutboxConsumer.process_claimed` 的 user/thread/run/source 复核。

## 实际模型与工具审计

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Run 执行链 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L104-L275 | 已认领 Run | 统一迁移 running/completed/failed，执行 workflow 并写事件 | Run 状态、事件、模型调用计数 | 会话详情与记忆观测 |
| 工作流步骤链 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | L56-L174 | WorkflowDefinition 与 RunContext | 逐节点写 step started/completed/failed，并把节点开始前的 `input_message/context_keys/variables` 快照同时写入 `AgentStep.input_data` 与 `step.started.input` | agent_steps、agent_events 与可配对的节点输出 | 管理端事件时间线 |
| Memory Outbox 投影边界 | `backend/app/modules/agent/memory_outbox.py` | `MemoryOutboxConsumer.process_claimed` | L231-L366 | 已认领且带 Run 的记忆任务 | 投影/失败状态前后复用记忆状态采集器；成功或失败都追加 `memory.outbox.*` trace，投影失败仍只回写 Outbox 状态 | `agent_memory_traces` 与原 Outbox 状态；不反向修改已完成 Run | Run 记忆变化时间线 |
| 检索实际参数 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | L132-L345 | query、实体类型、章节、难度过滤、排除 ID 与 Run ID | 在真实检索前写 `tool.called.public_metadata`，完成后写结果事件；异常转失败活动 | 可复盘的实际 query/filter/attempt；检索服务副作用 | `get_run_memory_observability` |
| 向量检索调用树 | `backend/app/modules/monitoring/vector_recalls.py`、`backend/app/modules/monitoring/router.py`、`frontend-admin/src/pages/Monitor/VectorRecall.tsx` | `VectorRecallRecorder`（L43-L216）、`list_vector_recalls`（L222-L263）、`list_vector_recall_logs`、`VectorRecallMonitor`（L83-L424） | 原始/实际 query、Trace、Run、activity、attempt、phase、collection 与 Qdrant hits | 独立事务记录每个大纲/内容召回；列表可按 Trace/Run 精确过滤，详情同时展示原始焦点、实际入参和关联 ID。标题优先使用 payload 或 MySQL 水合预览，UUID 仅作技术回退 | `vector_recall_logs` 与只读管理 DTO；记录失败不回滚业务检索 | 管理员核对一次用户活动内的全部底层召回 |

## 错误与安全传播

1. 普通用户路由不注册上述管理接口；`main.py` 为整个 `agent_admin_router` 注入 `require_current_admin`。
2. source 缺失、已删除、版本不符或作用域不匹配都由 `get_snapshot_item_source` 传播相同 404，调用者不能据此枚举其他用户数据。
3. Snapshot 正文、摘要和候选值只作为 JSON/纯文本数据返回；前端不得用 `dangerouslySetInnerHTML` 或 Markdown 执行器渲染。`memory_trace` 的 before/after 也必须先经过脱敏后再展示。
4. 事件、Artifact 和错误摘要在既有会话详情序列化时也经过同一脱敏函数，API key、Authorization、DSN 凭证和 traceback 不进入响应。
5. Outbox 重放沿用数据库唯一幂等身份；重复点击只更新同一行，但每次管理员动作都写独立审计记录。

## 监控采集器自身健康

| 采集器 | 文件 | 符号 | 代码范围 | 入口与处理 | 失败、副作用与最终消费 |
| --- | --- | --- | --- | --- | --- |
| 服务日志 Sink | `backend/app/modules/monitoring/log_sink.py`、`backend/app/modules/monitoring/queries.py` | `queue_log`、`_flush_batch`、`_worker_loop`、`get_sink_health`（L36-L248）、`get_service_log_stats`（L102-L135） | structlog 事件先进入 5000 条队列；队列满时淘汰最旧事件并保留最新故障。批量写库失败把原批次重新入队，同时累计 dropped/flush failure/last error | 日志失败不递归阻断业务；健康状态进入服务日志统计 API，`frontend-admin/src/pages/Monitor/Errors.tsx::MonitorErrors`（L28-L261）显示丢弃与写入告警 |
| API 统计 Flusher | `backend/app/modules/monitoring/api_stats.py`、`backend/app/modules/monitoring/queries.py` | `_flush_to_db`、`get_api_stats_health`（L105-L197）、`get_api_stats_overview`（L281-L417） | HTTP 中间件按小时在内存聚合；flush 前取快照，提交失败时与 flush 期间新数据合并回原桶，下周期重试 | 不再永久丢失整批 API 指标；pending buckets/失败次数/最后错误进入 API 监控响应，`frontend-admin/src/pages/Monitor/Api.tsx::ApiMonitor`（L11-L229）显示告警 |
| 进程树资源采样 | `backend/app/modules/monitoring/system_metrics.py` | `_safe_psutil_sample` | L25-L83 | 读取主机 CPU/内存/磁盘，并递归枚举当前进程 children，逐进程汇总 RSS/CPU；消失或无权限的子进程单独跳过 | 采样值反映 uvicorn/reload/worker 进程树；采集异常仍不阻断应用，最终由系统资源页消费 |

## 排查建议

1. “模型没按选择运行”：先看观测响应的 `model.calls` 和 `final_model_call_id`，再按 config ID 查看模型配置。
2. “检索范围不对”：只看 `tool_calls` 中来自 `tool.called` 的 query、chapter、difficulty、entity type 和 excludes，不用 Router 计划值代替。
3. “历史回答无法复现”：先看 Snapshot 是否存在，再检查 ordered items 的 frozen copy；source 404 只说明当前来源不可回查，不等于旧冻结副本未被消费。
4. “上下文记忆为什么变了”：从会话详情唯一入口打开记忆时间线，先看变化轮次和变化域，再展开该轮对照 before/after。若要解释一次 Run 内部的参数如何传递，返回流程图展开对应节点的输入、输出和调用证据；两种数据不在记忆抽屉重复展示。

## 下一步阅读

- 需要看事件和错误如何投影到用户端，转到 `events-timeline-errors.md`。
- 需要看记忆如何选择并冻结，转到 `routing-context-memory.md`。
- 需要看模型配置如何解析，转到 `model-runtime-streaming.md`。
