# Agent 对话模块实时进展

## 记录规则

每个 Agent 相关功能提交记录以下内容：

- 日期与目标；
- 主要实现；
- 对应教学文档更新；
- 测试或构建结果；
- Git 提交哈希与中文提交信息。

## 2026-07-24：调整管理端 Agent 功能菜单归属

### 目标

将 Agent Runs 监控归入“系统监控”，将 Agent 模型配置归入“系统配置”，并移除与多模型管理
冲突的旧“问答 LLM”基础配置页，让监控、模型维护和其他系统配置的层级更清晰。

### 实现

- 侧栏把 Agent Runs 作为系统监控子项，把 Agent 模型配置作为系统配置子项，并补充原 URL 到父
  菜单的映射，保证列表页、详情页刷新时选中并展开正确分组。
- 路由 URL 保持 `/admin/agent-runs`、`/admin/agent-runs/:id` 和 `/admin/agent-models` 不变，仅把
  路由声明移动到相应代码区域，避免破坏已有跳转和书签。
- Header 路由上下文同步显示“系统监控 / Agent Runs 监控”和“系统配置 / Agent 模型配置”。
- 基础配置移除旧“问答 LLM”Tab，默认打开题目结构 LLM；保存前显式剔除隐藏的 `llm` 字段，
  避免基础配置继续成为第二个 Agent 问答模型写入口。
- 保留后端 `system_configs.llm`、迁移回填和运行时兼容回退，本次只收敛管理界面，不破坏已有环境。

### 教学文档

- `01-technical-panorama.md`：更新管理员端全景，并新增侧栏、路由、Header、页面保存和模型管理
  API 的完整代码执行链及精确文件、符号、行号。
- `02-detailed-implementation.md`：说明菜单归属、保留 URL、移除旧问答 LLM 页面但保留兼容数据
  的原因和后续清理边界。

### 验证

- 管理端 `npm run build` 通过。
- 本次修改的 `Sider`、`Header`、`Settings`、`AgentModelsPage` 和路由文件定向 ESLint 通过。
- 管理端全量 `npm run lint` 未通过：仅命中未改动的 `AgentRunDetailPage.tsx` 1 条 hooks 依赖 warning，
  以及 `AgentRunsPage.tsx` 1 条 hooks 依赖、2 条非空断言 warning；无 error、无本次新增 warning。
- `git diff --check` 通过。

### 提交信息

`调整管理端 Agent 功能菜单归属`

## 2026-07-24：修复用户端模型选择器缺表故障

### 目标

解决 Agent 页面加载可选 LLM 时 MySQL 报错
`Table 'starmap.agent_model_configs' doesn't exist`，恢复用户端模型列表，并把真实执行入口、迁移、
查询和完整对话主链补成可按文件、函数和行号定位的教学文档。

### 实现

- 确认当前代码迁移 head 为 `20260723_agent_model_configs`，运行数据库实际停在父 revision
  `20260723_repair_agent_parent`。
- 执行 `alembic upgrade head` 前向迁移，创建 `agent_model_configs`；未使用 `stamp head`，未手工
  创建不完整表。
- 迁移从已启用的旧 `system_configs.llm` 自动回填 `legacy_llm / 默认问答模型 / glm-5.2`，并保持
  上线、用户可选和默认状态。
- 补充缺表故障的根因判断、标准诊断顺序、业务接口不应静默吞掉结构漂移的设计原因。
- 在技术全景中新增独立“代码执行全景总览”，按入口、函数、事务、Worker、模型、持久化、SSE
  和前端消费顺序列出准确代码锚点；同时补充模型加载、用户输入、审批和管理员模型配置旁路。

### 教学文档

- `01-technical-panorama.md`：新增启动迁移、模型列表、完整 turn 执行链和交互旁路的代码全景。
- `02-detailed-implementation.md`：新增 `agent_model_configs` 缺表实际案例、代码锚点和修复原则。
- `docs/guides/common-operations-guide.md`：补充专项排障代码定位、应用层验证和实际 revision 对比。

### 验证

- `alembic current`：`20260723_agent_model_configs (head)`。
- MySQL：`agent_model_configs` 表存在，公开记录为 `legacy_llm / glm-5.2`，且
  `online=1`、`selectable=1`、`is_default=1`。
- 应用真实数据库校验：`verify_database_schema` 返回最新 head，
  `AgentModelConfigService.list_public` 正常返回默认模型。
- 后端迁移、schema guard 和模型配置相关自动化测试通过。
- `git diff --check` 通过。

### 提交信息

`记录并验证 Agent 模型配置缺表修复`

## 2026-07-24：接入用户端 Agent 模型选择器

### 目标

让用户看到管理员已上线且允许选择的模型，并确保新会话首轮和已有会话后续轮次都把当前模型
明确提交给后端，不再只依赖运行时默认回退。

### 实现

- 用户端 API 新增公开模型列表类型与请求，turn 请求新增可选 `model_config_id`。
- Agent 页面加载模型列表，优先选中管理员默认模型，当前选择在空会话和已有会话输入框间共享。
- Composer 增加紧凑模型选择器、加载/空列表提示和失败重试，未获得有效模型时禁用发送按钮但
  保留文本编辑能力。
- `sendTurn` 通过 options 传递模型配置 ID，每一轮请求均显式绑定当前选择。
- 改进 Agent API 错误解析，提取 FastAPI `detail`；模型在提交前被下线时保留输入、展示中文错误
  并自动刷新可选列表。

### 教学文档

- 全景图补充用户模型加载、默认选择、turn 显式传值和过期选择恢复链路。
- 细致讲解补充为何选择属于 turn 而非 thread，以及前端提示与后端并发校验的职责边界。

### 验证

- 用户端 `npm run build` 通过。
- 用户端全量 `npm run lint` 通过。
- `git diff --check` 通过。

### 提交信息

`接入用户端 Agent 模型选择器`

## 2026-07-24：新增管理员 Agent 多模型管理页面

### 目标

把已经落地的多模型管理接口接入管理员端，使模型创建、密钥更新、上下线、默认切换和连通性
测试可以在同一页面安全完成。

### 实现

- 新增管理端模型 API 类型与请求封装，连通性测试使用独立的 120 秒超时。
- 新增 `/admin/agent-models` 页面和侧栏入口，表格展示显示名称、内部模型标识、密钥配置状态、
  上线、用户可选、默认状态和更新时间。
- 新增创建/编辑表单，支持采样参数、Token 上限和超时时间；已有 API Key 不回显，留空时省略
  更新字段以保留服务端原值。
- 支持行内上下线、用户可选、设置默认和连通性测试，并提供按钮级 loading 与结果反馈。
- 所有状态不变量继续由后端接口校验，页面不会绕过默认模型约束直接修改本地列表。

### 教学文档

- 全景图补充管理员模型页面、前端 API 边界和密钥安全编辑数据流。
- 细致讲解补充 React Query 刷新策略、按钮级测试状态、密钥保留方式和并发操作约束。

### 验证

- 管理端 `npm run build` 通过。
- 新增管理页、API、路由和侧栏文件定向 ESLint 通过。
- 管理端全量 `npm run lint` 仍被既有 Agent Runs 文件的 4 条 warning 阻断，本次未扩大范围修改。
- `git diff --check` 通过。

### 提交信息

`新增管理员 Agent 多模型管理页面`

## 2026-07-24：建立 Agent 多模型配置与运行时选择链路

### 目标

让管理员能够维护多个 Agent 模型并控制上线、用户可选和默认状态，同时让一次用户对话选择
明确进入 Run，避免后台配置表与实际模型调用再次形成两条链路。

### 实现

- 新增 `agent_model_configs` ORM 与 Alembic 前向迁移，迁移已启用的旧问答 LLM 为默认记录。
- 新增管理员模型列表、创建、更新、上下线、切换默认和连通性测试接口，列表对 API Key 脱敏。
- 使用 `default_slot` 数据库唯一约束保证最多一个默认模型，并阻止默认模型被直接下线。
- 新增用户可选模型接口，只暴露已上线且可选记录的 ID、显示名称和默认标记。
- turn 支持可选 `model_config_id`，创建 Run 前重新校验状态，并把模型选择纳入幂等冲突判断。
- 模型运行时按“Run 指定模型、数据库默认模型、旧系统配置、环境变量”顺序解析，并把实际
  模型配置 ID 固定写回 Run 元数据。

### 教学文档

- 全景图补充多模型管理端、用户模型列表、turn 选择、Run 固定与回退数据流。
- 细致讲解补充默认唯一约束、密钥脱敏、运行时解析顺序、迁移兼容和故障排查方法。

### 验证

- 后端全部 Agent 测试：87 项通过。
- Agent、迁移图与启动结构校验相关测试：101 项通过。
- Alembic 迁移图保持单 head：`20260723_agent_model_configs`。
- Agent 模块与新增测试 `compileall` 通过。
- `git diff --check` 通过。

### 提交信息

`建立 Agent 多模型配置与运行时选择链路`

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

## 2026-07-23：统一 Agent 页面视觉系统

### 目标

让 Agent 对话页面的背景、字体、颜色、圆角、边框和交互状态与用户端其他子页面保持一致，
同时保留消息流与内嵌工作流的专有布局。

### 实现

- 将 Agent 页面颜色变量映射到用户端全局设计 token，不再维护灰白蓝紫独立主题。
- 页面正文继承全局字体，标题和运行元信息分别复用全局衬线与等宽字体。
- 用户气泡、工作流状态、等待交互、失败提示和错误浮层统一使用全局语义色。
- 输入框、发送按钮、focus ring、边框、阴影和圆角调整为项目现有视觉语言。
- 保留时间线、流式消息、工作流卡片和移动端布局，不改变交互与数据契约。

### 教学文档

- 全景图补充 Agent 组件与全局设计 token 的依赖关系。
- 细致讲解补充原视觉割裂原因、语义变量映射和后续主题维护方式。

### 验证

- 前端 `npm run build` 通过。
- `git diff --check` 通过。

### 提交信息

`统一 Agent 对话页面与用户端视觉系统`

## 2026-07-24：将 Agent Runs 改为会话级多轮监控

### 目标

修复管理端进入 Agent Runs 详情时因不存在的审批接口弹出 `Not Found`，并让监控列表一条记录
对应一个完整会话，详情按每次用户提问展示该轮问答、root/child Run 和可折叠事件流。

### 实现

- 后端列表主查询从 `agent_runs` 改为 `agent_threads`，分页、状态统计和表格字段统一使用会话粒度。
- 详情接口一次读取 Thread 内消息、Run、事件、审批和产物，按 root run 聚合为多轮 `turns`。
- 详情 ID 优先按 Thread 查询，并兼容把旧 Run ID 自动解析到所属 Thread，保留历史书签。
- 管理端详情不再请求不存在的 `/approvals` 管理接口，消除页面挂载时的 404 弹窗。
- 前端列表展示会话标题、问答轮数、运行节点数和事件数；详情一轮一个折叠面板，每轮事件流可
  独立折叠。
- 事件类型统一显示为“中文（英文事件名）”，未知事件保留原始英文值方便排查。
- 增加 root/child Run、消息和 child event 正确归入同一轮的聚合测试。

### 教学文档

- `01-technical-panorama.md` 增加管理端从会话列表、聚合接口到多轮事件折叠的完整执行全景。
- `02-detailed-implementation.md` 解释 `Not Found` 的真实来源、会话级分页、状态统计、turn 聚合、
  旧链接兼容和中英文事件名称设计。
- 所有新增代码说明均标注仓库路径、完整函数或组件符号及精确代码范围。

### 验证

- 管理端 Agent 路由与会话聚合测试：36 项通过。
- 管理端 TypeScript 类型检查通过。
- `git diff --check` 通过。

### 提交信息

`将 Agent Runs 改为会话级多轮监控`

## 2026-07-24：支持 LLM 输出 Token 无限配置

### 目标

让 Agent 模型配置和系统内所有任务型 LLM 配置支持“无限”输出 Token，并修复 `glm-5.2` 因
`max_completion_tokens` 超过 131072 而在后续对话返回 400 的问题。

### 实现

- 管理端 Agent 模型与任务型 LLM 表单增加无限开关，`null` 表示不发送输出 Token 上限。
- Agent 模型列改为 nullable，并增加 Alembic 前向迁移；ORM 保留显式 SQL `NULL`。
- Agent Pydantic AI 运行时和共享 OpenAI 客户端仅在数值非空时加入 Token 参数。
- 保留“字段缺失使用默认值、数字表示明确限额、null 表示无限”的三态契约。
- 补充持久化、运行时参数省略、共享客户端、系统设置合并和迁移图测试。

### 验证

- 后端相关测试通过。
- 管理端 `npm run build` 通过。
- `git diff --check` 通过。

### 提交信息

`支持 LLM 输出 Token 无限配置`
