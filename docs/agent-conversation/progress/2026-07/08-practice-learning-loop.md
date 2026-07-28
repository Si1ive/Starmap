# 2026-07 Agent 练习与学习闭环

## 2026-07-28：阶段一——对话出题落入真实练习

- 目标：让 Validate 的完成状态代表“已创建可练习草稿”，并提供对话内跳转、本会话练习轨道和管理端观测。
- 实现：新增 Session 原生题目 item/provenance、Agent Thread/Run 来源和 draft 状态；题库题重读完整实体，即时题冻结在 Session；Artifact 输出受控动作，练习页点击后才开始计时。
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
