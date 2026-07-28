# Agent Runs、记忆与模型调用审计

## 适用场景

本分卷描述管理员如何从 Thread 级列表进入多轮问答详情，并查看某一 Run 的事件、审批、产物、
冻结 Snapshot、source 当前状态、实际工具参数和模型调用。所有入口继承 `/api/v1/admin` 的管理员认证；
冻结正文只在管理端按不可信纯文本展示，不能进入公共 SSE。

## 会话列表与单轮归并

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 会话状态统计 | `backend/app/modules/agent/admin_router.py` | `get_run_stats` | L251-L287 | Agent Thread 与 root Run | 用窗口函数取每个 Thread 最新 root Run 并按状态聚合 | 会话状态计数；只读数据库 | `AgentRunsPage.fetchStats` |
| 会话分页 | `backend/app/modules/agent/admin_router.py` | `list_all_runs` | L291-L387 | 页码、状态、workflow、用户与时间范围 | 先分页 Thread，再批量聚合 run/turn/event 数 | Thread 级 `items[]`；只读数据库 | `AgentRunsPage.fetchSessions` |
| 管理端契约 | `frontend-admin/src/api/agentRuns.ts` | `AdminAgentSession`、`AdminAgentTurn`、`AdminAgentSessionDetail` | L12-L113 | 后端 Thread/turn JSON | 约束会话摘要、多轮问答和单轮内嵌事实结构 | TypeScript 类型 | 管理端列表与详情页 |
| 旧链接兼容 | `backend/app/modules/agent/admin_router.py` | `_resolve_thread` | L234-L247 | Thread ID 或旧 Run ID | 统一解析为 Thread | Thread；不存在返回 `None` | `get_run_detail` |
| 按轮归并 | `backend/app/modules/agent/admin_router.py` | `_build_turns` | L141-L231 | messages、runs、events、approvals、artifacts | 以 root Run 为边界把 child Run 和事实归入同一轮 | `turns[]`；只读 | `get_run_detail` |
| 会话详情 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L477-L542 | 已解析 Thread | 一次读取五类事实并调用 `_build_turns` | 完整会话详情；不存在传播安全 404 | `AgentRunDetailPage` |
| 前端列表 | `frontend-admin/src/pages/AgentRunsPage.tsx` | `AgentRunsPage` | L58-L340 | 分页会话、统计和 Outbox 标签页 | 筛选、分页并进入 Thread 详情，同时挂载 Outbox 运维面板 | 会话监控表或 Outbox 面板 | 管理员操作 |
| 前端执行流程图 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `buildFlowSteps`、`StepNode`、`RunLane`、`TurnFlow`、`AgentRunDetailPage` | L118-L178、L194-L256、L259-L326、L329-L419、L422-L542 | `session.turns` 中的 Run、按 Run 排序的事件、审批与产物 | 用 `step_id` 配对 started/completed/failed，把步骤期间的工具/交互/落库事件挂到节点；根 Run 与 child Run 用交接线串联。节点内折叠展示执行前 `input`、完成 `output` 和调用证据；`fallback/notice/gate_passed=false` 显示“已降级继续”，只有真实 failed 显示红色 | 可直接定位停点和分支原因的纵向流程图；无 API 或数据库副作用 | 管理员展开证据、重放根 Run 或打开记忆抽屉 |

## Run/Snapshot 观测与只读复现

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 管理 API 入口 | `backend/app/modules/agent/admin_router.py` | `get_run_memory_admin`、`replay_run_memory_admin`、`get_run_memory_source_admin` | L449-L473 | 管理员认证后的 Run ID、可选 Item ID | 把 HTTP 请求交给只读记忆观测服务 | `data` 或安全 404；不运行 workflow | 管理端记忆面板 |
| Run 观测聚合 | `backend/app/modules/agent/admin_memory.py` | `_runtime_context_trace`、`get_run_memory_observability` | L137-L169、L172-L327 | Run ID | 复核 Run/绑定 Snapshot 的 user/thread 归属，读取冻结项、工具事件、步骤和派生 Outbox。相邻 `AgentStep.input_data.variables` 还原临时运行上下文及 added/removed/changed keys；`AgentMemoryTrace` 只表示持久化线程状态、Snapshot、长期项、掌握度、摘要和 Outbox 的前后变化。所有正文经递归脱敏 | `runtime_context_trace` 与 `memory_trace` 两条互不混淆的只读轨迹，以及理解、Snapshot、Token、模型、工具、Outbox | `RunMemoryDrawer` 或复现服务 |
| 事件前后记忆记录 | `backend/app/modules/agent/events.py`、`backend/app/modules/agent/memory_observability.py` | `EventStore.append`、`capture_memory_state`、`record_memory_trace` | L29-L112；L130-L331 | 可诊断 Agent 事件；跳过 `message.delta` | 事件写入前后读取当前分层记忆，按同一 `event_id/event_sequence` 保存 before/after；快照记录失败只记 debug，不阻断对话事件 | `agent_memory_traces`，`changed` 表示前后状态是否不同 | `RunMemoryDrawer` 的记忆变化时间线 |
| Snapshot 复现 | `backend/app/modules/agent/admin_memory.py` | `replay_run_memory_snapshot` | L284-L302 | Run ID | 重用观测结果，按原 Item 顺序组合冻结正文、丢弃原因、Token 预算与实际工具调用 | `frozen_snapshot_read_only`；无模型、工具或写库副作用 | 管理端复现抽屉 |
| source 绑定门 | `backend/app/modules/agent/admin_memory.py` | `get_snapshot_item_source` | L305-L352 | Run ID + Snapshot Item ID | 先要求 Item→Snapshot→Run 同链且 user/thread 一致，再回查 source 并校验版本 | 冻结副本、当前 source、superseded 标记；缺失/越权/版本漂移统一 404 | 管理端 source 对比 |
| source 类型回查 | `backend/app/modules/agent/admin_memory.py` | `_load_current_source` | L355-L473 | Item 的 source kind/ID 与 Run 作用域 | 分类型读取 message、artifact、summary、mastery、memory item 或 preference candidate；用户级 source 校验 user，线程级 source 同时校验 thread | 当前 source DTO；不支持或不匹配返回空 | `get_snapshot_item_source` |
| 响应脱敏 | `backend/app/modules/agent/admin_memory.py` | `redact_admin_value`、`safe_error_summary` | L44-L71 | 任意嵌套管理 DTO 或错误摘要 | 递归移除凭证字段并遮蔽 Bearer、带密码 URL、OpenAI 风格 Key 和 traceback | 脱敏副本；不修改数据库原值 | 所有 Agent 管理响应 |
| 模型调用标识与实际请求 | `backend/app/modules/agent/model_runtime/config.py`、`backend/app/modules/monitoring/llm_calls.py` | `AgentModelSession`、`AuditedOpenAIChatModel`、`open_agent_model`（L59-L144、L251-L327）、`LLMCallRecorder.record_pydantic_response`（L205-L224） | Run ID、调用用途、最终模型配置和每次 Pydantic AI request | 模型会话生成 `model_call_*` Trace 并写无密钥 Run metadata；非流式、流式和结构化重试分别记录真实请求/完整响应/单次 Token/耗时/错误，日志独立事务失败不阻断 Agent | 可按 Run/Trace 关联的 `llm_call_logs` 和模型会话序列 | Run 记忆观测模型区、管理端 LLM 调用页 |
| 前端管理契约 | `frontend-admin/src/api/agentRuns.ts` | `AdminMemorySnapshotItem`、`AdminMemoryTrace`、`AdminMemoryOutbox`、`MemoryOutboxParams`、`getAgentRunMemory`、`getMemoryOutbox`、`replayMemoryOutbox` | L127-L260、L282-L313 | 管理 API JSON 与筛选条件 | 约束 Snapshot、source 对比、模型/工具、Outbox 安全摘要和记忆 Trace 请求 | 类型化 DTO 与管理员认证请求；不执行正文 | `RunMemoryDrawer`、`MemoryOutboxPanel` |
| 上下文与记忆抽屉 | `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx` | `SnapshotItemCard`、`MemoryTraceCard`、`RuntimeContextCard`、`RunMemoryDrawer` | L70-L187、L189-L578 | Run ID 与观测、复现、source API | 用纯中文关系说明区分四层：本轮记忆选择回答“读取什么”，运行上下文回答“步骤间如何传递”，长期记忆时间线回答“可信事实改变什么”，记忆派生任务回答“谁异步写入”。每步仍可对照执行前变量、节点输出和下一步输入 | 无模型或工具副作用；纯文本展示脱敏 JSON；派生失败明确不反向修改 completed Run | 管理员分别判断工作流处理、长期状态变化和派生结果 |
| 不可信纯文本 | `frontend-admin/src/pages/agent-observability/PlainDataBlock.tsx` | `PlainDataBlock` | L7-L15 | 任意脱敏 JSON | 只经 `JSON.stringify` 写入 React 文本节点，不解析 Markdown/HTML | 可滚动、可聚焦的纯文本块 | Snapshot/source/Outbox 审计视图 |

复现坚持“冻结事实优先”：即使当前摘要已被 supersede，复现仍展示 Snapshot Item 的 `frozen_payload`；
source 回查只用于对比当前状态，绝不替代旧 Run 当时消费的正文。若合规删除使 source 不再存在，回查返回
404，但 Snapshot 保留策略允许时仍可展示冻结副本。

## Memory Outbox 列表、失败详情与幂等重放

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 失败摘要落库 | `backend/app/modules/agent/memory_outbox.py` | `MemoryOutboxStore.fail`、`MemoryOutboxConsumer.process_claimed` | L160-L195、L230-L310 | 已认领 Outbox 与投影异常 | SAVEPOINT 回滚派生写后，把递归脱敏且截断的错误写到同一 Outbox；预算内 pending，耗尽 failed | 原 Run 保持 completed；Outbox 重试或终态 | 管理列表 |
| 列表筛选 | `backend/app/modules/agent/admin_memory_outbox.py` | `list_memory_outbox` | L59-L132 | event/status/run/thread/source/time 与分页 | 组合 SQL 条件；source 仅检查约定 payload ID 字段 | 分页 DTO，不返回原始异常 | 管理端 Outbox 表 |
| 详情序列化 | `backend/app/modules/agent/admin_memory_outbox.py` | `serialize_memory_outbox`、`get_memory_outbox_detail` | L29-L56、L135-L146 | Outbox ID | 二次脱敏 payload/error，计算重放资格和阻断原因 | 单条详情或 404；只读 | 详情抽屉 |
| 重放状态门 | `backend/app/modules/agent/admin_memory_outbox.py` | `_replay_state` | L19-L26 | 当前状态、租约到期时间与 now | 禁止 completed 和有效 processing 租约；允许 failed/pending/过期 processing | allowed + block reason | `replay_memory_outbox` |
| 原记录重放 | `backend/app/modules/agent/admin_memory_outbox.py` | `replay_memory_outbox` | L149-L204 | Outbox ID、管理员、IP、User-Agent | `FOR UPDATE` 锁原行，保留 Run/type 或 task key，重置为立即 pending，并追加 `audit_logs` | 不克隆任务；冲突 409；同事务审计 | Worker 再次认领 |
| 运维 HTTP 入口 | `backend/app/modules/agent/admin_router.py` | `list_memory_outbox_admin`、`get_memory_outbox_detail_admin`、`replay_memory_outbox_admin` | L391-L445 | 管理员认证与查询/路径参数 | 转换时间过滤；重放显式解析当前管理员 | 列表、详情、重放 DTO | 管理端页面 |
| 前端记忆派生运维 | `frontend-admin/src/pages/agent-observability/MemoryOutboxPanel.tsx` | `MemoryOutboxPanel` | L45-L422 | event/status/run/thread/source/time 草稿筛选与分页 | UI 统一命名为“记忆派生任务”，解释它位于可信事实与长期记忆之间；应用组合筛选、显示安全错误/重试/租约资格，可进入 Run 或重放原记录 | GET 无副作用；POST 只触发后端状态门，409/失败转提示，不强制成功 | 管理员继续观察 Worker 结果 |

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
4. “上下文为什么变了”：直接在流程图展开目标节点，对照“传入参数与步骤前上下文”“步骤输出与分支依据”；再进入“查看上下文与记忆”，用本轮记忆选择确认来源、运行上下文轨迹确认临时变化、长期记忆时间线确认持久化副作用。无变化事件只是时间定位点，不代表重新选择了记忆。

## 下一步阅读

- 需要看事件和错误如何投影到用户端，转到 `events-timeline-errors.md`。
- 需要看记忆如何选择并冻结，转到 `routing-context-memory.md`。
- 需要看模型配置如何解析，转到 `model-runtime-streaming.md`。
