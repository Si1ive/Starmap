# 408 学习 Agent 对话运行时技术设计

> 版本：v1.1
> 日期：2026-07-21
> 状态：目标设计，Phase 0 实施基线
> 上游产品契约：[408 学习 Agent 主体 PRD](../product/408-agent-main-prd.md)
> 关联文档：[Agent 工作流编排技术设计](./408-agent-workflow-orchestration-design.md)、[Agent 工作流技术选型与风险分析](./408-agent-workflow-technology-selection-and-risk-analysis.md)、[用户端 Agent 技术架构](./user-agent-client-architecture.md)、[系统架构](./architecture.md)、[后端模块化单体演进方案](./backend-modular-monolith.md)、[多模态入库与检索设计](./multimodal-ingestion-retrieval-design.md)、[用户认证技术方案](./authentication-architecture-options.md)

## 1. 目的和边界

本文定义 408 学习 Agent 对话功能的可执行后端设计。它覆盖用户发送消息后，从线程、运行、模型和工具调用，到持久化事件、SSE、恢复、审批、引用和结构化产物的完整链路。

本文是以下实现细节的唯一事实源：

- Agent Runtime 的进程模型、模块边界和依赖方向。
- 线程、运行、步骤、事件、检查点、审批、工具调用和产物的数据模型。
- 运行状态机、事务边界、幂等、租约、重试、取消和恢复。
- 工作流编排的外层图、内层有界 Agent Loop、节点契约、受限分支、质量闸门和评测轨迹以[Agent 工作流编排技术设计](./408-agent-workflow-orchestration-design.md)为唯一事实源。
- 用户 API、SSE 事件协议、错误语义和客户端同步规则。
- 模型上下文、结构化输出、检索引用校验、工具权限和审计。
- 可观测性、测试、迁移、灰度和旧 `/api/v1/chat` 的退役路径。

本文不重新定义用户流程、页面布局、学习规则、题目质量规则或运营指标。它们以 PRD 为准；技术实现不得削弱 PRD 中的产品约束。

### 1.1 当前实现与目标的差异

当前代码已有 `backend/app/modules/chat`：`POST /api/v1/chat` 同步调用模型，以匿名 `session_id` 维护 Redis 缓存并将消息补写到 `ChatSession` / `ChatMessageRecord`。该接口不能表达已认证用户归属、运行状态、长任务恢复、工具审计或可靠副作用。

本设计新增的 `agent`、`workspace`、`learning`、`practice`、`user_sources` 和 `evals` 模块在本文发布时尚未落地。实施时必须增量建设，不得把目标文件或表误认为现有能力。

旧 Chat 接口保持为管理员调试和兼容入口；新用户端只通过 `/api/v1/app/*` 调用 Agent Runtime。旧接口不再新增 Agent 特性，完成迁移后再按数据保留策略下线。

## 2. 不可违反的设计约束

1. MySQL 是线程、运行、用户消息、工具结果、学习事实和事件的业务事实源；Redis、SSE 连接和前端状态均不是事实源。
2. 用户资源的归属从认证会话获得。客户端提交的 `user_id`、资源归属或权限级别一律忽略。
3. 模型只能生成受 Schema 约束的决策和内容；仅在已锁定的 `agent_loop` 中可从白名单 action 中选择下一次只读探索动作，不能直接调用 ORM、SQL、队列或任意网络/本地能力。
4. 影响学习域的写入必须通过领域命令，且命令具有稳定的幂等键；持久副作用成功后才能将对应 step 标记成功。
5. 每一个可展示的运行变化必须先持久化为事件，之后才推送给 SSE 客户端。SSE 丢失或重复不改变运行真实状态。
6. 用户资料、检索文本和模型输出都是不可信数据；权限、引用、工具参数和领域命令都在服务端重新验证。
7. 用户和管理员均只能看到安全摘要，不能获得系统提示词、密钥、隐藏思维链、其他用户数据或供应商原始错误。

## 3. 方案决策

| 事项 | 决策 | 原因 |
|------|------|------|
| 首发执行形态 | FastAPI API + 独立 Agent Worker 进程 | HTTP 请求不持有模型和工具长任务，Worker 可独立恢复与扩容。 |
| 持久执行 | MySQL 状态机、检查点、租约和 outbox | 业务状态可事务化，Redis 故障不丢失已提交运行。 |
| 任务唤醒 | Redis Stream/队列用于低延迟唤醒，MySQL outbox 轮询兜底 | Redis 不是唯一队列；重复投递由 run/step 幂等处理。 |
| 实时通道 | SSE | 对话运行主要是服务端单向状态和产物更新；双向命令仍走 HTTP。 |
| 业务编排契约 | 外层版本化受限 Workflow + 内层有界 `agent_loop` | 外层图、节点输入输出、副作用边界和分支均在版本化代码中声明；模型仅可在指定 Loop 中按 Schema 从 action 白名单选择下一次只读探索。详见[工作流编排技术设计](./408-agent-workflow-orchestration-design.md)。 |
 | 图执行与持久执行实现 | P0 首发自建最小 durable kernel；LangGraph 做 PoC；Temporal 按触发条件评估 | 以 `WorkflowDefinition`、`AgentLoopPolicy`、`NodeResult`、MySQL outbox/lease/Worker 为基础，框架只替换执行层，不改变 MySQL 事实、领域命令与 API/SSE 契约。LangGraph 进入 PoC 但不预设进入生产；Temporal 在 timer/跨服务/SLO 触发后评估。详见[工作流技术选型与风险分析](./408-agent-workflow-technology-selection-and-risk-analysis.md)。 |
 | 模型交互 / Loop 层 | 服务端模型适配层 + Pydantic AI + Pydantic Schema | Pydantic AI 作为 Loop 决策协议的轻量实现：类型安全的工具注册、结构化输出解析和多提供商切换。它不承载 Workflow，外层持久化、审批和恢复仍由自建 kernel 或 Temporal 负责。TypeScript Agent SDK（如 `pi-agent-core`）因语言栈错位被排除。详见[工作流技术选型与风险分析](./408-agent-workflow-technology-selection-and-risk分析.md)。 |

首发不引入 MCP server、WebSocket、通用浏览器自动化、通用命令执行或 TypeScript Agent SDK（如 `pi-agent-core`）。Pydantic AI 用于 Loop 层的工具注册和结构化输出，但不承载 Workflow 持久化。LangGraph 适配层进入 PoC 但不预设进入生产；Temporal 在触发条件满足后评估。所有框架替换只能改变编排适配层，不能改变 MySQL 事实、领域命令与 API/SSE 契约。

## 4. 总体拓扑

```text
React Web
  | authenticated HTTPS + Idempotency-Key
  v
FastAPI App API ---------------------> MySQL
  | create thread/message/run/outbox     | facts, events, checkpoints, artifacts
  |                                       |
  | SSE reads persisted event sequence    |
  v                                       v
Redis Stream / wake-up              Agent Worker pool
                                        | acquire DB lease
                                        | run model/tool/gate steps
                                        v
                         retrieval | content | learning | practice | user_sources
                                        |
                                 Qdrant / Object Storage / MinerU
```

### 4.1 写入与唤醒顺序

创建运行的 API 在同一 MySQL 事务中写入用户消息、`agent_runs`、第一条 `agent_events` 和 `agent_run_outbox`。提交后尝试发布 outbox 项到 Redis；发布失败返回成功，后台 dispatcher 轮询未发布 outbox 重试。Worker 也周期性扫描到期且非终态的 run，因此 Redis 全部不可用时新运行仍可在轮询间隔内执行。

Worker 不在持有数据库事务时调用 LLM、Qdrant、MinerU 或对象存储。它先取得 step 租约并提交；外部调用结束后以短事务保存结果、领域副作用引用、检查点和事件。`agent_loop` 不会把多次决策和工具调用包进一个长事务，而是每一 turn 提交 decision 摘要、工具审计、observation 引用、预算和 checkpoint。进程在外部调用期间崩溃时，租约过期后由其他 Worker 接管。

### 4.2 模块与依赖规则

```text
app/modules/
  workspace/        # thread, message, artifact, task-center query
  agent/            # run, step, event, checkpoint, approval, worker, tool registry
  learning/         # goals, plans, evidence, review scheduler
  practice/         # session, snapshot, attempt, deterministic grading, mistake
  user_sources/     # personal source lifecycle and retrieval permission
  evals/            # fixed fixtures, regression run, gate
```

- `workspace` 拥有对话容器和用户可见产物，不决定下一步工具。
- `agent` 拥有执行状态和编排，只依赖其他模块公开的查询服务与领域命令接口。
- `learning`、`practice`、`user_sources` 拥有其表、事务和权限判断；它们不允许 `agent` 直接导入 ORM model 写表。
- `retrieval`、`content`、`catalog`、`corpus` 提供受限的只读门面，返回可引用的结构化实体。
- `evals` 使用相同的编排入口，但用 fixture 工具和隔离数据库事务；它绝不执行真实用户副作用。

建议目录：

```text
backend/app/modules/agent/
  router.py                 # /api/v1/app/agent/* command/query/SSE routes
  schemas.py                # Pydantic request, response, event schemas
  models.py                 # agent-owned SQLAlchemy models
  service.py                # command/query application service
  worker.py                 # lease loop and workflow dispatcher
  state_machine.py          # explicit allowed transitions
  events.py                 # atomic event append and SSE serialization
  checkpoints.py            # checkpoint read/write/version validation
  outbox.py                 # dispatch and recovery scan
  tools/                    # registry, policy, adapters, schemas
  workflows/                # engine.py, registry.py, contracts.py, loops.py, common.py, explain.py, validate.py, grade.py, ...
  model_runtime/
    __init__.py               # 统一模型调用入口
    adapter.py                # 多提供商适配（OpenAI/Anthropic/Google 等）
    pydantic_ai_loop.py       # Pydantic AI Loop 决策协议封装：类型安全的工具注册、结构化输出解析
    schema.py                 # 结构化输出 Schema 和解析
    policy_gate.py            # Loop action/args/预算 policy 校验
  citations.py              # evidence normalization and support validation
  errors.py
backend/app/modules/workspace/
  models.py router.py service.py artifacts.py
```

## 5. 核心对象与数据模型

所有主键使用 UUID/ULID 字符串或项目已有统一 ID 类型；以下以 UUID 表示。所有表使用 UTC `datetime(6)`，JSON 使用 MySQL JSON 类型，正文和大 payload 保存为受控 JSON/blob 引用而非无限制内联。

### 5.1 `agent_threads`

| 字段 | 类型/约束 | 用途 |
|------|-----------|------|
| `id` | PK | 线程 ID |
| `user_id` | FK, NOT NULL, indexed | 资源归属 |
| `title` | varchar(160) | 可延后异步生成，不能阻断创建 |
| `status` | enum(`active`,`archived`,`deleted`) | 用户可见生命周期 |
| `context_scope_json` | JSON | 已授权资料、固定学习范围等，不存秘密 |
| `last_message_at` | datetime | 列表排序 |
| `created_at`, `updated_at` | datetime | 审计 |

索引：`(user_id, status, last_message_at desc)`。所有按线程读取必须同时带 `user_id`。

### 5.2 `agent_messages`

| 字段 | 类型/约束 | 用途 |
|------|-----------|------|
| `id` | PK | 消息 ID |
| `thread_id` | FK, NOT NULL, indexed | 线程 |
| `user_id` | FK, NOT NULL, indexed | 冗余归属，避免跨表漏过滤 |
| `run_id` | nullable FK | 用户消息触发的 run 或 Agent 产出 run |
| `role` | enum(`user`,`assistant`,`system`) | 展示角色；内部步骤不写作用户消息 |
| `content_ref` | JSON/text ref | 经长度限制和脱敏后的内容 |
| `content_format` | enum(`plain`,`markdown`,`structured`) | 渲染策略 |
| `client_message_id` | nullable varchar(128) | 客户端去重辅助 |
| `created_at` | datetime | 排序 |

唯一约束：`(user_id, client_message_id)`，其中 `client_message_id` 非空。用户消息与 run 在同一事务创建，失败不得留下孤立的“已发送”消息。

### 5.3 `agent_runs`

| 字段 | 类型/约束 | 用途 |
|------|-----------|------|
| `id` | PK | 运行 ID |
| `thread_id`, `user_id` | FK, NOT NULL, indexed | 归属与资源隔离 |
| `workflow_key`, `workflow_version` | varchar, NOT NULL | 已选顶层工作流及不可变版本，例如 `explain` / `v1` |
| `workflow_definition_digest`, `state_schema_version` | char(64) / varchar | 已发布工作流定义摘要与运行状态 schema，用于恢复和 replay 校验 |
| `status` | enum, NOT NULL, indexed | 见第 6 节 |
| `request_id` | varchar(64), indexed | 端到端追踪 |
| `client_idempotency_key` | varchar(128) | 写请求去重 |
| `request_hash` | char(64) | 同 key 不同请求检测 |
| `parent_run_id`, `retry_of_run_id` | nullable FK | 恢复和重试谱系 |
| `current_step_key` | nullable varchar(80) | 当前/待执行节点 |
| `last_event_sequence` | bigint unsigned, default 0 | 原子分配事件序号 |
| `cancel_requested_at` | nullable datetime | 取消是协作式信号 |
| `lease_owner`, `lease_expires_at` | nullable | 防止多个 Worker 同时推进 |
| `next_wake_at` | datetime, indexed | 等待、重试和扫描唤醒 |
| `model_config_id`, `prompt_bundle_version` | nullable | 可复现版本 |
| `started_at`, `completed_at`, `expires_at` | datetime | 生命周期 |
| `error_code`, `safe_error_summary` | nullable | 用户/运维可用的失败信息 |
| `created_at`, `updated_at`, `row_version` | datetime/int | 乐观并发控制 |

唯一约束：`(user_id, client_idempotency_key)`；如果同 key 的 `request_hash` 不同，API 返回 `IDEMPOTENCY_CONFLICT`。扫描索引：`(status, next_wake_at, lease_expires_at)`。

### 5.4 步骤、Loop 回合、工具调用、检查点和事件

| 表 | 必填字段和约束 | 说明 |
|----|----------------|------|
| `agent_steps` | `run_id`, `sequence`, `step_key`, `attempt_no`, `step_type`, `status`, `input_hash`, `idempotency_key`, `lease_expires_at`, `output_ref`, `error_code`；唯一 `(run_id, step_key, attempt_no)` | 外层 Workflow 节点的尝试历史；`step_key` 必须属于该 run 固定版本的图定义。一个 `agent_loop` step 可包含多条 Loop turn。 |
| `agent_loop_turns` | `run_id`, `parent_step_id`, `turn_no`, `status`, `policy_key`, `policy_digest`, `decision_ref`, `action_key`, `action_args_hash`, `observation_ref`, `input_hash`, `latency_ms`, `error_code`, `created_at`；唯一 `(parent_step_id, turn_no)` | 内层 Loop 的逐回合持久记录。只保存结构化决策、安全摘要和受控引用，不保存隐藏推理链；`parent_step_id` 必须属于 `step_type=agent_loop`。 |
| `agent_tool_calls` | `step_id`, `loop_turn_id`（可空 FK）, `tool_key`, `tool_version`, `request_ref`, `response_ref`, `side_effect_state`, `provider_request_id`, `latency_ms` | 只保存脱敏摘要和受控引用。Loop 内工具调用必须关联 `loop_turn_id`；外层普通节点保持为空。 |
| `agent_checkpoints` | `run_id`, `checkpoint_no`, `workflow_version`, `resume_step_key`, `state_ref`, `input_versions_json`, `created_at`；唯一 `(run_id, checkpoint_no)` | 保存可恢复引用，非完整 ORM dump。 |
| `agent_events` | `run_id`, `sequence`, `event_type`, `payload_json`, `created_at`；唯一 `(run_id, sequence)` | SSE 和审计的业务事件源。 |
| `agent_run_outbox` | `id`, `run_id`, `kind`, `available_at`, `published_at`, `attempts`, `last_error` | 事务提交后的 Worker 唤醒。 |
| `agent_approvals` | `run_id`, `action_key`, `status`, `diff_ref`, `precondition_ref`, `decision_idempotency_key`, `decided_by`, `expires_at` | 审批与运行解耦但由 run 等待。 |
| `agent_inputs` | `run_id`, `input_key`, `input_schema_version`, `prompt_ref`, `status`, `answer_ref`, `answered_by`, `expires_at`；唯一 `(run_id, input_key)` | 结构化澄清、范围选择和其他等待用户输入；不把自由文本直接当作下一节点状态。 |
| `agent_artifacts` | `thread_id`, `run_id`, `type`, `version`, `status`, `payload_ref`, `citation_set_ref`, `visibility` | 讲解、练习草稿、报告、计划草稿。 |

`input_hash = SHA-256(规范化输入 + 工作流/工具版本 + 关键资源版本)`。Loop turn 的 `input_hash` 还包含锁定的 policy 摘要、turn 编号和前一轮 observation 摘要，以便判断恢复时是否仍是同一 action 上下文。任何有副作用的工具必须使用 `(run_id, step_key, input_hash)` 派生的服务端幂等键；不得使用模型生成的随机标识。P0 的 Loop 不允许有副作用工具。

`agent_steps` 和 `agent_loop_turns` 的职责不得混淆：前者回答“这个业务阶段是否已经完成并可转到下一外层节点”，后者回答“该阶段中模型基于哪个 observation 选择了哪一个允许 action”。两者共同支持回放，但所有用户可见业务转移仍以外层 step、checkpoint 和事件为准。

### 5.5 外部领域表的引用规则

- `agent_artifacts` 可以引用 `practice_sessions.id`，但创建会话由 `practice.create_draft` 命令完成。
- `agent_steps.output_ref` 只存领域对象 ID、版本和摘要，不把题目答案、原始用户文件或大段检索原文复制进运行表。
- 学习事实表记录 `source_run_id`、`source_step_id` 和领域命令幂等键，支持回放和审计。
- 用户资料删除后，引用仍保留最小删除标记；读取原文、向量和资产必须返回不可用，不能复活已删除数据。

### 5.6 学习、资料和评测域持久化接口

下列领域表由各自模块拥有；`agent` 只能持有 ID 和调用领域命令。字段和迁移与 Agent 运行绑定的部分在此处统一设计，其他内容语料表继续遵循[多模态数据结构与迁移清单](./multimodal-schema-migration-plan.md)。

| 模块 | 表 | 关键字段和约束 |
|------|----|----------------|
| `learning` | `learning_profiles` | `user_id`, `exam_date`, `target_score`, `daily_minutes`, `stage`。 |
| `learning` | `learning_goals` / `study_plans` / `study_tasks` | 目标、计划版本、任务状态；计划修改使用 `version` 乐观并发控制。 |
| `practice` | `practice_sessions` / `practice_session_questions` | `user_id`, `mode`, `status`, `source_run_id`；题目快照 `snapshot_json` 在会话创建时固化。 |
| `practice` | `question_attempts` / `mistake_records` / `mistake_reason_confirmations` | 作答、错题和用户确认的错因；必须关联用户、会话题和来源运行。 |
| `learning` | `mastery_evidence` / `mastery_states` / `review_schedules` | 追加式证据、聚合读模型和版本化复习调度。Agent 不直接写掌握百分比。 |
| `user_sources` | `user_sources`, `user_source_versions`, `user_source_assets`, `user_source_chunks` | 每层均有 `owner_user_id` 或可验证的归属；删除状态先撤销检索可见性，再清理对象和向量。 |
| `workspace` | `user_notes` / `thread_summaries` / `user_memory_items` / `memory_change_log` | 线程摘要版本化；长期记忆只保存用户明确且可删除的学习偏好。 |
| `evals` | `eval_datasets`, `eval_cases`, `eval_runs`, `eval_case_results`, `eval_annotations`, `eval_metric_results` | fixture、版本、逐案例结果和人工标注；评测运行不写用户学习事实。 |
| `agent` | `prompt_versions`, `tool_versions`, `model_configs` | 所有可重放 run 都引用已发布的依赖版本，运行后不可就地篡改。 |

学习事实使用追加式事件，例如 `question_started`、`answer_saved`、`hint_viewed`、`question_submitted`、`objective_graded`、`subjective_feedback_generated`、`mistake_reason_confirmed`、`review_scheduled`、`review_started`、`review_completed`、`task_completed` 和 `user_mastery_override`。每条记录必须包含用户、来源对象、发生时间、幂等键和 schema 版本；`source_run_id` / `source_step_id` 在适用时必填。

## 6. 状态机、租约与恢复

### 6.1 Run 状态

```text
queued -> planning -> running -> waiting_for_user -> running -> completed
                             \-> waiting_for_approval -> running

queued/planning/running -> failed | cancelled
waiting_for_user/waiting_for_approval -> expired
```

允许的转移由 `state_machine.py` 以静态映射定义，并在 `UPDATE ... WHERE status IN (...) AND row_version = ?` 中原子检查。终态 `completed`、`failed`、`cancelled`、`expired` 不可回到运行态。用户点击重试创建一个新 run，带 `retry_of_run_id`；从检查点恢复可复用同一 run，但必须增加新的 step attempt，不能覆盖已成功记录。

`waiting_for_user` 只表示等待结构化澄清或作答输入；`waiting_for_approval` 只表示审批待决定。两者均不持有 Worker 租约。用户输入/审批 API 会校验当前 run 和等待对象后写入数据、更新 `next_wake_at` 并投递 outbox。

### 6.2 Worker 租约

Worker 通过短事务获取 run：

1. 查询 `status in ('queued','planning','running')` 且 `next_wake_at <= now()`，并排除未过期的其他 Worker 租约。
2. 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 锁定候选，写入 `lease_owner`、`lease_expires_at` 和 `row_version + 1` 后提交。
3. 每个外部调用前后续租；若不能续租，停止提交任何后续结果。
4. scanner 将过期租约的 run 重新投递。若 step 已处于执行中，先依据步骤类型判断是否可安全恢复。

初始参数：运行租约 60 秒，Worker 每 20 秒续租；外部调用自身超时必须小于一次可续租窗口或支持独立续租。具体数值放入配置，不能散落在 workflow 中。

### 6.3 步骤恢复矩阵

| Step 类型 | Worker 崩溃或超时后的动作 |
|-----------|----------------------------|
| `gate` / 本地纯计算 | 以相同输入重跑。 |
| 只读检索 | 允许有限次指数退避重试；结果可因索引版本变化而变化，记录版本。 |
| 模型生成 | 新建 attempt；不将“请求已发出”误认为成功。供应商支持请求查询时优先查询。 |
| `agent_loop` decision | 若未持久化 decision，重新执行当前 turn 的结构化决策；若 decision 已提交但 action 未完成，按 action 类型恢复；不得跳过 turn 或扩大 policy。 |
| `agent_loop` 只读 action / observation | observation 与工具审计已在同一短事务提交时，从下一个 `turn_no` 继续；仅当前未提交 action 可按只读重试规则重试，且仍受原 turn/预算约束。 |
| 临时 artifact | 使用派生幂等键查找已有成功 artifact；不存在才创建。 |
| 领域命令 | 先查询命令幂等记录；结果未知时只查询或执行补偿，禁止盲重试。 |
| 外部/删除动作 | P0 不允许由 Agent 运行执行；未来必须单独定义查询、补偿与人工处置。 |

每一个成功外层 step 都先写 `agent_steps` 输出、工具审计和必要领域引用，再写 checkpoint 与 `step.completed` / 后继状态事件。`agent_loop` 的每一 turn 则先写 `agent_loop_turns`、其工具审计和 observation 引用，再写该 turn checkpoint/event；只有 Loop 固定出口发生时才将父 `agent_steps` 标记成功并转到后继外层节点。后续模型失败不回滚前一步已经提交的成功结果。

### 6.4 取消和过期

取消 API 只设置 `cancel_requested_at` 并追加 `run.cancel_requested`。Worker 在每个 step 前、模型/工具调用的可中断点后检查它；未产生副作用的 pending step 标为 `cancelled`，run 进入 `cancelled`。已经提交的用户消息、临时 artifact 和学习事实不被删除。

超过 `expires_at` 的等待 run 由 scanner 标记 `expired`，并追加事件。审批过期不会应用变更；用户必须生成新差异。取消和过期 API 都具有幂等性。

## 7. 工作流编排基线

工作流决定 Agent 在何时澄清、检索、生成、校验、等待和提交领域命令；其中有界 Loop 只决定获授权阶段内的下一次只读探索动作。详细设计独立维护在[Agent 工作流编排技术设计](./408-agent-workflow-orchestration-design.md)。本 Runtime 只负责将外层图和每个 Loop turn 可靠地执行、提交和恢复；图执行、持久执行和任务唤醒的具体实现以[工作流技术选型与风险分析](./408-agent-workflow-technology-selection-and-risk-analysis.md)的 PoC 与 ADR 结论为准。

首发顶层工作流为 `conversation`（自然语言入口路由）、`explain`、`validate`、`grade`、`plan`；`review`、`source_ingest` 和 `report` 复用同一节点契约逐步接入。所有工作流必须满足：

1. 外层图、版本、节点输入输出、Loop policy、可用工具、最大分支和预算在代码中固定并在 run 创建时锁定。
2. 模型可提出分类、教学结构、候选排序或反馈内容；在指定 Loop 中仅可从 action 白名单选择下一次只读探索，但不能生成任意外层节点、调用未授权工具或决定写入、重试、取消和审批。
3. 每个外层节点先通过前置条件和输入校验；Loop 每一 turn 还须通过 policy/action/资源/预算校验。结果先落 `agent_steps` 或 `agent_loop_turns`、检查点和事件，再进入后继节点或下一 turn。
4. 所有用户等待均创建结构化 `agent_inputs` 或 `agent_approvals`，恢复时重新校验输入、版本和资源归属。
5. 每个新增工作流都必须附带固定 fixture、分支覆盖、失败恢复、质量门禁和版本发布记录，未满足前不得暴露给路由器。

## 8. 模型、工具与引用

### 8.1 模型适配层

`model_runtime.py` 为每次调用记录：`model_config_id`、provider、模型名、Prompt bundle 版本、workflow 版本、`step_id`、可空的 `loop_turn_id`、输入/输出 token、延迟、供应商 request ID、结果状态和脱敏错误码。原始输入输出按照数据保留策略保存为受控引用，不进入常规日志。

每个模型节点定义 Pydantic 输出类型。例如解释生成最少包括：

```json
{
  "summary": "string",
  "sections": [{"title": "string", "content": "string", "claim_ids": ["c1"]}],
  "claims": [{"id": "c1", "text": "string", "citation_ids": ["src_1"]}],
  "next_actions": [{"kind": "validate", "label": "用题验证"}]
}
```

`next_actions` 仅是用户可见的后续操作建议；客户端点击后仍由服务端创建或恢复对应的已注册工作流，绝不把它解释为当前 run 的执行跳转。解析失败可在受限次数内以相同任务重试；仍失败则 run 以 `MODEL_OUTPUT_INVALID` 失败或给出不依赖模型结构的安全降级结果。严禁对不合规 JSON 做脆弱的字符串修补后直接执行工具。

Loop decision 也经同一结构化输出适配层处理，但其 Prompt 只接收锁定 policy、当前允许 action 的参数 Schema、最小事实和已提交 observation 摘要。decision 的 `action`、`args`、`expected_outcome` 必须全部通过 policy gate 后才能执行；模型的自然语言理由不作为 action 依据，也不记录为隐藏思维链。格式修复不可以改变 action 集、资源范围或剩余预算。

### 8.2 上下文装配与压缩

上下文按以下固定顺序装配：系统和安全规则、工作流状态、用户授权范围、不可变领域事实、当前用户消息、版本化线程摘要、最少量经排序的检索证据。原始资料正文一律标注为不可信内容。

当预计下一次调用超过模型上下文预算的 60%、阶段性 step 完成、即将进入等待状态，或达到消息/工具结果数量阈值时，创建新的 `thread_summaries` 版本。摘要必须保留：当前目标和待办、已确认事实、审批状态、不可重复副作用、来源引用、已排除候选、用户纠正和未提交答案。身份授权、题目/答案快照、幂等键和计划版本必须从领域表/step 引用重建，不能只相信模型摘要。

先缩减低相关检索片段，再压缩旧对话；不得截断当前用户指令、审批差异或未提交作答。

### 8.3 工具注册契约

```python
@dataclass(frozen=True)
class ToolDefinition:
    tool_key: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permission_level: Literal["R0", "R1", "R2", "R3", "R4"]
    timeout_seconds: int
    max_attempts: int
    has_side_effect: bool
    audit_level: Literal["summary", "restricted"]
    execute: Callable[[ToolContext, BaseModel], Awaitable[BaseModel]]
```

`ToolContext` 只提供 `user_id`、`thread_id`、`run_id`、`step_id`、可空的 `loop_turn_id`、锁定的授权资源和请求追踪信息，不提供数据库 session 或通用服务定位器。工具执行前的统一 policy gate 验证：工具版本是否已启用、当前 workflow/Loop policy 是否允许、用户/线程归属、资源可见性、审批状态、输入长度及领域前置条件。Loop 内还必须验证 tool 为 R0、`has_side_effect=False`、action 参数 Schema 和剩余回合预算；无论工具 observation 写了什么，均不能改变这些条件。

| 等级 | 可用工具 | 执行策略 |
|------|----------|----------|
| R0 | 学习状态、平台检索、题目检索、已授权个人资料检索 | 自动，但强制范围过滤。 |
| R1 | 讲解 artifact、练习草稿、报告草稿 | 自动，可重建或删除。 |
| R2 | 提交作答、创建可撤销复习任务、确认用户明确动作 | 需用户动作或 PRD 指定的可撤销自动策略。 |
| R3 | 修改周计划、归档错题、批量目标调整 | 必须存在未过期的明确审批。 |
| R4 | 任意外发、本地命令、任意本地路径、删除账号 | P0 禁止注册。 |

工具标准返回包含 `ok`、`data`、`warnings`、`evidence`、`usage`，失败包含稳定 `error_code`、`safe_message`、`retryable`、`side_effect_state`。供应商原始异常仅保存到受控技术日志。

### 8.4 引用和证据校验

检索门面返回不可伪造的 `CitationCandidate`：来源类型、实体 ID、版本、标题、页码/题号/block ID、可见范围、摘要、检索分数和内容哈希。模型只能从候选 ID 中引用；API 在生成 artifact 前验证：

1. citation ID 存在于本次 run 的候选集合。
2. 来源在当前用户和线程范围可见，且未删除或撤销授权。
3. 题目、文档、页码、block 与版本之间关系有效。
4. 每条标为核心的断言有至少一个可用引用；模型推断另行标记。

校验失败时移除不可用引用并进入安全降级或重试，绝不替换成猜测的页码/题号。用户资料引用始终以“我的资料”展示，不能显示为平台权威内容。

### 8.5 用户资料处理与删除

`source_ingest@v1` 不在 HTTP 请求中解析文件。上传 API 只在用户主动选择文件后创建 source/version、完成隔离存储和基础类型限制，并投递异步解析 run。处理状态固定为：

```text
created -> uploading -> uploaded -> parsing -> indexed -> ready
                                      |          |
                                      v          v
                                   failed     deleting -> deleted
```

`user_sources` 模块在进入解析队列前执行 MIME、大小、页数、图片像素、压缩炸弹和恶意文件扫描。解析产物按页、块、图片、表格和公式分层保存，所有对象都带 `owner_user_id` 与 source/version 归属。Qdrant 必须使用单独 collection 或不可省略的 owner payload filter；搜索适配层拒绝缺失 owner filter 的用户资料查询。

删除请求先在数据库事务中将 source 标为 `deleting` 并撤销其检索授权，随后异步删除原文件、派生文本、向量、缓存和可删除副本。失败可重试，完成后写 `deleted` tombstone。关闭“允许 Agent 使用”仅改变当前检索授权，不删除文件。模型和 Agent 只能读取本次 run 明确授权且状态为 `ready` 的资料。

## 9. HTTP 与 SSE 契约

所有 `/api/v1/app/*` 路由使用身份模块的学习用户会话、CSRF 规则和资源级授权。写请求均要求 `Idempotency-Key`，建议 UUID；长度 16 至 128，按用户作用域唯一。

### 9.1 主要路由

```text
POST /api/v1/app/agent/threads
GET  /api/v1/app/agent/threads
GET  /api/v1/app/agent/threads/{thread_id}
POST /api/v1/app/agent/threads/{thread_id}/runs
GET  /api/v1/app/agent/runs/{run_id}
GET  /api/v1/app/agent/runs/{run_id}/events
POST /api/v1/app/agent/runs/{run_id}/inputs/{input_key}
POST /api/v1/app/agent/runs/{run_id}/cancel
POST /api/v1/app/agent/runs/{run_id}/retry
POST /api/v1/app/agent/approvals/{approval_id}/decide
```

创建 run 请求：

```json
{
  "message": "循环队列中 front 为什么这样计算？",
  "workflow_key": "explain",
  "context_refs": [{"kind": "knowledge_point", "id": "kp_123"}],
  "source_ids": ["usr_src_123"],
  "client_message_id": "01J...",
  "client_version": "web-0.4.0"
}
```

`workflow_key` 可省略，服务端路由；非白名单值拒绝。`source_ids` 是用户对本次检索的授权意图，不替代服务端资源校验。成功返回 `202 Accepted`：

```json
{
  "thread_id": "thr_...",
  "run_id": "run_...",
  "status": "queued",
  "event_cursor": 1,
  "accepted_at": "2026-07-21T10:00:00Z"
}
```

重复的同幂等键和相同请求返回同一资源（`200` 或 `202`，实现统一使用 `200`）；同 key 不同请求返回 `409 IDEMPOTENCY_CONFLICT`。客户端绝不能因连接中断而用新的 key 重新创建 run。

处于 `waiting_for_user` 的 run 只能通过 `POST /runs/{run_id}/inputs/{input_key}` 提交对应的结构化答案。API 校验 `agent_inputs` 的用户归属、`status=pending`、过期时间、输入 Schema 和 `Idempotency-Key`，然后原子保存答案、恢复检查点并投递 outbox。它不接受任意 `next_step`、工具名、资源归属或工作流版本；已完成、过期或不匹配的输入返回稳定错误码，客户端应创建新 run 或刷新状态。

### 9.2 Run 查询响应

`GET /runs/{run_id}` 返回当前状态、最近安全摘要、可执行用户动作、最新 artifact 摘要和 `event_cursor`。不返回模型内部 step input、原始工具 request/response 或其他用户内容。

```json
{
  "id": "run_...",
  "thread_id": "thr_...",
  "workflow_key": "explain",
  "status": "waiting_for_user",
  "event_cursor": 12,
  "safe_summary": "需要确认你想复习循环队列的哪一种实现。",
  "available_actions": [{"kind": "answer_clarification", "input_id": "ask_..."}],
  "artifacts": []
}
```

### 9.3 SSE 协议

`GET /api/v1/app/agent/runs/{run_id}/events` 返回 `text/event-stream`。服务器先读取持久化快照，再读取 `Last-Event-ID` 指定 sequence 之后的事件，之后保持连接并定期查询/push 新事件。

```text
id: 12
event: artifact.created
data: {"run_id":"run_...","sequence":12,"artifact":{"id":"art_...","type":"explanation"}}

```

- `id` 固定为单 run 单调递增的 `sequence`；`Last-Event-ID` 必须是整数 sequence。
- `event_id` 仍在数据库中保存为内部 UUID，但客户端去重键使用 `(run_id, sequence)`。
- 首条 `run.snapshot` 包含当前 run 公开状态和 `sequence`；它不增加业务 sequence。
- 事件类型：`run.started`、`step.started`、`step.progress`、`loop.turn.completed`、`tool.started`、`tool.completed`、`artifact.created`、`approval.required`、`run.waiting`、`run.completed`、`run.failed`、`run.cancelled`、`run.expired`。`loop.turn.completed` 只包含 turn 编号、action 安全名称、结果状态、预算摘要和可显示进度，绝不包含模型隐藏推理、原始检索正文或工具参数。
- 心跳使用 SSE comment，不修改 cursor。连接关闭后客户端用 run 查询确认终态。
- 长时间断线、游标早于保留窗口或解析失败时服务器发送新快照和最新 cursor；客户端丢弃本地不可信的过期 step 展示。
- SSE 不可用时客户端每 3 秒查询 run，收到终态后停止。轮询不创建任何新运行。

### 9.4 错误模型

```json
{
  "code": "VERSION_CONFLICT",
  "message": "计划已在另一台设备更新，请查看最新差异。",
  "request_id": "req_...",
  "retryable": false,
  "details": {"current_version": 8}
}
```

错误码包括：`AUTH_REQUIRED`、`FORBIDDEN_RESOURCE`、`THREAD_NOT_FOUND`、`RUN_NOT_FOUND`、`INVALID_STATE_TRANSITION`、`RUN_ALREADY_TERMINAL`、`IDEMPOTENCY_CONFLICT`、`VERSION_CONFLICT`、`INPUT_NOT_PENDING`、`INPUT_EXPIRED`、`INVALID_INPUT_SCHEMA`、`WORKFLOW_DEFINITION_UNAVAILABLE`、`WORKFLOW_BUDGET_EXHAUSTED`、`LOOP_POLICY_VIOLATION`、`LOOP_BUDGET_EXHAUSTED`、`SOURCE_NOT_READY`、`QUESTION_UNAVAILABLE`、`EVIDENCE_INSUFFICIENT`、`RATE_LIMITED`、`MODEL_TIMEOUT`、`TOOL_TIMEOUT`、`SERVICE_UNAVAILABLE`。`details` 不得泄露内部 SQL、Prompt、密钥或他人资源标识。

### 9.5 管理端运行与评测接口

管理端继续使用 `/api/v1/admin/*` 和独立管理员权限。首发接口如下，具体 request/response 以 OpenAPI 实现为准：

```text
GET  /api/v1/admin/agent-runs
GET  /api/v1/admin/agent-runs/{run_id}
POST /api/v1/admin/agent-runs/{run_id}/replay

GET  /api/v1/admin/evals/datasets
POST /api/v1/admin/evals/datasets
GET  /api/v1/admin/evals/datasets/{dataset_id}/cases
POST /api/v1/admin/evals/runs
GET  /api/v1/admin/evals/runs
GET  /api/v1/admin/evals/runs/{eval_run_id}
POST /api/v1/admin/evals/runs/{eval_run_id}/cancel
POST /api/v1/admin/evals/cases/{case_id}/annotations
POST /api/v1/admin/quality-gates/{gate_id}/approve
```

`replay` 通过 `evals` 的隔离编排入口执行，默认使用脱敏输入、版本锁定的 Prompt/Workflow/Loop policy、固定工具 fixture 与独立模型额度。它只能产出 `eval_runs` / `eval_case_results`，禁止调用真实 `learning`、`practice`、`user_sources` 写命令。运行详情默认展示外层 step 和 Loop turn 的脱敏摘要；访问原始用户内容需要角色校验、理由和审计记录。

### 9.6 学习、练习和资料接口

以下接口由对应领域模块实现；`agent` 不复制它们的写入逻辑。所有查询都从认证会话取得 `user_id`，写操作遵循本节开头的 CSRF 与 `Idempotency-Key` 约束。具体字段以各模块的 Pydantic Schema 和最终 OpenAPI 为准，但不得弱化下列资源与并发语义。

```text
GET  /api/v1/app/me
GET  /api/v1/app/today
GET  /api/v1/app/map

POST /api/v1/app/practice/sessions
GET  /api/v1/app/practice/sessions/{session_id}
PUT  /api/v1/app/practice/sessions/{session_id}/answers/{question_id}
POST /api/v1/app/practice/sessions/{session_id}/submit
POST /api/v1/app/practice/sessions/{session_id}/questions/{question_id}/hint

GET  /api/v1/app/mistakes
POST /api/v1/app/mistakes/{mistake_id}/reason
POST /api/v1/app/mistakes/{mistake_id}/review

GET  /api/v1/app/sources
POST /api/v1/app/sources
GET  /api/v1/app/sources/{source_id}
POST /api/v1/app/sources/{source_id}/process
DELETE /api/v1/app/sources/{source_id}
```

- 练习读取返回创建时固化的题目快照和作答版本，而不是以题库当前数据重写历史题面。保存答案和提交操作必须带版本前提；不满足时返回 `VERSION_CONFLICT` 及可显示的新旧摘要。
- `submit` 是领域命令：它原子持久化本次作答、确定性客观判定和必要学习事实，并以命令幂等键防止重复提交。主观反馈和错因候选可另行创建 run，但不延迟保存用户已经提交的答案。
- `reason` 只能确认、修改、拒绝或标为无法判断既有错因候选；服务端校验作答、错题和候选的共同用户归属。`review` 只能创建或调整当前用户可撤销的复习安排。
- `POST /sources` 只接受用户主动选择的文件或上传会话，并返回资料与处理状态；解析不在请求中同步执行。`process` 仅恢复或重投当前用户有权处理的失败/待处理版本，禁止把任意文件路径交给服务端读取。
- `DELETE /sources/{source_id}` 先事务性撤销新检索授权并返回删除任务状态，后续异步清理由 `user_sources` 完成。重复删除返回同一删除任务或已删除状态，不能复活资料。

## 10. 事务与并发细节

### 10.1 创建运行

```text
authenticate user
  -> validate thread ownership / create new thread
  -> validate request schema and source authorization
  -> lock idempotency record
  -> insert user message
  -> insert run(status=queued)
  -> append run.started event(sequence=1)
  -> insert run outbox record
  -> commit
  -> best-effort publish wake-up
  -> return 202
```

同一线程可以存在多个历史 run，但 P0 默认禁止两个非终态主 run 并发修改同一线程的上下文。以 `(thread_id, active_slot)` 唯一键或专用锁实现；用户可以取消、等待或在另一线程发起新请求。练习提交、审批和运行恢复使用资源级版本号，不能静默覆盖。

### 10.2 追加事件

`append_event()` 在持有 run 行锁的事务中执行：递增 `last_event_sequence`，插入 `agent_events`，更新 run 的 `updated_at` 和必要状态。业务对象、step 输出、checkpoint 与事件处于同一事务，保证客户端不会收到指向不存在 artifact 的事件。

### 10.3 领域命令

领域命令接收 `CommandContext(run_id, step_id, user_id, idempotency_key)`。命令拥有自己的幂等记录，成功时返回不可变结果引用。运行恢复时先调用 `get_command_result(idempotency_key)`；有结果即复用，无结果才执行。命令内部必须在单一 MySQL 事务中更新领域对象和事实事件。

### 10.4 Loop turn 提交

Loop 的 parent `agent_steps` 进入 `running` 后，Worker 通过 `(parent_step_id, next_turn_no)` 创建当前 `agent_loop_turns`。decision 与外部工具调用不持有数据库事务；但 action 完成后必须在同一短事务中完成以下事项：

```text
lock run + parent step
  -> assert locked policy digest and remaining budget
  -> insert/update loop turn(decision summary, action, observation ref, status)
  -> insert associated agent_tool_calls(loop_turn_id)
  -> update checkpoint(flow.agent_loops + global budget)
  -> append loop.turn.completed safe event
  -> commit
```

事务提交后才允许开始下一 turn。若 policy 输出 `finish`、`need_scope`、预算耗尽或被阻断，写入 final turn/exit summary 后由同一或下一次 Worker 将父 step 完成并按外层图边转移。Loop 内不得取得 `CommandContext`、创建 `agent_inputs` 或 `agent_approvals`；这些操作只能发生在外层 `command` 或 `wait` 节点。

## 11. 安全、隐私和审计

- App router 使用 `require_current_user` 依赖；管理 router 使用单独的管理员依赖，两个认证受众不得混用。
- 所有 thread/run/artifact/source 查询在 SQL where 条件中带 `user_id`。仅依据可从 thread 推导归属的表也要通过 join/exists 实施过滤，并写 IDOR 测试。
- 模型或资料文本不得生成工具权限。工具执行前由 policy gate 校验实际资源 ID 和审批记录。
- Loop policy 是已发布工作流摘要的一部分。模型输出、工具 observation、用户资料或 SSE 客户端参数均不能改变 `allowed_actions`、`allowed_tools`、资源范围、最大 turn、出口或 `allow_domain_command` / `allow_user_wait`。
- 文件、原文、模型输入输出和工具敏感字段只写入受控存储；普通 `agent_events` 和日志只保存摘要、hash、ID 与稳定错误码。
- 管理员查看完整用户内容、受限工具审计或 replay 输入时需要角色和理由，理由写审计日志。
- 删除线程/资料立即撤销新查询可见性；对象、向量、缓存、摘要和评测副本由删除任务异步清理。历史审计仅保留最小不可识别 tombstone，遵循数据生命周期策略。
- 限制每用户活跃 run、消息长度、每日 token、工具调用数、文件处理量和 SSE 连接数。限流键使用 `user_id` + endpoint/workflow，不信任客户端 IP 作为唯一主体。

## 12. 可观测性与运维

每个 API 请求、run、step、Loop turn、工具调用、模型调用和领域命令都透传 `request_id`、`trace_id`、`user_id`、`thread_id`、`run_id`、`step_id` 和适用时的 `loop_turn_id`。日志按结构化字段记录，PII 默认脱敏。

最小指标：

- `agent_run_total{workflow,status}`、状态停留时间、恢复率、取消耗时、过期率。
- `agent_step_total{type,status,error_code}`、租约接管次数、重试次数、outbox backlog。
- `agent_loop_turn_total{workflow,policy,action,status,exit_outcome}`、每 policy 的预算耗尽率、重复 observation 率、policy 拒绝率、接管后续跑成功率和每 turn 的 token/工具成本。
- `agent_tool_latency_ms{tool,version}`、工具失败率、Schema 拒绝率、副作用幂等命中率。
- `agent_model_latency_ms{model,prompt_version}`、token、成本、结构化输出失败率。
- `agent_sse_connections`、事件投递延迟、断点续传成功率、轮询降级率。
- 引用支持失败、越权拦截、资料删除后检索命中（必须为零）。

告警初始阈值：Worker 无心跳、outbox oldest age 超过 60 秒、运行队列持续积压、租约接管异常升高、核心 workflow 失败率越过基线、0 容忍安全错误非零。正式 SLO 和容量阈值在内测数据后固化。

## 13. 测试与发布门禁

### 13.1 自动化测试

| 层级 | 必测内容 |
|------|----------|
| 单元 | 状态转移、input hash、idempotency key、工具/Loop policy、Loop decision Schema、引用校验、上下文压缩。 |
| 集成 | MySQL 事务、外层 step 与 Loop turn 事件顺序、SSE `Last-Event-ID`、Worker 租约接管、outbox 重投、取消、审批版本冲突。 |
| 领域 | 重复作答/审批不产生重复事实，题目快照不可被题库更新改写。 |
| 安全 | 所有资源 IDOR、用户资料隔离、Prompt injection 不触发工具或扩大 Loop policy、隐藏字段不进入 SSE/日志。 |
| E2E | 新建线程、刷新恢复、断线补发、解释到验证、Loop observation 提交后接管、模型超时后局部重试。 |
| 评测 | 固定用户状态和工具 fixture 下的引用、Loop action/turn/出口、工具顺序、证据不足、审批和恢复断言。 |

### 13.2 发布阻断项

- 引用不存在或越权、审批前长期写入、客观题最终判定错误、重复副作用、工具 Schema 绕过、用户资料隔离失败均为 0 容忍。
- 任何非终态 run 在 Worker 崩溃恢复后不得重复执行已成功领域命令。
- Loop action 不得调用未锁定的工具、写入领域事实、创建等待或超出 policy/总预算；所有 `LOOP_POLICY_VIOLATION` 必须在固定回归中可解释地收敛到定义出口。
- 核心 SSE 场景必须验证事件无序列缺口，且客户端重复事件不会重复渲染或发起写请求。
- 评测运行必须在隔离模式下验证不会写真实用户学习事实。

### 13.3 评测维度与固定回归集

评测同时覆盖离线固定 fixture、线上脱敏运行监控和人工复核。线上运行数据不得未经审核直接进入训练或发布判断；任何可复现问题都应沉淀为固定案例。

| 维度 | 最小断言 |
|------|----------|
| 意图和澄清 | 进入允许的工作流；歧义请求先询问必要信息。 |
| 检索和引用 | 候选证据召回满足基线；核心断言有可见、真实且关系正确的引用。 |
| 证据不足 | 无足够证据时输出明确降级，不捏造结论、页码或来源。 |
| 工具和权限 | 只选择当前工作流允许的工具，输入符合 Schema，资源与审批均经过 policy gate。 |
| Loop 边界 | 每轮 action/args/工具、turn 和出口均符合锁定 policy；observation 不能扩大权限、工具、预算或业务边。 |
| 练习和批改 | 题型、来源和质量门禁正确；客观题由确定性规则判定；主观反馈关联评分点证据。 |
| 学习闭环 | 错因候选不自动确认，复习与计划写入遵守用户动作和审批边界。 |
| 运行可靠性 | 幂等、取消、恢复、超时、重复事件和局部重试不重复产生副作用。 |
| 安全 | 不泄露敏感信息，不越权读取资料，不允许不可信内容扩大工具能力。 |

首批固定案例必须在版本控制中维护，至少覆盖：

- `E01`：循环队列 `front` 计算和 FQ-01 选项恢复。
- `E02`：含 A/B/C/D 寄存器名称的 FQ-02 主观题，避免题型和选项误判。
- `E03`：FQ-05/FQ-06 低质量、不完整题的阻断。
- `E04`：FQ-03 的长题干、公式和双图片引用。
- `E05`：平台证据不足时的诚实降级。
- `E06`：计划调整在审批前后不得越界写入。
- `E07`：工具成功后模型超时，验证局部重试不重复副作用。
- `E08`：用户表达焦虑时回到具体学习证据，不输出人格化结论。
- `E09`：证据探索在第三轮仍不足时进入 `evidence_gate` 降级，不产生第四轮调用。
- `E10`：检索 observation 试图要求调用未登记工具或写计划时，Loop policy 拒绝且命令数为零。
- `E11`：Loop observation 已提交后 Worker 崩溃，接管者从下一 turn 恢复，不重复已审计的工具调用。

每个案例固定输入、用户状态、可见资源、工具 fixture、允许调用序列、必须与禁止事实、引用集合、预期 Schema、评分 rubric 及模型/Prompt/工具/数据版本。评测执行时记录逐断言结果，不能只产出单一总分。

### 13.4 质量阈值与发布决策

核心集中的引用越权或不存在、客观题最终判定错误、审批前长期写入、题型或来源标签错误、工具 Schema 错误、重复副作用、资料隔离失败和安全输出违规均为 0 容忍。

核心集的引用支持率、证据不足正确降级率、工作流完成率和恢复率不得低于当前生产基线；p95 延迟、失败率和单次运行成本不得超过发布前冻结的预算。阈值在第一批人工标注后写入质量门禁配置，并按版本记录豁免理由。任何高风险单例失败都可以阻断发布，不能用平均分掩盖。

## 14. 实施顺序与迁移

### Phase 0：运行骨架

1. 新建 `workspace` 与 `agent` 模块、迁移表、资源归属索引和 app router。
2. 实现 thread/run/message、幂等写入、事件追加、SSE 快照/断点续传。
3. 实现 MySQL outbox、Worker 租约、扫描恢复和取消。
4. 实现 `agent_loop_turns`、Loop policy digest、每 turn checkpoint/事件与故障注入；为用户端替换 Agent fixture：只接入真实 thread/run/event，不先接入复杂学习写入。

### Phase 1：解释与验证

1. 把现有 `chat` 的 RAG 调用封装为 `retrieve_knowledge` 和模型适配器，不让新模块依赖旧 `ChatService` 的 Redis session。
2. 实现 `explain@v1` 的只读 `evidence_exploration_loop`、结构化 explanation artifact、引用候选和支持校验。
3. 实现 `validate@v1` 的只读 `question_discovery_loop`，再通过 `content` / `practice` 门面创建题目快照草稿。

### Phase 2 及以后

增加 grade、错因、复习、计划审批、用户资料和评测工具，但每一个新工作流先交付 Schema、幂等、权限、fixture、故障恢复和测试，再暴露给模型路由。

### 14.1 旧 Chat 迁移

1. 保留 `/api/v1/chat` 行为和现有 `ChatSession` 数据，不迁移或删除历史数据。
2. 新 Web Agent 页面只调用新 `/api/v1/app/agent/*`；旧 `/chat` 页面重定向到 Agent 工作区。
3. 旧 Chat 后端仅修复安全/稳定性问题，不新增工具、运行或用户学习状态。
4. 观测无新流量和保留期满足后，再为旧接口增加 deprecation header 并计划下线。

## 15. 未决项

1. Redis Stream 与仅 MySQL polling 的最终实现选择：P0 可以先用 MySQL polling + outbox；引入 Redis Stream 前必须补充多消费者、pending reclaim 和故障演练设计。
2. 运行与事件正文的保留期、加密和备份可删除性：由隐私/合规决策记录确定。
3. 模型供应商的请求查询/取消能力：适配层不得假定所有供应商支持；无支持时按第 6.3 节处理未知状态。
4. Worker 部署进程、并发和容量：以内测 token、延迟和队列深度数据确定，不把 FastAPI `asyncio.create_task()` 当作生产耐久队列。
5. 对象存储沿用现有部署还是引入 S3 兼容服务：以文件规模、备份、签名访问、删除追踪和可删除副本能力决策；本地路径不得成为用户 API 契约。
6. 复习调度是否采用 FSRS：首发先实现版本化、可回放的规则调度器；只有离线回放和线上学习证据证明收益后才替换。
7. 是否提供 MCP adapter：首发不开放 MCP server，未来 adapter 必须继续执行本文的工具 policy、资源归属、审批、审计和幂等约束，不能将内部领域能力无差别暴露。

任何新增工具、模型自主决策或运行状态都必须更新本文，说明其资源归属、输入输出 Schema、幂等、超时、恢复、权限、审计、评测 fixture 和删除影响。

## 16. 前端架构

本文档前文聚焦于后端运行时设计，本节补充前端（用户端与管理员端）的功能模块设计、API 调用模式、SSE 连接管理、状态管理策略及与后端的交互契约。

### 16.1 用户前端（frontend）

#### 16.1.1 页面与路由

- `AgentPage`：主对话页面，路径 `/agent` 和 `/agent/:threadId`。
  - 三栏布局：线程列表（左）、对话区（中）、执行轨迹（右）。
  - 支持新建线程、切换线程、发送消息、实时 SSE 推送。
  - 自动路由到新线程，无选中线程时展示引导文案。

#### 16.1.2 API 客户端（`api/agent.ts`）

封装与后端 `/api/v1/agent` 对应的所有接口：

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/agent/threads` | 创建线程 |
| GET  | `/api/v1/agent/threads` | 获取线程列表（分页） |
| GET  | `/api/v1/agent/threads/{id}` | 获取线程详情 |
| POST | `/api/v1/agent/runs` | 创建运行 |
| GET  | `/api/v1/agent/runs/{id}` | 查询运行状态 |
| POST | `/api/v1/agent/runs/{id}/submit` | 提交用户输入 |
| GET  | `/api/v1/agent/runs/{id}/events` | 分页获取事件 |
| GET  | `/api/v1/agent/runs/{id}/events/stream` | SSE 实时事件流 |
| GET  | `/api/v1/agent/runs/{id}/artifacts` | 获取运行产物 |

所有请求均携带 `credentials: 'include'` 以支持 Cookie 认证；SSE 使用原生 `EventSource` 并开启 `withCredentials`。

#### 16.1.3 状态管理（`store/agentStore.ts`）

采用 **React Context + useReducer** 方案，不引入 Redux 或 Zustand，降低学习成本与打包体积：

- **状态结构**：`threads`、`currentThreadId`、`currentRunId`、`runs`、`events`、`artifacts`、`loading`、`error`、`sseConnected`。
- **核心 Action**：`SET_THREADS`、`SET_CURRENT_THREAD`、`SET_CURRENT_RUN`、`SET_RUN`、`APPEND_EVENTS`、`SET_ARTIFACTS`、`SET_SSE_CONNECTED` 等。
- **SSE 连接管理**：`connectSSE(runId, afterSequence?)` 创建 `EventSource`，监听 `onmessage` 解析 JSON 并 dispatch `APPEND_EVENTS`；`disconnectSSE()` 关闭连接。连接断开后由页面级重试逻辑兜底（目前为手动刷新）。
- **副作用封装**：`loadThreads`、`createThread`、`createRun`、`submitInput` 等 Action 封装在 Context 中，组件层只需调用即可。

**注意**：`AgentProvider` 必须在 `main.tsx` 中包裹 `<App />`，否则 `useAgent()` 会在任何组件中抛出错误。

```tsx
// main.tsx 关键结构
<AuthProvider>
  <AgentProvider>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </AgentProvider>
</AuthProvider>
```

#### 16.1.4 组件设计

- **ThreadSidebar**：线程列表侧边栏，支持新建线程、切换线程、搜索线程。
- **ChatMessage**：对话消息组件，根据 `role`（user/assistant/system）渲染不同样式。
- **RunTrace**：执行轨迹面板，展示当前 run 的 step/event 流，支持步骤展开/折叠。
- **EventLog**：事件日志组件，按时间顺序展示 SSE 事件，自动滚动到底部。

### 16.2 管理员前端（frontend-admin）

#### 16.2.1 页面与路由

- `AgentRunsPage`：Agent Runs 监控页面，路径 `/admin/agent-runs`。
  - 路由注册在 `frontend-admin/src/router/index.tsx`。
  - 顶部统计卡片：总计、运行中、已完成、失败、等待用户、队列中。
  - 筛选栏：按状态、工作流、用户 ID、时间范围筛选。
  - 列表展示 Run ID、工作流、状态、用户、当前步骤、事件数、创建时间。
  - 操作列：详情、重放。

#### 16.2.2 API 客户端（`api/agentRuns.ts`）

封装管理员端 `/api/v1/admin` 对应接口：

| 方法 | 路径 | 用途 |
|------|------|------|
| GET  | `/api/v1/admin/agent-runs` | 分页查询运行列表 |
| GET  | `/api/v1/admin/agent-runs/{id}` | 查询运行详情 |
| GET  | `/api/v1/admin/agent-runs/{id}/events` | 查询运行事件（回放） |
| POST | `/api/v1/admin/agent-runs/{id}/replay` | 重新运行（评测入口） |
| GET  | `/api/v1/admin/agent-runs/stats` | 统计概览 |

使用 `adminClient`（Axios 实例）统一处理 Token 注入和错误拦截。

#### 16.2.3 组件设计

- **统计卡片**：使用 Ant Design `Statistic` + `Card`，按状态着色（运行中蓝色、已完成绿色、失败红色、等待用户橙色）。
- **筛选栏**：`Select`（状态、工作流）、`Search`（用户 ID）、`RangePicker`（时间范围）、`Button`（刷新）。
- **数据表格**：`Table` 组件，支持分页、排序、滚动固定操作列。
- **操作按钮**：
  - 详情：导航到 `/admin/agent-runs/:id`（目前复用同一页面，后续可扩展详情页）。
  - 重放：调用 `POST /api/v1/admin/agent-runs/{id}/replay`，成功后提示 Eval Run ID。

### 16.3 前后端交互契约

#### 16.3.1 认证方式

- **用户端**：通过 Cookie 认证（`credentials: 'include'`），依赖 `AuthProvider` 维护登录态。
- **管理员端**：通过 `Authorization: Bearer <token>` 头部认证，`adminClient` 拦截器自动注入。

#### 16.3.2 SSE 事件协议

客户端通过 `EventSource` 连接 `GET /api/v1/agent/runs/{run_id}/events/stream`：
- 支持 `Last-Event-ID` 断线重连（通过 query 参数 `after_sequence` 传递）。
- 事件格式为 JSON，`event_type` 字段标识事件类型（`run.started`、`step.started`、`loop.turn.completed`、`artifact.created` 等）。
- 客户端需对事件去重（按 `sequence`），并处理事件序列的单调递增。
- 心跳使用 SSE comment（`:` 开头的行），不触发 `onmessage`。
- 连接断开后，客户端应轮询 `GET /api/v1/agent/runs/{run_id}` 确认终态，避免无限重连。

#### 16.3.3 错误处理

- **用户端**：API 错误统一抛出 `AgentApiError`，组件层通过 try-catch 捕获并展示 Toast/Alert。
- **管理员端**：`adminClient` 响应拦截器统一处理 401（跳转登录）、403（无权限提示）、429（限流提示）。

#### 16.3.4 状态同步策略

- **乐观更新 vs 悲观更新**：
  - 用户发送消息后立即在 UI 中展示（乐观），随后通过 SSE 事件同步后端真实状态。
  - 线程创建、运行创建等操作等待 API 成功后再更新 UI（悲观），避免回滚复杂。
- **SSE 事件驱动**：前端状态以 SSE 事件为唯一实时更新来源，HTTP 轮询仅作为 SSE 不可用时的降级方案。
- **离线恢复**：页面刷新后，通过 `GET /api/v1/agent/runs/{id}` 获取最新状态和事件快照，重新建立 SSE 连接时携带 `after_sequence`。

### 16.4 安全与性能

- **防 XSS**：所有来自 SSE payload 的内容在渲染前进行 HTML 转义，避免模型输出或工具结果中的恶意脚本执行。
- **防重复渲染**：`APPEND_EVENTS` action 中对事件按 `sequence` 去重，避免 SSE 重连时的重复事件导致 UI 闪烁。
- **连接管理**：页面卸载时自动关闭 SSE 连接，避免内存泄漏。
- **限流保护**：前端对发送按钮进行防抖（300ms），避免用户频繁点击创建重复 run。
- **数据隔离**：用户端只展示当前用户的线程和运行；管理员端通过后端权限校验保证只能访问授权范围的数据。

### 16.5 前端与管理前端落实步骤

本节将前端与管理前端的实施步骤从路线图同步至运行时设计文档，确保设计与实现一致。

#### 16.5.1 用户前端（frontend）落实步骤

| 步骤 | 文件 | 任务 | 说明 |
|------|------|------|------|
| 1 | `frontend/src/api/agent.ts` | 创建 API 客户端 | 封装 thread/run/event/artifact/approval 的 CRUD 和 SSE 连接；使用原生 `fetch` + `credentials: 'include'` 的 Cookie 认证。 |
| 2 | `frontend/src/store/agent-context.tsx` | 创建状态管理 | React Context + useReducer；管理 threads、runs、events、artifacts、approvals、SSE 连接状态。 |
| 3 | `frontend/src/store/agent-context.tsx` | 实现 SSE 连接管理 | `connectSSE(runId, afterSequence?)` 创建 EventSource；`disconnectSSE()` 关闭连接；`onmessage` 解析 JSON 并 dispatch APPEND_EVENTS；自动重连。 |
| 4 | `frontend/src/pages/AgentPage.tsx` | 实现 Agent 对话页面 | 三栏布局：线程列表(AppShell侧边栏)/对话区/执行轨迹+证据面板；支持新建线程、发送消息、SSE 实时推送、审批 diff 渲染、工作流自动路由。 |
| 5 | `frontend/src/App.tsx` | 注册路由 | 添加 `/agent` 和 `/agent/:threadId` 路由，映射到 `AgentPage`。 |
| 6 | `frontend/src/main.tsx` | 包裹 AgentProvider | 在 `AuthProvider` 内包裹 `AgentProvider`，确保 `useAgent()` 可用。 |
| 7 | - | 联调验证 | 验证 thread 创建、run 创建、SSE 事件流、事件重放、断线重连等完整链路。 |

> **补充实施项**：
> - 提交按钮 loading 状态与 disabled 绑定，防止重复提交
> - 错误提示横幅：API 失败时自动展示，5 秒后自动清除
> - 工作流自动路由：`detectWorkflow` 根据用户输入关键词自动匹配 explain/validate/grade/plan

#### 16.5.2 管理员前端（frontend-admin）落实步骤

| 步骤 | 文件 | 任务 | 说明 |
|------|------|------|------|
| 1 | `frontend-admin/src/api/agentRuns.ts` | 创建 API 客户端 | 封装 `/api/v1/admin/agent-runs/*` 接口：分页查询、详情、事件回放、重放、统计、产物、审批。 |
| 2 | `frontend-admin/src/pages/AgentRunsPage.tsx` | 实现监控页面 | 统计卡片、筛选栏、运行列表；支持状态/工作流/用户/时间筛选。 |
| 3 | `frontend-admin/src/router/index.tsx` | 注册路由 | 添加 `/admin/agent-runs` 和 `/admin/agent-runs/:id` 路由。 |
| 4 | `frontend-admin/src/components/Sider/index.tsx` | 添加导航菜单 | 在左侧菜单添加 "Agent Runs 监控" 入口，图标使用 `ThunderboltOutlined`。 |
| 5 | - | 联调验证 | 验证列表查询、筛选、详情跳转、重放操作、统计接口等完整链路。 |

> **补充实施项**：
> - `AgentRunDetailPage.tsx` 事件类型过滤：支持按 `step.started`/`completed`/`failed`/`message.completed`/`run.status_changed`/`error` 等类型筛选
> - `AgentRunDetailPage.tsx` 产物查看：新增产物卡片，按类型展示结构化 JSON
> - 审批操作卡片：支持 approve/reject，操作后自动刷新审批列表和运行状态
> - 统计接口补全 `waiting_for_approval` 状态计数，前端统计卡片同步展示
