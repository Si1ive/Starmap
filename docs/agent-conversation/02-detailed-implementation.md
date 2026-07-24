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

当前这一阶段只打通原有单个 `system_configs.llm` 配置。后台多模型记录、上线/下线和用户选择
属于后续独立演进，不能把 `model_config_source` 误当成未来真实的模型配置 ID。

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
