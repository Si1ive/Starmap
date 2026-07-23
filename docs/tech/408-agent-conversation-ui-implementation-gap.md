# 408 Agent 对话界面实现逻辑与代码缺口

> 版本：v0.3
>
> 日期：2026-07-23
>
> 状态：已完成动态路由与 Pydantic AI 上下文架构复审，按本文修订顺序继续实施
>
> 关联设计：[408 Agent 对话界面重设计](../product/408-agent-conversation-ui-redesign.md)

## 1. 结论

当前代码已经落地 thread 时间线、消息持久化、root/child run 聚合、thread SSE 和内嵌 workflow UI，但还没有实现真正的“统一 Agent 入口”。

当前最关键的缺口已经从页面和时间线，转移为 **动态决策、上下文装配与线程内调度**：

- 前端仍暴露 explain/validate/grade/plan 处理方式，并通过 `preferred_action` 传递用户预设。
- `conversation@v1` 只识别少量意图，最终仍把所有输入固定调度到 `explain`。
- 没有 `direct_answer` 普通问答路径；路由前澄清与 workflow 内结构化输入尚未区分。
- Worker 只把当前 `input_message` 放入执行上下文，没有读取 thread 历史、已有 artifact、附件和 `context_refs`。
- 每个 turn 都提前创建可见的 conversation workflow 块，内部路由过程会污染用户时间线。
- 同一 thread 没有 root run tree 串行调度约束，连续发送可能产生上下文竞争和回复乱序。
- 设计选定了 Pydantic AI 作为 Loop/模型运行时，但仓库未安装 `pydantic-ai`，现有 `ModelAdapter` 仍是直接调用 OpenAI SDK 的手写封装。

因此继续实施前必须先补齐：**统一入口 → thread 上下文构建 → Pydantic AI 类型安全路由 → 普通问答/澄清 → 业务 workflow 动态调度 → 线程内串行队列。** 在此之前继续增加取消、重试或消息操作，会把能力建立在错误的路由语义上。

## 2. 当前实现链路

```text
AgentPage
  ├─ thread timeline + thread SSE
  ├─ 用户选择 auto/explain/validate/grade/plan
  └─ POST /threads/{thread_id}/turns(preferred_action)

Backend
  create_turn
    ├─ 持久化 user message
    ├─ 创建可见 conversation root run
    ├─ 创建 message/workflow timeline item
    └─ outbox -> Worker

  conversation@v1
    ├─ 仅用当前 input_message 做意图识别
    ├─ 固定创建 explain child run
    └─ 输出“意图识别完成”内部消息

  explain@v1
    └─ 仅用当前 input_message 调用手写 OpenAI ModelAdapter
```

该结构已经能恢复一个 thread 的消息和多个 root run，但还不能根据完整对话上下文动态决定本轮行为。

上图为前端 `API_BASE=/api/v1` 之后使用的相对路径；仓库当前公开接口实际为 `/api/v1/agent/*`。本文目标契约沿用既有运行时设计中的用户端命名空间 `/api/v1/app/agent/*`。实施时应在网关或 FastAPI 路由层一次性确定该前缀，并在迁移期为 `/api/v1/agent/*` 提供兼容，前端代码中不要同时硬编码两套前缀。

## 3. 已确认的代码缺口

### 3.1 前端页面

| 缺口 | 当前代码 | 影响 | 优先级 |
|------|----------|------|--------|
| 用户仍可预设 workflow | `ChatComposer` 暴露 auto/explain/validate/grade/plan 下拉框 | 产品语义变成“选择执行模式”，而不是统一 Agent | P0 |
| 仍发送 `preferred_action` | `AgentPage`、context 和 API 类型继续传递该字段 | 路由责任泄漏到客户端 | P0 |
| 消息不是乐观插入 | 等待 `POST /turns` 成功后才刷新 timeline | 网络慢时缺少即时反馈，失败重试体验不完整 | P1 |
| 运行中可再次发送但无真实队列 | composer 只在 HTTP 提交期间禁用 | 可能创建并发 root run，回复顺序不可预测 | P0 |
| Assistant 正文仍是基础文本 | 尚未接入受控 Markdown、复制和反馈 | 完整对话能力未闭环 | P1 |
| 取消和真正的失败步骤重试缺失 | UI 只有继续对话等降级动作 | workflow 无法完整恢复 | P1 |
| 审批历史只投影 pending 项 | 决策后控件消失 | 无法回看批准或拒绝记录 | P1 |

### 3.2 后端模型与 API

| 缺口 | 当前实现 | 目标 | 优先级 |
|------|----------|------|--------|
| Router 固定调度 explain | `conversation._route_node` 写死 `target_workflow = "explain"` | 根据结构化 RouterDecision 动态选择处理方式 | P0 |
| 无普通问答路径 | conversation 只能创建业务 child run | `direct_answer` 直接产生 Assistant 消息且不显示 workflow | P0 |
| 路由前澄清与 workflow 输入混淆 | clarify 会降级到 explain | 路由前澄清走普通消息，workflow 内输入继续绑定原 run | P0 |
| 无 thread 上下文构建器 | Worker 只注入当前 `input_message` | 按预算装配历史消息、artifact、附件和 context refs | P0 |
| Pydantic AI 未实际接入 | requirements 无 `pydantic-ai`；`ModelAdapter` 直接调用 OpenAI SDK | 用 Pydantic AI 承担模型运行、依赖注入、受控消息历史消费和结构化输出 | P0 |
| conversation workflow 默认可见 | 每个 turn 预建 `presentation="workflow"` 时间线项 | 内部 router 静默，只有业务 workflow 被动态显现 | P0 |
| conversation 消息被统一丢弃 | thread event projector 忽略 conversation 的消息事件 | 只过滤内部事件，允许公开 direct answer/clarify 消息 | P0 |
| 无 thread 级执行互斥 | lease 只锁单 run | 每个 thread 同时最多运行一个 root run tree | P0 |
| 附件和引用未传给 child | 只存在 root metadata 中 | Router 与 child workflow 使用同一受控上下文 | P0 |
| 公开 `/runs` 可直接指定 workflow | 用户端仍可提交 `workflow_name` | 降为内部/管理端兼容接口，普通聊天只使用 turns | P0 |
| 审批响应结构不统一 | 列表与 approve/reject 响应字段不同 | 返回完整 approval 或统一 envelope | P1 |
| 状态枚举不完整 | 模型缺少 `planning`、`cancelled`、`expired` | 与运行时文档及 UI 状态一致 | P1 |
| 无 cancel/retry API 实现 | 运行时文档已定义，当前路由缺失 | 停止、局部重试和谱系可用 | P1 |

## 4. 目标领域关系

```text
AgentThread
  ├─ AgentMessage[]
  │    ├─ role: user | assistant | system
  │    ├─ status: pending | streaming | completed | failed
  │    └─ trigger/root run reference
  │
  ├─ AgentThreadItem[]                # thread 级只读时间线投影
  │    ├─ message item
  │    ├─ workflow item
  │    └─ system notice item
  │
  └─ AgentRun[]
       ├─ trigger_message_id
       ├─ parent_run_id / root_run_id
       ├─ presentation
       ├─ AgentStep[]
       ├─ AgentEvent[]
       ├─ AgentArtifact[]
       ├─ AgentInput[]
       └─ AgentApproval[]
```

`AgentThreadItem` 是展示投影，不替代业务实体。它解决不同类型内容的稳定排序、分页和 cursor 问题。

## 5. 数据模型补充

### 5.1 `agent_messages`

建议新增：

| 字段 | 类型/约束 | 用途 |
|------|-----------|------|
| `id` | varchar(32), PK | 消息 ID |
| `thread_id` | FK, indexed | 所属线程 |
| `user_id` | indexed | 权限隔离 |
| `run_id` | nullable FK | 生成或消费该消息的 run |
| `role` | enum | `user`、`assistant`、`system` |
| `status` | enum | `pending`、`streaming`、`completed`、`failed` |
| `content_text` | longtext | 当前可恢复文本快照 |
| `content_blocks_json` | nullable JSON | 公式、代码、引用、附件等结构化块 |
| `client_message_id` | nullable varchar(128) | 客户端幂等去重 |
| `error_code` | nullable varchar(64) | 消息生成失败稳定码 |
| `created_at`、`updated_at`、`completed_at` | datetime | 生命周期 |

约束：

- `(user_id, client_message_id)` 在 `client_message_id` 非空时唯一。
- 用户消息与 root run 必须在同一事务创建。
- Agent 流式消息先创建 `streaming` 记录，完成后原子更新为 `completed`。
- 不在消息正文中存储隐藏推理。

### 5.2 `agent_thread_items`

建议新增轻量 read model：

| 字段 | 类型/约束 | 用途 |
|------|-----------|------|
| `id` | varchar(32), PK | 时间线项 ID |
| `thread_id` | FK, indexed | 所属线程 |
| `sequence` | bigint, NOT NULL | thread 内单调递增顺序 |
| `item_type` | enum | `message`、`workflow`、`notice` |
| `ref_id` | varchar(32) | 对应 message 或 root run |
| `run_id` | nullable FK | workflow 或关联 run |
| `visibility` | enum | `visible`、`hidden` |
| `created_at` | datetime | 创建时间 |

唯一约束：`(thread_id, sequence)`。

`agent_threads` 增加 `last_item_sequence`，追加时间线项时使用行锁或原子更新分配 sequence。

为什么不只按 `created_at` 排序：同一事务、并发 run、重试和子 workflow 可能拥有相同或交错时间；时间戳不能承担稳定 cursor。

### 5.3 `agent_runs` 增补字段

| 字段 | 用途 |
|------|------|
| `trigger_message_id` | 绑定触发该 run 的用户消息 |
| `parent_run_id` | 父 workflow/run |
| `root_run_id` | UI 聚合与查询 root workflow |
| `retry_of_run_id` | 重试谱系 |
| `workflow_key`、`workflow_version` | 替代把版本拼进字符串 |
| `presentation` | `silent`、`compact`、`workflow` |
| `public_title` | UI 可直接展示的名称 |
| `public_summary` | 当前安全摘要快照 |
| `current_public_step` | 当前公开步骤 key |
| `started_at`、`completed_at` | 可靠耗时 |

`conversation` 路由 run 通常可设为 `silent` 或作为 root；真正执行的子 workflow 通过 `root_run_id` 聚合进同一个可见 workflow 块。不要让前端根据 workflow 名称猜测哪些 run 要隐藏。

### 5.4 公开步骤元数据

workflow 定义需要为每个可见节点提供：

```python
public_step = {
    "key": "quality_check",
    "label": "检查题目质量",
    "description": "检查题干、选项、答案和解析是否完整",
    "visibility": "visible",
}
```

内部节点名、类名和工具名不能直接作为用户文案。

## 6. UI 面向的 API 契约

### 6.1 创建一次对话 turn

推荐新增 UI 面向接口：

```text
POST /api/v1/app/agent/threads/{thread_id}/turns
```

请求：

```json
{
  "content": "根据刚才的讲解给我出 3 道题",
  "attachments": [],
  "context_refs": [],
  "client_message_id": "01K..."
}
```

响应：

```json
{
  "user_message": {
    "id": "msg_user_1",
    "status": "completed",
    "content": "根据刚才的讲解给我出 3 道题"
  },
  "root_run": {
    "id": "run_1",
    "status": "queued",
    "presentation": "silent",
    "public_title": null
  },
  "timeline_cursor": 18
}
```

服务端在该接口中完成：

1. 校验 thread 归属。
2. 以 `client_message_id` 幂等创建用户消息。
3. 服务端执行 `conversation@v1` 路由，不信任客户端 workflow key。
4. 创建 `presentation=\"silent\"` 的 conversation root run、可见 user message item 和隐藏的 workflow 占位 item。
5. 同一事务提交后投递 outbox。
6. Router 决定启动业务 workflow 后，把占位 item 切为可见并投影业务 child run；direct answer/clarify 则保持隐藏。

兼容期可保留现有 `POST /api/v1/agent/runs`，但用户端不再直接调用；管理端和测试工具可以继续使用显式 workflow。

### 6.2 获取 thread 时间线

```text
GET /api/v1/app/agent/threads/{thread_id}/timeline?before={cursor}&limit=50
```

响应：

```json
{
  "thread": {
    "id": "thr_1",
    "title": "循环队列理解与练习",
    "updated_at": "2026-07-23T10:10:00Z"
  },
  "items": [
    {
      "id": "item_16",
      "sequence": 16,
      "type": "message",
      "message": {
        "id": "msg_user_1",
        "role": "user",
        "status": "completed",
        "content": "根据刚才的讲解给我出 3 道题"
      }
    },
    {
      "id": "item_17",
      "sequence": 17,
      "type": "workflow",
      "workflow": {
        "root_run_id": "run_1",
        "status": "running",
        "title": "生成专项练习",
        "summary": "正在检查候选题质量",
        "progress": {"completed": 2, "total": 4},
        "steps": [],
        "pending_input": null,
        "pending_approval": null,
        "artifacts": []
      }
    }
  ],
  "previous_cursor": 16,
  "latest_cursor": 18,
  "has_more": true
}
```

原则：前端不应通过合并所有 run、event、artifact、approval 后自行猜测时间线。后端返回已经过权限过滤和公开字段裁剪的投影。

### 6.3 thread 事件流

```text
GET /api/v1/app/agent/threads/{thread_id}/events/stream?after_sequence=18
```

所有事件使用 thread 级 `sequence`，建议事件类型：

| 事件 | 用途 |
|------|------|
| `timeline.item.created` | 新消息或新 workflow 插入 |
| `message.started` | 创建 Agent 流式消息 |
| `message.delta` | 追加文本片段 |
| `message.completed` | 消息完成并附最终快照 |
| `message.failed` | 消息生成失败 |
| `workflow.updated` | 状态、摘要、进度更新 |
| `workflow.step.updated` | 公开步骤更新 |
| `workflow.input.required` | 需要结构化补充 |
| `workflow.approval.required` | 需要审批 |
| `workflow.artifact.created` | 新产物可用 |
| `workflow.completed` | workflow 完成 |
| `workflow.failed` | workflow 失败及保留结果 |
| `workflow.cancelled` | workflow 已停止 |

示例：

```text
id: 22
event: message.delta
data: {"sequence":22,"message_id":"msg_a1","delta":"循环队列中，front 表示"}
```

### 6.4 timeline snapshot

连接建立或 cursor 失效时，服务端先发送：

```text
event: timeline.snapshot
data: {
  "latest_sequence": 22,
  "active_items": [...],
  "updated_items": [...]
}
```

snapshot 用于纠正本地状态，不增加业务 sequence。客户端收到后以服务端快照为准，再消费后续事件。

### 6.5 workflow 操作

```text
POST /api/v1/app/agent/runs/{run_id}/inputs/{input_key}/answer
POST /api/v1/app/agent/runs/{run_id}/approvals/{approval_id}/decide
POST /api/v1/app/agent/runs/{run_id}/cancel
POST /api/v1/app/agent/runs/{run_id}/retry
```

审批接口建议统一为：

```json
{
  "decision": "approved",
  "client_idempotency_key": "01K..."
}
```

响应返回更新后的完整 workflow 投影或至少返回最新 cursor，避免前端只更新局部 approval 后丢失 run 状态。

## 7. 流式消息持久化

### 7.1 生成流程

```text
创建 assistant message(status=streaming)
  -> append timeline item
  -> emit message.started
  -> 模型流式返回
  -> 每个 chunk emit message.delta
  -> 每 250–500ms 或累计一定字符更新 content_text 快照
  -> 完成时更新 message(status=completed)
  -> emit message.completed(final snapshot)
```

### 7.2 为什么不能只在内存中拼接

- 页面刷新后会丢失已生成部分。
- Worker 崩溃后无法区分“从未开始”和“已输出一半”。
- SSE 断线后客户端没有可信恢复点。

### 7.3 写入节流

不建议每个 token 都写数据库：

- SSE 可以高频发送 delta。
- 数据库快照按 250–500ms、20–50 token 或句子边界批量更新。
- 完成、失败、取消前必须强制 flush 最终快照。

## 8. workflow 聚合规则

### 8.1 root 与 child run

同一用户 turn 可以产生：

```text
conversation root run
  └─ validate child run
       ├─ retrieve step
       ├─ quality gate step
       └─ create practice step
```

UI 默认只显示一个 workflow 块：

```text
生成专项练习
```

聚合规则：

- `root_run_id` 相同且 `presentation != workflow` 的 child run 不创建新的顶层 timeline item。
- child run 的公开步骤合并到 root workflow 投影。
- child run 若要求独立审批、产生可单独使用的长期任务，定义可将 `presentation` 设为 `workflow`，此时创建新的顶层块。
- 所有 run 都保留完整后台审计，不因 UI 聚合删除技术记录。

### 8.2 多次 workflow

每一次用户输入创建独立 conversation root run。只有 Agent Router 决定启动业务 workflow 时，对应的 workflow timeline item 才变为可见；状态更新必须按 `root_run_id` 精确更新原位置，不能使用全局 `currentRunId`。

### 8.3 重试

局部步骤重试优先留在原 workflow 块中：

- `attempt_no` 增加。
- 已成功步骤不回退。
- UI 显示“第 2 次尝试”。

如果用户在终态后主动重新执行整个任务，则创建新 root run 和新 workflow 块，并通过 `retry_of_run_id` 关联。

## 9. 前端目标结构

建议把 Agent 页面从单文件拆成：

```text
frontend/src/
  pages/agent/
    AgentConversationPage.tsx
    NewConversationPage.tsx
  widgets/agent-conversation/
    ConversationStream.tsx
    ConversationItem.tsx
    UserMessage.tsx
    AssistantMessage.tsx
    WorkflowBlock.tsx
    WorkflowSteps.tsx
    WorkflowClarification.tsx
    WorkflowApproval.tsx
    WorkflowArtifact.tsx
    WorkflowFailure.tsx
    ConversationComposer.tsx
    EvidenceDrawer.tsx
    ScrollToLatestButton.tsx
  entities/agent/
    types.ts
    api.ts
    event-reducer.ts
    timeline-normalizer.ts
  features/agent/
    send-turn.ts
    answer-input.ts
    decide-approval.ts
    cancel-run.ts
    retry-run.ts
```

如果暂不引入目录重构，至少也应先把上述组件从 `AgentPage.tsx` 拆出，避免新的时间线逻辑继续堆在一个页面文件中。

## 10. 前端状态模型

### 10.1 状态边界

| 状态 | 存放位置 |
|------|----------|
| thread、timeline、run、message、approval | 服务端事实缓存 |
| URL 中的 `thread_id`、定位 item | Router |
| 输入草稿、展开状态、抽屉开关 | 局部 UI 状态 |
| SSE 连接状态、cursor | thread 订阅控制器 |

建议引入 TanStack Query 管理服务端事实；如果第一阶段继续使用 reducer，也必须按 thread 归一化，而不是使用单一 `currentRunId`。

### 10.2 建议类型

```ts
type ConversationItem =
  | { id: string; sequence: number; type: 'message'; message: MessageView }
  | { id: string; sequence: number; type: 'workflow'; workflow: WorkflowView }
  | { id: string; sequence: number; type: 'notice'; notice: NoticeView }

interface ThreadConversationState {
  threadId: string
  itemsById: Record<string, ConversationItem>
  orderedIds: string[]
  messageDrafts: Record<string, string>
  latestSequence: number
  connection: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'offline'
}
```

### 10.3 事件 reducer 规则

```text
timeline.item.created
  -> 若 sequence 已存在则忽略
  -> 插入 orderedIds 并保持 sequence 顺序

message.delta
  -> 按 message_id 追加 delta
  -> 若 delta_index 已消费则忽略

message.completed
  -> 用 final snapshot 覆盖本地拼接内容
  -> status = completed

workflow.updated
  -> 按 root_run_id 更新对应 workflow item
  -> 不移动 item 位置

timeline.snapshot
  -> 用服务端 active/updated items 修正本地
  -> latestSequence = snapshot.latest_sequence
```

所有事件必须幂等。当前 `APPEND_EVENTS` 直接拼接数组的实现需要替换。

## 11. 订阅与恢复逻辑

### 11.1 打开线程

```text
1. GET timeline 最近 50 项
2. 立即渲染持久化内容
3. 记录 latest_cursor
4. 连接 thread SSE(after_sequence=latest_cursor)
5. 收到 snapshot 后校正 active workflow 和 streaming message
6. 用户向上滚动时按 before cursor 加载更早内容
```

### 11.2 断线

```text
SSE error
  -> connection = reconnecting
  -> 指数退避 1s / 2s / 4s / 8s，最大 15s
  -> 先 GET timeline/updates?after=cursor 补拉
  -> 再重连 SSE
  -> 去重 sequence
```

页面只在持续离线后显示弱提示；不要用全屏错误覆盖已加载对话。

### 11.3 刷新恢复

- 不依赖内存中的 `events[runId]`。
- timeline 返回正在流式的 assistant message 快照和 active workflow 摘要。
- 服务端 cursor 决定从哪里继续，不从 0 重放全部事件。

## 12. 发送消息逻辑

### 12.1 乐观消息

1. 客户端生成 `client_message_id`。
2. 本地插入 `pending` 用户消息。
3. 调用 `POST /turns`。
4. 成功后用服务端 message ID 替换临时 ID。
5. 超时后使用同一 idempotency key 查询或重试，不创建第二条消息。

### 12.2 workflow 路由

删除用户端 workflow 选择器、`detectWorkflow` 和 `preferred_action`。所有普通输入只进入统一的 `conversation@v1`：

- 服务端结合当前输入、thread 历史、附件、上下文引用和最近 artifact，决定直接回答、澄清或调度 explain/validate/grade/plan。
- 建议按钮只能提交自然语言，例如“根据刚才的内容给我出三道题”，不能传 workflow key 或绕过 RouterDecision。
- workflow key 不在普通 UI 中暴露。
- 路由前 `clarify` 产生普通 Assistant 消息；workflow 已启动后的补充输入继续使用 `AgentInput` 并绑定原 run。
- `conversation` root 默认是 `silent`，只有决定启动业务 workflow 后才显现对应的 workflow timeline item。

结构化路由契约：

```python
class RouterDecision(BaseModel):
    action: Literal[
        "direct_answer",
        "clarify",
        "explain",
        "validate",
        "grade",
        "plan",
    ]
    confidence: float = Field(ge=0, le=1)
    reason_code: str
    public_summary: str | None = None
    clarification_question: str | None = None
```

选择标准不是简单关键词映射：

- `direct_answer`：当前上下文足以完成的普通问答、追问和轻量解释。
- `clarify`：缺少题目、作答、目标或必要引用，无法安全继续判断。
- `explain`：需要检索证据、组织结构化讲解或生成可复用讲解产物。
- `validate`：用户要求出题、验证理解或生成练习。
- `grade`：用户提供作答并要求评分、分析或反馈。
- `plan`：用户要求根据学习证据生成或修改计划。

### 12.3 运行中继续发送

后端需要明确选择一种策略：

**推荐 P0：同线程串行 turn 队列。**

- 每个 thread 同时最多一个会改变 thread 上下文的 root run。
- 新 turn 持久化为 `queued`，UI 立即显示。
- 当前 root run 终止或进入长期等待后，调度下一条 turn。
- 用户可以取消尚未开始的 turn。

只读且互不影响的 run 以后可以并行，但不能由前端无条件创建并发 run。

### 12.4 Pydantic AI 上下文与模型运行时

#### 12.4.1 选型结论

Pydantic AI 继续作为本项目的模型 Loop/Agent 运行时，但不作为 thread、message、run 或 workflow 的持久化事实源。

职责边界：

| 层 | 负责内容 | 不负责内容 |
|----|----------|------------|
| MySQL + Agent kernel | thread/message/run/workflow 状态、队列、审批、幂等、恢复、权限和公开时间线 | 模型 provider 细节和 prompt 内消息编排 |
| `ThreadContextBuilder` | 从持久化事实中选择、裁剪、摘要并组装本轮上下文 | 执行业务 workflow 或直接调用模型 |
| Pydantic AI | 消费 `message_history`、`RunContext/deps`、工具注册、结构化输出、输出校验和 usage limits | 自动决定哪些数据库事实应进入上下文；替代 durable workflow 状态机 |
| workflow definitions | explain/validate/grade/plan 的确定性步骤、等待、审批和副作用边界 | 保存完整聊天历史或自行拼接 provider 私有消息格式 |

官方能力参考：

- [Message History](https://ai.pydantic.dev/message-history/)
- [Dependencies / RunContext](https://ai.pydantic.dev/dependencies/)
- [Output](https://ai.pydantic.dev/output/)
- [Usage Limits](https://ai.pydantic.dev/agents/#usage-limits)
- [Durable Execution](https://ai.pydantic.dev/durable_execution/)

Pydantic AI 提供 durable execution 集成能力，不等于只安装 SDK 就自动获得本项目需要的持久化。当前仍使用 MySQL outbox/lease/Worker 作为生产事实和恢复边界；未来若评估 Temporal、DBOS、Prefect 或 Restate，必须通过独立 PoC 迁移，不能让模型运行时直接接管现有业务状态。

#### 12.4.2 上下文事实源

每次 turn 执行前由 `ThreadContextBuilder` 读取并生成 `AgentRunContext`：

```python
class AgentRunContext(BaseModel):
    thread_id: str
    user_id: str
    turn_id: str
    current_message_id: str
    current_input: str
    recent_messages: list[ConversationMessage]
    conversation_summary: str | None
    recent_artifacts: list[ArtifactContext]
    attachments: list[AttachmentContext]
    context_refs: list[ContextReference]
    pending_interactions: list[PendingInteraction]
    permission_scope: PermissionScope
    token_budget: int
```

数据来源与用途：

| 数据 | 来源 | 进入模型的形式 |
|------|------|----------------|
| 最近用户/Assistant 对话 | `agent_messages` | 转换为 Pydantic AI `message_history` |
| 较早对话 | thread summary 或摘要 artifact | 一条受控摘要消息，不无限回放原文 |
| workflow 结果 | `agent_artifacts` 和公开 run summary | 结构化短摘要与稳定 artifact id |
| 当前附件 | root run metadata/附件表 | 经权限和类型校验后的文本或引用 |
| `context_refs` | 业务资源解析器 | 解析后的只读领域对象摘要 |
| 待审批/待输入 | `agent_approvals`、`agent_inputs` | 仅提供当前公开状态和可执行动作 |

禁止直接进入上下文：

- 隐藏思维链、内部 prompt 和未经裁剪的工具返回。
- 其他用户或无权限资源。
- 已过期的审批 token、秘密字段和 provider 凭据。
- 整个 thread 的无限原文历史。

#### 12.4.3 Pydantic AI 的具体使用方式

Router、普通回答和需要模型参与的 workflow 节点分别定义独立 Agent，不使用一个无限能力的全局 Agent：

```python
router_agent = Agent(
    model=router_model,
    deps_type=RouterDeps,
    output_type=RouterDecision,
)

result = await router_agent.run(
    current_input,
    deps=router_deps,
    message_history=context.message_history,
    usage_limits=router_usage_limits,
)
```

实现约束：

- `deps` 注入本轮只读服务、权限范围、thread/turn 标识和经过校验的领域上下文；不得把全局可写数据库能力无边界暴露给 Router。
- `message_history` 由 `ThreadContextBuilder` 生成，不把前端提交的任意历史当作事实。
- `ThreadContextBuilder` 在调用模型前完成预算裁剪，再把处理后的历史作为 `message_history` 传入：保留最近相关消息、当前任务所依赖的 artifact 和未完成交互，压缩较早历史。
- `output_type=RouterDecision` 取代手写字符串解析；验证失败按稳定策略重试或降级为安全澄清，不能默认降级到 explain。
- `UsageLimits` 与现有 `max_model_calls`、token 预算和工具调用预算映射，超限后返回可恢复错误。
- Pydantic AI 的 `new_messages()` 可用于运行时审计和调试，但用户可见事实仍写入 `agent_messages`、`agent_events` 和 artifact；不能把 provider 私有消息对象直接作为唯一持久化格式。

#### 12.4.4 上下文裁剪策略

P0 使用确定性预算策略，不让模型自由决定是否遗忘关键业务状态：

1. 永远保留当前用户输入、权限范围和 system instructions。
2. 永远保留未完成的审批、结构化输入和当前引用对象。
3. 保留最近 6 至 12 个可见 turn，最终数量由 token 预算决定而不是固定条数决定。
4. 保留被当前输入显式引用的 artifact、题目、作答和计划摘要。
5. 较早对话压缩成版本化 thread summary；摘要必须能追溯到覆盖的 message sequence。
6. 工具大结果只保留摘要和稳定引用，需要时由受控工具再次读取。
7. Router 使用较小上下文预算；业务 workflow 可以按任务需要加载更窄、更深的领域上下文。

上下文构建结果应记录可观测元数据：选入的 message/artifact id、裁剪原因、摘要版本、估算 token、实际 usage 和策略版本，但不记录隐藏思维链。

## 13. waiting、approval、artifact 的恢复

### 13.1 结构化输入

timeline/workflow 投影必须返回：

```json
{
  "id": "input_1",
  "input_key": "scope_choice",
  "status": "pending",
  "question": "你想先理解，还是直接做题？",
  "schema": {
    "kind": "single_choice",
    "choices": [
      {"value": "explain", "label": "先理解"},
      {"value": "validate", "label": "直接做题"}
    ]
  },
  "expires_at": null
}
```

前端不能只得到 `waiting_for_user` 后展示通用 textarea。

### 13.2 审批

`diff_ref` 不应由前端直接 `JSON.parse` 一个不透明字符串。后端需返回经过 schema 验证的：

```json
{
  "kind": "plan_change",
  "title": "调整本周学习计划",
  "summary": "增加循环队列复习 20 分钟",
  "before": [...],
  "after": [...],
  "reversible": true,
  "reject_effect": "拒绝后不影响当前对话"
}
```

若数据库继续保存 ref，API 层负责解析与校验，失败时返回安全降级文案。

### 13.3 artifact

统一字段名：

```ts
interface ArtifactView {
  id: string
  type: 'explanation' | 'practice' | 'feedback' | 'plan' | 'message'
  title: string
  summary?: string
  content: Record<string, unknown>
  actions: Array<{ kind: string; label: string; href?: string }>
}
```

artifact 创建后作为 workflow 内部产物预览；用户点击后再进入练习或详情页。

## 14. Markdown 与内容安全实现

建议增加受控渲染层：

- `react-markdown` + `remark-gfm`，或同等安全方案。
- 禁止原始 HTML。
- 标题组件统一映射为受控字号。
- 链接增加协议白名单和外链标记。
- 代码块、公式和表格使用专用组件。
- 引用 token 转换为可访问按钮并打开 `EvidenceDrawer`。
- 流式未闭合 Markdown 使用增量容错，不直接注入 HTML。

模型返回的任意 class、style、script 均不得进入 DOM。

## 15. 样式改造边界

### 15.1 需要移除或停用

- Agent 区域的 `var(--serif)` 标题规则。
- `.agent-workspace` 的常驻两栏布局。
- `.agent-context` 中的 `ExecutionTrace`。
- `.agent-answer section > h2` 的大标题表现。
- `.run-summary` 的整页报告卡语法。
- waiting/approval 页面上的内联 style。
- mock 完成步骤和 mock 来源的运行时 fallback。

### 15.2 建议新增 token

```css
--chat-width: 760px;
--chat-canvas: #f7f8fa;
--chat-surface: #ffffff;
--chat-ink: #20242b;
--chat-muted: #667085;
--chat-line: #e6e9ee;
--chat-accent: #4059d8;
--chat-user-bg: #eff1f4;
--chat-radius: 12px;
--chat-composer-radius: 18px;
```

Agent 新组件统一使用 `agent-chat-*` 或 CSS module，避免继续与全站 `.section`、`.eyebrow` 等高范围选择器互相覆盖。

## 16. 分阶段实施

### Phase 0：统一 Agent 路由与上下文，当前 P0

该阶段必须先于原操作闭环继续实施，并按独立中文提交拆分：

1. 移除前端 workflow 模式选择、`preferred_action` 请求字段和用户端直接创建 workflow 的入口。
2. 引入并固定 Pydantic AI 依赖，使用测试模型完成 RouterDecision、依赖注入、消息历史和 usage limits 的最小 PoC。
3. 新增 `ThreadContextBuilder`，从 MySQL 装配受控 `message_history`、artifact、附件和引用。
4. 实现 `direct_answer` 与路由前 `clarify`，内部 conversation workflow 保持静默。
5. 实现 explain/validate/grade/plan 的动态 child run 调度和 workflow 可见性切换。
6. 实现同 thread root run tree 串行队列，保证上下文提交顺序与回复顺序一致。

验收：同一 thread 依次完成“普通回答 → validate workflow → grade workflow → 普通追问 → plan workflow”，每一轮都能引用此前消息或 artifact，且用户从未指定 workflow key。

### Phase A：契约与持久化，P0

1. 新增 `agent_messages`、`agent_thread_items` 迁移。
2. `agent_runs` 增加触发消息、父子关系、公开展示字段。
3. 新增 turn 创建事务和 timeline 查询 API。
4. 新增 thread 级 sequence 与事件流。
5. 统一 artifact、approval、input 的公开响应 schema。
6. 为现有 run 回填最小 timeline item；无法恢复的旧 run 标记为 legacy summary。

验收：刷新任意 thread 能恢复完整消息和多次 workflow 顺序。

### Phase B：前端数据层，P0

1. 新增 timeline API client 和类型。
2. 用 thread conversation state 替代单一 `currentRunId` 页面模型。
3. 实现 snapshot、cursor、去重和重连。
4. 删除客户端 `detectWorkflow`。
5. 接通流式 assistant message。

验收：模拟断线、刷新和重复事件后，消息不丢、不重、不乱序。

### Phase C：UI 组件重构，P0

1. 实现 `ConversationStream`、消息组件和 composer。
2. 将 `ExecutionTrace` 改为内嵌 `WorkflowBlock`。
3. 将澄清、审批、失败和 artifact 嵌入 workflow。
4. 移除 Agent 区衬线大标题和报告式卡片。
5. 保留并改造证据抽屉。

验收：一个 thread 中连续出现 3 次 workflow，状态和触发关系清晰。

### Phase D：操作闭环，P1

1. cancel、retry、queued turn cancel。
2. 附件和上下文引用。
3. 消息复制、反馈、重新生成。
4. 长线程分页和搜索。

### Phase E：质量与性能，P1

1. 长列表虚拟化评估；达到 300 个顶层 item 或出现性能证据后启用。
2. 流式 Markdown 性能优化。
3. 可访问性、减少动画和移动键盘专项测试。
4. 事件延迟、断线恢复率和重复消息监控。

## 17. 具体文件改造清单

### 17.1 用户前端

| 文件 | 改造 |
|------|------|
| `frontend/src/pages/AgentPage.tsx` | 移除 action 状态和 `preferredAction` 发送；始终提交自然语言 turn |
| `frontend/src/features/agent/ChatComposer.tsx` | 移除 workflow 模式下拉框，只保留消息、附件、引用和发送动作 |
| `frontend/src/store/agent-context.tsx` | 改为 thread timeline 状态；支持 cursor、去重、snapshot 和重连 |
| `frontend/src/api/agent.ts` | 删除 `preferred_action`，增加 turn、timeline、thread SSE、cancel、retry；统一响应字段 |
| `frontend/src/index.css` | 新增 chat token 和组件样式；停用 Agent 区衬线与两栏 workflow |
| `frontend/src/data/fixtures.ts` | fixtures 仅保留 Story/测试，不参与生产 fallback |
| `frontend/src/components/AppShell.tsx` | 最近线程按 `updated_at`；展示轻量活动状态 |

### 17.2 后端

| 文件/模块 | 改造 |
|-----------|------|
| `backend/requirements.txt` | 引入并锁定经过 PoC 验证的 `pydantic-ai` 版本，升级/移除不兼容的旧 OpenAI SDK 依赖 |
| `backend/app/modules/agent/models.py` | 新增 message/timeline model，扩展 run 关系字段 |
| `backend/app/modules/agent/schemas.py` | 删除 `preferred_action`；新增 RouterDecision、上下文审计和公开 view schema |
| `backend/app/modules/agent/router.py` | 普通用户只通过 turns 进入 Router；收口显式 `/runs` 创建入口 |
| `backend/app/modules/agent/context_builder.py` | 新增 thread 历史、摘要、artifact、附件、引用和权限上下文装配 |
| `backend/app/modules/agent/model_runtime/` | 用真实 Pydantic AI Agent 替换伪命名 adapter；实现 deps、受控 `message_history`、output 和 usage limits |
| `backend/app/modules/agent/service.py` | 实现原子创建 turn、sequence、隐藏 workflow 占位和 timeline projection |
| `backend/app/modules/agent/events.py` | 增加 thread 级事件与 snapshot |
| `backend/app/modules/agent/worker.py` | 注入 AgentRunContext；实现 thread root tree 串行领取和 Assistant 消息生命周期 |
| `backend/app/modules/agent/workflows/conversation.py` | Pydantic AI 动态路由、direct answer、clarify 和 child workflow 显现 |
| `backend/app/modules/agent/workflows/*` | 接收受控上下文；提供 public step 元数据和 parent/root run 关系 |
| Alembic migration | 新表、字段、索引、旧数据兼容回填 |

## 18. 测试矩阵

### 18.1 后端

- 同一 `client_message_id` 重试不会创建重复消息或 run。
- 同 thread 并发创建 turn 时 sequence 唯一且有序。
- 子 run 正确绑定 parent/root/trigger message。
- timeline 分页无重复、无遗漏。
- SSE 从任意 cursor 重连可补齐事件。
- 消息流中断后 timeline 返回已持久化部分。
- approval/input 过期、重复提交和越权返回稳定错误。
- retry 不重复执行已提交的副作用。
- RouterDecision 六种 action 均有确定性测试，结构校验失败不会默认进入 explain。
- direct answer 和路由前 clarify 不创建可见 workflow item。
- validate/grade/plan child run 正确继承 trigger/root 和受控上下文引用。
- 上下文构建不会读取其他用户消息或无权限 artifact。
- `ThreadContextBuilder` 在 token 预算内保留当前输入、未完成交互和显式引用，较早历史进入可追溯摘要。
- Pydantic AI 测试使用 TestModel/FunctionModel 或等价测试模型，不依赖真实外部模型网络。
- 同 thread 连续 turn 只能按 root run tree 顺序领取，后续 Router 能读到前一轮已提交结果。

### 18.2 前端

- 初次加载、空线程、长线程。
- 连续普通问答。
- 一次线程多次 workflow。
- 同类型 workflow 多次出现。
- 流式正文中包含列表、代码块、公式和表格。
- 用户向上滚动后不被自动拉回底部。
- waiting/approval 在刷新后仍位于原 workflow。
- SSE 重复、乱序、断线和 snapshot 覆盖。
- approve/reject/cancel/retry 的乐观与失败回滚。
- 桌面 1280/1440 和移动 390 宽度。
- 键盘、屏幕阅读器和减少动画。

### 18.3 端到端验收脚本

```text
1. 用户问“解释循环队列 front 的推导”。
2. 页面显示用户消息、讲解 workflow 和流式 Agent 回复。
3. 用户继续问一个不触发 workflow 的追问。
4. 用户要求“给我出 3 道题”，出现第二个 workflow。
5. workflow 要求确认难度，用户在原块内选择。
6. 练习生成后出现 artifact。
7. 用户要求调整计划，出现第三个 workflow 和审批。
8. 刷新页面，三次 workflow 的顺序、展开状态和审批结果仍正确。
9. 人为断开 SSE，再恢复网络，消息没有重复。
```

## 19. 发布阻断项

以下任一项未满足，不应发布新的聊天 UI：

- 刷新后只剩最新 run。
- workflow 仍依赖右栏才能理解。
- waiting 或 approval 仍切换成独立页面。
- 完成消息仍来自硬编码 fixture。
- SSE 重连会重复消息或丢失状态。
- 运行中发送会无提示创建并发 run。
- 前端继续显示模式下拉框、传 `preferred_action` 或直接指定 workflow。
- Router 仍只读取当前 `input_message`，没有 thread 历史、artifact、附件和引用。
- 代码仍把手写 OpenAI SDK 封装标记为 Pydantic AI，而未实际使用其 Agent、deps、message history 和结构化 output。
- 普通问答或路由前澄清仍显示“处理请求”workflow 块。
- workflow 展示内部 node 名、prompt、隐藏推理或未裁剪工具数据。
- 审批、重试或取消可能重复执行持久化副作用。

## 20. 推荐决策

1. 采用 thread 级 timeline read model，不在前端临时拼装完整对话。
2. 普通用户输入统一进入服务端 `conversation@v1`，移除客户端关键词路由。
3. workflow 默认按 `root_run_id` 聚合，作为可重复的内嵌时间线节点。
4. 第一阶段采用同 thread 串行 turn 队列，暂不允许无约束并发 root run。
5. assistant message 必须有持久化流式快照和 `message.delta` 协议。
6. 证据抽屉保留，workflow 右栏取消。
7. MySQL 持有完整、可恢复的对话与 workflow 事实；Pydantic AI 只消费 `ThreadContextBuilder` 生成的本轮上下文。
8. Router、普通回答和各业务 workflow 使用职责受限的独立 Pydantic AI Agent，不创建拥有全部工具权限的全局 Agent。
9. `ThreadContextBuilder` 负责调用前裁剪和摘要，Pydantic AI 只消费处理后的 `message_history`；裁剪策略、摘要版本和选入资源必须由项目记录并可审计。
10. 当前继续使用 MySQL durable kernel；Pydantic AI durable execution 集成只作为后续独立 PoC，不与本轮 UI 重构捆绑。
