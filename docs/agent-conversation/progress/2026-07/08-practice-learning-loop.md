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
