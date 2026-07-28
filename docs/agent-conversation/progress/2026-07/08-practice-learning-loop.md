# 2026-07 Agent 练习与学习闭环

## 2026-07-28：阶段一——对话出题落入真实练习

- 目标：让 Validate 的完成状态代表“已创建可练习草稿”，并提供对话内跳转、本会话练习轨道和管理端观测。
- 实现：新增 Session 原生题目 item/provenance、Agent Thread/Run 来源和 draft 状态；题库题重读完整实体，即时题冻结在 Session；Artifact 输出受控动作，练习页点击后才开始计时。
- 管理端：Agent Runs 会话详情同步返回并展示关联练习、状态、题数、得分和来源 Run。
- 验证：`pytest` 覆盖 Validate、持久化、私有答案和 MySQL 外键索引替换顺序；用户端与管理端生产构建通过；真实 MySQL 从 `20260728_practice_hints` 前向升级到单 head `20260728_agent_practice_drafts`。首次升级暴露非事务 DDL 的索引依赖后，迁移改为先建替代索引并支持原地重入，全程未使用 stamp。
- 中文提交信息：`打通 Agent 出题与真实练习入口`。
