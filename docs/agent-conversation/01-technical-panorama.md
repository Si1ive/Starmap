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
  ├─ POST 一轮消息
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
  ├─ 读取管理员问答 LLM 配置
  ├─ 调用模型运行时与领域工具
  └─ 持久化状态、消息、事件和产物
          │
          ├───────────────► LLM Provider
          └───────────────► 学习领域服务 / 检索工具

管理员端
  ├─ /api/v1/admin/agent-runs ──► agent_runs / agent_events / artifacts
  ├─ LLM 配置与连通性测试 ──► 独立 AsyncOpenAI 客户端 ──► LLM Provider
  └─ 基础设施状态 ──► MySQL / Redis / Qdrant
```

Redis 在当前 Agent 核心执行链路中不是事实来源。Agent 的可靠任务唤醒依赖 MySQL outbox
和周期扫描，因此 Redis 短暂不可用不应导致已提交的对话丢失；Redis 主要服务于缓存、其他
任务队列或实时能力的辅助部分。

## 3. 主要代码边界

| 层次 | 主要位置 | 职责 |
| --- | --- | --- |
| 用户端页面 | `frontend/src/pages/AgentPage.tsx` | thread 选择、消息提交、时间线加载和 SSE 生命周期 |
| 用户端组件 | `frontend/src/features/agent/` | 消息流、输入框、内嵌工作流和时间线状态归并 |
| 用户端 API | `frontend/src/api/agent.ts` | Agent HTTP/SSE 契约和前端类型 |
| HTTP 接口 | `backend/app/modules/agent/router.py` | 认证、参数校验、thread/run/timeline/event API |
| 对话时间线 | `timeline.py`、`thread_events.py` | 原子创建一轮对话、公开投影和统一事件 cursor |
| 执行调度 | `outbox.py`、`worker.py` | 可靠任务扫描、线程串行化、认领、租约和重试 |
| 工作流 | `workflows/` | conversation 路由与 explain/validate/grade/plan 等工作流 |
| 模型运行时 | `model_runtime/` | 模型适配、结构化路由、回答生成和策略门禁 |
| 上下文 | `context_builder.py` | 对话历史、权限范围、学习上下文和 root run 完整性 |
| 持久化模型 | `models.py` | Agent 领域表、状态和索引定义 |
| 管理员接口 | `admin_router.py` | 在 `/api/v1/admin/agent-runs` 下提供 Run 查询、详情、统计与管理能力 |
| 管理员页面 | `frontend-admin/src/pages/AgentRunsPage.tsx` 等 | 运行监控、筛选与详情展示 |

## 4. 一轮对话的生命周期

```text
用户发送消息
  -> 事务写入 user message
  -> 创建 conversation root run
  -> 创建 timeline item / thread event
  -> 创建 pending outbox
  -> 提交事务并立即返回
  -> Worker 扫描 outbox
  -> 读取 system_configs.llm，创建独立 AsyncOpenAI
  -> conversation workflow 判断 direct answer / clarify / business action
  -> 生成 assistant message 或 child workflow
  -> 持久化公开事件
  -> SSE/补拉 API 更新用户端时间线
```

同一个 thread 中，较早且仍处于 `queued` / `running` 的 root run tree 会阻塞后续 tree，
避免两轮用户输入并发修改同一对话上下文。进入等待用户、等待审批或终态后，事实已经稳定，
后续轮次可以继续执行。

## 5. 数据与状态的来源

- MySQL 是 thread、message、run、event、workflow 状态的事实来源。
- `agent_thread_items` 是面向用户时间线的有序投影。
- `agent_thread_events.sequence` 和 `agent_threads.last_item_sequence` 提供 thread 级统一 cursor。
- SSE 是传输优化，不是唯一数据来源；断线后客户端通过时间线快照或事件补拉恢复。
- `agent_run_outbox` 是任务唤醒事实，Worker 通过数据库扫描提供 Redis 故障时的兜底。

模型调用不使用 OpenAI Python SDK 的全局配置。每次请求根据当前配置创建独立的
`AsyncOpenAI` 客户端，并在请求结束后关闭。这样管理员测试不同配置、后台任务和用户问答
并发发生时，各自的 API Key、Base URL、模型与超时时间不会互相覆盖，也为后续多模型选择
提供了安全的客户端基础。

当前 Agent 生产执行优先读取 MySQL `system_configs.llm` 中管理员启用的“问答 LLM”；只有
该配置未启用时才回退 `OPENAI_API_KEY` 与 `OPENAI_MODEL` 环境变量。解析出的配置来源、模型
名称和供应商会写入 Run 元数据，便于管理员追踪实际使用了哪一套运行时配置。管理员连通性
测试和 Agent 回答因此使用同一个配置事实来源，不再出现“测试成功但 Agent 实际没用”的
割裂状态。

Agent 时间采用“两段式 UTC 契约”：MySQL `DATETIME` 继续保存无时区的 UTC 值，避免改变现有
表结构和 SQL 比较行为；HTTP JSON 与 SSE 一旦把时间发送给浏览器，就统一序列化为带 `Z` 的
ISO 8601 字符串。前端 `new Date(...)` 因此能先识别 UTC，再按用户设备时区显示。

## 6. 当前重点演进方向

1. 修复并强化管理员 Agent Runs、基础设施状态和 LLM 连通性监控。
2. 打通用户消息到模型回答的可观察链路，避免“无响应但无错误”。
3. 统一 UTC 存储与用户时区展示。
4. 让 Agent 页面遵循用户端全局设计系统。
5. 支持后台配置多个模型、模型上线/下线和用户端选择可用模型。

每完成一项，必须同步更新本全景图、细致讲解和进展记录。
