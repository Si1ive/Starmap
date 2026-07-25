# 用户端交互与视觉

## 适用场景

本分卷说明 Agent 用户端如何管理时间线、等待态、工作流卡片和输入区样式。排查“为什么页面看起来像静态页”
或“为什么失败/等待态展示不对”时，应优先阅读这里。

## 页面、状态和事件流

| 执行阶段 | 文件 | 符号 | 代码范围 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 页面入口 | `frontend/src/pages/AgentPage.tsx` | `AgentPage` | L47-L285 | 页面挂载、发送消息、时间线刷新 | 管理空会话首页与有会话页、`pendingResponse`、模型选择和输入提交流程 | 页面布局与交互 |
| 全局状态容器 | `frontend/src/store/agent-context.tsx` | `AgentProvider` | L56-L520 | thread、timeline、SSE 事件 | 统一处理 turn 请求、EventSource、工作流输入/审批和错误恢复 | React context |
| 消息归并 | `frontend/src/features/agent/timeline-state.ts` | `applyMessageEvent` | L85-L165 | `message.delta`、`message.completed`、`message.failed` | 对 delta 有序追加，对 completed/failed 收敛状态和错误信息 | `messagesById` |
| 工作流归并 | `frontend/src/features/agent/timeline-state.ts` | `applyWorkflowEvent` | L167-L224 | `workflow.activity.updated` 等工作流事件 | 以 activity ID 为键维护活动、步骤、审批和产物状态 | `workflowByRunId` |
| 消息与工作流渲染 | `frontend/src/features/agent/ConversationStream.tsx` | `AssistantPending`、`TimelineItemView`、`ConversationStream` | L18-L170 | timeline items | 无正文时显示等待三点；失败时保留 partial 正文并单独显示原因；工作流项展示内嵌卡片 | 对话滚动区 |
| 内嵌工作流卡片 | `frontend/src/features/agent/InlineWorkflow.tsx` | `ActivityCard` / `InlineWorkflow` | L92-L242 | `workflow.activities[]` 与步骤链 | 展示检索状态、命中资料、审批/输入和最终产物 | 工作流消息块 |

## 输入区与首页/会话内双形态

| 执行阶段 | 文件 | 符号 | 代码范围 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 自动计算高度 | `frontend/src/features/agent/ChatComposer.tsx` | `ChatComposer`（textarea 高度 effect） | L36-L41 | 输入值变化 | 先清零再按 `scrollHeight` 增长到 180px | 浏览器 textarea 布局 |
| 首页场景标记 | `frontend/src/pages/AgentPage.tsx` | `AgentPage`（根 className 与 empty 分支） | L199-L199、L236-L259 | 当前 thread 没有历史时间线项 | 给根节点追加 `agent-chat-page--empty`，并在首页重用同一个 `ChatComposer` | 首屏输入区 |
| 会话内紧凑规则 | `frontend/src/features/agent/agent-chat.css` | `.agent-composer` / `.agent-composer textarea` / `.agent-composer__footer` | L691-L733 | 已有会话 | 收紧 padding、控制 24px 单行高度和 32px footer | 会话内 78px 左右输入区 |
| 首页宽松规则 | `frontend/src/features/agent/agent-chat.css` | `.agent-chat-page--empty .agent-composer` / `.agent-chat-page--empty .agent-composer textarea` | L1045-L1054 | 空会话首页 | 恢复更宽松的 padding，textarea 最小高度 88px | 首屏主输入区 |
| 底部安全距离 | `frontend/src/features/agent/agent-chat.css` | `.agent-chat-composer-dock` 与移动端 media query | L674-L682、L978-L1000 | 桌面和移动端底部 dock | 给底部安全区、移动端隐藏快捷键提示并保持发送按钮对齐 | 输入区底部布局 |

## 失败与等待态设计约束

1. `pendingResponse` 在发送请求后立刻进入等待态，直到时间线出现新的 assistant 消息或 workflow 项才清除。
2. `message.failed` 必须保留已收到的 partial 正文；前端只在红色小字区域显示安全错误原因。
3. 工作流活动卡片直接消费后端公开文案，例如“没有检索到相关文档”“暂时无法检索相关文档”，前端不额外翻译内部错误策略。

## 下一步阅读

- 要看后端事件与刷新恢复逻辑，转到 `implementation/events-timeline-errors.md`。
- 要看 explain/validate 工具活动如何进入用户端工作流卡片，转到 `implementation/rag-and-tools.md`。
