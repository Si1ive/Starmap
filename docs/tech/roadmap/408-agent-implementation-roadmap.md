 # 408 学习 Agent 分步实施路线图

 > 版本：v1.0
 > 日期：2026-07-22
 > 状态：实施规划，由编排设计与运行时设计整合而来
 > 上游文档：
 > - [408-agent-workflow-orchestration-design.md](../408-agent-workflow-orchestration-design.md)
 > - [408-agent-conversation-runtime-design.md](../408-agent-conversation-runtime-design.md)

 ## 0. 设计哲学：从核心开始，逐步扩展

 本路线图的出发点是**最小可用核心（MVC）**：先让一条工作流能跑通、可恢复、可观测，再逐步叠加新能力。所有设计按 P0（必须）、P1（重要但可延后）、P2（高级扩展）三层标注。

 **P0 判定标准**：没有它，Agent 无法完成一次最小闭环（用户提问 → 检索证据 → 模型生成讲解 → 用户可见）。

 **P1 判定标准**：没有它，Agent 仍可工作，但功能不完整（缺少练习、批改、计划）。

 **P2 判定标准**：锦上添花或需要额外基础设施（AI 生成题、多模态输入等）。

 ---


## 0.5 架构规划：现有代码与新模块的关系

### 0.5.1 现有代码结构分析

当前后端（`backend/app/`）结构如下：

```text
backend/app/
├── main.py                    # FastAPI 入口：路由注册、生命周期管理
├── core/                      # 配置、日志、监控
│   ├── config.py              # 系统配置（API key、数据库 URL）
│   ├── logging.py             # 结构化日志
│   └── monitoring.py          # 基础监控指标
├── db/                        # 数据库连接（复用，不改动）
│   ├── mysql.py               # SQLAlchemy async engine + session
│   ├── redis.py               # Redis 客户端（用于旧 Chat session 缓存）
│   └── qdrant.py              # Qdrant 向量库
├── models/                    # ORM 模型 + Pydantic Transaction Schema
│   ├── mysql_models.py        # 现有 CrawlTask、CrawlLog、ChatSession 等
│   └── transaction.py         # ChatRequest、ChatResponse、ChatHistory
├── infrastructure/            # 共享基础设施
│   └── ai/
│       ├── llm_client.py      # 老版 OpenAI API（openai.ChatCompletion）
│       └── embedding_service.py # 向量化服务
├── modules/                   # 业务模块
│   ├── chat/                  # 现有聊天（同步 POST，无 run/step/event）
│   │   ├── router.py          # POST /chat、GET /chat/{session_id}/history
│   │   ├── service.py         # ChatService（Redis session + 同步生成）
│   │   └── retrieval_context.py # RAG 上下文构建
│   ├── identity/              # 认证、授权（复用，不改动）
│   ├── retrieval/             # 检索引擎（dense/sparse/hybrid，可复用）
│   │   ├── service.py         # RetrievalService（async，接受 AsyncSession）
│   │   ├── search_engine.py   # 检索主逻辑
│   │   └── segment_service.py # 分片服务
│   ├── monitoring/            # LLM 调用监控（可复用）
│   │   └── llm_calls.py       # LLMCallRecorder（上下文管理器）
│   ├── corpus/                # 语料管理（与 Agent 无关，不改动）
│   ├── crawler/               # 爬虫管理（与 Agent 无关，不改动）
│   └── operations/            # 运维管理（与 Agent 无关，不改动）
```

### 0.5.2 新增功能与现有代码的关系

| 新增功能 | 依赖现有模块 | 关系说明 | 调整方式 |
|---------|-------------|---------|---------|
| **Thread 管理** | `identity`（用户认证） | 需要 `user_id` 关联 | 复用 identity 的 `get_current_user` |
| **Run 执行** | `llm_client.py`（旧版） | 当前用 `openai.ChatCompletion`（老 API），需新增 `model_runtime` | 不改动旧版，新增 Pydantic AI 封装 |
| **RAG 检索（Tool）** | `retrieval/service.py` | 已有 async `RetrievalService.search_with_outline_expansion` | 复用，包一层 Tool adapter |
| **LLM 调用记录** | `monitoring/llm_calls.py` | 已有 `LLMCallRecorder`（上下文管理器） | 复用，在 Pydantic AI adapter 中接入 |
| **数据库连接** | `db/mysql.py`、`db/redis.py` | 已有 async session manager | 直接复用，新增表共用同一 engine |
| **向量存储** | `db/qdrant.py` | 已有 `qdrant_manager` | 复用 |
| **认证中间件** | `identity/dependencies.py` | 已有 `get_current_user` | 复用 |

**结论**：**不修改任何现有模块代码**。新增模块独立开发，仅通过依赖注入调用现有服务。

### 0.5.3 数据表规划（Alembic 迁移）

新增数据表统一放在 `models/mysql_models.py` 末尾，按命名空间前缀 `agent_` 区分：

| 表名 | 用途 | 阶段 |
|------|------|------|
| `agent_threads` | 会话容器（用户级） | P0 |
| `agent_runs` | 单次执行（工作流实例） | P0 |
| `agent_steps` | 节点/步骤 | P0 |
| `agent_events` | 事件流（sequence 单调递增） | P0 |
| `agent_checkpoints` | 断点状态（崩溃恢复） | P0 |
| `agent_run_outbox` | 任务唤醒（Worker 扫描） | P0 |
| `agent_loop_turns` | Loop 决策与 observation 持久化 | P0 |
| `agent_inputs` | 等待态用户输入 | P1 |
| `agent_artifacts` | 渲染产物 | P0 |
| `agent_approvals` | 计划审批 | P1 |

**迁移策略**：新增 migration 文件（如 `alembic revision -m "add_agent_tables"`），不影响现有表。旧 `chat_sessions` 等表完全不动。

### 0.5.4 P0 代码模块划分与文件位置

```text
backend/app/
├── main.py                          # 新增注册：agent_router、workspace_router
├── models/mysql_models.py           # 新增：agent_* ORM 模型
├── models/transaction.py            # 新增：AgentRequest、AgentEvent 等 Pydantic Schema
├── infrastructure/ai/
│   ├── llm_client.py               # 不动（旧版保持运行）
│   └── model_runtime/              # 新增 P0：Pydantic AI 运行时
│       ├── __init__.py
│       ├── adapter.py              # OpenAI 提供商适配
│       ├── schema.py               # 结构化输出 Schema（action/reasoning）
│       └── recorder.py             # 复用 LLMCallRecorder 的 wrapper
├── modules/
│   ├── workspace/                   # 新增 P0：线程/产物管理
│   │   ├── __init__.py
│   │   ├── router.py               # POST /threads、GET /threads/{id}
│   │   ├── service.py              # ThreadService、ArtifactService
│   │   └── models.py               # Thread、Artifact ORM + Schema
│   └── agent/                       # 新增 P0：核心 Runtime
│       ├── __init__.py
│       ├── router.py               # POST /runs、GET /runs/{id}、SSE /runs/{id}/events
│       ├── service.py              # AgentService（业务入口，编排 run 创建）
│       ├── models.py               # Run、Step、Event、Outbox ORM + Schema
│       ├── worker.py               # Worker：租约获取 + 单节点执行循环
│       ├── state_machine.py        # 基础状态转移（queued → running → completed/failed）
│       ├── events.py               # 事件追加 + SSE 序列化
│       ├── checkpoints.py          # 断点读写（context → JSON）
│       ├── outbox.py               # Outbox 投递 + 扫描恢复
│       ├── tools/                  # P0：注册表 + retrieve_knowledge 适配器
│       │   ├── __init__.py
│       │   ├── registry.py         # Tool 注册表（name → execute func）
│       │   └── retrieve_knowledge.py # 调用 RetrievalService 的 adapter
│       ├── model_runtime/          # P0：Pydantic AI 封装
│       │   ├── __init__.py
│       │   ├── adapter.py          # OpenAI 单提供商适配（含 timeout/retry）
│       │   ├── schema.py           # Loop action Schema（Pydantic model）
│       │   └── policy_gate.py      # 白名单校验（只允许 retrieve_knowledge）
│       └── workflows/              # P0：仅 conversation + explain
│           ├── __init__.py
│           ├── contracts.py          # NodeResult、WorkflowDefinition 基类
│           ├── registry.py           # 硬编码注册（后续迁移到 DB）
│           ├── engine.py             # 单节点执行 + 状态转移
│           ├── explain.py            # explain@v1 节点和图
│           └── conversation.py       # conversation@v1 节点和图
```

### 0.5.5 关键复用策略

| 能力 | 现有代码位置 | 复用方式 |
|------|-------------|---------|
| 用户认证 | `modules/identity/dependencies.py` → `get_current_user` | 作为所有 Agent API 的 `Depends` |
| 数据库连接 | `db/mysql.py` → `mysql_client.session()` | 所有 Agent Service 注入 `AsyncSession` |
| RAG 检索 | `modules/retrieval/service.py` → `RetrievalService` | Agent Tool adapter 调用（需要 `AsyncSession`） |
| LLM 调用记录 | `modules/monitoring/llm_calls.py` → `LLMCallRecorder` | 在 `model_runtime/recorder.py` 中包装 Pydantic AI 调用 |
| 向量 Embedding | `infrastructure/ai/embedding_service.py` | RetrievalService 内部已使用，Agent 不直接调用 |
| Redis（Session） | `db/redis.py` | 旧 Chat 继续使用；Agent 不用 Redis（用 MySQL outbox） |

### 0.5.6 边界约束

1. **新旧 Chat 完全隔离**：
   - 旧 Chat API（`POST /chat`）继续使用 `chat_sessions` 表和 Redis 缓存
   - 新 Agent API（`POST /runs`）使用 `agent_threads` / `agent_runs` 表
   - 两者不共享表、不共享 Redis key
   - 最终（P2）旧 Chat 迁移由独立任务完成，不在 P0/P1 阻塞

2. **模块单向依赖**：
   - Agent 模块可以依赖 `identity`、`retrieval`、`monitoring`
   - 现有模块**不允许**依赖 `agent` 模块
   - 通过 Service 层接口而非直接 ORM 调用来交互

3. **事务边界**：
   - Agent 内部：Run 状态更新 + Event 写入 + Outbox 投递，在同一个 DB 事务内
   - 跨模块：Agent 调用 RetrievalService 时，各自管理自己的事务边界
   - 监控：LLM 调用记录与业务调用在同一 HTTP 请求内，但使用独立 session（现有 `LLMCallRecorder` 行为）

4. **模型迁移路线**：
   - P0：新增 `model_runtime/`（Pydantic AI），旧 `llm_client.py` 保持运行
   - P1：逐步将旧 Chat 中的 `ChatLLMClient` 迁移到 `model_runtime`
   - P2：完全移除 `llm_client.py`，统一走 `model_runtime`


 ## 1. P0：最小可用核心（MVP）

 ### 1.1 目标

 用户能在 Web 工作台发送一个问题，Agent 完成：意图路由 → 检索证据 → 模型生成结构化讲解 → 引用校验 → 渲染 artifact → SSE 推送。Run 可恢复、可观测、幂等。

 ### 1.2 必须有的 Runtime 基础设施

 | 模块 | 内容 | 说明 |
 |------|------|------|
 | Thread/Run/Step 模型 | `agent_threads`, `agent_runs`, `agent_steps` | 最基础的对话容器和执行单元 |
 | 事件模型 | `agent_events`（sequence 单调递增） | SSE 的事实源，断线可重放 |
 | Worker 租约 | `lease_owner` + `lease_expires_at` | 防止多 Worker 同时推进同一 run |
 | Outbox + 扫描 | `agent_run_outbox` + 定时扫描 | 任务唤醒，Redis 故障有兜底 |
 | 幂等写入 | `(user_id, client_idempotency_key)` 唯一约束 | 重复提交返回同一结果 |
 | 基础状态机 | `queued → running → completed/failed` | 先支持 3 个核心状态，等待态延后 |
 | SSE 通道 | `/runs/{run_id}/events` | 按 `Last-Event-ID` 重放 |
 | `agent_loop_turns` 完整持久化 | `parent_step_id` + `turn_no` + `decision_ref` + `action_key` + `observation_ref` | 每一轮 Loop 决策与 observation 全量可追溯，支撑崩溃恢复与调试 |
 | 基础 API | 创建 run、查询 run、提交 input | 先支持 conversation/explain 两种工作流 |

 #### 1.2.1 刻意简化的设计（P0 够用即可）

 | 原设计 | P0 简化方式 | 理由 |
 |--------|-------------|------|
 | `waiting_for_user` / `waiting_for_approval` 状态 | P0 只保留 `waiting_for_user`，`waiting_for_approval` 移到 P1 | 计划审批是 P1 功能 |
 | `agent_approvals` 表 | P0 不建 | 没有审批流程 |
 | 复杂预算体系（token/时间/turn 多维） | P0 只限制模型调用次数（如最多 6 次） | 够用即可，后续校准 |
 | 多模型提供商切换 | P0 只接入一个提供商（如 OpenAI） | 降低复杂度 |
 | 旧 Chat 迁移 | P0 完全不碰 | 新旧并行，互不干扰 |
 | Redis Stream | P0 先用 MySQL outbox + 定时扫描；Redis Stream 作为 P1 优化 | 避免引入新基础设施 |
 | shadow/canary 评测 | P0 用 pytest fixture + 人工审核 | 正式评测基础设施 P2 再建 |

 ### 1.3 必须有的工作流（Workflow）

 #### 1.3.1 `conversation@v1`（最小路由工作流）

 这是 Agent 的入口。用户发送自然语言后：

 1. 意图识别（代码规则 + 轻量模型分类）
 2. 歧义判断：如需要澄清，创建 `agent_inputs` 等待用户回答（最多 2 轮）
 3. 路由调度：直接创建 `explain` 子 run 或返回澄清问题
 4. 无领域副作用

 **节点数**：3-4 个（路由 → 意图 → [澄清] → 调度）

 #### 1.3.2 `explain@v1`（核心讲解工作流）

 这是 P0 的核心价值。流程：

 1. `load_scope`：读取用户授权的资料范围
 2. `evidence_exploration_loop`（有界 Agent Loop）：
    - 白名单只读工具：`retrieve_knowledge`（RAG 检索）
    - 最多 3 轮决策
    - 固定出口：`finish`（证据充分）或 `need_scope`（需要用户补充范围）
 3. `evidence_gate`：校验引用是否真实、可见、无冲突
 4. `generate_explanation`：模型生成结构化讲解（提纲 + 正文 + 引用）
 5. `citation_gate`：再次校验讲解中的引用
 6. `render_artifact`：生成最终展示产物
 7. `completed`

 **节点数**：7-8 个

 **预算**：最多 6 次模型调用（含 Loop 内 3 轮 + 讲解生成 + 可能的修复）

 ### 1.4 P0 质量闸门（最小集合）

 | 闸门 | 用途 | 默认行为 |
 |------|------|----------|
 | `resource_gate` | 校验用户是否有权访问某资料 | 越权直接阻断 |
 | `schema_gate` | 模型输出是否符合结构化 Schema | 解析失败可尝试修复 1 次 |
 | `evidence_gate` | 引用是否真实、可见、无冲突 | 无支持时降级 |
 | `render_gate` | artifact 是否含敏感字段 | 移除隐藏内容 |

 ### 1.5 P0 Agent Loop 约束

 - 白名单只读工具：仅 `retrieve_knowledge`
 - 不允许：写入、创建等待、调用未登记工具、超过最大轮次
 - 出口：只有 `finish` 和 `need_scope`（后者创建 `agent_inputs`）
 - 每轮 decision 必须结构化（Pydantic Schema），包含 `action` 和 `reasoning`

 ### 1.6 P0 目录结构

 ```text
 backend/app/modules/
   workspace/              # P0: thread, message, artifact
   agent/
     models.py             # P0: thread, run, step, event, outbox
     router.py             # P0: 创建/查询 run, SSE events
     service.py            # P0: 业务逻辑入口
     worker.py             # P0: 租约获取 + 单节点执行
     state_machine.py      # P0: 基础状态转移
     events.py             # P0: 事件追加 + SSE 序列化
     checkpoints.py        # P0: checkpoint 读写
     outbox.py             # P0: outbox 投递 + 扫描恢复
     tools/                # P0: 注册表 + retrieve_knowledge 适配器
     model_runtime/        # P0: Pydantic AI 封装 + OpenAI 适配
       __init__.py
       adapter.py          # P0: 单提供商适配
       schema.py           # P0: 结构化输出 Schema
       policy_gate.py      # P0: Loop action 白名单校验
     workflows/            # P0: 仅 conversation + explain
       contracts.py        # P0: NodeResult, WorkflowDefinition 基类
       registry.py         # P0: 硬编码注册（后续再迁移到 DB）
       engine.py           # P0: 单节点执行 + 状态转移
       explain.py          # P0: explain@v1 节点和图
       conversation.py     # P0: conversation@v1 节点和图
   ```

 ### 1.7 P0 测试与发布

 - 单元测试：状态转移、幂等、事件序列、引用校验
 - 集成测试：Worker 崩溃恢复（租约过期后接管）、SSE 断线重放
 - 端到端测试：从用户提问到 artifact 渲染的完整链路
 - 安全：资源 IDOR、Prompt injection 不触发工具、用户资料隔离
 - 回归集：E01（循环队列讲解）、E05（证据不足降级）、E09（澄清 → 路由）

 ---

 ## 2. P1：核心学习闭环（重要但可延后）

 ### 2.1 目标

 在 P0 基础上增加练习创建、批改反馈和学习计划。用户能完成：用题验证 → 创建练习 → 提交答案 → 获取反馈 → 查看学习建议。

 ### 2.2 新增 Runtime 能力

 | 模块 | 内容 |
 |------|------|
 | `agent_inputs` 多轮等待 | 结构化澄清、范围选择（conversation 中已部分支持，这里扩展为通用能力） |
 | `agent_approvals` 表 | 计划 diff 审批（plan 工作流需要） |
 | `waiting_for_approval` 状态 | 计划审批等待 |
 | 完整预算体系 | token/时间/turn 多维限制 + 预算耗尽处理 |
 | Redis Stream | 替换 MySQL 轮询，降低延迟 |
 | 多模型提供商切换 | OpenAI → Anthropic 等 |

 ### 2.3 新增工作流

 #### 2.3.1 `validate@v1`（用题验证工作流）

 1. `load_learning_evidence`：读取用户学习证据
 2. `question_discovery_loop`：检索候选题
 3. `question_gate`：资格校验（题型、难度、来源、重复度）
 4. `set_composition_gate`：题目组合校验
 5. `practice.create_draft`：创建练习草稿（**唯一副作用**）
 6. `render_practice_artifact`：渲染练习产物
 7. `completed`

 **注意**：P1 只使用平台已有题目，**不接入 AI 生成题**（移至 P2）。

 #### 2.3.2 `grade@v1`（批改反馈工作流）

 1. `load_attempt_snapshot`：读取固化题面和作答
 2. `objective_grade_or_skip`：客观题确定性判定（代码完成）
 3. `resolve_rubric_gate`：rubric 校验
 4. `generate_subjective_feedback`：主观反馈生成
 5. `feedback_support_gate`：反馈证据校验
 6. `create_feedback_artifact`：渲染反馈产物
 7. `completed`

 #### 2.3.3 `plan@v1`（学习计划工作流，简化版）

 1. `aggregate_learning_evidence`：聚合学习证据
 2. `planning_precondition_gate`：前置条件校验
 3. `propose_plan_delta`：生成计划变更草案
 4. `plan_quality_gate`：质量校验
 5. `create_approval`：创建审批请求
 6. `wait_for_approval`：等待用户审批
 7. `apply_plan_change`（审批通过后）：应用变更
 8. `render_plan_result`：渲染结果
 9. `completed`

 **P1 简化**：P1 版本的 plan 不实现复杂约束求解器，先用可配置规则模板。

 ### 2.4 新增质量闸门

 | 闸门 | 用途 |
 |------|------|
 | `question_gate` | 题目资格校验 |
 | `feedback_gate` | 反馈证据校验 |
 | `constraint_gate` | 计划约束校验（简化版） |

 ### 2.5 P1 评测扩展

 - 回归集增加：E02-E08（题型判定、长题干、证据冲突、计划审批等）
 - 增加 shadow/canary 发布基础设施（`evals` 模块）
 - 增加在线指标收集

 ---

 ## 3. P2：高级扩展与 PoC

 ### 3.1 目标

 在稳定的核心之上，验证新技术、扩展新能力。

 ### 3.2 新增能力

 | 能力 | 说明 |
 |------|------|
 | AI 生成题 | 独立验证器、生成/验证循环、题目质量闸 |
 | 计划约束求解器 | 复杂日程优化、冲突检测 |
 | MCP adapter | 外部工具接入 |
 | 多模态输入 | 图片、文件等非文本输入 |
 | 完整 evals 模块 | shadow run、canary、人工标注闭环 |
 | 旧 Chat 迁移 | 数据保留、接口下线 |

 ### 3.3 新增评测

 - E09-E19（Loop policy 注入、恢复、越权等高级场景）
 - 完整轨迹评分（`expected_trace`）
 - 固定回归集自动化

 ---

 ## 4. 已移除或大幅简化的设计

 | 原设计 | 处理方式 | 理由 |
 |--------|----------|------|
 | `agent_approvals` 表在 P0 | **移除**，P1 再引入 | P0 无审批需求 |
 | AI 生成题（`generate_ai_candidates`） | **移除出 P0/P1**，移至 P2 | 复杂度高，且有独立验证器、质量闸门等依赖 |
 | Temporal/LangGraph | **移除出 P0/P1**，P2 作为 PoC | 不是核心功能，且需要额外基础设施 |
 | 完整多维预算 | **简化为**调用次数限制 | P0 够用即可 |
 | shadow/canary 发布 | **简化为** pytest + 人工审核 | 正式评测基础设施 P2 再建 |
 | 多模型提供商切换 | **简化为**单提供商 | P0 降低复杂度 |
 | Redis Stream | **移除出 P0**，P1 引入 | P0 用 MySQL polling 兜底 |
 | 旧 Chat 迁移 | **移除出 P0**，P1/P2 再评估 | 不阻塞新功能 |
 | 多模态输入 | **移除出 P0/P1** | 首发只支持文本 |
 | `plan` 复杂约束求解器 | **简化为**可配置规则模板 | P1 够用即可 |
 | MCP server | **移除** | 首发不开放 |

 ---

 

## 4.5 前端实施步骤

### 4.5.1 用户前端（frontend）实施步骤（已完成）

| 步骤 | 文件 | 任务 | 说明 | 状态 |
|------|------|------|------|------|
| 1 | `frontend/src/api/agent.ts` | 创建 API 客户端 | 封装 thread/run/event/artifact/approval 的 CRUD 和 SSE 连接；使用原生 `fetch` + `credentials: 'include'` 的 Cookie 认证。 | ✅ 已完成 |
| 2 | `frontend/src/store/agent-context.tsx` | 创建状态管理 | React Context + useReducer；管理 threads、runs、events、artifacts、approvals、SSE 连接状态。 | ✅ 已完成 |
| 3 | `frontend/src/store/agent-context.tsx` | 实现 SSE 连接管理 | `connectSSE(runId, afterSequence?)` 创建 EventSource；`disconnectSSE()` 关闭连接；`onmessage` 解析 JSON 并 dispatch APPEND_EVENTS；自动重连。 | ✅ 已完成 |
| 4 | `frontend/src/pages/AgentPage.tsx` | 实现 Agent 对话页面 | 三栏布局：线程列表(AppShell侧边栏)/对话区/执行轨迹+证据面板；支持新建线程、发送消息、SSE 实时推送、审批 diff 渲染、工作流自动路由。 | ✅ 已完成 |
| 5 | `frontend/src/App.tsx` | 注册路由 | 添加 `/agent` 和 `/agent/:threadId` 路由，映射到 `AgentPage`。 | ✅ 已完成 |
| 6 | `frontend/src/main.tsx` | 包裹 AgentProvider | 在 `AuthProvider` 内包裹 `AgentProvider`，确保 `useAgent()` 可用。 | ✅ 已完成 |
| 7 | - | 联调验证 | 验证 thread 创建、run 创建、SSE 事件流、事件重放、断线重连等完整链路。 | ✅ 已完成 |

> **补充实施项**：
> - 提交按钮 loading 状态与 disabled 绑定，防止重复提交
> - 错误提示横幅：API 失败时自动展示，5 秒后自动清除
> - 工作流自动路由：`detectWorkflow` 根据用户输入关键词自动匹配 explain/validate/grade/plan

### 4.5.2 管理员前端（frontend-admin）实施步骤（已完成）

| 步骤 | 文件 | 任务 | 说明 | 状态 |
|------|------|------|------|------|
| 1 | `frontend-admin/src/api/agentRuns.ts` | 创建 API 客户端 | 封装 `/api/v1/admin/agent-runs/*` 接口：分页查询、详情、事件回放、重放、统计、产物、审批。 | ✅ 已完成 |
| 2 | `frontend-admin/src/pages/AgentRunsPage.tsx` | 实现监控页面 | 统计卡片、筛选栏、运行列表；支持状态/工作流/用户/时间筛选。 | ✅ 已完成 |
| 3 | `frontend-admin/src/router/index.tsx` | 注册路由 | 添加 `/admin/agent-runs` 和 `/admin/agent-runs/:id` 路由。 | ✅ 已完成 |
| 4 | `frontend-admin/src/components/Sider/index.tsx` | 添加导航菜单 | 在左侧菜单添加 "Agent Runs 监控" 入口，图标使用 `ThunderboltOutlined`。 | ✅ 已完成 |
| 5 | - | 联调验证 | 验证列表查询、筛选、详情跳转、重放操作、统计接口等完整链路。 | ✅ 已完成 |

> **补充实施项**：
> - `AgentRunDetailPage.tsx` 事件类型过滤：支持按 `step.started`/`completed`/`failed`/`message.completed`/`run.status_changed`/`error` 等类型筛选
> - `AgentRunDetailPage.tsx` 产物查看：新增产物卡片，按类型展示结构化 JSON
> - 审批操作卡片：支持 approve/reject，操作后自动刷新审批列表和运行状态
> - 统计接口补全 `waiting_for_approval` 状态计数，前端统计卡片同步展示
## 5. 实施时间表（参考）

 | 阶段 | 周期（估算） | 产出 |
 |------|-------------|------|
 | P0 | 4-6 周 | conversation + explain 可用，SSE 可推，Worker 可恢复 |
 | P1 | 4-6 周 | validate + grade + plan（简化版）可用，完整学习闭环 |
 | P2 | 按需 | AI 生成题、多模态输入等 |

 **关键里程碑**：
 - **W2**：Runtime 骨架（thread/run/event/SSE）可用
 - **W4**：`conversation@v1` 路由可用
 - **W6**：`explain@v1` 完整链路可用（含 Loop + 引用 + artifact）
 - **W8**：P0 回归集全部通过
 - **W10**：P1 开始（validate）

 ---

 ## 6. 风险评估

 | 风险 | 影响 | 缓解 |
 |------|------|------|
 | P0 过度设计 | 延迟上线 | 严格执行 P0 边界，非 P0 功能一律延后 |
 | 模型调用不稳定 | P0 讲解质量波动 | 先接入一个稳定提供商，加 timeout + 重试 |
 | Worker 崩溃恢复 | 任务丢失 | 租约机制 + outbox 扫描，内测时注入故障验证 |
 | 引用不准确 | 用户信任度下降 | P0 证据闸门 + 诚实降级，不捏造引用 |
 | 旧 Chat 与新 Agent 并行 | 数据不一致 | 完全隔离，旧接口不读新表，新接口不读旧 Redis session |

 ---

 ## 7. 附录：与上游文档的对照

 | 本文优先级 | 编排设计章节 | 运行时设计章节 | 处理说明 |
 |-----------|-------------|---------------|----------|
 | P0 | §3.1 首发范围（conversation, explain） | §5 核心数据模型 | 全部采纳 |
 | P0 | §4 编排架构（简化） | §6 状态机（核心状态） | 采纳， waiting/approval 简化 |
 | P0 | §7 Loop 设计（有界、白名单） | §10.4 Loop turn 提交 | 采纳，turn 持久化简化 |
 | P0 | §11.1 闸门（resource, schema, evidence, render） | - | 采纳 |
 | P1 | §8 validate, §9 grade, §10 plan | §5.6 领域表 | 采纳，移至 P1 |
 | P1 | §12 预算/并发/重试（完整） | - | 简化后采纳 |
 | P2 | §14 Phase W3 | §14 Phase 2 及以后 | 采纳，移至 P2 |
 | 移除 | AI 生成题（§8.3） | - | P2 再评估 |
 | 移除 | MCP server | §15 未决项 #7 | 暂不实现 |
 | 移除 | shadow/canary（完整） | §13.4 | P0 简化，P2 完整实现 |

 ---

 *本路线图是活的文档。每完成一个阶段后，应根据实际运行数据调整下一阶段优先级。*
