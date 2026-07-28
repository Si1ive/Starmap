# Agent 练习与学习闭环四阶段任务

## 目标与边界

把 Agent 对话中的“出题完成”从只读 Markdown Artifact 提升为真实练习、学习证据和后续个性化上下文。
本任务不引入 MCP；内部能力先使用类型安全 Python 接口与现有 Pydantic AI 运行时。

## 阶段状态

| 阶段 | 目标 | 状态 | 验收 |
| --- | --- | --- | --- |
| 1 | 出题后创建练习草稿、跳转练习页，并在对话与管理端保留练习轨道 | 已完成 | Validate Worker 产生 `PracticeSession(status=draft)`；用户端与 Agent Runs 可见 |
| 2 | 普通练习与 Agent 练习产生统一学习活动/评分证据 | 已完成 | 提交后学习记录可回链到 Session、Thread 与 Run；讲解只形成活动事实 |
| 3 | 统一普通错题与 Agent 评分的薄弱点投影 | 已完成 | 同一知识点按可信证据跨入口聚合且可回溯 |
| 4 | 建立受控 Capability/Tool Harness | 已完成 | 模型只见获授权能力；工具受 workflow/参数门禁；写入仍由幂等领域服务与事实投影完成，不含 MCP |

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
| 管理监控 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L489-L593 | Thread 或历史 Run ID | 随会话查询关联 PracticeSession，返回来源 Run、状态与成绩 | Agent Runs `practices[]` | 管理端会话详情 |

### 设计原因

- `draft` 与 `active` 分离，避免用户仍在对话时练习计时已经开始。
- Session Item 自带稳定 `item_id` 和冻结快照；题库外键可空，因此 Agent 即时题不需要伪装成公共审核题。
- 题库候选在持久化前重新读取完整 `Question`，不会把不含答案的公开检索 DTO 当成批改依据；实体失效时整轮安全失败。
- Run 是写入幂等键，同一 Worker 重试返回同一个练习，不会重复生成历史记录。

## 后续阶段约束

学习活动与掌握证据必须分离；讨论完成可记录接触事实，但只有结构化作答和确定性评分才能影响掌握度。
薄弱点由证据投影产生，不提供“直接设置薄弱点”的模型写工具。Capability Harness 复用领域服务和 Workflow，
不把数据库表操作直接暴露给模型。

## 阶段二最终执行链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 练习交卷 | `backend/app/modules/practice/router.py` | `_submit` | L118-L158 | 行锁 Session、冻结题目、用户答案 | 按快照确定性判分并在同一事务调用学习事件投影；draft 禁止直接交卷 | submitted Session、答案 verdict | `record_practice_submission` |
| 评价事件 | `backend/app/modules/learning/events.py` | `record_practice_submission` | L28-L83 | Session、Session Item、已判分答案 | 以 `session:item` 幂等；区分普通题与 Agent 练习，保留关键词、知识点、提示与回链 | `practice_answer_graded` | `LearningProgressService.get` / 薄弱点投影 |
| 讲解活动 | `backend/app/modules/learning/events.py` | `record_explanation_activity` | L86-L130 | Explain Run、Artifact、冻结 active topic | 只在有可信主题时写 exposure；quality=0.35 且 verdict 为空，不更新掌握度 | `agent_explanation_completed` | 学习记录 |
| 学习聚合 | `backend/app/modules/learning/service.py` | `LearningProgressService.get`、`_load_activity_events`、`_activity_evidence`、`_activity_payload` | L100-L240 | 当前用户活动事件、历史练习、掌握度 | 新事件优先；旧练习仅在没有同源事件时兼容读取，避免双计数；生成关键词轨迹和最近活动 | progress topics、recent_activities | TodayPage |
| 学习记录 UI | `frontend/src/pages/TodayPage.tsx` | `TodayPage` | L280-L318 | `recent_activities` | 区分 Agent 讲解、正确/错误练习，并按来源回到对话或练习结果 | 最近学习记录 | 用户复盘 |
| 管理监控 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L489-L607 | 当前 Thread | 查询 `learning_activity_events` 并公开事件类型、主题、证据层级、质量与 Run | Agent Runs `learning_activities[]` | 管理详情 |

讲解完成只能证明用户接触了主题，因此会进入学习记录和保持率轨迹，但 `is_correct=None`，不会成为掌握度 verdict。
练习完成使用冻结标准答案产生确定性评价事件；重复提交与自动交卷通过 Session 状态和事件唯一键保持幂等。

## 阶段三最终执行链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Agent Grade 事件 | `backend/app/modules/agent/memory_projection.py`、`backend/app/modules/learning/events.py` | `_record_grade_result_confirmed`（L308-L424）、`record_agent_grade_activity`（L145-L210） | 可信 Feedback grading、冻结 topic / knowledge point | 掌握度写入后，以 evidence ID 幂等写统一评价事件；主题优先读 snapshot，缺失时水合知识点；无主题安全跳过 | `agent_grade_confirmed`、mastery | WeaknessService |
| 统一证据转换 | `backend/app/modules/learning/weaknesses.py` | `project_weakness_rows`、`project_weakness_events`、`project_weakness_evidence` | L38-L180 | 新活动事件与历史 Session 行 | 转成同一 evidence 契约，按 keyword 合并正确/错误；后续正确只能进入待间隔验证，不立即删除错误历史 | clusters、timeline | 用户/管理端 |
| 用户级读取 | `backend/app/modules/learning/weaknesses.py` | `WeaknessService.get` | L183-L241 | 当前用户 | 新事件优先；排除已有同源事件的历史行；跨 Agent Grade、Agent 练习和普通练习重新投影 | 用户薄弱点 | MistakesPage |
| 来源回跳 | `frontend/src/pages/MistakesPage.tsx` | `MistakesPage.openEvidence` | L58-L65 | representative evidence | 有 Session 回练习反馈，无 Session 但有 Thread 回 Agent 对话 | 原始证据页面 | 用户复盘 |
| 管理监控 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L489-L611 | Thread 学习事件 | 对当前会话事件运行同一 projector，不另造管理统计规则 | `weaknesses` | AgentRunDetailPage |

薄弱点仍是评价证据的派生视图，不新增“设置薄弱点”写接口。Agent 讲解事件没有 verdict，天然不会进入该投影；
Agent Grade 只有通过既有评分门禁、携带 question/knowledge point 和确定 verdict 后才产生评价事件。

## 阶段四最终执行链

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 能力目录 | `backend/app/modules/agent/capabilities.py` | `CapabilitySpec`、`CapabilityRegistry`、`capability_registry` | L15-L126 | direct/clarify/explain/validate/grade/plan 业务边界 | 定义稳定 key、action、说明、执行模式、副作用与工具依赖；模型视图去除实现细节，审计视图保留策略属性 | model/audit manifest；无数据库副作用 | Router / dispatch / Agent Runs |
| Router 上下文与冻结 | `backend/app/modules/agent/model_runtime/router.py`、`backend/app/modules/agent/workflows/conversation.py` | `RouterDeps` / `_router_policy`（L31-L41、L100-L122）、`_route_node`（L45-L157） | 本轮允许能力、冻结对话上下文 | 模型只见最小能力清单且被禁止直接写学习事实；决定后把策略版本、完整 allowlist 与选中项写 root Run metadata | RouterDecision、`capability_snapshot` | direct / clarify / child dispatch |
| Child 授权交接 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata`、`_dispatch_workflow_node` | L219-L307 | Router action、选中 Capability、父 Run/Context | action 必须命中能力目录和业务 workflow；幂等创建 child，并只冻结当前能力及其工具 | child Run capability snapshot | Worker |
| Tool 门禁与执行 | `backend/app/modules/agent/tools/registry.py`、`backend/app/modules/agent/tools/retrieve_knowledge.py` | `ToolSpec`、`ToolRegistry.execute`（L15-L103）、`register_retrieve_knowledge`（L438-L450） | 工具名、workflow、声明参数、服务端 DB/Run | 仅允许已注册只读工具；Explain/Validate allowlist、schema/注入参数逐项校验；失败沿节点错误传播 | 真实 `retrieve_knowledge` 调用与原 tool events | RAG / Workflow |
| 调用方接入 | `backend/app/modules/agent/workflows/explain.py`、`backend/app/modules/agent/workflows/validate.py` | `_evidence_loop_node`（L133-L148）、`_question_discovery_node`（L144-L162） | 冻结 query/bundle、当前 Run | 都通过 registry 执行检索；run ID 由服务端注入，模型不能自报身份 | evidence/candidates 或安全失败 | Explain / Practice draft |
| 管理监控 | `backend/app/modules/agent/admin_router.py`、`frontend-admin/src/pages/AgentRunDetailPage.tsx` | `_serialize_run`（L60-L88）、`RunLane`（L260-L297） | root/child metadata | 脱敏返回能力快照；Run 入口显示选中能力和去重工具标签，旧 Run 无快照时安全空态 | Agent Runs 能力/工具审计 | 管理员排障 |

学习记录、掌握度和薄弱点没有注册成模型写工具：练习/批改先经过可信业务门禁，再由幂等事件投影产生记录，
薄弱点继续是评价证据的读模型。这样既让 Agent 上下文明确“系统会什么”，又不会让一次模型误判直接改写学习事实。
