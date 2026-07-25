# 管理端与模型配置主链

## 适用场景

本分卷覆盖管理员查看 Agent 会话、进入单轮详情、维护 Agent 模型配置，以及这些配置如何进入一次真实 Run。

## 用户模型列表与运行时配置

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/alembic/versions/20260723_agent_model_configs.py` | `upgrade` | L21-L90 | 旧数据库位于 `20260723_repair_agent_parent` | 创建 `agent_model_configs`、默认项唯一约束和索引，并回填启用的旧配置 | 模型配置表和可选默认记录 | schema guard |
| 2 | `backend/alembic/versions/20260724_agent_unlimited_tokens.py` | `upgrade` | L20-L27 | 已存在 `agent_model_configs` | 把 `max_tokens` 改成 nullable | 数据库支持“不设上限” | runtime config |
| 3 | `backend/app/modules/operations/schema_guard.py` | `verify_database_schema` | L29-L138 | 启动期 `AsyncSession` 与 Alembic heads | 同时校验 revision、`agent_runs` 必需列和 `agent_model_configs` 真表结构 | 结构正确才允许后端启动 | 用户模型接口 |
| 4 | `backend/app/modules/agent/router.py` | `list_selectable_models` | L55-L63 | 当前用户 | 查询公开且可选的 Agent 模型配置 | `{items}` | `AgentPage.loadModels` |
| 5 | `backend/app/modules/agent/model_configs.py` | `AgentModelConfigService.list_public` | L168-L180 | `agent_model_configs` 表 | 筛选 `online=true` 且 `selectable=true`，默认项优先 | 模型列表 | 用户端选择器 |
| 6 | `backend/app/modules/agent/model_runtime/config.py` | `open_agent_model` | L157-L217 | 当前 run ID 与 child metadata | 解析模型配置、API Key、Base URL、超时和 Token 限额，并把实际使用配置写回 run metadata | 与本轮 Run 绑定的独立模型客户端 | Router / Answer / Explain runtime |

## 管理员维护 Agent 模型配置

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| 管理端页面入口 | `frontend-admin/src/pages/AgentModelsPage.tsx` | `AgentModelsPage` | L60-L377 | 查询模型列表、创建/编辑记录、切换上下线/默认项和测试连通性 |
| 管理端 API 封装 | `frontend-admin/src/api/agentModels.ts` | `listAgentModels` 等函数 | L44-L66 | 请求 `/api/v1/admin/agent-models` 系列接口 |
| 后端管理入口 | `backend/app/modules/agent/model_config_router.py` | `list_agent_models` 至 `test_agent_model` | L29-L138 | 调用配置服务，返回脱敏数据或测试结果 |
| 状态不变量 | `backend/app/modules/agent/model_configs.py` | `AgentModelConfigService.create` 至 `get_user_selectable` | L46-L186 | 保证显示名称唯一、最多一个默认模型、默认项不可直接下线，turn 创建前二次校验是否仍可选 |
| 无限输出 Token 契约 | `frontend-admin/src/components/TokenLimitField/index.tsx` | `TokenLimitField` / `switchMode` | L12-L80 | 用“按额度/不设上限”三态输入统一数字与 `null` |
| ORM 空值语义 | `backend/app/modules/agent/models.py` | `AgentModelConfigRecord.max_tokens` | L40-L44 | 通过 `evaluates_none()` 保持显式 `None`，避免被 Python 默认值覆盖 |

## 管理端会话列表与详情

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| 会话级列表 | `frontend-admin/src/pages/AgentRunsPage.tsx` | `AgentRunsPage.fetchSessions` / `AgentRunsPage` | L76-L96、L119-L193 | 加载 Thread 级会话列表，一行代表一个 Thread，并提供详情入口 |
| 管理端列表 API | `frontend-admin/src/api/agentRuns.ts` | `getAgentRuns` / `getAgentRunDetail` | L125-L135 | 请求 `/api/v1/admin/agent-runs` 及详情接口 |
| 后端分页聚合 | `backend/app/modules/agent/admin_router.py` | `list_all_runs` | L277-L374 | 先分页 `AgentThread`，再批量补 Run 数、turn 数和事件数 |
| 旧链接兼容 | `backend/app/modules/agent/admin_router.py` | `_resolve_thread` | L220-L234 | 把详情路径中的历史 run ID 转换为所属 Thread ID |
| 会话详情聚合 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L377-L443 | 一次读取 Thread 下消息、runs、events、approvals、artifacts，并构造成 `turns[]` |
| 多轮归并 | `backend/app/modules/agent/admin_router.py` | `_build_turns` | L127-L217 | 以 root run 为边界，把用户消息、assistant 消息、child runs 和审批/产物归到同一轮 |
| 前端多轮详情 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `AgentRunDetailPage`、`TurnDetail` | L251-L376、L95-L248 | 一轮一个一级 Collapse，运行链路、事件流、审批与产物分别二次折叠 |

## 导航与栏目归类

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| 侧栏分组 | `frontend-admin/src/components/Sider/index.tsx` | `menuItems`、`selectableMenuKeys`、`menuGroups`、`AppSider` | L34-L224 | 把 Agent Runs 归入系统监控，把 Agent 模型配置归入系统配置，并保持原 URL |
| 路由入口 | `frontend-admin/src/router/index.tsx` | `AppRoutes` | L187-L233 | 为 `/admin/agent-runs`、详情页和 `/admin/agent-models` 提供路由 |
| Header 栏目标题 | `frontend-admin/src/components/Header/index.tsx` | `routeContexts`、`AppHeader` | L14-L48 | 根据当前路径显示系统监控或系统配置标题 |

## 下一步阅读

- 需要看管理端如何消费 Run、事件、审批与 Artifact 的聚合结果，转到 `implementation/admin-observability.md`。
- 需要看模型配置如何影响 Router/Answer/Explain 的真实调用，转到 `implementation/model-runtime-streaming.md`。
