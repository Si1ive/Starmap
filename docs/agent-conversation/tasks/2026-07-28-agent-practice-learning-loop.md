# Agent 练习与学习闭环四阶段任务

## 目标与边界

把 Agent 对话中的“出题完成”从只读 Markdown Artifact 提升为真实练习、学习证据和后续个性化上下文。
本任务不引入 MCP；内部能力先使用类型安全 Python 接口与现有 Pydantic AI 运行时。

## 阶段状态

| 阶段 | 目标 | 状态 | 验收 |
| --- | --- | --- | --- |
| 1 | 出题后创建练习草稿、跳转练习页，并在对话与管理端保留练习轨道 | 已完成 | Validate Worker 产生 `PracticeSession(status=draft)`；用户端与 Agent Runs 可见 |
| 2 | 普通练习与 Agent 练习产生统一学习活动/评分证据 | 待开始 | 提交后学习记录可回链到 Session、Thread 与 Run |
| 3 | 统一普通错题与 Agent 评分的薄弱点投影 | 待开始 | 同一知识点按可信证据聚合且可解释 |
| 4 | 建立受控 Capability/Tool Harness | 待开始 | 模型只见获授权能力；写能力幂等、可审计，不含 MCP |

## 阶段一最终执行链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Workflow 持久化 | `backend/app/modules/agent/workflows/validate.py` | `_create_draft_node` | L290-L315 | 已校验候选题、PracticeBundle、Run/User | 生成标题并调用领域服务；错误沿 WorkflowEngine 失败链传播 | `practice_sessions` draft 与 session ID | `_render_artifact_node` |
| 领域写入 | `backend/app/modules/practice/service.py` | `PracticeService.create_agent_draft` | L21-L125 | Run/User、题库题或模型题 | 校验 Run 所有权和幂等键；题库题重读完整 Question，模型题只写私有 Session 快照 | `PracticeSession`、`PracticeSessionQuestion`；不污染公共题库 | Artifact 渲染 |
| 受控动作 | `backend/app/modules/agent/workflows/validate.py` | `_render_artifact_node` | L318-L385 | draft session ID、公开题面、私有答案 | 公开内容写 `open_practice` 动作；模型答案仍留私有 metadata | Practice Artifact | Timeline 投影 |
| 动作投影 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService._artifact_view` | L648-L665 | 已持久化 Artifact | 只读取服务端生成的 `content.actions` | `WorkflowArtifactView.actions` | 用户端 ArtifactCard |
| 对话动作消费 | `frontend/src/features/agent/InlineWorkflow.tsx` | `ArtifactCard` | L175-L218 | Artifact 与受控 action | 只消费 `open_practice + target_id`，拼受信任站内路由 | “开始练习”按钮 | PracticePage |
| 会话练习轨道 | `frontend/src/features/agent/ConversationPracticeRail.tsx` | `ConversationPracticeRail` | L11-L50 | 当前 Thread 的练习列表 | 按 draft/active/submitted 显示连续状态和站内入口 | 对话侧栏或移动端横轨 | 练习/结果页 |
| 草稿启动 | `backend/app/modules/practice/router.py` | `start_practice_session` | L472-L486 | 用户所有的 draft Session | 行锁校验所有权；首次点击写 started_at，重试幂等 | active Session、计时开始 | 作答 API |
| 管理监控 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L486-L579 | Thread 或历史 Run ID | 随会话查询关联 PracticeSession，返回来源 Run、状态与成绩 | Agent Runs `practices[]` | 管理端会话详情 |

### 设计原因

- `draft` 与 `active` 分离，避免用户仍在对话时练习计时已经开始。
- Session Item 自带稳定 `item_id` 和冻结快照；题库外键可空，因此 Agent 即时题不需要伪装成公共审核题。
- 题库候选在持久化前重新读取完整 `Question`，不会把不含答案的公开检索 DTO 当成批改依据；实体失效时整轮安全失败。
- Run 是写入幂等键，同一 Worker 重试返回同一个练习，不会重复生成历史记录。

## 后续阶段约束

学习活动与掌握证据必须分离；讨论完成可记录接触事实，但只有结构化作答和确定性评分才能影响掌握度。
薄弱点由证据投影产生，不提供“直接设置薄弱点”的模型写工具。Capability Harness 复用领域服务和 Workflow，
不把数据库表操作直接暴露给模型。
