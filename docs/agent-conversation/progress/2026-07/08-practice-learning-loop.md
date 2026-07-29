# 2026-07 Agent 练习与学习闭环

## 2026-07-28：阶段一——对话出题落入真实练习

- 目标：让 Validate 的完成状态代表“已创建可练习草稿”，并提供对话内跳转、本会话练习轨道和管理端观测。
- 实现：新增 Session 原生题目 item/provenance、Agent Thread/Run 来源和 draft 状态；题库题重读完整实体，即时题冻结在 Session；Artifact 输出受控动作，练习页点击后才进入 active 会话。
- 管理端：Agent Runs 会话详情同步返回并展示关联练习、状态、题数、得分和来源 Run。
- 验证：`pytest` 覆盖 Validate、持久化、私有答案和 MySQL 外键索引替换顺序；用户端与管理端生产构建通过；真实 MySQL 从 `20260728_practice_hints` 前向升级到单 head `20260728_agent_practice_drafts`。首次升级暴露非事务 DDL 的索引依赖后，迁移改为先建替代索引并支持原地重入，全程未使用 stamp。
- 中文提交信息：`打通 Agent 出题与真实练习入口`。

## 2026-07-28：阶段二——统一学习活动与评价证据

- 目标：Agent 讲解和 Agent/普通练习都进入可回溯学习记录，同时禁止把“讨论过”误写成“已掌握”。
- 实现：新增 `learning_activity_events`；Explain 完成写无 verdict 的主题 exposure，练习交卷按 Session Item 写正确/错误评价事件；学习进度新事件优先、旧数据兼容且同源去重。
- 用户端：学习进度页新增最近学习记录，可回到 Agent 对话或练习结果；关键词轨迹标出 Agent 讲解、Agent 练习和普通作答来源。
- 管理端：Agent Runs 会话详情新增学习事件区，显示主题、事件类型、来源 Run 与“活动/正确/错误”证据层级。
- 验证：学习事件、Validate→Session→交卷整链、记忆投影、迁移图与 Schema Guard 测试通过；双前端生产构建通过；真实 MySQL 升至 `20260728_learning_activity`。
- 中文提交信息：`统一 Agent 学习活动与练习证据`。

## 2026-07-28：阶段三——统一 Agent 与练习薄弱点

- 目标：让对话内确定性批改和练习页交卷进入同一个薄弱点证据模型，并保留原始入口回链。
- 实现：Agent Grade 在掌握度门禁通过后写 `agent_grade_confirmed`；WeaknessService 新事件优先、历史 Session 兼容，将 Agent Grade、Agent 练习和普通练习按关键词重新投影；后续答对只标记待间隔验证。
- 用户端：错题页可从 Session 证据回练习结果，也可从对话评分证据回原 Thread，空态与说明覆盖两种来源。
- 管理端：Agent Runs 使用同一 projector 展示本会话薄弱点，不维护第二套统计口径。
- 验证：覆盖 Agent Grade 事件、Agent 错误→练习答对的跨入口验证、历史错题兼容和双前端生产构建。
- 中文提交信息：`统一 Agent 与练习薄弱点投影`。

## 2026-07-28：阶段四——受控 Capability/Tool Harness

- 目标：让 Router 明确看到服务端授权能力，让内部工具具备真实注册、工作流和参数门禁，同时不引入 MCP 或模型任意写库接口。
- 实现：新增版本化 Capability 目录；Router 注入最小能力 manifest，root/child Run 冻结审计快照；Explain/Validate 检索统一经过只读 Tool Registry，Run ID 只能由服务端注入。
- 事实边界：练习由领域服务幂等创建；学习活动由完成/评价事实投影；薄弱点只读聚合。三者均不暴露为模型写工具。
- 管理端：Agent Runs 每个运行入口显示选中 capability 与授权工具；完整响应沿用脱敏规则，旧 Run 保持空态。
- 验证：Capability 视图隔离、越权 workflow/未知参数拒绝、Router/child 快照、Explain/Validate 等聚焦回归 78 项及用户端/管理端生产构建通过；全量后端 890 项中 889 项通过，唯一失败是 `test_agent_workflow_engine.py::test_explain_workflow_keeps_artifact_through_render_and_completion` 仍按旧契约期待裸正文/字符串引用，而当前既有 Explain 契约会写知识库来源区块和结构化 citation，本阶段未回退正确产物。
- 中文提交信息：`建立受控 Agent 能力与工具层`。

## 2026-07-29：移除主动学习计时

- 目标：移除需要用户主动点击才会产生记录的专注/休息计时，避免把不完整的停留时长当作学习事实。
- 实现：删除练习库番茄钟、`/timers` API、`StudyTimerRecord` ORM、学习进度的时长汇总/周节奏和作答每题耗时；学习进度只保留真实作答、评分证据与最近活动。模拟考和刷题会话的服务器限时仍用于自动交卷，不作为学习时长统计。
- 数据库：新增 `backend/alembic/versions/20260729_remove_study_timing.py::upgrade`（L19-L22），前向删除计时表、计时索引和 `practice_answers.time_spent_seconds`，降级可恢复旧结构。
- 验证：迁移图、计时迁移 DDL、学习进度定向测试与用户端生产构建通过；提交前另行确认 `git diff --check`。
- 中文提交信息：`移除主动学习计时`。

## 2026-07-29：收紧 Agent 对话练习侧栏布局

- 目标：练习侧栏没有关联练习时不再显示空白占位或无效可访问内容；存在练习时保持对话流、输入区和侧栏边界对齐，并兼容窄屏布局。
- 实现：`frontend/src/pages/AgentPage.tsx::AgentPage`（L117-L125）继续在 Thread 或时间线 cursor 变化后读取练习列表，失败时回退为空列表；`frontend/src/features/agent/ConversationPracticeRail.tsx::ConversationPracticeRail`（L11-L55）将空列表收敛为隐藏的空侧栏，有数据时保留练习状态和练习/反馈页导航。`AgentPage`（L275-L320）在对话流和输入 dock 之间加入无障碍 spacer；`frontend/src/features/agent/agent-chat.css` 的 `.agent-practice-rail`、`.agent-practice-rail--empty`、`.agent-chat-rail-spacer`（L93-L111）统一桌面宽度，`@media (max-width: 900px)`（L1283-L1306）隐藏 spacer 并压缩空侧栏。
- 副作用与错误：本次没有新增 API、数据库写入或时间线状态；练习列表接口失败仍只影响侧栏并显示为空，不阻断对话；点击已有练习仍通过站内路由进入继续练习或反馈页。
- 验证：`cd frontend && npm run build` 通过；涉及 TS 文件的 `npx eslint src/features/agent/ConversationPracticeRail.tsx src/pages/AgentPage.tsx` 无错误，仅保留 `AgentPage.tsx:72` 原有非空断言警告；`git diff --check` 通过。
- 中文提交信息：`收紧 Agent 对话练习侧栏布局`。
