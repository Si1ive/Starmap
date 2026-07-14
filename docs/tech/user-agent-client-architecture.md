# 用户端 Agent 技术架构

> 版本：v0.1
> 日期：2026-07-15
> 决策：Web-first，桌面能力按需附加

## 1. 结论

第一版继续使用现有 React + Vite 用户端，建设响应式 Web 学习工作台。Agent 的规划、检索、工具调用、记忆、审批、任务恢复和评测都放在后端。

从第一天定义统一的客户端能力接口。普通浏览器使用 Web 实现；当真实场景需要持续目录访问、文件监听、全局快捷键或系统级集成时，再使用 Tauri 2 包装同一套 React 应用并提供增强适配器。

不采用：

- 桌面端优先。
- Electron 与 Web 两套独立客户端。
- 第一版自研本地 Agent 守护进程。
- 让浏览器直接执行任意 Shell 命令。

## 2. 为什么不桌面端优先

408 学习 Agent 的核心能力包括：

- 基于平台知识库检索和回答。
- 生成或组织练习。
- 记录作答、错题和掌握状态。
- 制定计划和复盘。
- 运行可恢复的多步骤 Agent 工作流。

这些能力依赖的是服务端数据、工作流和模型工具，不依赖桌面容器。

桌面端会提前引入与产品验证无关的工作：

- macOS、Windows 的构建和签名。
- 安装、升级、回滚。
- WebView 差异。
- 本地权限和安全策略。
- Sidecar 生命周期。
- 崩溃日志和平台兼容测试。

这些工作能提升本地集成，却不会自动提升 Agent 的规划、记忆或教学质量。

## 3. 方案比较

| 方案 | 核心 Agent | 本地文件 | 浏览器上下文 | 客户端成本 | 结论 |
|------|------------|----------|--------------|------------|------|
| 响应式 Web | 完整 | 用户主动选择/上传 | 受浏览器权限限制 | 最低 | 第一版 |
| PWA | 完整 | 与浏览器能力接近 | 与浏览器能力接近 | 低到中 | 有离线需求后 |
| Tauri 桌面壳 | 完整 | 可做持续授权和监听 | 仍需扩展或注入 | 中 | 按触发条件增加 |
| Electron 桌面端 | 完整 | 强 | 仍需额外实现 | 中到高 | 当前无必要 |
| Web + 本地守护进程 | 完整 | 强 | 可扩展 | 高，安装与通信复杂 | 暂不采用 |
| 浏览器扩展 | 完整 | 弱 | 强 | 中 | 需要网页上下文时增加 |

## 4. 浏览器能力的真实边界

Web 可以完成：

- 用户选择文件后读取和上传。
- 在支持的浏览器中选择目录，并在授权范围内读写。
- 剪贴板、通知、摄像头和麦克风等受控能力。
- 本地缓存部分学习内容。
- 流式接收 Agent 事件。

Web 不适合默认完成：

- 未经用户交互扫描任意本地目录。
- 长期后台监听文件变化。
- 稳定读取其他应用窗口内容。
- 全局快捷键和系统托盘。
- 任意执行本地命令。

因此，“Web Agent 能力少”只对本地系统控制成立，对服务端 Agent 的规划、工具调用和学习闭环不成立。

## 5. 推荐总体架构

```text
React Web / Tauri WebView / Browser Extension
                 |
          Client Capability API
                 |
       Public User API + Agent Event API
                 |
        Agent Runtime / Learning Domain
                 |
  Knowledge | Questions | User Sources | Models
                 |
      MySQL | Qdrant | Redis | Object Storage
```

### 5.1 客户端

职责：

- 呈现工作区和结构化产物。
- 发送用户命令。
- 订阅 Agent 运行事件。
- 收集用户审批。
- 调用当前环境允许的客户端能力。
- 管理瞬时交互状态。

客户端不负责：

- 决定下一步 Agent 工具。
- 维护唯一的任务运行状态。
- 在本地拼接不可追踪的提示词。
- 直接访问管理端 API。

### 5.2 Agent Runtime

职责：

- 创建持久 Agent 线程和运行。
- 根据模式选择工作流。
- 调用结构化工具。
- 保存检查点和事件。
- 等待审批并恢复。
- 产出计划、练习集、报告等结构化产物。
- 记录成本、延迟、失败和评测信息。

### 5.3 学习域

职责：

- 用户目标和计划。
- 练习会话和作答。
- 错题与错因。
- 掌握状态。
- 间隔复习队列。
- 学习活动时间线。

Agent 只能通过学习域工具修改这些数据，不能直接拼 SQL 或自由修改状态。

## 6. 当前代码与目标之间的缺口

| 当前状态 | 问题 | 目标 |
|----------|------|------|
| 用户端知识与题目请求 `/admin/*` | 管理路由已要求管理员身份，不是稳定用户 API | 建立 `/api/v1/app/*` 用户端路由 |
| 只有管理员用户 | 无真实学习用户身份 | 建立用户认证与 `user_id` 隔离 |
| `UserQuestionRecord` 仅有 `session_id` | 不能形成长期个人画像 | 迁移为用户作答领域模型 |
| Chat 以 `session_id` 为中心 | 线程归属和权限不足 | Agent 线程归属用户并支持列表、归档 |
| Chat 请求同步返回 | 长工具链难观察和恢复 | 命令 API + SSE 事件流 |
| 无 Agent 运行实体 | 刷新页面后无法恢复工具状态 | 持久化 run、step、checkpoint、event |
| 无审批实体 | 无法安全执行持续性动作 | approval request/decision |
| 无学习计划与掌握状态 | 只能问答，不能个性化 | 独立 learning 模块 |
| Zustand 仍有旧 `currentPerson` | 历史模板残留 | 重建用户端状态边界 |

这意味着用户端不能简单继续美化现有页面。应保留可复用 API 封装和 React 工程，重构产品壳与领域数据流。

## 7. 建议后端模块

```text
app/modules/
  identity/          # 学习用户、会话、登录和设备
  workspace/         # Agent 线程、产物和活动时间线
  agent/             # 运行、步骤、事件、审批、工具注册
  learning/          # 目标、计划、掌握状态、复习队列
  practice/          # 练习集、作答、批改、错题
  user_sources/      # 用户资料、解析和权限
```

现有模块继续复用：

- `catalog`：大纲和章节。
- `content`：审核后的知识点和题目。
- `retrieval`：检索与关系扩展。
- `chat`：逐步迁移为 Agent 的“讲解/问答”工具，而不是继续承担全部 Agent 职责。
- `corpus`：平台管理员入库链路；用户资料解析应通过受限门面调用，不暴露管理能力。

## 8. 建议数据模型

### 8.1 身份与工作区

- `app_users`
- `user_sessions`
- `agent_threads`
- `agent_runs`
- `agent_steps`
- `agent_events`
- `agent_approvals`
- `agent_artifacts`

### 8.2 学习域

- `learning_goals`
- `study_plans`
- `study_tasks`
- `practice_sessions`
- `practice_session_questions`
- `question_attempts`
- `mistake_records`
- `mastery_evidence`
- `mastery_states`
- `review_schedules`

### 8.3 用户资料与记忆

- `user_sources`
- `user_source_chunks`
- `user_notes`
- `user_preferences`
- `thread_summaries`

平台知识库与用户资料在存储、检索过滤和引用标签上保持独立。

## 9. Agent 运行协议

### 9.1 命令

```text
POST /api/v1/app/agent/threads
POST /api/v1/app/agent/threads/{thread_id}/runs
POST /api/v1/app/agent/runs/{run_id}/cancel
POST /api/v1/app/agent/approvals/{approval_id}/decide
```

### 9.2 查询

```text
GET /api/v1/app/agent/threads
GET /api/v1/app/agent/threads/{thread_id}
GET /api/v1/app/agent/runs/{run_id}
GET /api/v1/app/today
```

### 9.3 事件流

第一阶段使用 SSE：

```text
GET /api/v1/app/agent/runs/{run_id}/events
```

事件至少包括：

- `run.started`
- `step.started`
- `step.progress`
- `tool.started`
- `tool.completed`
- `artifact.created`
- `approval.required`
- `run.completed`
- `run.failed`
- `run.cancelled`

事件带单调递增序号。客户端断线后通过 `Last-Event-ID` 或查询游标补发，不能依赖内存 loading 状态。

只有在引入实时语音或真正双向协作后，才评估 WebSocket。

## 10. Agent 状态机

```text
queued
  -> planning
  -> running
  -> waiting_for_user | waiting_for_approval
  -> running
  -> completed | failed | cancelled
```

每个工具步骤需要：

- 幂等键。
- 结构化输入输出。
- 超时和重试策略。
- 可见的错误信息。
- 审计记录。
- 对应的权限级别。

LLM 超时不能导致已经成功的工具结果丢失。工具结果先落库，再推进工作流状态。

## 11. Agent 工具分层

| 等级 | 示例 | 默认策略 |
|------|------|----------|
| 只读 | 检索知识点、题目、掌握状态 | 自动 |
| 临时写入 | 创建未提交练习草稿、临时产物 | 自动 |
| 用户数据写入 | 保存笔记、调整今日任务 | 可撤销或轻确认 |
| 长期影响 | 修改周计划、归档错题、导入目录 | 明确审批 |
| 外部/本地高风险 | 发出资料、执行本地命令 | 默认禁止，逐项授权 |

第一版不提供通用 Shell 工具。需要本地动作时，为具体场景定义窄工具，例如“读取已授权目录中的 PDF”，而不是“执行命令”。

## 12. 记忆设计

### 12.1 工作记忆

当前 Agent 运行的消息、工具结果和临时计划。

### 12.2 线程记忆

当前学习主题的摘要、未解决问题和已生成产物。

### 12.3 学习状态

由作答、用时、提示、复习间隔等证据计算，是最重要的长期记忆。

### 12.4 用户偏好

用户明确设置或确认的讲解深度、每日时间和提醒偏好。

不把所有聊天内容自动写入永久“用户记忆”。长期记忆应可查看、修改和删除。

## 13. 客户端能力适配

```ts
interface ClientCapabilities {
  environment: 'web' | 'tauri' | 'extension'
  selectFiles(): Promise<SelectedFile[]>
  selectDirectory?(): Promise<DirectoryGrant>
  watchDirectory?(grantId: string): Promise<void>
  readClipboard?(): Promise<string>
  writeClipboard?(value: string): Promise<void>
  notify?(input: NotificationInput): Promise<void>
  getBrowserContext?(): Promise<BrowserContext>
}
```

实现：

- `WebCapabilities`：文件选择、浏览器允许的剪贴板和通知。
- `TauriCapabilities`：持续目录授权、文件监听、系统通知、快捷键。
- `ExtensionCapabilities`：当前标签页正文、选区和网页元数据。

业务组件只依赖接口，不直接调用 Tauri 或浏览器扩展 API。

## 14. Tauri 启用条件

满足任一条件且有真实用户需求时，才进入桌面阶段：

1. 用户需要持续监听一个资料目录，而不是偶尔上传文件。
2. 需要离开浏览器后继续处理本地资料。
3. 全局快捷键或系统托盘显著改善高频学习流程。
4. 需要本地模型或本地隐私处理。
5. 浏览器权限与兼容性已经造成可量化的任务失败。

启用方式：

- 复用 `frontend` 构建产物。
- 增加 Tauri shell 和 capability adapter。
- 服务端 API、Agent Runtime 和领域模型不分叉。
- Sidecar 只承载明确的本地能力，不复制后端业务。

## 15. 浏览器扩展启用条件

当产品需要“解释当前网页选中内容”“把网页题目加入学习线程”时，浏览器扩展比桌面壳更直接。

扩展只负责：

- 用户主动触发后读取当前页或选区。
- 将结构化上下文发送到已有 Agent 线程。
- 展示最小状态和权限。

扩展不复制完整学习工作台。

## 16. 用户端前端结构

建议在视觉设计确定后，把现有 `frontend/src` 收敛为：

```text
src/
  app/             # 路由、Provider、应用壳
  pages/           # Today、Agent、Map、Practice、Mistakes、Sources
  widgets/         # Thread timeline、Context panel、Task queue
  features/        # send-command、submit-answer、approve-action
  entities/        # thread、run、question、mastery、source
  shared/          # api、ui、capabilities、utils
```

状态边界：

- TanStack Query：服务端事实状态。
- URL：可分享和可恢复的筛选、线程、题目位置。
- 局部组件状态：输入、展开、临时选择。
- Zustand：只保留跨页面但不属于服务端事实的轻量 UI 状态。

不要把 Agent 运行状态只放在 Zustand 或组件 `loading` 中。

## 17. 安全边界

- 用户端与管理端使用独立认证受众和路由。
- 所有用户数据查询必须按 `user_id` 限定。
- Agent 工具在服务端执行权限检查。
- 本地能力按功能授权，不申请全磁盘权限。
- 用户资料外发给模型前记录提供商、用途和范围。
- 所有持续性写操作保留审计与撤销所需信息。
- 引用 URL 和富文本经过安全处理。
- Agent 生成内容不能覆盖原始知识库事实。

## 18. 技术决策

### 已决定

- 响应式 Web 为首发客户端。
- 不在首发实现 PWA 离线缓存。
- 服务端 Agent Runtime 是唯一任务事实源。
- SSE 作为第一阶段 Agent 事件通道。
- React 用户端通过能力接口为 Tauri 和扩展预留适配点。
- 不提供通用本地 Shell 工具。

### 以后按证据决定

- PWA 安装与离线练习。
- Tauri 桌面壳。
- 浏览器扩展。
- 本地模型或本地资料 Sidecar。
- 实时语音与 WebSocket。
