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

## 2026-07-24：修复 Agent 失败回复重复提示

### 目标

修复用户端 assistant 失败消息把同一句安全提示显示两遍的问题，并保留红色错误样式。

### 实现

- failed 消息只渲染一个错误节点，优先使用后端投影的安全正文。
- 仅在正文为空时使用默认失败文案，不通过字符串比较或截断做偶然去重。

### 验证

- 用户端 `npm run build` 通过。
- `git diff --check` 通过。

### 提交信息

`修复 Agent 失败回复重复提示`

## 2026-07-24：统一 LLM 输出配额控件设计

### 目标

解决管理端多处“无限”Switch 与数字输入框风格割裂的问题，让限额与不设上限成为同一个清晰、
克制且可复用的配置控件。

### 实现

- 新增共享 `TokenLimitField`，用“按额度/不设上限”分段选择器统一两种配置状态。
- 限额模式显示带 Token 单位的数值输入；无限模式在相同容器内解释不会发送供应商上限。
- 组件记忆切换前额度，返回限额模式时恢复原值；只有主动选择不设上限才写入 `null`。
- Agent 模型与任务型系统 LLM 表单复用同一组件和视觉规则。
- Agent 模型列表把高亮“无限”标签改为弱化的“不设上限”文本，降低视觉噪声。

### 教学文档

- 全景文档补充共享配额组件进入 Agent 模型和任务型 LLM 表单的执行链。
- 细致讲解补充交互状态、数值恢复、空输入保护、表格文案和样式定位。
- 所有代码说明均标注仓库相对路径、完整符号及最终精确代码范围。

### 验证

- 管理端 `npm run build` 通过。
- `git diff --check` 通过。

### 提交信息

`统一 LLM 输出配额控件设计`

## 2026-07-25：修复 Agent 无限 Token 保存数据库漂移

### 目标

修复 Agent 模型选择“不设上限”后保存返回“服务器内部错误”的问题，并让同类列约束漂移在后端
启动阶段被明确发现。

### 根因与实现

- 实际数据库停在 `20260723_agent_model_configs`，落后最新 `20260724_agent_unlimited` 一个 revision，
  导致 ORM 写入 `NULL` 时触发旧 `NOT NULL` 约束。
- 使用现有 Alembic 前向迁移升级真实数据库到 `20260724_agent_unlimited (head)`，未使用 stamp。
- 启动期结构校验新增 `agent_model_configs.max_tokens` nullable 检查，版本表与真实约束漂移时中止启动。
- 更新 schema guard 的迁移 head 断言，并新增非 nullable 漂移回归测试。
- 通用操作指南补充该 500 的诊断命令、真实列核对方式和安全修复步骤。

### 教学文档

- 全景文档补齐建表迁移、nullable 迁移、FastAPI lifespan 与真实结构校验的启动链。
- 细致讲解记录本次 revision 差异、事务回滚原因、前向迁移与启动期防护。
- 所有新增代码说明均标注仓库相对路径、完整符号及最终精确代码范围。

### 验证

- 数据库 `alembic current` 返回 `20260724_agent_unlimited (head)`。
- schema guard、迁移、模型配置和无限 Token 相关测试：43 项通过。
- `git diff --check` 通过。

### 提交信息

`修复 Agent 无限 Token 保存数据库漂移`

## 2026-07-25：增强 Agent 等待回复动态反馈

### 目标

让用户发送消息后，在模型尚未产生公开正文时看到明确的动态状态；保留现有 delta 展示能力，但本轮
不接入真正模型 Token 流式调用。

### 实现

- Agent 页面按 thread 与响应 cursor 记录等待中的 turn，发送失败或出现新的 assistant/workflow 项时
  自动清除。
- 对话流在尚无真实 streaming assistant 时显示“正在组织回答”和三点动态反馈。
- 若未来或测试链路收到 `message.delta`，立即改为展示真实增量正文与光标，不重复显示等待占位。
- 动画复用用户端语义色，并为 `prefers-reduced-motion` 停止跳动。
- 核实当前流式边界：SSE 协议、事件投影、前端 reducer 和渲染已支持 delta，模型运行时仍一次性返回。

### 教学文档

- 全景文档补充 reducer、等待 cursor 状态与最终渲染步骤。
- 细致讲解明确模型执行、完成事件、delta 投影、前端归并与动态等待各层边界。
- 所有代码说明均标注仓库相对路径、完整符号及最终精确代码范围。

### 验证

- 用户端 `npm run build` 通过。
- `git diff --check` 通过。

### 提交信息

`增强 Agent 等待回复动态反馈`

## 2026-07-25：将 Agent 工作流执行链接入真实动态事件

### 目标

让 Router 分流到 explain、validate、grade 或 plan 后，原有内嵌执行链按真实后端进度动态更新；
对于 RAG 检索进一步展示实际数据通道、查询内容、命中数量和资料，而不是静态或 mock 数据。

### 实现

- WorkflowEngine 在每个节点开始和结束后提交步骤、Run Event 与 Thread Event，消除整条任务完成后
  才一次性可见的事务问题。
- 新增 `workflow.activity.updated` 公开事件和 Alembic ENUM 前向迁移，数据库已升级到最新 head。
- explain 与 validate 的 `retrieve_knowledge` 在真实 Qdrant+MySQL 混合检索前后写入同一活动 ID。
- 公开载荷只包含安全的工具名、检索通道、查询范围、命中数和资料摘要，不暴露隐藏推理或正文。
- timeline snapshot 从持久化 tool events 重建 activities，SSE 断线或刷新后不会丢失执行记录。
- 前端 reducer 按活动 ID 动态 upsert，InlineWorkflow 展示运行状态、检索参数和命中资料。

### 教学文档

- 全景文档新增 Router 分流到 child workflow、逐节点 commit、真实 RAG、事件投影和 UI 消费的完整链。
- 细致讲解补充原页面像 mock 的事务根因、公开数据边界和刷新重建机制。
- 所有新增代码说明均标注仓库相对路径、完整符号及最终精确代码范围。

### 验证

- 完整 Agent 后端回归：91 项通过。
- 用户端 `npm run build` 通过。
- 数据库 `alembic current` 返回 `20260725_agent_activity (head)`。
- `git diff --check` 通过。

### 提交信息

`将 Agent 工作流执行链接入真实动态事件`

## 2026-07-25：接入 DirectAnswer 结构化正文流

### 目标

让 Router 选择普通问答后，DirectAnswerRuntime 在最终结构化结果完成前持续输出可见正文，同时保留
Router 的完整结构化决策和最终消息收敛能力。

### 实现

- DirectAnswerRuntime 使用 Pydantic AI `run_stream` 和 100ms debounce 的 `stream_output`。
- 从 partial `DirectAnswerOutput.content` 计算安全前缀增量，不直接展示半截结构化 JSON。
- conversation 节点把每批正文写入 `message.delta` 并 commit，使 SSE 在模型生成期间可读。
- 第一个 delta 创建真实 assistant 时间线项，后续 delta 追加；最终 `message.completed` 用完整正文收敛。
- RouterRuntime 保持非流式，不公开内部 reason、partial 决策或隐藏推理。
- 保留无 callback 的非流式执行入口，支持测试模型和需要完整结果的内部调用。

### 教学文档

- 全景文档更新普通回答从 Router、结构化 stream、delta commit、事件投影到前端显示的完整链。
- 细致讲解补充 partial validation、前缀增量、100ms 批处理和最终 completed 收敛策略。
- 所有新增代码说明均标注仓库相对路径、完整符号及最终精确代码范围。

### 验证

- 完整 Agent 后端回归：93 项通过。
- `git diff --check` 通过。

### 提交信息

`接入 DirectAnswer 结构化正文流`

## 2026-07-25：修复 explain 模型配置与真实检索链路

### 目标

修复 Router 已成功选择 `explain`，但资料规划和讲解生成仍因旧适配器缺少环境变量凭据而失败的问题；
同时让零命中和检索异常在用户端显示可理解的资料提示。

### 根因与实现

- 真实故障 Run 的 evidence loop 在产生动作前已报 `Missing credentials`，因此没有任何
  `tool.called/tool.result`，RAG 根本未执行；异常又被记录成步骤完成，造成误导。
- 新增 `ExplanationRuntime`，资料规划和讲解正文都通过 `open_agent_model` 使用 child Run 绑定的
  Agent 模型配置，不再读取旧全局 `ModelAdapter` 的空 Key 和错误模型名。
- conversation 创建业务 child Run 时继承父 Run 的 `model_config_id`，保证用户选择的非默认模型不会
  在 Router 之后丢失；只复制配置 ID，不复制密钥。
- explain 首次至少真实检索一次，只把成功且非空结果计入有效 evidence；规划模型异常直接产生失败
  步骤，不再伪装成“查找资料完成”。
- 零命中公开“没有检索到相关文档”，检索异常公开“暂时无法检索相关文档”，不向用户暴露内部
  容错术语；没有文档时仍允许模型基于可靠通用知识讲解，但禁止伪造引用。

### 教学文档

- 全景文档补齐父 Run 模型选择、child metadata、结构化资料规划、RAG、证据门、讲解生成、产物和
  前端活动消费的完整执行链。
- 细致讲解记录真实 Run 证据、旧/新运行时差异、错误传播、零命中语义和回归测试锚点。
- 所有代码定位均使用本次最终代码的仓库相对路径、完整符号和精确行范围。

### 验证

- explain 定向回归：18 项通过。
- 完整 Agent 后端回归：101 项通过，只有既有 `datetime.utcnow()` 弃用警告。
- `git diff --check` 通过。

### 提交信息

`修复 explain 模型配置与真实检索链路`

## 2026-07-25：收紧 Agent 输入框并增加底部间距

### 目标

减少用户端 Agent 输入框在空文本和单行文本时的多余高度，并让已有会话中的底部输入区与页面下沿
保持稍大的安全距离，避免视觉上贴边或被遮挡。

### 根因与实现

- 全局旧 Agent CSS 的同名选择器仍给 textarea 保留 20px padding，给 footer 保留 54px 最小高度、
  padding 和顶边框；新组件样式未显式重置，自动高度把旧 padding 一起计入了 `scrollHeight`。
- 当前 Agent 页面明确清除 textarea/footer 遗留属性，把单行 textarea 收敛为 24px、footer 收敛为
  32px，composer 总高稳定为 78px；多行输入仍可自动增长到 160px。
- 桌面 dock 底部 padding 从 13px 增加到 18px，移动端从 8px 增加到 13px，并叠加系统安全区。
- 发送按钮收敛到 32px；移动端隐藏快捷键提示后，发送按钮继续保持最右对齐。

### 教学文档

- 细致讲解新增旧/新 CSS 选择器叠加、`scrollHeight` 计算、重置边界和移动端安全区说明。
- 所有样式说明均标注仓库相对路径、组件/选择器符号及最终精确代码范围。

### 验证

- 用户端 `npm run build` 通过。
- 无头 Chrome 在 1440×900 与 390×844 下验证空文本和单行输入：composer 78px、textarea 24px、
  footer 32px，无横向溢出、无页面运行时异常。
- 桌面与移动端截图确认文本、模型选择和发送按钮对齐，底部说明及导航均未遮挡。
- `git diff --check` 通过。

### 提交信息

`收紧 Agent 输入框并增加底部间距`

## 2026-07-25：修正 Agent 路由意图与模型 Token 预算

### 目标

修复“讲解红黑树”等明确业务请求仍被 Router 归为 `direct_answer`，以及项目把 4096 历史上下文预算
误作 Pydantic AI 输入加输出总量限制，导致长回答在模型能力范围内仍被提前中止的问题。

### 根因与实现

- Router 原提示只说“普通问答”，边界过宽；真实 Run 因此把“给我讲解一下红黑树”判为
  `standard_knowledge_question`。现在明确 direct/explain/validate/grade/plan/clarify 的语义边界。
- 增加服务端显式意图护栏，对讲解、出题、批改和学习计划的明确措辞纠偏；保留模型的 clarify 决策，
  并继续执行 allowed action 授权校验。
- 4096 继续用于筛选可信历史和记录上下文审计，不再传给 Pydantic AI 的
  `total_tokens_limit`；Router、DirectAnswer 和 Explanation 只保留每次运行两次模型请求的保护。
- 输出 Token 继续由本轮 Agent 模型配置控制；管理员设置“不设上限”时不发送 `max_tokens`，由真实
  模型和供应商上下文窗口决定可生成长度。

### 教学文档

- 全景文档补充 Router 模型调用、显式意图护栏、历史选择预算和模型输出限制的完整边界。
- 细致讲解记录真实 Run 的 56/4096/4863 Token 证据、为什么它不是 glm-5.2 的模型上限，以及各运行时
  的精确调用位置和回归测试。

### 验证

- Router、DirectAnswer、Explanation 定向回归：19 项通过。
- `git diff --check` 通过。

### 提交信息

`修正 Agent 路由意图与模型 Token 预算`

## 2026-07-26：保留 Agent 流式失败内容并细分错误提示

### 目标

让模型在已流式生成部分正文后失败时保留用户已经看到的内容，并把笼统失败提示改为可理解的大致
原因，同时保证供应商原始错误仍只用于管理端排障。

### 根因与实现

- `message.failed` 旧投影无条件用失败文案覆盖 `AgentMessage.content_text`，前端 failed 分支又只渲染
  错误，因此 99 批已落库 delta 也会在最终失败时消失。
- 新增公开错误分类，覆盖模型未配置、回答过长、上下文过长、输出参数越界、限流、超时、结构化
  返回格式错误和未知异常；Run 保留原始错误，SSE 只公开稳定错误码和安全中文原因。
- 失败消息投影不再覆盖已有正文；刷新时从持久化 error_code 重建安全说明，实时事件同时携带正文、
  原因和 partial 保留标记。
- 前端把失败正文和红色错误说明分开渲染；没有正文时只显示一次原因，并兼容历史上把默认失败文案
  存进 content 的记录。

### 教学文档

- 全景文档新增从 Worker 异常、错误分类、Run 审计、消息投影、SSE 到前端显示的完整失败执行链。
- 细致讲解记录正文消失和重复提示的双重根因、错误码映射、刷新恢复及前后端精确定位。

### 验证

- conversation、公开错误、时间序列化和管理员路由定向回归：26 项通过。
- 完整 Agent 后端回归：117 项通过，只有既有 `datetime.utcnow()` 弃用警告。
- 用户端 `npm run build` 通过。
- `git diff --check` 通过。

### 提交信息

`保留 Agent 流式失败内容并细分错误提示`

## 2026-07-26：恢复 Agent 首页宽松输入框

### 目标

保留用户认可的会话内紧凑输入框，同时把没有历史内容的 Agent 首页恢复为更醒目的大输入区。

### 实现

- 复用页面已有 `agent-chat-page--empty` 状态，只给空会话首页覆盖 composer padding 和 textarea 高度。
- 首页 textarea 最小高度设为 88px、最大高度仍为 180px，空白和单行时有明确主操作体量，多行仍自动
  增长。
- 已有会话继续使用 24px textarea、32px footer 和约 78px composer，不受首页规则影响。
- 发送、模型选择、键盘快捷键和自动增长逻辑继续复用同一个 `ChatComposer`，没有复制组件状态。

### 教学文档

- 细致讲解补充首页与会话内输入框的场景层级、CSS 覆盖关系、自动高度边界和准确代码定位。

### 验证

- 用户端 `npm run build` 通过。
- 无头 Chrome 在 1440×900 和 390×844 下核对：空首页 composer/textarea/footer 分别为
  150px/88px/32px；已有会话基础场景仍为 78px/24px/32px；两种视口均无页面或输入框横向溢出，
  无运行时异常。
- `git diff --check` 通过。

### 提交信息

`恢复 Agent 首页宽松输入框`

## 2026-07-26：收敛 Agent 返回格式错误提示

### 目标

让 `agent_response_format_invalid` 只说明模型返回内容无法解析，不再附加重试或联系管理员的建议。

### 实现

- 保留 `agent_response_format_invalid` 稳定错误码和 `Exceeded maximum output retries` 分类规则。
- 公开文案改为“模型返回内容格式不符合要求，系统未能完成解析。”。
- Run 中的供应商原始错误、管理端审计和其他错误分类均不变；刷新恢复继续按错误码读取最新文案。

### 教学文档

- 细致讲解补充该错误码的精确公开文案、行为边界和回归测试锚点。

### 验证

- 公开错误分类与 conversation 失败消息链路回归：18 项通过。
- `git diff --check` 通过。

### 提交信息

`收敛 Agent 返回格式错误提示`

## 2026-07-26：建立 Agent 教学文档分卷与按需读取规则

### 目标

停止把 Agent 架构、实现、故障和进展持续追加到两个大正文文件中，降低自动化代理定位文档时的无关
上下文读取成本，并把拆分规则固化为仓库级长期约束。

### 实现

- 量化现有三份核心文档约 141 KB，确认主要成本来自整份读取和大范围行号复核，而不是文件存在本身。
- 在根 `AGENTS.md` 增加 README 路由、主题分卷、incident 单页、月度进展、按需读取和软/硬体积阈值。
- Agent 文档目标结构按 architecture、implementation、incidents、progress 四类职责拆分。
- 现有 01、02 和 progress-log 标记为迁移源；下一次新增正文前必须先独立拆分，旧路径最终保留薄索引。
- `docs/agent-conversation/README.md` 增加目标目录树和按改动类型选择最小分卷的路由表。

### 验证

- `AGENTS.md` 与 README 规则互相一致，目标路径和迁移约束完整。
- `git diff --check` 通过。

### 提交信息

`建立 Agent 教学文档分卷规则`
