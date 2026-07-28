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
| 会话级列表 | `frontend-admin/src/pages/AgentRunsPage.tsx` | `AgentRunsPage` | L56-L306 | 加载 Thread 级会话列表，一行代表一个 Thread；保留原统计、筛选和分页结构，不再建立 Memory Outbox 子页 |
| 管理端列表 API | `frontend-admin/src/api/agentRuns.ts` | `getAgentRuns`、`getAgentRunDetail` | L248-L257 | 请求 `/api/v1/admin/agent-runs` 及详情接口 |
| 后端分页聚合 | `backend/app/modules/agent/admin_router.py` | `list_all_runs` | L291-L387 | 先分页 `AgentThread`，再批量补 Run 数、turn 数和事件数 |
| 旧链接兼容 | `backend/app/modules/agent/admin_router.py` | `_resolve_thread` | L234-L247 | 把详情路径中的历史 Run ID 转换为所属 Thread ID |
| 会话详情聚合 | `backend/app/modules/agent/admin_router.py` | `get_run_detail` | L477-L542 | 一次读取 Thread 下 messages、runs、events、approvals、artifacts，并构造成 `turns[]` |
| 多轮归并 | `backend/app/modules/agent/admin_router.py` | `_build_turns` | L141-L231 | 以 root Run 为边界，把用户消息、assistant 消息、child runs 和审批/产物归到同一轮 |
| 前端多轮详情 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `buildFlowSteps`、`StepNode`、`RunLane`、`TurnFlow`、`AgentRunDetailPage` | L116-L176、L192-L257、L260-L304、L306-L384、L386-L514 | 一轮一个一级 Collapse；内部从用户输入开始，用纵向流程图串联根 Run、child Run 和全部步骤。每个节点就地展示状态、降级原因，并可展开输入、输出和工具事件；Run 卡不再提供记忆或回放按钮，会话工具栏提供唯一记忆入口 |

## 管理员查看会话上下文记忆变化

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `frontend-admin/src/pages/AgentRunDetailPage.tsx` | `AgentRunDetailPage` | L386-L514 | 已加载的 Thread 会话详情 | 会话工具栏以 Thread ID 打开唯一上下文记忆入口；根 Run 和 child Run 不再分别触发抽屉，也不提供回放 | `threadId` 与抽屉打开状态；无后端副作用 | 步骤 2 |
| 2 | `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx` | `RunMemoryDrawer` | L95-L179 | Thread ID | 调用 `getConversationMemory`；加载失败显示安全提示，成功后按轮次建立纵向时间线 | 会话记忆请求或空态 | 步骤 3 |
| 3 | `frontend-admin/src/api/agentRuns.ts` | `getConversationMemory` | L328-L332 | Thread ID | 经管理员客户端请求 `/agent-runs/threads/{thread_id}/memory` | 类型化只读响应或 HTTP 错误 | 步骤 4 |
| 4 | `backend/app/modules/agent/admin_router.py` | `get_conversation_memory_admin` | L455-L462 | 通过管理员认证的 Thread ID | 把请求交给会话记忆聚合服务 | `data` 或 404；不运行 workflow | 步骤 5 |
| 5 | `backend/app/modules/agent/admin_memory.py` | `get_conversation_memory_observability` | L361-L446 | Thread、同线程 root/child Run 与全部 `AgentMemoryTrace` | 按 root Run 建轮次并归并 child Trace；第一轮从空基线建立状态，后续轮次以前一轮最终状态连续比较当前轮最终状态 | 每轮 before/after、变化域和变化轮数；只读数据库 | 步骤 6 |
| 6 | `frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx` | `TurnMemoryChange` | L39-L93 | 步骤 5 DTO | 只展示线程热状态、Snapshot、可信事实、长期项、掌握度和摘要的轮次前后对照；步骤参数仍在详情流程图消费 | 脱敏纯文本差异；无模型、工具、回放或写库副作用 | 管理员定位变化轮次和记忆域 |

## Memory Outbox 后端运维能力

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/modules/agent/admin_router.py` | `list_memory_outbox_admin`、`get_memory_outbox_detail_admin` | L392-L427 | 管理员过滤条件或 Outbox ID | 调用分页筛选或详情服务 | 脱敏列表/详情；错误向 HTTP 传播 | 受权运维客户端 |
| 2 | `backend/app/modules/agent/admin_router.py` | `replay_memory_outbox_admin` | L431-L447 | Outbox ID 与当前管理员 | 提取管理员、IP、User-Agent 后进入事务服务 | 重放结果或 404/409 | 步骤 3 |
| 3 | `backend/app/modules/agent/admin_memory_outbox.py` | `replay_memory_outbox` | L149-L204 | 原 Outbox 与审计身份 | 锁原行、复核状态/租约、重置调度字段并写审计 | 同一个 Outbox 变 pending；唯一幂等键不变 | Agent Worker |
| 4 | `backend/app/modules/agent/memory_outbox.py` | `MemoryOutboxConsumer.process_claimed` | L230-L310 | Worker 再次认领的原 Outbox | 在 SAVEPOINT 内重新执行 source 归属/版本复核和 projector | complete 或带安全错误的 retry/failed | 管理列表刷新 |
| 5 | `frontend-admin/src/api/agentRuns.ts` | `getMemoryOutbox`、`getMemoryOutboxDetail`、`replayMemoryOutbox` | L345-L359 | 组合筛选、Outbox ID | 保留受约束管理 API 封装，但 Agent Runs 页面不再挂载任务列表或重放控件 | 脱敏 DTO 或错误 | 专用运维工具按需调用；不进入默认页面主链 |

## 导航与栏目归类

| 执行阶段 | 文件 | 符号 | 代码范围 | 职责 |
| --- | --- | --- | --- | --- |
| 侧栏分组 | `frontend-admin/src/components/Sider/index.tsx` | `menuItems` | L40-L95 | 每个可切换功能页均提供语义图标；系统监控概览使用运行投影视图图标，Agent Runs/LLM/向量召回等保留各自图标，并保持原 URL |
| 路由入口 | `frontend-admin/src/router/index.tsx` | `AppRoutes` | L75-L217 | 为 `/admin/agent-runs`、详情页和 `/admin/agent-models` 提供路由 |
| Header 栏目标题 | `frontend-admin/src/components/Header/index.tsx` | `routeContexts`、`AppHeader` | L14-L70 | 根据当前路径显示系统监控或系统配置标题 |

## 下一步阅读

- 需要看管理端如何消费 Run、事件、审批与 Artifact 的聚合结果，转到 `implementation/admin-observability.md`。
- 需要看模型配置如何影响 Router/Answer/Explain 的真实调用，转到 `implementation/model-runtime-streaming.md`。
