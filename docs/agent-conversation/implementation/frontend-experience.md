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
| 顶部真实任务中心 | `frontend/src/components/AppShell.tsx` | `AppShell` | L33-L105、L168-L239 | 从当前已打开 Thread 的 `timeline.workflowsByRootRunId` 筛选 queued/running/waiting_input/waiting_approval，按真实更新时间排序；红点只在确有运行时出现，空状态明确范围只限当前对话 | 工作流标题、当前步骤、真实进度和等待状态；点击返回当前 Thread，不读取 fixture |
| 任务中心视觉 | `frontend/src/index.css` | `.task-center`、`.task-center__item`、`.task-center__empty` | L853-L940 | 真实工作流或空状态 DOM | 沿用纸张、墨色和玉色；空状态与列表共享同一紧凑浮层，不使用虚假占位任务 | 用户端全局顶栏 |
| 消息与工作流渲染 | `frontend/src/features/agent/ConversationStream.tsx` | `AssistantPending`（L19-L38）、`TimelineItemView`（L40-L114） | timeline items | 无正文时显示等待动画和本地累计思考秒数；完成回答后展示练习、理解检查、学习计划三类继续提问示例，引导进入对应 workflow；正文仍由 `MarkdownContent` 渲染 | 对话滚动区 |
| 继续提问样式 | `frontend/src/features/agent/agent-chat.css` | `.agent-message__next-prompts`（L155-L176） | 完成态助手消息 | 用轻量标签区分引导语与示例，不伪装成已自动提交的按钮 | 助手消息尾部 |
| 内嵌工作流卡片 | `frontend/src/features/agent/InlineWorkflow.tsx` | `HitSummary`（L130-L148）、`ActivityCard`（L204-L268）、`InlineWorkflow`（L270-L460） | `workflow.activities[]` 与步骤链 | 展示检索状态、查询和命中数量；把知识点、题目和其他命中分组，每条只显示标题、章节、段落类型和来源页，最多显示 6 条，不展示内部数据通道 | 工作流消息块 |

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

## Markdown 正文与产物分型

| 执行阶段 | 文件 | 符号 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- |
| Markdown 安全渲染 | `frontend/src/features/agent/MarkdownContent.tsx` | `MarkdownContent`（L14-L23） | 助手消息或允许展示正文的 Artifact 字符串 | 使用 `react-markdown` + `remark-gfm` 渲染标题、列表、代码、表格、任务列表和引用；显式 `skipHtml`，不启用 raw HTML/HTML 注入 | 助手气泡与讲解 Artifact |
| 助手消息归并 | `frontend/src/features/agent/ConversationStream.tsx` | `TimelineItemView`（L32-L106） | assistant `message.completed`、streaming 或 failed partial content | 正文和失败时保留的 partial 内容都进入同一 Markdown 组件；失败原因仍作为独立红色纯文本显示，避免覆盖正文 | 用户对话流 |
| Artifact 分型与练习动作 | `frontend/src/features/agent/InlineWorkflow.tsx` | `artifactTypeLabel`（L153-L163）、`artifactMarkdown`（L165-L173）、`ArtifactCard`（L175-L218） | `workflow.artifacts[]` | 讲解默认展开 Markdown；练习 Artifact 只识别服务端 `open_practice + target_id` 并拼站内路由，不执行任意 href | 工作流结果卡片与练习页 |
| 本会话练习轨道 | `frontend/src/features/agent/ConversationPracticeRail.tsx`、`frontend/src/pages/AgentPage.tsx` | `ConversationPracticeRail`（L11-L50）、`AgentPage`（L26-L125、L275-L300） | 当前 Thread 的用户归属练习 | SSE cursor 变化后刷新练习列表；桌面显示左侧连续轨道，窄屏折叠为顶部横轨；draft/active/submitted 使用一致动作词 | 练习页或反馈页 |
| 最近学习记录 | `frontend/src/pages/TodayPage.tsx`、`frontend/src/api/learning.ts` | `TodayPage`（L280-L318）、`LearningActivity` / `LearningProgress`（L18-L45） | `recent_activities`、关键词轨迹来源 | Agent 讲解显示为活动，正确/错误练习显示评价结果；Session 回练习结果、Thread 回原对话；不把 exposure 文案写成掌握 | 学习进度页 |
| Markdown 主题样式 | `frontend/src/features/agent/agent-chat.css` | `.agent-markdown`（L155-L281）、`.inline-workflow__artifact` 分型样式（L798-L895） | Markdown DOM 与 Artifact 类型 class | 统一标题、列表、引用、代码块、GFM 表格、链接和分型色彩；代码块可横向滚动，长文本换行，不撑破对话框 | 用户端响应式 UI |

## 下一步阅读

- 要看后端事件与刷新恢复逻辑，转到 `implementation/events-timeline-errors.md`。
- 要看 explain/validate 工具活动如何进入用户端工作流卡片，转到 `implementation/rag-and-tools.md`。
