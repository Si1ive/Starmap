# MEM-008：管理端记忆可观测性与安全

## 状态与范围

状态：已完成。Run/Snapshot/source 只读观测与复现、Memory Outbox 运维 API 和管理端界面均已闭环。
本分卷冻结管理员 Agent Runs 对分层记忆的观测、复现和运维验收面。用户端时间线和
公开 SSE 不暴露记忆正文；管理端读取也必须经过现有管理员权限和数据作用域校验。

## Run 详情

每个 Run 至少展示以下只读信息：

| 区域 | 必须展示 | 数据来源与限制 |
| --- | --- | --- |
| 当前轮理解 | 原始输入、独立请求、主题及来源、结构化引用、约束 | 来自 Run metadata 与绑定 Snapshot；不得重新调用模型推导 |
| Snapshot | ID、版本/状态版本、创建时间、MemoryNeed | 必须校验 Run、user、thread 归属 |
| 记忆选择 | selected/dropped、partition、source kind/ID/version、选择或丢弃原因、token estimate | 默认安全摘要；正文按显式 source 回查单独加载 |
| 模型与工具 | 最终模型调用 ID、最终检索 query、entity type、difficulty、chapter、exclude IDs 与安全过滤参数 | 使用实际调用事件，不使用计划值；隐藏 API key、Authorization 与供应商 secret |
| 派生任务 | Memory Outbox 类型、状态、retry count、scheduled/processed 时间、最后安全错误 | 不向普通用户 SSE 投影 |

## Source ID 回查

管理员从 Snapshot Item 的 source kind/ID/version 回查时，服务端必须重新校验管理员权限以及 source 的
user/thread 作用域；不存在、已删除、版本不符和越权使用不可区分的安全 404。响应区分“冻结副本”和
“当前 source”，便于判断 source 是否已 supersede，但不得把当前新正文冒充为旧 Run 实际消费内容。

当前实现通过 `backend/app/modules/agent/admin_router.py::get_run_memory_source_admin`（L395-L408）只接收
Run ID 与 Snapshot Item ID，不开放裸 source ID；`backend/app/modules/agent/admin_memory.py::get_snapshot_item_source`
（L281-L328）和 `_load_current_source`（L331-L449）复核 Item→Snapshot→Run、user/thread 与版本。冻结正文来自
Item，当前 source 只作对照；缺失、越权或版本漂移统一返回 404。

## Snapshot 复现

复现是只读解释，不重新运行 workflow 或工具。输入为 Run ID，输出按当时顺序重组：TurnUnderstanding、
选中 Snapshot Items 的冻结副本、丢弃原因、Token 预算与实际工具参数。即使当前摘要、偏好或向量已更新/
删除，只要审计保留策略允许，旧 Snapshot 仍展示冻结副本；若正文依法清除，则明确显示 tombstone，不能
回退到当前 source。

当前实现由 `backend/app/modules/agent/admin_memory.py::get_run_memory_observability`（L135-L257）聚合冻结项、
真实工具事件与调用审计，再由 `replay_run_memory_snapshot`（L260-L278）按 Item ID 顺序只读重组；没有模型、
工具或数据库写副作用。生产模型会话由 `backend/app/modules/agent/model_runtime/config.py::open_agent_model`
（L168-L235）生成 `model_call_*` 审计 ID，因而响应可定位最后一次真实模型调用。

## Memory Outbox 运维

- 列表支持按 event type、status、run/thread/source ID 和时间过滤，失败项显示安全错误与重试次数。
- 重放只能作用于允许重放的 failed/pending 项，使用原幂等键，不克隆新任务；processing 且租约未过期
  的任务不可重放。
- 重放接口必须记录管理员、时间和目标 Outbox ID；消费者仍执行 user/thread/source version 归属复核。
- UI/API 都不得提供跳过版本校验、强制标成功或直接写 derived memory 的旁路。

当前实现由 `backend/app/modules/agent/admin_memory_outbox.py::list_memory_outbox`（L59-L132）完成组合筛选，
`get_memory_outbox_detail`（L135-L146）返回脱敏载荷和失败摘要，`replay_memory_outbox`（L149-L204）锁定原行、
保留 Run/type 或 task key 幂等身份并追加管理员审计。`backend/app/modules/agent/memory_outbox.py::MemoryOutboxStore.fail`
（L160-L195）持久化安全错误；completed 与有效 processing 租约不能重放，过期 processing 可恢复后仍由消费者
执行原有的 user/thread/source version 复核。

## 安全与验收

1. 普通用户无法访问任何管理端记忆接口；管理员也不能通过任意 source ID 绕过用户/线程作用域。
2. API key、Authorization header、模型供应商 secret、数据库 DSN 和原始异常堆栈不进入响应。
3. 记忆正文按不可信数据展示，前端使用文本渲染，不执行 HTML/Markdown 中的指令、链接脚本或事件属性。
4. 公共 SSE 契约回归证明 Snapshot Item body、摘要正文、候选正文和 Outbox error 均不会泄露。
5. API、服务、前端和端到端测试覆盖 Run 详情、source 404、Snapshot 复现、Outbox 失败筛选与幂等重放。

管理端由 `frontend-admin/src/pages/AgentRunDetailPage.tsx::AgentRunDetailPage`（L386-L514）从会话工具栏唯一入口进入
`frontend-admin/src/pages/agent-observability/RunMemoryDrawer.tsx::RunMemoryDrawer`（L95-L179）；
`TurnMemoryChange`（L39-L93）只把按轮连续比较后的记忆 before/after 交给
`frontend-admin/src/pages/agent-observability/PlainDataBlock.tsx::PlainDataBlock`（L7-L15）纯文本节点。
`frontend-admin/src/pages/AgentRunsPage.tsx::AgentRunsPage`（L56-L306）不再挂载 Memory Outbox 标签页，Run 卡也不再提供
上下文记忆或回放按钮；步骤入参、输出与工具证据仍在详情流程图中按需展开。
