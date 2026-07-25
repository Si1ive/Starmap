# 第一部分：Agent 对话模块技术实现全景图

## 1. 系统目标

Agent 对话模块不仅负责普通聊天，还要把学习任务编排成可恢复、可审计、可交互的工作流。
它需要同时满足以下目标：

- 用户消息提交后可靠落库，不能因 Redis 或浏览器断开而丢失。
- 普通问答和讲解、练习、批改、计划等业务工作流使用统一时间线展示。
- 长任务由后台 Worker 执行，支持租约、重试、等待用户输入和等待审批。
- 用户只看到公开消息和公开工作流状态，内部推理与敏感上下文不直接暴露。
- 管理员能够查看运行状态、错误和模型调用情况。
- 模型供应商与具体模型可配置，并逐步支持用户选择已上线模型。

## 2. 端到端全景

```text
用户端 AgentPage
  │
  ├─ 创建/选择 Thread
  ├─ GET 已上线且可选的模型，并默认选中管理员默认项
  ├─ POST 一轮消息，明确携带本轮 model_config_id
  ├─ GET 时间线快照
  └─ SSE 接收增量事件
          │
          ▼
FastAPI Agent Router
  │
  ├─ 身份认证与 thread 所有权校验
  ├─ AgentTimelineService 原子创建消息/run/outbox
  └─ ThreadEventStore 生成统一 cursor
          │
          ▼
MySQL 持久化事实
  ├─ agent_model_configs
  ├─ agent_threads / agent_messages / agent_thread_items
  ├─ agent_runs / agent_steps / agent_events
  ├─ agent_thread_events
  └─ agent_run_outbox / checkpoint / input / approval / artifact
          │
          ▼
Agent Worker
  ├─ 扫描并认领 outbox
  ├─ 获取 run 租约
  ├─ 调用 Workflow Registry / Engine
  ├─ 解析 Run 指定模型或管理员默认模型
  ├─ 调用模型运行时与领域工具
  └─ 持久化状态、消息、事件和产物
          │
          ├───────────────► LLM Provider
          └───────────────► 学习领域服务 / 检索工具

管理员端
  ├─ 系统监控
  │   └─ Agent Runs 监控 ──► /api/v1/admin/agent-runs ──► agent_runs / agent_events / artifacts
  ├─ 系统配置
  │   ├─ 基础配置（不再维护旧问答 LLM）
  │   └─ Agent 模型配置 ──► /api/v1/admin/agent-models
  │         └─ 创建/编辑、上下线、用户可选、默认模型、连通性测试
  └─ 基础设施状态 ──► MySQL / Redis / Qdrant
```

Redis 在当前 Agent 核心执行链路中不是事实来源。Agent 的可靠任务唤醒依赖 MySQL outbox
和周期扫描，因此 Redis 短暂不可用不应导致已提交的对话丢失；Redis 主要服务于缓存、其他
任务队列或实时能力的辅助部分。

## 3. 主要代码边界

| 层次 | 主要位置 | 职责 |
| --- | --- | --- |
| 用户端页面 | `frontend/src/pages/AgentPage.tsx` | thread 选择、消息提交、时间线加载和 SSE 生命周期 |
| 用户端组件 | `frontend/src/features/agent/` | 消息流、模型选择输入框、内嵌工作流、时间线状态归并，并复用全局设计 token |
| 用户端 API | `frontend/src/api/agent.ts` | Agent HTTP/SSE 契约、公开模型列表、错误解析和前端类型 |
| HTTP 接口 | `backend/app/modules/agent/router.py` | 认证、参数校验、thread/run/timeline/event API |
| 对话时间线 | `timeline.py`、`thread_events.py` | 原子创建一轮对话、公开投影和统一事件 cursor |
| 执行调度 | `outbox.py`、`worker.py` | 可靠任务扫描、线程串行化、认领、租约和重试 |
| 工作流 | `workflows/` | conversation 路由与 explain/validate/grade/plan 等工作流 |
| 模型运行时 | `model_runtime/` | 模型适配、结构化路由、回答生成和策略门禁 |
| 模型配置 | `model_configs.py`、`model_config_router.py` | 多模型管理、默认模型约束、公开模型列表和密钥脱敏 |
| 上下文 | `context_builder.py` | 对话历史、权限范围、学习上下文和 root run 完整性 |
| 持久化模型 | `models.py` | Agent 领域表、状态和索引定义 |
| 管理员接口 | `admin_router.py` | 在 `/api/v1/admin/agent-runs` 下提供 Run 查询、详情、统计与管理能力 |
| 管理员页面 | `frontend-admin/src/pages/AgentRunsPage.tsx`、`AgentModelsPage.tsx` | 运行监控，以及多模型创建、编辑、状态控制和连通性测试 |
| 管理端导航 | `frontend-admin/src/components/Sider/index.tsx`、`Header/index.tsx`、`router/index.tsx` | 把 Agent Runs 归入系统监控，把 Agent 模型配置归入系统配置，并保持原 URL |
| 管理端基础配置 | `frontend-admin/src/pages/Settings/index.tsx` | 维护任务型 LLM、向量化和解析器配置；不再展示或提交旧问答 LLM |
| 管理员模型 API | `frontend-admin/src/api/agentModels.ts` | 管理端模型接口类型、请求封装和测试超时策略 |

## 4. 代码执行全景总览

本节按真实调用顺序记录入口、函数、事务和异步交接点。代码范围以当前版本为准；定位故障时，
先找到对应入口，再沿“下一步”逐行向后追，不要只根据页面现象猜测后端模块。

### 4.1 后端启动、数据库迁移与用户模型列表

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `docker-compose.podman.yml` | `services.backend.command` | L190-L190 | 后端容器启动 | 先执行 `alembic upgrade head`，成功后才启动 Uvicorn | 数据库推进到当前 head；迁移失败则后端不启动 | `20260723_agent_model_configs.upgrade` |
| 2 | `backend/alembic/versions/20260723_agent_model_configs.py` | `upgrade` | L21-L90 | 旧数据库位于 `20260723_repair_agent_parent` | 创建 `agent_model_configs`、唯一约束和索引，并从启用的 `system_configs.llm` 回填默认模型 | 新表和可选默认记录落库，Alembic revision 前移 | `20260724_agent_unlimited_tokens.upgrade` |
| 3 | `backend/alembic/versions/20260724_agent_unlimited_tokens.py` | `upgrade` | L20-L27 | 数据库已存在 `agent_model_configs` | 把 `max_tokens` 从 `NOT NULL` 改为 nullable，保留已有数字 | 数据库可持久化代表“不设上限”的 SQL `NULL` | `20260725_agent_activity.upgrade` |
| 4 | `backend/alembic/versions/20260725_agent_activity.py` | `upgrade` | L34-L41 | thread event 表使用旧 ENUM | 增加 `workflow.activity.updated` | 数据库可持久化真实工具活动 | `lifespan` |
| 5 | `backend/app/main.py` | `lifespan` | L77-L107 | FastAPI 进程启动 | 连接 MySQL，并在调度器、日志 sink 和 Worker 启动前执行结构校验 | 结构正确则继续启动；版本落后或约束漂移则关闭连接并抛出 `DatabaseSchemaError` | `verify_database_schema` |
| 6 | `backend/app/modules/operations/schema_guard.py` | `verify_database_schema` | L29-L138 | 当前 `AsyncSession` 与迁移图 heads | 比较 `alembic_version`，检查 `agent_runs` 必需列、`agent_model_configs` 真表及 `max_tokens` nullable 约束 | 返回当前 revisions；结构漂移时明确提示执行 `alembic upgrade head` | Agent 页面加载模型 |
| 7 | `frontend/src/pages/AgentPage.tsx` | `AgentPage.loadModels` | L78-L95 | Agent 页面挂载或用户点击重试 | 请求公开模型列表，保留仍有效的选择，否则选默认项或第一项 | 更新 `models`、`selectedModelId`、loading 和错误状态 | `listSelectableAgentModels` |
| 8 | `frontend/src/api/agent.ts` | `listSelectableAgentModels` | L358-L362 | 浏览器认证态 | 请求 `GET /api/v1/app/agent/models` | 返回公开模型数组，不包含 API Key、Base URL 等凭据 | `list_selectable_models` |
| 9 | `backend/app/modules/agent/router.py` | `list_selectable_models` | L55-L63 | 当前用户和请求级数据库 session | 创建配置服务并查询公开记录 | 返回 `{items}` | `AgentModelConfigService.list_public` |
| 10 | `backend/app/modules/agent/model_configs.py` | `AgentModelConfigService.list_public` | L168-L180 | `agent_model_configs` 表 | 筛选 `online=true` 且 `selectable=true`，默认模型优先、显示名称次序 | ORM 记录列表 | `AgentPage.loadModels` 消费响应 |

这里的关键边界是：模型选择器不是静态配置。页面每次加载都会查询真实数据库；因此出现
MySQL `1146 Table '...agent_model_configs' doesn't exist` 时，根因在数据库迁移状态，不在下拉框
字段映射。不能让接口静默返回空列表，也不能手工建一个不完整的同名表。

### 4.2 用户发起一轮对话直到前端显示结果

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `frontend/src/pages/AgentPage.tsx` | `AgentPage.handleSend` | L101-L144 | 输入文本、thread ID、`selectedModelId` | 空会话先建 thread，再把模型 ID 交给上下文 store；模型失效时保留输入并刷新列表 | 开始一次 turn 请求 | `AgentProvider.sendTurn` |
| 2 | `frontend/src/store/agent-context.tsx` | `AgentProvider.sendTurn` | L425-L446 | thread、内容和 `modelConfigId` | 生成 `client_message_id`，转换为后端 `model_config_id`；成功后刷新时间线并确保 SSE 已连接 | `TurnCreateResponse` 和最新时间线 | `createTurn` |
| 3 | `frontend/src/api/agent.ts` | `createTurn` | L364-L375 | `TurnCreateRequest` | POST `/api/v1/app/agent/threads/{thread_id}/turns` | HTTP 201 或带 `detail` 的 API 错误 | `create_turn` |
| 4 | `backend/app/modules/agent/router.py` | `create_turn` | L167-L212 | 已认证用户、请求体、请求级 session | 转换模型/幂等/线程异常为 400、409、404；其余工作委托给时间线服务 | 用户消息、root run 和 cursor | `AgentTimelineService.create_turn` |
| 5 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService.create_turn` | L166-L317 | user/thread/content/client ID/model ID | 锁定 thread，验证模型仍可选；原子创建用户消息、conversation root run、时间线项、run/thread 事件和 outbox | 多表写入尚处于同一事务，Run 状态为 `queued` | `OutboxStore.enqueue` 后返回路由 |
| 6 | `backend/app/modules/agent/outbox.py` | `OutboxStore.enqueue` | L24-L44 | root run ID | 新增 `pending` outbox 并 flush | 可靠 Worker 唤醒事实 | 请求 session 退出 |
| 7 | `backend/app/db/mysql.py` | `MySQLClient.session` | L131-L155 | 路由依赖创建的 session | 正常退出统一 commit；异常统一 rollback 并继续抛出 | 消息、Run、事件和 outbox 同时可见，或全部回滚 | Worker 异步扫描 |
| 8 | `backend/app/modules/agent/worker.py` | `start_worker` | L397-L423 | FastAPI lifespan 启动 | 保存 `asyncio.Task` 强引用并注册异常退出回调 | 后台 `AgentWorker.start` 循环存活 | `AgentWorker.start` |
| 9 | `backend/app/modules/agent/worker.py` | `AgentWorker.start` | L366-L384 | 扫描间隔 | 周期调用 `scan_and_process` | 每批处理完成后继续下一轮扫描 | `AgentWorker.scan_and_process` |
| 10 | `backend/app/modules/agent/worker.py` | `AgentWorker.scan_and_process` | L307-L364 | pending outbox | 先筛选可执行任务，再为每个 run 创建独立 session、原子认领 outbox | 单个 run 的 session 与其他 run 隔离 | `AgentWorker.process_run` |
| 11 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run` | L100-L267 | 已认领 run | 获取租约、提交 running 状态、恢复 checkpoint、执行工作流；完成后创建 artifact、更新 Run、写事件 | Run 进入 running、waiting、completed 或 failed | `WorkflowEngine.execute` |
| 12 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | L27-L212 | workflow 定义、执行上下文和 Run | 逐节点创建 step；在开始、完成或失败后提交真实进度；累计模型调用并在 WAITING 时保存 checkpoint | SSE 执行期间可见的步骤链、最终 `NodeResult` 或可恢复等待点 | conversation 节点或业务 child workflow |
| 13 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | L42-L102 | 当前 conversation run | 构建受控线程上下文，完整调用结构化 Router，记录上下文审计并选择 direct answer / clarify / child workflow | 下一节点名称与路由决策；Router 自身不流式 | `_direct_answer_node` 或 `_dispatch_workflow_node` |
| 14 | `backend/app/modules/agent/workflows/conversation.py` | `_direct_answer_node` | L104-L142 | `AgentRunContext` | 把 100ms 聚合后的正文 delta 写入事件并 commit；最终把完整输出包装成 message artifact | 可实时读取的 `message.delta` 与最终 assistant 内容 | `DirectAnswerRuntime.answer` |
| 15 | `backend/app/modules/agent/model_runtime/config.py` | `open_agent_model` | L157-L208 | 当前 run ID | 读取 Run 指定模型；否则取数据库默认/旧配置/环境回退，创建独立 `AsyncOpenAI`，并把实际模型信息固定写回 Run 元数据 | 隔离的模型 session；退出时关闭客户端 | Router 或 Answer runtime 的模型调用 |
| 16 | `backend/app/modules/agent/model_runtime/answer.py` | `DirectAnswerRuntime.answer` / `DirectAnswerRuntime._run_stream` | L91-L204 | 当前输入、历史、模型 session、token 预算和 delta callback | 调用 Pydantic AI `run_stream` 与 `stream_output(debounce_by=0.1)`；只发布延续已发布前缀的 `content` 增量 | 多个正文 delta 和最终完整 `DirectAnswerOutput` | conversation 节点回调与 artifact |
| 17 | `backend/app/modules/agent/events.py` | `EventStore.append` | L24-L69 | run 事件类型和 payload | 分配 run 内序号、写 `agent_events`，再触发公开 thread 投影 | 内部事件与公开事件保持关联 | `ThreadEventStore.project_run_event` |
| 18 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event` / `ThreadEventStore._project_message_event` | L102-L204 / L232-L337 | Run 事件 | 将公开消息、工作流步骤和工具活动写入 `agent_messages`、`agent_thread_items`、`agent_thread_events` | 可按统一 cursor 消费的时间线事实 | `stream_thread_events` |
| 19 | `backend/app/modules/agent/router.py` | `stream_thread_events` | L280-L348 | thread ID 与 `after_sequence` | 校验所有权，循环补查事件并输出 SSE heartbeat/事件 | `StreamingResponse` | 浏览器 `EventSource` |
| 20 | `frontend/src/store/agent-context.tsx` | `AgentProvider.connectThreadStream` | L246-L362 | thread ID 和 cursor | 建立 EventSource、归并事件；投影类事件触发时间线快照刷新，断线按退避重连 | reducer 中的最新 timeline/connection | `applyMessageEvent` |
| 21 | `frontend/src/features/agent/timeline-state.ts` | `applyMessageEvent` | L85-L161 | `message.delta`、`message.completed` 或 `message.failed` | delta 追加到现有正文并保持 streaming；完成或失败事件收敛最终状态 | 规范化 `messagesById` | `AgentPage` / `ConversationStream` |
| 22 | `frontend/src/pages/AgentPage.tsx` | `AgentPage`（`pendingResponse` 与 `handleSend`） | L47-L72、L119-L146、L268-L285 | turn 提交状态、响应 cursor 和最新 timeline items | 请求开始即记录等待状态；出现 cursor 之后的 assistant 消息或 workflow 时清除等待状态 | 在后端尚未创建可见回复项时仍有明确 UI 状态 | `ConversationStream` |
| 23 | `frontend/src/features/agent/ConversationStream.tsx` | `AssistantPending` / `TimelineItemView` / `ConversationStream` | L18-L29、L31-L95、L97-L162 | 等待标记与 timeline items | 无正文时显示动态三点；收到 delta 后展示真实正文和光标；已有 streaming 消息时避免重复占位 | 用户看到等待、增量正文或最终结果 | 页面滚动区 |

HTTP 创建 turn 仍使用一个请求级事务，确保消息、Run、事件和 outbox 原子提交；HTTP 与 Worker 之间
以 MySQL outbox 交接，不依赖浏览器连接或 Redis 存活。Worker 为每个 outbox 使用独立 session，但
不再把整条长任务压成一个提交：running 状态、每个工作流步骤、公开工具活动和 100ms 聚合的回答
delta 都是可恢复 commit 边界。这样 SSE session 能在任务执行期间读取进度；最终 artifact、Run 终态
和 `message.completed` 继续负责收敛完整结果。

#### 4.2.1 Router 分流到业务工作流后的真实公开执行链

Router 的决策本身保持完整结构化返回，不流式暴露内部原因；当 action 为 `explain`、`validate`、
`grade` 或 `plan` 时，child workflow 的公开步骤和工具活动才进入用户可见事件流。

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/workflows/conversation.py` | `_dispatch_workflow_node` | L182-L224 | Router 选出的业务 action 与受控上下文 | 幂等创建 compact child run，并创建对话内 workflow 时间线项 | 用户先看到真实排队中的业务卡片 | `AgentWorker.process_run` |
| 2 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（进入 running） | L127-L138 | queued child run | 写 `run.status_changed` 并立即 commit | SSE 可在节点执行前看到“执行中” | `WorkflowEngine.execute` |
| 3 | `backend/app/modules/agent/workflows/engine.py` | `WorkflowEngine.execute` | L61-L157 | workflow 节点图 | 每个节点开始写 `step.started` 并 commit；完成、等待或失败后写对应事件再 commit | 真实步骤逐个出现，Worker 中断后仍可恢复最后进度 | 具体节点或工具 |
| 4 | `backend/app/modules/agent/tools/retrieve_knowledge.py` | `retrieve_knowledge` | L19-L176 | explain/validate 的查询词、范围和 run ID | 检索前写 `tool.called`；调用真实 RetrievalService；完成后只公开安全的通道、查询、命中数量和资料摘要并写 `tool.result` | 两次提交形成 running → completed/failed activity | `RetrievalService.search_with_outline_expansion` |
| 5 | `backend/app/modules/retrieval/service.py` | `RetrievalService.search_with_outline_expansion` | L44-L107 | 查询、学科/章节/实体过滤和 limit | 先用 canonical chapter 扩展查询，再执行 Qdrant dense/sparse hybrid 检索并合并过滤 | 真实命中结果与 outline expansion | `retrieve_knowledge` 精简公开结果 |
| 6 | `backend/app/modules/agent/events.py` | `EventStore.append` | L24-L61 | step/tool Run 事件与公开 payload | 分配 run 内 sequence，写 `agent_events`，同事务触发 thread 投影 | 内部可审计事实与公开事件保持关联 | `ThreadEventStore.project_run_event` |
| 7 | `backend/app/modules/agent/thread_events.py` | `ThreadEventStore.project_run_event`（tool 分支） | L161-L204 | `tool.called` / `tool.result` | 只转发显式 `public_metadata`，统一投影成 `workflow.activity.updated` | `agent_thread_events` 获得 thread cursor | SSE |
| 8 | `backend/alembic/versions/20260725_agent_activity.py` | `upgrade` | L34-L41 | 数据库升级到新 head | 给公开 thread event ENUM 增加 `workflow.activity.updated` | MySQL 可持久化活动事件 | 后端运行 |
| 9 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._build_workflow_views` / `_activity_views` | L399-L538 | Run、Step、Tool Event、交互和产物事实 | 按 root run 聚合，使用同一 activity ID 合并 called/result | 刷新或断线后可重建 `workflow.activities[]` | timeline snapshot |
| 10 | `frontend/src/features/agent/timeline-state.ts` | `applyWorkflowEvent` | L163-L220 | SSE `workflow.activity.updated` | 按 activity ID 新增或更新状态，保留已到达元数据 | React 状态立即变化 | `InlineWorkflow` |
| 11 | `frontend/src/features/agent/InlineWorkflow.tsx` | `ActivityCard` / `InlineWorkflow`（实时记录） | L92-L133、L218-L242 | `workflow.activities[]` | 展示检索通道、查询内容、命中数、资料名称和运行/完成状态 | 用户看到真实动态执行链，不展示隐藏推理 | 对话内 workflow 卡片 |

### 4.3 等待用户输入、审批与管理员模型配置旁路

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责与最终落点 |
| --- | --- | --- | --- | --- |
| 用户补充输入 | `frontend/src/store/agent-context.tsx` | `AgentProvider.answerWorkflowInput` | L457-L464 | 调用输入回答 API，成功后刷新当前 thread 时间线 |
| 后端接收输入 | `backend/app/modules/agent/router.py` | `submit_input_answer` | L547-L568 | 校验用户和等待项，写入答案并重新投递 Run |
| 用户审批 | `frontend/src/store/agent-context.tsx` | `AgentProvider.decideWorkflowApproval` | L466-L480 | 调用批准/拒绝 API，成功后刷新时间线 |
| 后端审批 | `backend/app/modules/agent/router.py` | `approve_approval` / `reject_approval` | L607-L622 / L626-L641 | 更新审批事实并恢复或终止相应工作流 |
| 管理员页面入口 | `frontend-admin/src/pages/AgentModelsPage.tsx` | `AgentModelsPage` | L60-L165 | 加载模型、提交创建/编辑、切换状态/默认项和测试连通性 |
| 管理端 HTTP 封装 | `frontend-admin/src/api/agentModels.ts` | `listAgentModels` 等模型 API 函数 | L44-L66 | 请求 `/api/v1/admin/agent-models` 系列接口 |
| 后端管理入口 | `backend/app/modules/agent/model_config_router.py` | `list_agent_models` 至 `test_agent_model` | L29-L138 | 调用配置服务，事务提交后返回脱敏数据或测试结果 |
| 状态不变量 | `backend/app/modules/agent/model_configs.py` | `AgentModelConfigService.create` 至 `get_user_selectable` | L46-L186 | 保证显示名称唯一、最多一个默认模型、默认项不可直接下线，并在 turn 创建前二次校验可用性 |

### 4.4 管理端导航到 Agent 页面和基础配置保存

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `frontend-admin/src/components/Sider/index.tsx` | `menuItems` | L34-L89 | 管理端布局渲染侧栏 | 把 `/admin/agent-runs` 配置为“系统监控”子项，把 `/admin/agent-models` 配置为“系统配置”子项 | 两个 Agent 页面不再占用顶级菜单 | `AppSider` |
| 2 | `frontend-admin/src/components/Sider/index.tsx` | `selectableMenuKeys` / `menuGroups` | L91-L127 | 当前 `location.pathname` | 详情路径仍选中 Agent Runs；原 URL 分别映射到监控组和配置组 | 进入页面或刷新页面时自动展开正确父菜单 | `AppSider` |
| 3 | `frontend-admin/src/components/Sider/index.tsx` | `AppSider`（导航状态计算） | L129-L194 | 当前 `location.pathname` | 计算权限过滤、选中项和应自动展开的父菜单 | 得到 `selectedKey` 与 `openKeys` | `AppSider` 菜单渲染 |
| 4 | `frontend-admin/src/components/Sider/index.tsx` | `AppSider`（菜单点击） | L196-L224 | 管理员点击子菜单 | 把选中项和展开项交给 Ant Design Menu，并执行 `navigate(key)` | URL 保持 `/admin/agent-runs` 或 `/admin/agent-models` | `AppRoutes` |
| 5 | `frontend-admin/src/router/index.tsx` | `AppRoutes`（Agent Runs 路由） | L187-L189 | React Router 匹配 `/admin/agent-runs` 或详情 URL | 渲染 `AgentRunsPage` / `AgentRunDetailPage` | 监控页面挂载；详情返回路径继续有效 | Agent Runs 查询接口 |
| 6 | `frontend-admin/src/router/index.tsx` | `AppRoutes`（Agent 模型路由） | L232-L233 | React Router 匹配 `/admin/agent-models` | 渲染 `AgentModelsPage` | 模型配置页面挂载；旧书签继续有效 | `listAgentModels` |
| 7 | `frontend-admin/src/components/Header/index.tsx` | `routeContexts` | L14-L41 | 管理端路由表初始化 | 声明 Agent URL 对应的栏目与标题 | 路由上下文映射表 | `AppHeader` |
| 8 | `frontend-admin/src/components/Header/index.tsx` | `AppHeader`（路由上下文选择） | L43-L48 | 当前 `location.pathname` | 按前缀查找当前栏目和页面标题 | Header 显示系统监控或系统配置 | 页面交互 |
| 9 | `frontend-admin/src/pages/Settings/index.tsx` | `Settings`（默认页签） | L234-L244 | 基础配置页面挂载 | 默认选择 `pdf-structure-llm`，加载系统配置 | 问答 LLM 不再作为默认入口 | `Settings` Tab 渲染 |
| 10 | `frontend-admin/src/pages/Settings/index.tsx` | `Settings`（Tab 渲染） | L323-L352 | 系统配置数据加载完成 | 只注册题目结构、大纲拆分、文档元信息和富化等仍受基础配置维护的页签 | 页面不存在旧“问答 LLM”Tab | `Settings.handleSubmit` |
| 11 | `frontend-admin/src/pages/Settings/index.tsx` | `Settings.handleSubmit` | L264-L295 | 管理员提交基础配置表单 | 复制表单值并删除隐藏 `llm`，再执行解析器切换校验 | `updateSettings` 只保存仍可见的配置域 | 系统配置 API |
| 12 | `frontend-admin/src/pages/AgentModelsPage.tsx` | `AgentModelsPage`（查询与操作） | L60-L165 | 管理员进入 Agent 模型配置 | React Query 加载列表，并执行创建、编辑、状态切换、默认模型和连通性测试 | `/api/v1/admin/agent-models` 成为 Agent 问答模型的唯一管理界面 | `AgentModelConfigService` |

这里保持 URL 不变是有意的：菜单归属属于信息架构，URL 是页面和导航之间的稳定契约。若为了
菜单层级同时改成 `/admin/monitor/agent-runs` 或 `/admin/settings/agent-models`，详情页返回、浏览器
书签和外部链接都需要兼容重定向，而本次没有这种业务必要。

### 4.5 管理端从会话列表进入多轮问答与事件流

管理端 URL 继续使用 `agent-runs`，但页面主实体已经从单次 `AgentRun` 改为完整
`AgentThread`。一次用户提问仍对应一个 root run，root run 触发的 child runs、事件、审批和
产物在详情接口中聚合为同一个 turn；这样列表一行就是一个会话，而详情中的一块折叠面板就是
一次问答。

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `frontend-admin/src/pages/AgentRunsPage.tsx` | `AgentRunsPage.fetchSessions` | L76-L96 | 页码、每页数量和管理员筛选条件 | 调用会话级列表 API，并把分页结果写入 React 状态 | 表格一行对应一个 Thread | `AgentRunsPage` 表格详情按钮 |
| 2 | `frontend-admin/src/pages/AgentRunsPage.tsx` | `AgentRunsPage`（表格列定义） | L119-L193 | `AdminAgentSession` | 展示会话标题、Thread ID、最新状态、问答轮数、Run 数和事件数 | 点击详情时 URL 使用 `thread_id` | `getAgentRunDetail` |
| 3 | `frontend-admin/src/api/agentRuns.ts` | `getAgentRuns` / `getAgentRunDetail` | L125-L135 | 列表查询参数或 Thread/旧 Run ID | 请求 `/api/v1/admin/agent-runs` 及详情路径 | 得到强类型会话摘要或多轮详情 | `list_all_runs` / `get_run_detail` |
| 4 | `backend/app/modules/agent/admin_router.py` | `list_all_runs` | L277-L374 | 管理员分页、状态、工作流、用户和时间筛选 | 先分页 `AgentThread`，再批量读取该页 Thread 的 runs 和事件计数；状态与工作流筛选使用 root run 是否存在 | `{data: {items, total, page, page_size}}`，每个 item 只代表一个 Thread | 管理端会话表格 |
| 5 | `backend/app/modules/agent/admin_router.py` | `_resolve_thread` | L220-L234 | 详情路径中的 ID | 优先按 Thread ID 查询；查不到时把旧 Run ID 转换为所属 Thread ID | 旧书签不会因主实体变化而 404 | `get_run_detail` |
| 6 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L377-L443 | 已解析的 Thread | 一次读取会话内 messages、runs、events、approvals、artifacts | 完整会话事实集合 | `_build_turns` |
| 7 | `backend/app/modules/agent/admin_router.py` | `_build_turns` | L127-L217 | 会话内五类事实记录 | 以 `root_run_id` 分组 child runs，把触发用户消息、assistant 消息和各 Run 的事件/审批/产物归到同一轮 | 按时间排序的 `turns[]` | `AdminAgentSessionDetail` |
| 8 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `AgentRunDetailPage.fetchSession` | L258-L268 | 路由中的 Thread ID 或兼容 Run ID | 只请求一次聚合详情，不再并行调用不存在的管理端 approvals 路由 | 消除详情挂载时的 `Not Found` 弹窗 | `AgentRunDetailPage` 渲染 |
| 9 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `AgentRunDetailPage`（多轮折叠渲染） | L305-L376 | `session.turns` | 每一轮渲染独立折叠面板，默认展开最后一轮 | 管理员可逐轮查看问题、回答与运行状态 | `TurnDetail` |
| 10 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `TurnDetail` | L95-L248 | 单轮 messages、runs、events、approvals、artifacts | 运行链路、事件流、审批与产物分别二次折叠；事件按筛选条件渲染 | 一次问话引发的事件流可以独立收起 | `getAgentEventTypeLabel` |
| 11 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `getAgentEventTypeLabel` | L49-L69 | 英文 `event_type` | 查询中文名称并保留英文原名；未知类型使用“未知事件”兜底 | 统一显示“中文（英文）” | 事件筛选器和 Timeline |

这里的数据库读取是只读聚合，不创建新的监控表。事实来源仍然是 `agent_threads`、
`agent_messages`、`agent_runs`、`agent_events`、`agent_approvals` 和 `agent_artifacts`；因此 Worker
写入完成后，管理员刷新详情即可看到新的轮次和事件。

### 4.5 管理员设置“无限输出 Token”直到模型请求

“无限”不是一个超大整数，而是 `max_tokens=null`。它的最终语义是调用模型时省略输出上限参数。

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `frontend-admin/src/components/TokenLimitField/index.tsx` | `TokenLimitField` / `switchMode` | L12-L80 | Form 注入的数字或 `null`、该用途默认值 | 用“按额度/不设上限”分段选择统一两种状态；切换到无限发出 `null`，切回时恢复上一次数字 | 形成可被多个 LLM 表单复用的三态输入值 | Agent 模型或任务型 LLM Form |
| 2 | `frontend-admin/src/pages/AgentModelsPage.tsx` | `AgentModelsPage`（输出 Token 列与表单） | L227-L237、L368-L377 | 管理员查看列表或修改 Agent 模型配额 | 表格用弱化文本显示“不设上限”，编辑表单把 `TokenLimitField` 直接绑定到 `max_tokens` | 创建/编辑请求携带数字或 JSON `null` | `create_agent_model` / `update_agent_model` |
| 3 | `frontend-admin/src/pages/Settings/index.tsx` | `defaultMaxTokens` / `LlmConfigTab` | L19-L25、L27-L122 | 管理员配置题目结构、大纲、元信息或富化 LLM | 所有任务型 LLM 复用同一配额控件，切回限额时按用途恢复默认值 | `system_configs` 对应分区保存数字或 `null` | `BaseLLMClient.__init__` |
| 4 | `backend/app/modules/agent/model_config_router.py` | `create_agent_model` / `update_agent_model` | L38-L69 | `max_tokens` 为数字或显式 `null` | Pydantic 校验后保留显式空值，更新接口用 `exclude_unset` 区分“未传”与“传 null” | 交给配置服务 | `AgentModelConfigService.create` / `update` |
| 5 | `backend/app/modules/agent/model_configs.py` | `AgentModelConfigService.create` / `update` | L38-L110 | 配置字典 | 缺省值使用 2000；显式 `None` 原样写入 | ORM 记录待提交 | `AgentModelConfigRecord.max_tokens` |
| 6 | `backend/app/modules/agent/models.py` | `AgentModelConfigRecord.max_tokens` | L40-L44 | 数字或 `None` | `evaluates_none()` 防止 SQLAlchemy 把显式空值重新替换为 Python 默认值 | `agent_model_configs.max_tokens` 保存 SQL `NULL` | `load_agent_model_config` |
| 7 | `backend/alembic/versions/20260724_agent_unlimited_tokens.py` | `upgrade` | L20-L27 | 数据库升级到新 head | 把 `agent_model_configs.max_tokens` 改为 nullable | 既有数字不变，新配置可保存 `NULL` | Agent Runtime |
| 8 | `backend/app/modules/agent/model_runtime/config.py` | `AgentModelConfig.model_settings` / `_record_to_runtime_config` | L29-L87 | 数据库配置快照 | `None` 保持无限；仅数字值写入 Pydantic AI 的 `model_settings` | 无限时 settings 只有 temperature | Router/Answer Runtime |
| 9 | `backend/app/modules/agent/model_runtime/router.py` | `RouterRuntime.decide` | L70-L121 | 当前消息、历史和运行配置 | 把条件生成的 `model_settings` 交给 Pydantic AI 并校验结构化 action | 供应商请求不再出现越界的 `max_completion_tokens` | 路由结果 |
| 10 | `backend/app/modules/agent/model_runtime/answer.py` | `DirectAnswerRuntime.answer` | L91-L166 | 当前问题、历史和运行配置 | 使用相同 settings 调用回答模型；存在 callback 时进入结构化正文流 | 无限时由模型/供应商上下文限制决定输出 | delta 与消息完成事件 |
| 11 | `backend/app/infrastructure/ai/llm_client.py` | `BaseLLMClient.__init__` / `_chat` | L48-L137 | 任务型系统 LLM 配置 | 保留显式 `None`，构造 SDK kwargs 时仅在非空时加入 `max_tokens` | 任务型 LLM 同样支持无限 | OpenAI 兼容供应商 |

`null`、字段缺失和数字是三种不同状态：`null` 表示无限；字段缺失使用该用途默认值；数字表示
管理员明确指定上限。这样既保留历史默认行为，也不会再用 200000 等值撞上不同供应商的上限。

## 5. 一轮对话的生命周期

```text
用户发送消息
  -> GET /app/agent/models 选择已上线模型（也可不显式选择）
  -> POST turn 携带可选 model_config_id
  -> 校验模型仍处于 online + selectable
  -> 事务写入 user message
  -> 创建 conversation root run，并把选择写入 metadata
  -> 创建 timeline item / thread event
  -> 创建 pending outbox
  -> 提交事务并立即返回
  -> Worker 扫描 outbox
  -> 优先解析 Run 指定模型，否则读取 agent_model_configs 默认模型
  -> 无多模型默认记录时兼容 system_configs.llm / 环境变量
  -> 创建独立 AsyncOpenAI，并把实际模型 ID 固定到 Run 元数据
  -> conversation workflow 判断 direct answer / clarify / business action
  -> 生成 assistant message 或 child workflow
  -> 持久化公开事件
  -> SSE/补拉 API 更新用户端时间线
```

同一个 thread 中，较早且仍处于 `queued` / `running` 的 root run tree 会阻塞后续 tree，
避免两轮用户输入并发修改同一对话上下文。进入等待用户、等待审批或终态后，事实已经稳定，
后续轮次可以继续执行。

## 6. 数据与状态的来源

- MySQL 是 thread、message、run、event、workflow 状态的事实来源。
- `agent_thread_items` 是面向用户时间线的有序投影。
- `agent_thread_events.sequence` 和 `agent_threads.last_item_sequence` 提供 thread 级统一 cursor。
- SSE 是传输优化，不是唯一数据来源；断线后客户端通过时间线快照或事件补拉恢复。
- `agent_run_outbox` 是任务唤醒事实，Worker 通过数据库扫描提供 Redis 故障时的兜底。
- `agent_model_configs` 是管理员维护的 Agent 模型事实来源；`default_slot` 的唯一约束保证数据库
  层最多只有一个默认模型，用户接口只返回 `online + selectable` 记录。

模型调用不使用 OpenAI Python SDK 的全局配置。每次请求根据当前配置创建独立的
`AsyncOpenAI` 客户端，并在请求结束后关闭。这样管理员测试不同配置、后台任务和用户问答
并发发生时，各自的 API Key、Base URL、模型与超时时间不会互相覆盖，也为后续多模型选择
提供了安全的客户端基础。

当前 Agent 生产执行优先使用 Run 的 `model_config_id`；用户没有显式选择时使用
`agent_model_configs` 默认记录。第一次模型调用会把最终解析出的配置 ID、来源、模型名称和
供应商写回 Run 元数据，因此同一 Run 后续调用不会因管理员切换默认模型而漂移。只有尚未
建立多模型默认记录时，运行时才兼容旧 `system_configs.llm`，最后再回退
`OPENAI_API_KEY` 与 `OPENAI_MODEL` 环境变量。API Key 只保存在服务端，管理员列表返回掩码，
用户模型列表只返回 ID、显示名称和默认标记。

管理员端 `/admin/agent-models` 直接消费上述管理接口。页面只根据 `has_api_key` 展示“已配置”，
编辑已有模型时 API Key 输入框保持空白；保存时省略空密钥字段，使服务端保留原值。上线与用户
可选状态使用独立状态接口，设置默认前要求模型同时上线且可选，连通性测试使用按钮级 loading
并展示模型回复或截断后的错误。这样管理动作都经过后端约束，而不是在浏览器本地伪造状态。

用户端 Agent 页面加载时请求 `/api/v1/app/agent/models`，只把公开 ID、显示名称和默认标记保存
在页面状态中。当前选择在空会话与已有会话的两个 Composer 间共享，每次 `sendTurn` 都将其作为
`model_config_id` 写入请求。列表加载中、为空或选择失效时发送按钮不可用；若提交时模型刚被
管理员下线，页面保留输入内容、展示服务端中文错误并刷新列表，重新选择默认项或第一条可用项。

Agent 时间采用“两段式 UTC 契约”：MySQL `DATETIME` 继续保存无时区的 UTC 值，避免改变现有
表结构和 SQL 比较行为；HTTP JSON 与 SSE 一旦把时间发送给浏览器，就统一序列化为带 `Z` 的
ISO 8601 字符串。前端 `new Date(...)` 因此能先识别 UTC，再按用户设备时区显示。

Agent 对话保留消息流、工作流卡片和底部输入区等专有布局，但不维护独立品牌主题。
`agent-chat.css` 的页面级变量只是语义别名，实际颜色、字体和表面层级来自 `index.css` 的
`--canvas`、`--paper`、`--ink`、`--blue`、`--jade`、`--amber`、`--red`、`--serif` 和
`--mono`。因此全站调整主题时，Agent 页面会跟随更新，而不会再次产生蓝紫色孤岛。

## 7. 当前重点演进方向

1. 修复并强化管理员 Agent Runs、基础设施状态和 LLM 连通性监控。
2. 打通用户消息到模型回答的可观察链路，避免“无响应但无错误”。
3. 统一 UTC 存储与用户时区展示。
4. 让 Agent 页面遵循用户端全局设计系统。
5. 为模型选择与实际 Run 增加更直观的历史展示和管理员审计筛选。

每完成一项，必须同步更新本全景图、细致讲解和进展记录。
