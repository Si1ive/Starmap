# 用户端交互与视觉

## 适用场景

本分卷说明 Agent 用户端如何管理时间线、等待态、工作流卡片和输入区样式。排查“为什么页面看起来像静态页”
或“为什么失败/等待态展示不对”时，应优先阅读这里。

## 页面、状态和事件流

| 执行阶段 | 文件 | 符号 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 页面入口 | `frontend/src/pages/AgentPage.tsx` | `AgentPage` | 页面挂载、发送消息、时间线刷新 | 管理空会话首页与有会话页、`pendingResponse`、模型选择和输入提交流程 | 页面布局与交互 |
| 全局状态容器 | `frontend/src/store/agent-context.tsx` | `AgentProvider` | thread、timeline、SSE 事件 | 统一处理 turn 请求、EventSource、工作流输入/审批和错误恢复 | React context |
| 消息归并 | `frontend/src/features/agent/timeline-state.ts` | `applyMessageEvent` | `message.delta`、`message.completed`、`message.failed` | 对 delta 有序追加，对 completed/failed 收敛状态和错误信息 | `messagesById` |
| 工作流归并 | `frontend/src/features/agent/timeline-state.ts` | `applyWorkflowEvent` | `workflow.activity.updated` 等工作流事件 | 以 activity ID 为键维护活动、步骤、审批和产物状态 | `workflowByRunId` |
| 消息与工作流渲染 | `frontend/src/features/agent/ConversationStream.tsx` | `AssistantPending`、`TimelineItemView`、`ConversationStream` | timeline items | 无正文时显示等待三点；失败时保留 partial 正文并单独显示原因；工作流项展示内嵌卡片 | 对话滚动区 |
| 内嵌工作流卡片 | `frontend/src/features/agent/InlineWorkflow.tsx` | `HitSummary`（L130-L148）、`ActivityCard`（L179-L243）、`InlineWorkflow`（L245-L414） | `workflow.activities[]` 与步骤链 | 展示检索状态、查询和命中数量；把知识点、题目和其他命中分组，每条只显示标题、章节、段落类型和来源页，最多显示 6 条，不展示内部数据通道 | 工作流消息块 |

## 检索命中摘要

| 执行阶段 | 文件 | 符号 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 章节引用回填 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalSearchEngine._load_chapter_refs`（L385-L406） | `RetrievalSegment.chapter_ids` | 只读查询 canonical chapter，把 ID 补成名称、层级、章节编码；缺失章节仍保留 ID 和空名称，不阻断检索结果 | `RetrievalResult.to_dict` 的 `chapters` |
| 用户工具摘要 | `frontend/src/features/agent/InlineWorkflow.tsx` | `HitSummary`（L130-L148）、`ActivityCard`（L179-L243） | `tool.result.public_metadata.documents` | 按 `entity_type` 分为知识点/题目/其他，段落类型翻译为摘要、正文、解析、题面等；每组保留紧凑摘要并提示省略数量，不渲染 `backend` | 用户端工作流活动卡片 |
| 摘要视觉层 | `frontend/src/features/agent/agent-chat.css` | `.inline-workflow__source-groups` 至 `.inline-workflow__source-more`（L453-L546） | 分组摘要 DOM | 用知识点/题目不同边框色、标题层级和换行规则限制卡片宽度，避免命中资料撑大对话框 | 用户端响应式布局 |

## 输入区与首页/会话内双形态

| 执行阶段 | 文件 | 符号 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 自动计算高度 | `frontend/src/features/agent/ChatComposer.tsx` | `ChatComposer`（textarea 高度 effect） | 输入值变化 | 先清零再按 `scrollHeight` 增长到 180px | 浏览器 textarea 布局 |
| 首页场景标记 | `frontend/src/pages/AgentPage.tsx` | `AgentPage`（根 className 与 empty 分支） | 当前 thread 没有历史时间线项 | 给根节点追加 `agent-chat-page--empty`，并在首页重用同一个 `ChatComposer` | 首屏输入区 |
| 会话内紧凑规则 | `frontend/src/features/agent/agent-chat.css` | `.agent-composer` / `.agent-composer textarea` / `.agent-composer__footer` | 已有会话 | 收紧 padding、控制 24px 单行高度和 32px footer | 会话内 78px 左右输入区 |
| 首页宽松规则 | `frontend/src/features/agent/agent-chat.css` | `.agent-chat-page--empty .agent-composer` / `.agent-chat-page--empty .agent-composer textarea` | 空会话首页 | 恢复更宽松的 padding，textarea 最小高度 88px | 首屏主输入区 |
| 底部安全距离 | `frontend/src/features/agent/agent-chat.css` | `.agent-chat-composer-dock` 与移动端 media query | 桌面和移动端底部 dock | 给底部安全区、移动端隐藏快捷键提示并保持发送按钮对齐 | 输入区底部布局 |

## 失败与等待态设计约束

1. `pendingResponse` 在发送请求后立刻进入等待态，直到时间线出现新的 assistant 消息或 workflow 项才清除。
2. `message.failed` 必须保留已收到的 partial 正文；前端只在红色小字区域显示安全错误原因。
3. 工作流活动卡片直接消费后端公开文案，例如“没有检索到相关文档”“暂时无法检索相关文档”，前端不额外翻译内部错误策略。

## 下一步阅读

- 要看后端事件与刷新恢复逻辑，转到 `implementation/events-timeline-errors.md`。
- 要看 explain/validate 工具活动如何进入用户端工作流卡片，转到 `implementation/rag-and-tools.md`。
