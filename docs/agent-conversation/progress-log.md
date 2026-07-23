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

## 2026-07-23：打通管理员 LLM 配置与 Agent 回答

### 目标

解决管理员已保存并测试问答 LLM，但用户发送消息后 Agent 没有回复、后台也缺少有效诊断
日志的问题。

### 实现

- Agent Router 和 DirectAnswer 优先读取 MySQL `system_configs.llm`，未启用时才回退环境变量。
- 每次调用创建独立 `AsyncOpenAI`、`OpenAIProvider` 和 `OpenAIChatModel`，并在调用后关闭。
- Run 元数据记录配置来源、模型名称、供应商和稳定错误码，不记录 API Key。
- Worker 保存后台 Task 强引用，防止重复启动，记录异常退出，并在应用关闭时有序停止。
- 增加 Worker 扫描、Run 处理、配置解析和模型调用关键日志。
- 静默 conversation run 失败时投影用户可见的 assistant `message.failed`，前端同步失败内容。
- 对重复失败记录增加终态保护，避免二次非法状态转换掩盖原始异常。

### 教学文档

- 全景图补充管理员问答 LLM 到 Worker 模型运行时的真实配置流。
- 细致讲解补充配置链路割裂原因、独立客户端、Worker 生命周期、失败投影与日志排查顺序。
- 明确当前仍是单模型兼容阶段，多模型配置 ID 将在后续功能中实现。

### 验证

- 后端全部 Agent 测试：71 项通过。
- 前端 `npm run build` 通过。
- `git diff --check` 通过。

### 提交信息

`打通管理员 LLM 配置与 Agent 回答执行链路`

## 2026-07-23：修复 Agent 历史时间时区偏差

### 目标

解决 Agent 会话历史和管理员运行记录中的时间在上海等时区刚好相差数小时的问题，并明确
数据库、API 与浏览器之间的时间契约。

### 实现

- 新增 Agent UTC 时间工具，数据库继续保存 naive UTC，API 统一输出带 `Z` 的 ISO 8601。
- Pydantic Agent 响应模型统一使用 UTC 时间序列化器。
- 用户线程、Run、事件、产物、审批和管理员 Agent Runs 的手写响应统一补 UTC 标记。
- SSE 快照与事件负载递归转换嵌套时间，避免实时数据和历史快照使用两套时间语义。
- Agent 生产代码将 `datetime.utcnow()` 替换为明确的 `utc_now()`，消除 Python 3.14 弃用路径。
- 不修改 MySQL 表结构和历史数据，历史记录重新通过 API 加载即可按浏览器时区正确显示。

### 教学文档

- 全景图补充 MySQL naive UTC、API `Z` 和浏览器本地化的两段式时间契约。
- 细致讲解补充固定小时差的原因、序列化边界、为何不需要数据库迁移及未来演进风险。

### 验证

- UTC 工具、Pydantic 响应、SSE、时间线和管理员序列化测试：30 项通过。
- 后端全部 Agent 测试通过。
- 前端 `npm run build` 通过。
- `git diff --check` 通过。

### 提交信息

`统一 Agent UTC 时间序列化并修复历史时间偏差`
