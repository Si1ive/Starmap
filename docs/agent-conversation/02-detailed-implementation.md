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

具体手动操作见 `docs/project-common-operations-guide.md`。

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

## 5. 模型配置与运行时

当前项目存在系统配置、通用 LLM client 和 Agent `model_runtime` 等多条模型调用路径。后续
多模型功能应统一抽象为“模型配置记录 + 上线状态 + 能力用途 + 运行时解析”，避免管理员
测试连接使用一套客户端、Agent 回答又读取另一套配置。

## 6. 时间处理

数据库时间应使用统一 UTC 语义存储，API 返回带明确时区的 ISO 8601 时间，前端再根据用户
浏览器时区格式化。不能把无时区的 UTC 字符串直接交给浏览器当成本地时间，否则在上海等
UTC+8 时区会刚好相差 8 小时。

## 7. 用户端视觉系统

Agent 页面应复用用户端全局颜色、字体、间距、边框和表面层级变量，避免在
`agent-chat.css` 中形成独立主题。对话特有组件可以保留布局差异，但视觉 token 应来自全局
设计系统。
