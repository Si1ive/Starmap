# 第二部分：Agent 对话模块细致讲解

## 1. 数据库迁移与运行时结构契约

### 1.1 为什么 ORM 中有字段，数据库仍可能报不存在

SQLAlchemy 的 `AgentRun.parent_run_id` 只是应用对目标表结构的声明，不会自动修改已经存在的
MySQL 表。真实数据库结构必须通过 `backend/alembic/versions/` 中的迁移推进。

如果代码已更新但数据库未执行迁移，或者有人使用 `alembic stamp head` 只修改版本记录，
ORM 仍会生成包含新字段的 SQL，MySQL 随后返回 `Unknown column`。

### 1.2 `parent_run_id` 在调度中的作用

`parent_run_id` 表示当前 run 的直接父运行，`root_run_id` 表示整个工作流树的根运行。Worker
扫描 outbox 时需要区分 root run 和 child run，并判断同一 thread 中是否存在更早的活动树。
因此不能通过删除查询中的 `parent_run_id` 条件规避故障，否则会破坏同一 thread 的执行顺序。

### 1.3 本次防护

- `20260723_repair_agent_parent` 是前向、幂等的修复迁移，负责补齐字段、索引和自引用外键。
- 应用启动校验除了比较 `alembic_version`，还检查 Worker 依赖的 `parent_run_id` 和
  `root_run_id` 是否真实存在。
- 版本号正确但实际结构漂移时，后端会在启动阶段失败并给出迁移提示，而不是让 Worker
  周期性重复打印 SQL 错误。

具体手动操作见 `docs/guides/common-operations-guide.md`。

### 1.4 模型选择器报 `agent_model_configs` 不存在时如何定位

2026-07-24 的一次实际故障中，用户端打开 Agent 页面后模型列表请求返回 500，MySQL 报错：

```text
Table 'starmap.agent_model_configs' doesn't exist
```

页面请求地址和查询条件都是正确的。真实原因是代码迁移 head 已经是
`20260723_agent_model_configs`，运行数据库却仍停在它的父 revision
`20260723_repair_agent_parent`。因此 ORM 正常生成了查询 SQL，但 MySQL 中还没有目标表。

关键代码定位如下：

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| 定义前向迁移 | `backend/alembic/versions/20260723_agent_model_configs.py` | `upgrade` | L21-L90 | 创建 `agent_model_configs`，建立默认槽位唯一约束和索引，并回填启用的旧 LLM 配置 |
| 启动时阻断旧结构 | `backend/app/main.py` | `lifespan` | L77-L107 | MySQL 连接成功后先执行 schema guard，失败时关闭连接并终止启动 |
| 校验版本与真表 | `backend/app/modules/operations/schema_guard.py` | `verify_database_schema` | L28-L104 | 同时校验 Alembic head、`agent_runs` 必需字段和 `agent_model_configs` 是否真实存在 |
| 用户模型接口 | `backend/app/modules/agent/router.py` | `list_selectable_models` | L55-L63 | 认证后调用公开模型查询，不向用户返回连接凭据 |
| 触发报错的查询 | `backend/app/modules/agent/model_configs.py` | `AgentModelConfigService.list_public` | L168-L180 | 从真表筛选已上线且允许用户选择的记录 |
| 前端请求与恢复 | `frontend/src/pages/AgentPage.tsx` | `AgentPage.loadModels` | L60-L77 | 加载模型、选择默认项；失败时展示错误并允许重试 |

标准诊断顺序是：

1. 在 `backend` 目录执行 `alembic current`，确认数据库当前 revision。
2. 执行 `alembic heads`，确认当前代码要求的 head。
3. 若 current 落后，执行 `alembic upgrade head`，不能使用 `stamp head`。
4. 再执行 `alembic current`，并查询 `SHOW TABLES LIKE 'agent_model_configs'`。
5. 最后通过 `AgentModelConfigService.list_public` 或真实 HTTP 接口验证，而不是只看迁移命令退出码。

本次修复执行前，current 为 `20260723_repair_agent_parent`；执行前向迁移后，current 为
`20260723_agent_model_configs (head)`。迁移从旧 `system_configs.llm` 回填出
`legacy_llm / 默认问答模型 / glm-5.2`，其 `online`、`selectable`、`is_default` 均为真，应用服务
查询能够正常返回该记录。

为什么不在模型列表接口里捕获 1146 并返回空数组：空数组会把“数据库结构未部署”伪装成“管理员
尚未配置模型”，既延迟告警，也可能让其他依赖同表的管理端和 Worker 继续产生 500。结构漂移必须
在部署迁移或启动 guard 处被解决，业务接口不负责运行时建表。

## 2. 对话创建与时间线

### 2.1 HTTP 入口

`POST /agent/threads/{thread_id}/turns` 接收用户消息。路由只负责认证和协议转换，核心事务由
`AgentTimelineService.create_turn` 完成。

### 2.2 原子写入

一轮对话必须在同一事务中创建用户消息、root run、时间线投影、thread event 和 outbox。
这样可以保证 API 返回成功后，后台一定存在可恢复的执行事实。

### 2.3 前端恢复

用户端先读取时间线快照，再通过 SSE 获取新增事件。SSE 断开时，客户端可以使用 cursor
补拉，不能只依赖浏览器内存中的“最后一条消息”。

## 3. Worker 与工作流

### 3.1 Outbox 扫描

Worker 周期性查找 `pending`、已到计划时间且未超过重试次数的 outbox。扫描查询同时保证
同一 thread 的 root run tree 串行，跨 thread 则可以独立推进。

### 3.2 认领与租约

认领 outbox 使用条件更新，run 执行使用租约，二者共同降低多 Worker 重复执行风险。每个
run 使用独立数据库 session，避免一个失败事务污染后续任务。

### 3.3 Conversation 工作流

conversation 工作流先构建历史和学习上下文，再由模型路由决定：

- `direct_answer`：生成普通助手消息。
- `clarify`：请求用户补充信息。
- `explain` / `validate` / `grade` / `plan`：创建对应 child workflow。

后续章节会随着多模型选择、可观察性和具体故障修复持续补充。

## 4. 管理员监控

管理员 Agent Runs 页面通过 `admin_router.py` 查询 run、step 和 event。监控接口必须与当前
数据库模型、管理员 API 响应格式和前端请求封装保持一致。出现“页面加载失败”时，应依次
检查 HTTP 状态码、后端异常、数据库迁移和前端字段映射。

### 4.1 为什么页面曾经完全加载不出来

管理员前端的 Axios 客户端统一以 `/api/v1/admin` 作为基础地址，所以
`get('/agent-runs')` 最终请求的是 `/api/v1/admin/agent-runs`。Agent 管理路由原先却注册在
`/api/v1/agent-runs`，两边只差一个 `admin`，但对 HTTP 路由来说就是两个完全不同的地址，
因此请求会得到 404，页面只能显示加载失败。

现在 `admin_router.py` 自身使用 `/admin/agent-runs` 前缀，再由主应用添加 `/api/v1`。这样
最终地址与所有其他管理员接口保持一致，并继续由主应用统一挂载管理员认证依赖。路由契约
测试会直接检查最终路径，防止后续重构再次漏掉 `admin` 前缀。

### 4.2 管理列表的数据契约

管理员前端约定响应形状为 `{ "data": ... }`。列表、详情和统计现在都遵循这一约定；统计
接口不再把统计字段直接放在响应根部。Run 字段也从当前 ORM 字段读取：

- `workflow_key` 和 `workflow_version` 优先使用真实版本字段，兼容旧记录时才回退；
- 当前步骤使用 `current_public_step`；
- 开始、结束时间使用 `started_at`、`completed_at`，不再拿创建、更新时间代替；
- 最后事件序号从 `agent_events` 按 run 聚合查询；
- 模型配置 ID 和错误码暂从运行元数据读取，后续多模型实现会将其纳入统一运行时契约。

分页总数查询先把带筛选条件的 Run 查询转换为子查询，再对该子查询执行 `count(*)`。这样
不会在外层错误引用 `agent_runs.id`，可避免额外 FROM 表和错误的总数结果。

### 4.3 排查顺序

管理员页面报错时，先在浏览器网络面板确认请求是否为
`GET /api/v1/admin/agent-runs`，再依次检查：HTTP 401/403 是否为管理员认证问题，404 是否为
路由契约问题，500 是否为数据库迁移或查询问题。数据库字段故障的处理方式见项目常见操作
指南。

## 5. 模型配置与运行时

当前项目存在系统配置、通用 LLM client 和 Agent `model_runtime` 等多条模型调用路径。后续
多模型功能应统一抽象为“模型配置记录 + 上线状态 + 能力用途 + 运行时解析”，避免管理员
测试连接使用一套客户端、Agent 回答又读取另一套配置。

### 5.1 为什么会出现 `openai.ChatCompletion` 报错

项目当前安装 `openai==2.46.0`，但原实现仍按 0.x SDK 调用
`openai.ChatCompletion.create()` 和 `openai.Embedding.create()`。OpenAI Python SDK 从
1.0 开始移除了这些模块级旧接口，改为先创建 `OpenAI` 或 `AsyncOpenAI` 客户端，再通过
`client.chat.completions.create()`、`client.embeddings.create()` 发起请求。因此管理员保存
配置没有失败，但点击“测试连通性”真正执行旧调用时才会立即报接口不再支持。

不采用固定 `openai==0.28` 的方式规避：降级只能暂时保留旧接口，会阻碍安全更新和后续
依赖升级，而且仍保留全局配置带来的并发串线风险。正确做法是让应用代码适配当前 SDK。

### 5.2 独立异步客户端

共享 `BaseLLMClient` 和 `EmbeddingService` 现在按一次调用创建一个 `AsyncOpenAI` 实例：

```text
当前业务配置
  ├─ api_key
  ├─ base_url
  ├─ model
  └─ timeout
       │
       ▼
独立 AsyncOpenAI 实例
       │
       ├─ chat.completions.create(...)
       └─ embeddings.create(...)
```

旧实现先修改 `openai.api_key` 和 `openai.api_base` 全局变量，调用完成后再恢复。两个异步请求
交错执行时，请求 A 可能在发出前读到请求 B 的配置；保存和恢复无法消除这个竞态。独立客户
端把配置封装在实例中，不共享可变全局状态，才能安全支撑多个供应商和多个模型并发使用。

聊天服务中的 RAG 回答、直接回答和建议问题也统一经过 `ChatLLMClient`。环境变量回退仍然
保留，但只负责构造配置，同样走共享客户端和统一 LLM 调用记录。Embedding 返回值提取同时
兼容 SDK 1.x/2.x 的类型化对象以及测试中的字典响应。

### 5.3 为什么管理员保存成功，Agent 仍然无响应

修复前存在两条互不相连的配置链路：管理员页面把问答模型保存到 MySQL
`system_configs.llm`，连通性测试也读取这份数据；Pydantic AI 的 Router 和 DirectAnswer
却只读取 `OPENAI_API_KEY`、`OPENAI_MODEL`、`AGENT_ROUTER_MODEL` 环境变量。因此管理员侧
测试成功只证明保存的配置可用，并不代表 Agent Worker 会使用它。环境变量没有配置时，
conversation run 会在后台失败；又因为普通问答 run 的 `presentation` 是 `silent`，原来的
事件投影会直接忽略失败，用户端最终只留下自己发出的消息。

现在生产调用链统一为：

```text
用户消息
  -> conversation run / outbox
  -> Agent Worker
  -> SystemSettingsService.load()["llm"]
  -> AgentModelConfig 不可变配置快照
  -> 独立 AsyncOpenAI
  -> OpenAIProvider / OpenAIChatModel
  -> RouterRuntime / DirectAnswerRuntime
  -> assistant message
```

管理员配置已启用时，运行时会校验供应商、模型名称和 API Key；配置未启用时才回退环境变量。
两处都不可用会抛出 `AgentModelConfigurationError`，Run 元数据记录稳定错误码
`agent_model_unavailable`。模型调用前还会记录配置来源、供应商和模型名，但不会记录 API Key。
调用结束后关闭客户端，防止连接泄漏。

### 5.4 Worker 为什么要保留后台任务引用

FastAPI 启动时通过 `asyncio.create_task()` 启动 Worker。只创建 Task 而不保存强引用，会让
生命周期不可管理：应用无法判断是否重复启动，也无法在关闭数据库连接前等待 Worker 退出，
后台异常还可能只成为“无人读取的 Task 异常”。现在模块保存 `_worker_task`，给 Task 命名，
注册异常退出回调，并在 FastAPI lifespan 关闭阶段先调用 `stop_worker()`，再关闭 Redis 和
MySQL。这样停机时不会让 Worker 拿着已关闭的数据库连接继续扫描。

### 5.5 静默普通问答失败如何对用户可见

`silent` 的含义是“不展示内部工作流卡片”，不是“隐藏所有错误”。对于 conversation run，
`run.failed` 现在会被 `ThreadEventStore` 特判并投影成 assistant `message.failed`：如果模型未
配置，用户看到“Agent 模型尚未配置好”；其他执行异常显示可重试的通用提示。前端时间线
reducer 会使用事件中的公开内容更新失败消息并标记完成时间。

排查“发消息后无响应”时，可以按日志顺序检查：turn/run/outbox 创建、Worker 扫描到任务、
Run 开始处理、模型配置解析完成、Router 调用开始与完成、回答调用开始与完成、Run 完成或
失败。如果连“Worker 扫描到待执行任务”都没有，应先检查 Worker 是否启动和 outbox 状态；
如果停在配置解析，应检查管理员问答 LLM 是否启用以及模型名、API Key、Base URL。

### 5.6 多模型配置如何进入一次 Run

多模型配置存储在 `agent_model_configs`。管理员可以维护显示名称、OpenAI 兼容地址、模型名、
API Key、采样参数、上线状态、用户可选状态和默认状态。`default_slot` 只有默认记录写入 `1`，
其他记录写入 `NULL`；数据库唯一约束因此允许多个非默认记录，却不允许两个默认记录并存。
切换默认模型时，服务先清除旧默认再设置新默认；默认模型不能被直接下线或改为不可选。

用户端只通过 `GET /api/v1/app/agent/models` 获取 `online + selectable` 的记录，响应不包含
Base URL、模型内部名称或 API Key。创建 turn 时可携带 `model_config_id`。后端在消息、Run 和
outbox 入库前再次校验该记录仍可用，防止用户拿过期列表提交已下线模型；同一个
`client_message_id` 重试时，模型 ID 也属于幂等内容，换模型重试会返回冲突而不是复用旧 Run。

运行时解析顺序如下：

```text
Run.metadata.model_config_id
  -> agent_model_configs 默认记录
  -> 旧 system_configs.llm（迁移兼容）
  -> OPENAI_API_KEY + OPENAI_MODEL（最终兼容）
```

Router 第一次调用模型后会把实际 `model_config_id` 写回 Run。这样用户未显式选择时也会固定
当时的默认模型，随后 DirectAnswer 不会因为管理员中途切换默认模型而改用另一条配置。迁移
`20260723_agent_model_configs` 会创建新表，并把已启用的旧问答 LLM 安全复制为默认记录；迁移
不删除 `system_configs.llm`，便于滚动升级和旧功能继续运行。启动期 schema guard 除了核对
Alembic head，还会确认 `agent_model_configs` 真实存在，防止错误 `stamp head` 掩盖缺表。

管理员列表只返回 API Key 保留掩码和 `has_api_key`，更新请求携带保留掩码时不改写原密钥。
连通性测试与 Agent 运行时都复用独立客户端配置，不向 Run 元数据、日志或用户接口写入密钥。
排查选择模型失败时，依次检查配置是否存在、`online/selectable`、默认唯一约束、模型名/API
Key，以及 Run 元数据中的 `model_config_id` 和 `model_config_source`。

### 5.7 管理员页面如何安全维护模型

管理入口位于“系统配置 → Agent 模型配置”，URL 仍为 `/admin/agent-models`。
`frontend-admin/src/components/Sider/index.tsx` 的 `menuItems`（L34-L89）决定可见层级，
`menuGroups`（L120-L127）负责在原 URL 下自动展开“系统配置”；
`frontend-admin/src/components/Header/index.tsx` 的 `routeContexts`（L14-L41）同步显示所属栏目。
URL 没有随着菜单移动而改变，避免破坏已有书签和页面跳转。

`frontend-admin/src/api/agentModels.ts` 负责管理接口类型和
请求封装，页面通过 React Query 获取列表，并在创建、编辑、状态切换或设置默认成功后失效
`adminAgentModels` 查询，避免表格继续展示旧状态。连通性测试允许模型供应商响应较慢，因此
单独使用 120 秒请求超时，同时用记录 ID 控制按钮级 loading，管理员仍可辨认正在测试哪一行。

API Key 的编辑流程刻意不把服务端掩码填回密码框：列表只用 `has_api_key` 显示“已配置”，打开
编辑弹窗时密钥字段为空；如果管理员不输入新值，提交前删除 `api_key` 字段，Pydantic 的
`exclude_unset` 和配置服务便不会触碰原密钥。只有明确输入新值时才替换。这避免把空字符串或
`__KEEP_EXISTING__` 当成真实密钥保存，也防止浏览器表单、调试工具和前端状态接触明文旧密钥。

上线、用户可选和默认模型不是三个彼此独立的纯前端开关。页面调用 availability/default 专用
接口，服务端继续负责“默认模型必须上线且可选”“默认模型不能直接下线”等不变量；即使多个
管理员同时操作，最终约束仍由事务与数据库保证。遇到 400 时应先读取接口中文错误，再确认
是否需要先切换默认模型。测试返回 HTTP 成功但业务 `success=false` 时，页面展示响应中的错误，
因为供应商不可用属于配置测试结果，不应被误判为管理接口本身不可达。

### 5.8 为什么基础配置不再显示旧问答 LLM

旧“系统配置 → 基础配置 → 问答 LLM”和新的“系统配置 → Agent 模型配置”都能改变 Agent 问答
模型，管理员无法直观看出哪套配置优先，容易出现“刚保存却没有生效”的误判。因此
`frontend-admin/src/pages/Settings/index.tsx` 的 `Settings` 默认页签初始化（L234-L237）改为
`pdf-structure-llm`，Tab 渲染区（L323-L352）不再注册 `key="llm"`；问答模型统一从同级的
Agent 模型配置页面维护。

这里只移除管理入口，没有删除后端 `system_configs.llm` 数据。原因是
`20260723_agent_model_configs` 迁移会用它回填第一条默认模型，运行时也暂时保留旧数据库和环境变量
回退，以支持已有环境前向升级。为了避免 Ant Design Form 中通过 `setFieldsValue` 注入的隐藏旧值
随基础配置再次提交，`Settings.handleSubmit`（L264-L295）复制表单值后显式删除 `llm`，再执行
部署位置校验和 `updateSettings`。这样旧值只承担迁移兼容职责，不再成为可继续编辑的第二入口。

如果以后确认所有环境都已完成多模型迁移，应另开数据库清理迁移，并同时删除运行时回退、API
类型和旧配置字段；不能只在前端删除字段后直接清空数据库，否则滚动升级中的旧实例可能失去模型。

### 5.9 用户选择如何进入每一轮对话

`AgentPage` 挂载后调用 `listSelectableAgentModels()`，接口只返回 ID、显示名称和默认标记。页面
优先选择 `is_default=true` 的记录；如果管理员尚未指定默认但存在可用模型，则选择列表第一项。
刷新时会保留仍有效的当前选择，只有该 ID 已从公开列表消失时才回到默认项或第一项。这避免
普通的时间线刷新、路由切换把用户刚选择的模型意外重置。

模型选择是页面级状态，不写入 thread。原因是同一 thread 的不同 turn 可以使用不同模型，真正
需要审计的是每一轮创建请求和 Run 元数据，而不是给整个 thread 绑定一个可能过期的配置。
`ChatComposer` 在空会话与已有会话中消费同一组 props；`sendTurn` 通过 `SendTurnOptions` 把
`modelConfigId` 转成后端契约的 `model_config_id`。因此新 thread 的第一条消息和后续消息走完全
相同的显式选择链路。

加载模型期间、列表为空或没有选中 ID 时，发送按钮禁用，但文本框仍允许输入，避免网络抖动
让用户丢失正在组织的问题。加载失败时 Composer 展示重试按钮；没有可用记录时提示联系管理员。
模型列表可能在页面打开后失效，所以后端仍在创建 turn 前校验。若返回 400，页面保留原始文字，
解析 FastAPI 的 `detail` 为可读中文错误，并自动刷新模型列表；选择消失时会切到新的默认模型。
前端校验改善交互，后端校验才是并发状态变化下的最终安全边界。

## 6. 时间处理

### 6.1 为什么历史时间刚好差几个小时

MySQL `DATETIME` 本身不保存时区。Agent 原实现用 `datetime.utcnow()` 写入 UTC，例如数据库
中的 `2026-07-23 08:00:00` 实际代表北京时间 `2026-07-23 16:00:00`。但 FastAPI 原先把它
输出成没有后缀的 `2026-07-23T08:00:00`，浏览器无法知道这是 UTC；当字符串被当作本地时间
使用时，上海用户看到的时间就会少 8 小时。差值不是数据库随机错误，而是 UTC 信息在 API
边界丢失。

### 6.2 当前时间契约

项目采用以下约定：

```text
业务写入 utc_now()
  -> MySQL DATETIME: 2026-07-23 08:00:00（约定为 UTC）
  -> API/SSE: 2026-07-23T08:00:00Z
  -> 浏览器本地化: 2026-07-23 16:00:00（Asia/Shanghai）
```

`time_utils.py` 集中提供三类能力：`utc_now()` 生成 MySQL 兼容的 naive UTC，避免继续调用已被
Python 3.14 标记弃用的 `datetime.utcnow()`；`utc_isoformat()` 给响应时间补 `Z`；
`encode_utc_datetimes()` 递归处理 SSE 快照中的嵌套时间。Pydantic 响应模型则通过
`UTCDateTime` 序列化器保证 thread、message、workflow、step 和 event 的公开时间一致。

管理员 Agent Runs、用户线程列表、Run/事件/产物/审批等未使用强类型响应模型的接口，也在
各自序列化边界调用同一工具。这样新记录和历史记录都无需改写数据库：只要库中原有值确实
按项目约定表示 UTC，重新请求接口就会得到正确时区标记。

这次没有新增 Alembic 迁移，因为没有改变字段类型或数据库数据；修复的是“时间语义如何跨出
数据库”的 API 契约。如果未来需要让数据库列本身保存时区，应先评估 MySQL 驱动、索引比较、
历史数据转换和所有非 Agent 模块，不能直接把现有 `DATETIME` 当作带时区字段修改。

## 7. 用户端视觉系统

Agent 页面应复用用户端全局颜色、字体、间距、边框和表面层级变量，避免在
`agent-chat.css` 中形成独立主题。对话特有组件可以保留布局差异，但视觉 token 应来自全局
设计系统。

### 7.1 为什么原页面看起来像另一个产品

原来的 `agent-chat.css` 在页面根节点重新定义了灰白画布、蓝紫强调色和自己的字体栈，输入框、
发送按钮、用户气泡、工作流轨道和 focus ring 又继续硬编码同一套蓝紫色。即使组件结构本身
没有问题，只要基础 token 与全局 `index.css` 不同，用户在侧边栏和 Agent 页面之间切换时就会
明显感到颜色、字体、圆角和阴影来自两套设计系统。

### 7.2 当前复用方式

Agent 页面仍保留 `--chat-*` 语义变量，目的是让组件样式能表达“对话画布”“状态强调色”等
局部含义；但这些变量不再保存自己的颜色值，而是映射到全局 token：

```css
.agent-chat-page {
  --chat-canvas: var(--canvas);
  --chat-surface: var(--paper);
  --chat-ink: var(--ink);
  --chat-muted: var(--ink-faint);
  --chat-line: var(--line);
  --chat-accent: var(--blue);
  --chat-success: var(--jade);
  --chat-warning: var(--amber);
  --chat-danger: var(--red);
}
```

页面不再声明局部字体栈，正文直接继承全��无衬线字体；页面标题和空状态标题使用全局
`--serif`，运行元信息使用 `--mono`。用户气泡改用 `--blue-soft`，发送按钮与 focus 状态使用
绿色系 `--blue` / `--blue-dark`，等待交互和错误区域分别使用 `--amber-soft`、`--red-soft`。
边框统一来自 `--line` / `--line-strong`，控件圆角收敛到项目常见的 6–10px。

这种“全局 token + Agent 语义别名”的两层方式保留了组件可读性，也避免复制颜色常量。
以后修改全站品牌色时应优先修改 `index.css`；只有某个 Agent 状态需要新的业务语义时，才在
全局设计系统增加 token，再由 `--chat-*` 映射使用。
