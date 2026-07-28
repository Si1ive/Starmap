# 管理端与模型配置主链

## 适用场景

本分卷覆盖管理员查看 Agent 会话、进入单轮详情、维护 Agent 模型配置，以及这些配置如何进入一次真实 Run。

## 用户模型列表与运行时配置

| 执行序号 | 文件 | 符号 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/alembic/versions/20260723_agent_model_configs.py` | `upgrade` | L21-L90 | 旧数据库位于 `20260723_repair_agent_parent` | 创建 `agent_model_configs`、默认项唯一约束和索引，并回填启用的旧配置 | 模型配置表和可选默认记录 | schema guard |
| 2 | `backend/alembic/versions/20260724_agent_unlimited_tokens.py` | `upgrade` | L20-L27 | 已存在 `agent_model_configs` | 把 `max_tokens` 改成 nullable | 数据库支持“不设上限” | runtime config |
| 3 | `backend/app/modules/operations/schema_guard.py` | `verify_database_schema` | L45-L221 | 启动期 `AsyncSession`、Alembic heads 与 information_schema | 校验 revision、`agent_runs` 必需列、模型配置/记忆/偏好候选真表、Memory Outbox 失败列与唯一索引、模型列约束 | 结构正确才允许 Worker 与后端服务启动；漂移抛 `DatabaseSchemaError` | 用户模型接口 / Agent Worker |
| 4 | `backend/app/modules/agent/router.py` | `list_selectable_models` | L149-L156 | 当前用户 | 查询公开且可选的 Agent 模型配置 | `{items}` | `AgentPage.loadModels` |
| 5 | `backend/app/modules/agent/model_configs.py` | `AgentModelConfigService.list_public` | L172-L183 | `agent_model_configs` 表 | 筛选 `online=true` 且 `selectable=true`，默认项优先 | 模型列表 | 用户端选择器 |
| 6 | `backend/app/modules/agent/model_runtime/config.py` | `open_agent_model` | L168-L235 | 当前 Run ID 与 child metadata | 解析模型配置、API Key、Base URL、超时和 Token 限额，生成模型调用 ID，并把不含密钥的实际配置写回 Run metadata | 与本轮 Run 绑定的独立模型客户端及调用审计 | Router / Answer / Explain runtime |

## 管理员维护 Agent 模型配置

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| 管理端页面入口 | `frontend-admin/src/pages/AgentModelsPage.tsx` | `AgentModelsPage` | L80-L384 | 查询模型列表、创建/编辑记录、切换上下线/默认项和测试连通性 |
| 管理端 API 封装 | `frontend-admin/src/api/agentModels.ts` | `listAgentModels` 至 `testAgentModel` | L54-L90 | 请求 `/api/v1/admin/agent-models` 系列接口 |
| 后端管理入口 | `backend/app/modules/agent/model_config_router.py` | `list_agent_models` 至 `test_agent_model` | L22-L139 | 调用配置服务，返回脱敏数据或测试结果 |
| 状态不变量 | `backend/app/modules/agent/model_configs.py` | `AgentModelConfigService.create` 至 `AgentModelConfigService.get_user_selectable` | L46-L191 | 保证显示名称唯一、最多一个默认模型、默认项不可直接下线，turn 创建前二次校验是否仍可选 |
| 无限输出 Token 契约 | `frontend-admin/src/components/TokenLimitField/index.tsx` | `TokenLimitField` | L12-L80 | 用“按额度/不设上限”三态输入统一数字与 `null` |
| ORM 空值语义 | `backend/app/modules/agent/models.py` | `AgentModelConfigRecord.max_tokens` | L43-L47 | 通过 `evaluates_none()` 保持显式 `None`，避免被 Python 默认值覆盖 |

## 管理端会话列表与详情

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| 会话级列表 | `frontend-admin/src/pages/AgentRunsPage.tsx` | `AgentRunsPage` | L58-L340 | 加载 Thread 级会话列表，一行代表一个 Thread，并通过并列标签页挂载 Memory Outbox 运维入口 |
| 管理端列表 API | `frontend-admin/src/api/agentRuns.ts` | `getAgentRuns`、`getAgentRunDetail` | L248-L257 | 请求 `/api/v1/admin/agent-runs` 及详情接口 |
| 后端分页聚合 | `backend/app/modules/agent/admin_router.py` | `list_all_runs` | L291-L387 | 先分页 `AgentThread`，再批量补 Run 数、turn 数和事件数 |
| 旧链接兼容 | `backend/app/modules/agent/admin_router.py` | `_resolve_thread` | L234-L247 | 把详情路径中的历史 Run ID 转换为所属 Thread ID |
| 会话详情聚合 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L477-L542 | 一次读取 Thread 下 messages、runs、events、approvals、artifacts，并构造成 `turns[]` |
| 多轮归并 | `backend/app/modules/agent/admin_router.py` | `_build_turns` | L141-L231 | 以 root Run 为边界，把用户消息、assistant 消息、child runs 和审批/产物归到同一轮 |
| 前端多轮详情 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `TurnDetail`、`AgentRunDetailPage` | L98-L434 | 一轮一个一级 Collapse，运行链路、事件流、审批与产物分别二次折叠；运行卡同时保留评测重放并进入冻结记忆抽屉 |

## 管理员只读复现冻结记忆

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/admin_router.py` | `get_run_memory_admin`、`replay_run_memory_admin` | L449-L458 | 通过管理员认证的 Run ID | 分别进入观测聚合或只读复现服务 | 管理 JSON；错误向 HTTP 传播 | 管理端 Run 详情 |
| 2 | `backend/app/modules/agent/admin_memory.py` | `get_run_memory_observability` | L135-L257 | Run ID | 校验 Run 直接或 child metadata 绑定的 Snapshot 归属，读取 Item、实际工具事件、模型 metadata 与派生 Outbox | 冻结记忆观测 DTO；数据库只读 | 直接响应或步骤 3 |
| 3 | `backend/app/modules/agent/admin_memory.py` | `replay_run_memory_snapshot` | L260-L278 | 步骤 2 的冻结 DTO | 保持 Snapshot Item 原始顺序，组合理解、正文、丢弃原因、Token 和工具参数 | `frozen_snapshot_read_only`；不调用模型/工具 | 前端复现视图 |
| 4 | `backend/app/modules/agent/admin_router.py` | `get_run_memory_source_admin` | L461-L473 | Run ID + Item ID | 禁止直接使用裸 source ID，把回查交给绑定门 | source 对比或统一 404 | 步骤 5 |
| 5 | `backend/app/modules/agent/admin_memory.py` | `get_snapshot_item_source`、`_load_current_source` | L281-L449 | Item→Snapshot→Run 链、user/thread/version | 重验作用域和版本，分类型读取当前 source；冻结副本始终来自 Item | frozen/current/superseded；只读数据库 | 前端 source 对比 |
| 6 | `frontend-admin/src/api/agentRuns.ts` | `getAgentRunMemory`、`replayAgentRunMemory`、`getAgentRunMemorySource` | L270-L285 | Run ID 或 Run ID + Item ID | 经管理员客户端请求三个受约束入口，不提供裸 source ID 请求 | 类型化只读响应或 HTTP 错误 | 步骤 7 |
| 7 | `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx` | `RunMemoryDrawer` | L85-L420 | 步骤 6 DTO | 展示冻结理解和选择账本；管理员显式操作后才加载 source 正文或只读复现，所有正文按纯文本消费 | 无工作流、模型、工具或写库副作用 | 管理员审计结论 |

## 管理员重放 Memory Outbox

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/admin_router.py` | `list_memory_outbox_admin`、`get_memory_outbox_detail_admin` | L391-L426 | 管理员过滤条件或 Outbox ID | 调用分页筛选或详情服务 | 脱敏列表/详情；错误向 HTTP 传播 | 管理端 Outbox 页面 |
| 2 | `backend/app/modules/agent/admin_router.py` | `replay_memory_outbox_admin` | L430-L445 | Outbox ID 与当前管理员 | 提取管理员、IP、User-Agent 后进入事务服务 | 重放结果或 404/409 | 步骤 3 |
| 3 | `backend/app/modules/agent/admin_memory_outbox.py` | `replay_memory_outbox` | L149-L204 | 原 Outbox 与审计身份 | 锁原行、复核状态/租约、重置调度字段并写审计 | 同一个 Outbox 变 pending；唯一幂等键不变 | Agent Worker |
| 4 | `backend/app/modules/agent/memory_outbox.py` | `MemoryOutboxConsumer.process_claimed` | L230-L310 | Worker 再次认领的原 Outbox | 在 SAVEPOINT 内重新执行 source 归属/版本复核和 projector | complete 或带安全错误的 retry/failed | 管理列表刷新 |
| 5 | `frontend-admin/src/api/agentRuns.ts` | `getMemoryOutbox`、`getMemoryOutboxDetail`、`replayMemoryOutbox` | L287-L301 | 组合筛选、Outbox ID | 请求列表/详情；只有确认操作发送重放 POST | 脱敏 DTO 或错误 | 步骤 6 |
| 6 | `frontend-admin/src/pages/agent-observability/MemoryOutboxPanel.tsx` | `MemoryOutboxPanel` | L38-L396 | 步骤 5 DTO | 呈现失败摘要、重试次数和重放阻断原因；成功重放后刷新当前分页，失败明确提示状态可能变化 | 页面状态更新；不提供强制成功、跳过版本或直接写记忆入口 | 等待步骤 4 再消费 |

## 导航与栏目归类

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| 侧栏分组 | `frontend-admin/src/components/Sider/index.tsx` | `menuItems` | L40-L95 | 每个可切换功能页均提供语义图标；系统监控概览使用运行投影视图图标，Agent Runs/LLM/向量召回等保留各自图标，并保持原 URL |
| 路由入口 | `frontend-admin/src/router/index.tsx` | `AppRoutes` | L75-L217 | 为 `/admin/agent-runs`、详情页和 `/admin/agent-models` 提供路由 |
| Header 栏目标题 | `frontend-admin/src/components/Header/index.tsx` | `routeContexts`、`AppHeader` | L14-L70 | 根据当前路径显示系统监控或系统配置标题 |

## 下一步阅读

- 需要看管理端如何消费 Run、事件、审批与 Artifact 的聚合结果，转到 `implementation/admin-observability.md`。
- 需要看模型配置如何影响 Router/Answer/Explain 的真实调用，转到 `implementation/model-runtime-streaming.md`。
