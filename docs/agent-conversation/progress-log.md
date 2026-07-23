# Agent 对话模块实时进展

## 记录规则

每个 Agent 相关功能提交记录以下内容：

- 日期与目标；
- 主要实现；
- 对应教学文档更新；
- 测试或构建结果；
- Git 提交哈希与中文提交信息。

## 2026-07-23：修复 Agent Run 数据库结构漂移

### 目标

解决 Worker 扫描时 MySQL 报错 `Unknown column agent_runs_3.parent_run_id`，并避免数据库
版本记录正常但真实字段缺失时后台持续循环报错。

### 实现

- 新增 `20260723_repair_agent_parent` 前向修复迁移。
- 缺失时补齐 `parent_run_id`、索引和自引用外键，已存在时保持幂等。
- 启动时校验 Agent Worker 依赖的 `parent_run_id` 与 `root_run_id` 真实存在。
- 新增迁移恢复、幂等和 schema drift 测试。
- 新增项目常见操作指南，记录数据库迁移诊断与手动恢复命令。

### 教学文档

- 全景图补充 MySQL outbox、Worker 串行调度和数据库事实来源。
- 细致讲解补充 ORM、Alembic 和真实表结构之间的关系。

### 验证

- Agent、迁移、schema guard 和部署契约相关测试：78 项通过。
- Alembic 迁移图保持单 head：`20260723_repair_agent_parent`。
- `git diff --check` 通过。

### 提交信息

`修复 Agent Run 数据库结构漂移并建立教学文档规范`
