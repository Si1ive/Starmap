# 408 Agent 对话界面实现逻辑与代码缺口

> 版本：v0.1
>
> 日期：2026-07-23
>
> 状态：实施设计，需与运行时模型评审后进入开发
>
> 关联设计：[408 Agent 对话界面重设计](../product/408-agent-conversation-ui-redesign.md)

## 1. 结论

当前代码已经具备 thread、run、step、event、artifact、input 和 approval 的部分骨架，但还不能实现真正的持续对话页。

最关键的缺口不是 CSS，而是缺少一个稳定的 **thread 级对话时间线协议**：

- 没有持久化用户消息与 Agent 消息的 `agent_messages` 实体。
- 没有能够统一排序 message 与 workflow 的 thread 级时间线。
- 前端只选取最新 run，无法恢复完整对话。
- SSE 只绑定一个 run，没有 thread 级 cursor、消息增量和可靠重连。
- 父 workflow 与子 workflow 缺少持久关联，前端不能正确合并展示。
- 等待补充、审批、失败和产物没有统一嵌入 workflow 的视图模型。

因此实施顺序必须是：**先补对话契约和数据投影，再重构组件与样式。** 单独改 `AgentPage.tsx` 和 CSS 会得到一个“看起来像聊天、刷新后仍不是聊天”的页面。

## 2. 当前实现链路

```text
AgentPage
  ├─ 客户端 detectWorkflow(input)
  ├─ POST /agent/threads（首条消息时）
  ├─ POST /agent/runs
  ├─ currentRunId = 最新 run
  ├─ EventSource(/runs/{run_id}/events/stream)
  └─ events -> buildStepsFromEvents -> 单次 run 页面

Backend
  AgentThread
    └─ AgentRun[]
         ├─ AgentStep[]
         ├─ AgentEvent[]
         ├─ AgentArtifact[]
         ├─ AgentInput[]
         └─ AgentApproval[]
```

该结构能展示“一个 run 的运行页”，不能稳定生成“一个 thread 的聊天记录”。

上图为前端 `API_BASE=/api/v1` 之后使用的相对路径；仓库当前公开接口实际为 `/api/v1/agent/*`。本文目标契约沿用既有运行时设计中的用户端命名空间 `/api/v1/app/agent/*`。实施时应在网关或 FastAPI 路由层一次性确定该前缀，并在迁移期为 `/api/v1/agent/*` 提供兼容，前端代码中不要同时硬编码两套前缀。

## 3. 已确认的代码缺口

### 3.1 前端页面

| 缺口 | 当前代码 | 影响 | 优先级 |
|------|----------|------|--------|
| 只展示最新 run | `AgentPage` 在 `loadThreadRuns` 后选择最新 run | 历史消息和多次 workflow 消失 | P0 |
| 无完整历史事件加载 | 有 `getRunEvents` API，但 context 没有加载动作，页面只连运行中 SSE | 刷新已完成 run 后拿不到步骤和回复 | P0 |
| waiting 状态独立页面 | `waiting_for_user`、`waiting_for_approval` 提前 `return` | 对话上下文被切断 | P0 |
| workflow 常驻右栏 | `ExecutionTrace` 放在 `agent-context` | workflow 与触发消息脱离 | P0 |
| 客户端选择 workflow | `detectWorkflow` 和 `<select>` | 路由规则分散，客户端可能调用未发布 workflow | P0 |
| 没有真实消息流 | 页面只显示 `run.input_message` 和 `lastMessage` | 无多轮对话、无 Agent 消息实体 | P0 |
| 完成结果取值不匹配 | 前端等待 `message.completed.content` 或 `run.completed.result`；后端当前不发送这两个字段 | 完成态容易显示占位文案 | P0 |
| artifact 字段不一致 | 前端类型使用 `artifact_type`，后端列表返回 `type` | 产物无法可靠归一化 | P0 |
| SSE 不更新 run 状态 | reducer 追加事件，但不根据 `run.status_changed`、`run.completed` 更新 run | UI 可能长期停留在 `running` | P0 |
| SSE 无补发和去重 | 默认从 0 连接，`APPEND_EVENTS` 不按 `(run_id, sequence)` 去重 | 重连后可能重复事件或遗漏 | P0 |
| SSE 出错即关闭 | `onerror` 关闭连接，无退避重连、无 HTTP 补拉 | 网络波动后页面停止更新 | P0 |
| 仅一个 EventSource | context 只保存一个 `esRef` | 多 run 或子 run 无法同时更新 | P0 |
| 运行中发送语义不真实 | 非 waiting 状态直接创建新 run，但文案承诺“当前步骤后处理” | 可能并发执行，用户预期错误 | P0 |
| 审批后未恢复订阅 | approve/reject 只更新 approval | run 继续后页面不一定收到后续事件 | P0 |
| 重试未实现 | “仅重试失败步骤”为 TODO | 失败态无法闭环 | P1 |
| 附件按钮无逻辑 | 仅有图标 | 输入能力与 UI 承诺不一致 | P1 |
| 大量 mock 内容 | 证据、步骤、结果、失败产物混合 fixtures | 真实数据与示例可能同时出现 | P0 |

### 3.2 后端模型与 API

| 缺口 | 当前实现 | 目标 | 优先级 |
|------|----------|------|--------|
| 无 `agent_messages` 表 | 用户输入只存于 `agent_runs.input_message` | 消息独立持久化，支持多轮和流式状态 | P0 |
| 无 thread 级顺序 | event sequence 只在单个 run 内单调递增 | message/workflow 在 thread 内稳定排序 | P0 |
| 无 timeline API | 只有 thread、runs、单 run events | 一次返回可渲染 thread 时间线 | P0 |
| 无 thread SSE | 只有 `/runs/{run_id}/events/stream` | 一个连接接收当前线程所有可见更新 | P0 |
| 无消息流事件 | 只有 step、run、artifact 等事件 | `message.started/delta/completed/failed` | P0 |
| 子 run 无关系字段 | `conversation` 会创建 explain 子 run，但 `AgentRun` 无 `parent_run_id` | 可恢复 run 树并归入同一 workflow 块 | P0 |
| 子 run 无触发消息 | run 未绑定 `message_id` | 明确 workflow 属于哪条用户消息 | P0 |
| workflow 公开展示元数据缺失 | 客户端直接显示 node/workflow 名 | 服务端提供公开名称、阶段和摘要 | P0 |
| 结构化输入无查询协议 | 有 answer API，但没有完整可渲染 input 查询/事件 | 时间线可恢复澄清控件 | P0 |
| 审批响应结构不统一 | 列表与 approve/reject 响应字段不同 | 返回完整 approval 或统一 envelope | P1 |
| 状态枚举不完整 | 模型缺少 `planning`、`cancelled`、`expired` | 与运行时文档及 UI 状态一致 | P1 |
| 无 cancel/retry API 实现 | 运行时文档已定义，当前路由缺失 | 停止、局部重试和谱系可用 | P1 |
| SSE 终止条件不完整 | 仅 completed/failed 结束 | 支持 cancelled/expired；waiting 状态保持或可靠恢复 | P1 |
| 无流式快照 | 断线后只能重放单 run event | timeline snapshot + cursor 恢复 | P0 |

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
  "client_message_id": "01K...",
  "preferred_action": null
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
    "presentation": "workflow",
    "public_title": "生成专项练习"
  },
  "timeline_cursor": 18
}
```

服务端在该接口中完成：

1. 校验 thread 归属。
2. 以 `client_message_id` 幂等创建用户消息。
3. 服务端执行 `conversation@v1` 路由，不信任客户端 workflow key。
4. 创建 root run 和 thread timeline items。
5. 同一事务提交后投递 outbox。

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

每一次用户显式任务创建独立 root run 和独立 workflow timeline item。状态更新必须按 `root_run_id` 精确更新原位置，不能使用全局 `currentRunId`。

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

删除用户端 `detectWorkflow`。所有普通输入进入 `conversation@v1`：

- 服务端决定直接回答、澄清或调度 explain/validate/grade/plan。
- 显式建议按钮可以传 `preferred_action`，但服务端仍校验工作流是否发布、输入是否完整和用户是否有权限。
- workflow key 不在普通 UI 中暴露。

### 12.3 运行中继续发送

后端需要明确选择一种策略：

**推荐 P0：同线程串行 turn 队列。**

- 每个 thread 同时最多一个会改变 thread 上下文的 root run。
- 新 turn 持久化为 `queued`，UI 立即显示。
- 当前 root run 终止或进入长期等待后，调度下一条 turn。
- 用户可以取消尚未开始的 turn。

只读且互不影响的 run 以后可以并行，但不能由前端无条件创建并发 run。

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
| `frontend/src/pages/AgentPage.tsx` | 拆分为新对话页和 thread 对话页；移除单 run 分支页面 |
| `frontend/src/store/agent-context.tsx` | 改为 thread timeline 状态；支持 cursor、去重、snapshot 和重连 |
| `frontend/src/api/agent.ts` | 增加 turn、timeline、thread SSE、cancel、retry；统一响应字段 |
| `frontend/src/index.css` | 新增 chat token 和组件样式；停用 Agent 区衬线与两栏 workflow |
| `frontend/src/data/fixtures.ts` | fixtures 仅保留 Story/测试，不参与生产 fallback |
| `frontend/src/components/AppShell.tsx` | 最近线程按 `updated_at`；展示轻量活动状态 |

### 17.2 后端

| 文件/模块 | 改造 |
|-----------|------|
| `backend/app/modules/agent/models.py` | 新增 message/timeline model，扩展 run 关系字段 |
| `backend/app/modules/agent/schemas.py` | 新增 turn、timeline、message、workflow view schema |
| `backend/app/modules/agent/router.py` | 新增 turn/timeline/thread stream/cancel/retry 接口 |
| `backend/app/modules/agent/service.py` | 实现原子创建 turn、sequence 分配、timeline projection |
| `backend/app/modules/agent/events.py` | 增加 thread 级事件与 snapshot |
| `backend/app/modules/agent/worker.py` | 维护公开 workflow 状态和 assistant message 生命周期 |
| `backend/app/modules/agent/workflows/*` | 提供 public step 元数据；建立 parent/root run 关系 |
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
- 前端继续用关键词选择 workflow 作为生产路由。
- workflow 展示内部 node 名、prompt、隐藏推理或未裁剪工具数据。
- 审批、重试或取消可能重复执行持久化副作用。

## 20. 推荐决策

1. 采用 thread 级 timeline read model，不在前端临时拼装完整对话。
2. 普通用户输入统一进入服务端 `conversation@v1`，移除客户端关键词路由。
3. workflow 默认按 `root_run_id` 聚合，作为可重复的内嵌时间线节点。
4. 第一阶段采用同 thread 串行 turn 队列，暂不允许无约束并发 root run。
5. assistant message 必须有持久化流式快照和 `message.delta` 协议。
6. 证据抽屉保留，workflow 右栏取消。
7. 数据契约完成后再进行 Agent 页面 CSS 重构。
