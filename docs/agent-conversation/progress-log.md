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

## 2026-07-23：修复管理员 Agent Runs 监控接口

### 目标

解决管理员页面请求 `/api/v1/admin/agent-runs` 时因后端路由地址不一致而无法加载，并清理
统计响应、分页总数和 Run 字段映射中的陈旧实现。

### 实现

- 将 Agent 管理路由统一注册到 `/api/v1/admin/agent-runs`。
- 统计接口统一返回 `{ data: ... }`，与管理员前端 API 契约一致。
- 分页总数改为对子查询执行 `count(*)`，避免错误引用外层 `agent_runs`。
- 使用真实的工作流版本、公开步骤、开始/完成时间，并聚合最后事件序号。
- 增加管理员路由契约和 Run 序列化测试。

### 教学文档

- 全景图明确管理员 Agent Runs 的最终 API 地址和数据来源。
- 细致讲解补充路由前缀、响应契约、字段映射和排查顺序。

### 验证

- 管理员 Agent 路由、响应契约和模块化路由测试：36 项通过。
- `git diff --check` 通过。

### 提交信息

`修复管理员 Agent Runs 监控接口与数据契约`

## 2026-07-23：升级 OpenAI Python SDK 调用方式

### 目标

解决管理员测试 ChatLLM 连通性时调用已移除的 `openai.ChatCompletion` 接口，并消除多个
模型配置通过 OpenAI 全局变量相互覆盖的风险。

### 实现

- ChatLLM 统一使用 `openai.AsyncOpenAI().chat.completions.create()`。
- Embedding 统一使用 `openai.AsyncOpenAI().embeddings.create()`。
- 每次调用使用独立客户端并可靠关闭，不再写入 `openai.api_key/api_base` 全局变量。
- ChatService 的 RAG、直接回答、建议问题及环境变量回退统一复用 `ChatLLMClient`。
- 增加 ChatLLM、Embedding 和 ChatService 回退路径的 SDK 兼容测试。

### 教学文档

- 全景图补充独立异步客户端在管理员配置和模型供应商之间的位置。
- 细致讲解补充 OpenAI 0.x 到 1.x/2.x 的接口变化、降级方案缺陷和并发配置隔离原理。
- 明确本次修复尚未代替 Agent 工作流配置链路修复。

### 验证

- OpenAI 客户端、LLM 默认值、ChatService 和系统设置规则测试：19 项通过。
- 代码中不存在旧 `ChatCompletion`、`Embedding.create` 或 `openai.api_*` 调用。
- `git diff --check` 通过。

### 提交信息

`升级 ChatLLM 与向量服务到 OpenAI 1.x 客户端`
