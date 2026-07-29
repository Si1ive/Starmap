# 模型运行时、Token 与流式输出

## 适用场景

本分卷解释 Router、普通回答、Explain 与历史摘要模型调用的运行时契约，重点覆盖模型配置、输出 Token 语义、
结构化流式正文、异步压缩和 child run 如何继承本轮模型选择。

## Pydantic AI 实际请求审计

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 审计模型请求 | `backend/app/modules/agent/model_runtime/config.py` | `_audit_model_messages`、`_audit_model_response`、`AuditedOpenAIChatModel.request`、`AuditedOpenAIChatModel.request_stream` | L68-L144 | Pydantic AI `ModelMessage`、模型设置、结构化参数或流式请求 | 每次真实 model request 创建记录器；非流式记录归一化响应，流式消费结束后通过 `stream.get()` 取得完整正文和最终单次 usage。结构化校验触发重试时会再次经过该边界 | 每个真实 request 一条 `llm_call_logs`，含请求/响应、Token、耗时、错误、Run、Trace；记录失败不改变模型异常传播 | Router/指代/Explain/回答/摘要/偏好运行时 |
| 打开审计会话 | `backend/app/modules/agent/model_runtime/config.py` | `open_agent_model` | L251-L327 | Run ID、用途与最终模型配置 | 生成 `model_call_*` Trace，构造审计模型，把无密钥配置和用途追加到 Run metadata；finally 关闭隔离客户端 | `AgentModelSession`；LLM 日志用同一 Trace 关联实际 request | 各 Pydantic AI Agent |
| 归一化日志写入 | `backend/app/modules/monitoring/llm_calls.py` | `LLMCallRecorder.record_pydantic_response`、`LLMCallRecorder.persist` | L205-L270 | 响应正文、`RequestUsage` 和安全 JSON 副本 | 映射 input/output/total Token、成本、耗时和完整响应；独立 session 提交，异常自动记录 error/timeout 且原异常继续传播 | `llm_call_logs` | 管理端 LLM 调用详情 |

## 模型配置进入一次 Run

| 执行阶段 | 文件 | 符号 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 用户提交模型选择 | `frontend/src/pages/AgentPage.tsx` | `AgentPage.handleSend` | 用户发送一轮对话 | 把 `selectedModelId` 交给 context store；新建 thread 前后都保留用户选择 | `TurnCreateRequest.model_config_id` |
| 提交 turn | `frontend/src/store/agent-context.tsx` | `AgentProvider.sendTurn` | thread、内容、`modelConfigId` | 生成 `client_message_id` 并把模型配置 ID 传给后端 | `createTurn` |
| Root Run 落库 | `backend/app/modules/agent/timeline.py` | `AgentTimelineService.create_turn` | 用户消息和 `model_config_id` | 在创建 root run 时写入所选模型配置 ID | run 级配置事实 |
| Child 继承模型与教学策略 | `backend/app/modules/agent/workflows/conversation.py` | `_child_context_metadata`（L275-L323） | 父 run 的 `model_config_id`、FrozenTeachingPolicy | 只复制模型配置 ID、策略版本和 teaching_mode/目标/诊断/只读意图到 child metadata；不复制函数或密钥 | child run 后续使用同一模型配置和教学策略 |
| 打开实际模型 | `backend/app/modules/agent/model_runtime/config.py` | `open_agent_model` | run ID | 从 run 或 child metadata 读取配置，创建独立 `AsyncOpenAI` 客户端，并写回运行时审计元数据 | Router/Answer/Explain/Summary runtime |

## 开放回答 Assessor 与生成题可信度

开放题的模型调用只负责受冻结 rubric 约束的结构化评价。证据 ID、partial credit、证据强度和
掌握度仍由 Grade、EvidenceWeightPolicy 与 MasteryProjector 计算；模型输出携带
`mastery`/`delta` 等额外字段会在 Pydantic 边界被拒绝。Validate 生成题则记录题目生成模型版本和
标准答案可信度，后续证据策略会再次降权。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Rubric 冻结 | `backend/app/modules/agent/model_runtime/assessor.py` | `OpenAnswerRubricCriterion`、`OpenAnswerRubric`、`CriterionScore`、`OpenAnswerAssessment`、`OpenAnswerAssessorDeps` | L33-L118 | 服务端题面标准答案/解析、答案来源、Run/User/Question ID | `extra=forbid`；criterion ID 唯一、权重总和为 1；Assessment 只允许四种 verdict、criterion scores、错误标签和 confidence，不提供掌握度字段 | 受控 Assessor 输入/输出契约；无数据库副作用 | `OpenAnswerAssessorRuntime.assess` |
| Assessor 调用与归一化 | `backend/app/modules/agent/model_runtime/assessor.py` | `normalize_open_answer_assessment`、`OpenAnswerAssessorRuntime.assess` | L172-L210、L219-L283 | 冻结题面、rubric、用户回答、知识点 ID、提示级别、答案暴露状态、Run 模型配置 | 通过 Pydantic AI 结构化调用并限制最多两次请求；服务端重写 evidence ID，校验 rubric 完整性/criterion 覆盖/最低置信度，低置信度、不完整或模型异常收敛为 `ungradable`；实际请求写统一 LLM 审计 | `OpenAnswerAssessment`；模型错误向 Grade 节点收敛为安全反馈，不写 mastery | `grade._open_answer_assessment_node` |
| 生成题可信度 | `backend/app/modules/agent/model_runtime/schema.py`、`backend/app/modules/agent/model_runtime/practice.py` | `GeneratedPracticeQuestion`、`PracticeGenerationRuntime.generate`、`_model_version` | schema L207-L230；practice L41-L77、L93-L99 | 冻结主题/难度、Run 模型配置 | 结构化生成题保留 `model_version` 和 `answer_confidence`；运行时在模型没有返回版本时用绑定配置补齐；答案仍由 schema 校验必须属于选项 | Validate 私有题目元数据中的生成模型/答案可信度；后续 EvidenceWeightPolicy 进行独立降权 | Validate Practice Session / Grade |

## Token 与请求保护语义

| 执行阶段 | 文件 | 符号 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 历史选择预算 | `backend/app/modules/agent/workflows/conversation.py` | `_route_node` | conversation run 开始路由 | `token_budget=4096` 只用于筛历史消息，不限制模型最终生成长度 | `AgentRunContext` 与 `RouterDeps` |
| Conversation 总调用预算 | `backend/app/modules/agent/workflows/conversation.py`（L312-L335） | `build_conversation_workflow` | conversation workflow 注册 | `max_model_calls=3`，容纳可选指代消解 + Router + direct answer；摘要选择不调用模型，无歧义时不消费指代调用 | `ExecutionContext.charge_model_call` |
| 指代请求保护 | `backend/app/modules/agent/model_runtime/referent.py`（L73-L169） | `ReferentRuntime.resolve`、`ReferentRuntime._run` | 确定性指代未解且存在语义候选 | 使用 `UsageLimits(request_limit=2)`；非法候选键报错，低置信度降级 unresolved | `TurnUnderstanding.reference_resolution` |
| Router/Tutor 请求保护 | `backend/app/modules/agent/model_runtime/router.py` | `_EXPLICIT_WORKFLOW_PATTERNS`、`_explicit_workflow_action`、`ConversationTutorRuntime.decide`、`ConversationTutorRuntime._run`（L86-L124、L233-L320、L323-L338） | ConversationTutorAgent 调用 | 使用 `UsageLimits(request_limit=2)` 防止单次决策无限重试；明确“再出/重新出上一题”在模型误判为 direct 时仍由确定性护栏纠正为 Validate，教学策略、目标 ID 和只读意图随后做范围校验 | 结构化 `ConversationDecision`（旧 `RouterDecision` 兼容） |
| 普通回答请求保护 | `backend/app/modules/agent/model_runtime/answer.py` | `DirectAnswerRuntime._run_stream` / `_run` | 普通回答流式或非流式调用 | 只限制请求次数；输出上限由模型配置的 `max_tokens` 决定 | 流式 delta 或完整回答 |
| Explain 请求保护 | `backend/app/modules/agent/model_runtime/explanation.py` | `ExplanationRuntime._run_decision` / `_run_generation` | explain 规划或正文生成 | 只限制请求次数，不把项目内部 Token 预算误作总输出上限 | `LoopDecision` / `ExplanationOutput` |
| 摘要请求保护 | `backend/app/modules/agent/model_runtime/conversation_summary.py`（L59-L133） | `ConversationSummaryRuntime.summarize`、`ConversationSummaryRuntime._run` | Outbox 选出旧摘要和一批新增消息 | 使用触发 Run 绑定模型配置与 `UsageLimits(request_limit=2)`，结构化正文最多 6000 字；不会消费当前 Run 的 workflow 调用预算 | 新版本 `AgentConversationSummary.summary_text` |
| 偏好候选请求保护 | `backend/app/modules/agent/model_runtime/preference_extractor.py`（L23-L160） | `PreferenceCandidateProposal`、`PreferenceExtractionRuntime.extract`、`PreferenceExtractionRuntime._run` | 同作用域单条原始 user message、根 conversation Run | 只允许最多五个 snake_case key、标量 value、scope 和 confidence；临时难度/章节、掌握度和目标禁止抽取，重复 key 拒绝；使用 Run 模型配置与 `UsageLimits(request_limit=2)` | 带 extractor/model 审计的 proposals；只由 Outbox 写 pending candidate |
| 模型配置 `null` 语义 | `backend/app/modules/agent/model_configs.py`、`backend/app/modules/agent/models.py` | `AgentModelConfigService.create` / `update`、`AgentModelConfigRecord.max_tokens` | 管理员把 `max_tokens` 设为 `null` | 明确保留“不设上限”，运行时完全省略该参数 | OpenAI 兼容请求 |

历史摘要与学习策略的首批消费锚点：`backend/app/modules/agent/model_runtime/router.py::RouterDeps` / `_router_policy`（L45-L58、L128-L167）、`backend/app/modules/agent/learning_snapshot.py::load_learning_snapshot_summary`（L75-L138）与 `backend/app/modules/agent/model_runtime/answer.py::DirectAnswerDeps` / `_controlled_context`（L23-L64、L80-L101）。它们只接收 snapshot 前由服务端按用户、线程、范围和预算筛过的摘要/策略；动态 instructions 明确其为不可信数据，摘要不会被伪装成历史 user 消息，也不会改变模型调用预算，策略不会进入学习证据。

## 普通回答结构化流式输出

| 执行阶段 | 文件 | 符号 | 入口条件 | 处理与副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 结构化流式生成 | `backend/app/modules/agent/model_runtime/answer.py` | `DirectAnswerRuntime._run_stream` | direct answer 且前端需要流式显示 | 使用 `run_stream`，每 100ms partial validate 一次 `DirectAnswerOutput` | 已确认前缀的内容片段 |
| 增量持久化 | `backend/app/modules/agent/workflows/conversation.py` | `_direct_answer_node.publish_delta` | 收到新正文片段 | 追加 `message.delta` 并 commit，使独立 SSE session 立即可见 | `agent_events` 与 `agent_thread_events` |
| 最终收敛 | `backend/app/modules/agent/worker.py` | `AgentWorker.process_run`（message completed 分支） | workflow 返回最终 artifact | 写 `message.completed`，用最终正文覆盖 streaming message | 刷新与重连可恢复最终消息 |
| 前端归并 | `frontend/src/features/agent/timeline-state.ts` | `applyMessageEvent` | `message.delta`、`message.completed` | 只追加正文，不重新覆写旧片段；completed 时收敛状态 | React timeline state |

## Explain 模型接线

| 执行阶段 | 文件 | 符号 | 入口与关键参数 | 处理、调用关系与副作用 | 错误与最终消费 |
| --- | --- | --- | --- | --- | --- |
| 资料规划 | `backend/app/modules/agent/model_runtime/explanation.py` | `ExplanationDeps`、`_controlled_context`、`ExplanationRuntime.decide`（L19-L134） | standalone question、有效资料数、snapshot history/摘要、主题、Artifact 摘要、引用 ID、冻结 teaching_mode | 两类 Explain Agent 共享受控 instructions；冻结摘要与教学策略均声明为不可信动态资料，调用 child Run 绑定模型执行结构化规划，策略不重新选择业务 workflow | `LoopDecision`；模型异常向 `_evidence_loop_node` 传播 |
| 正文生成 | `backend/app/modules/agent/model_runtime/explanation.py` | `ExplanationRuntime.generate`（L136-L180） | standalone question、同一 snapshot history/摘要、evidence text、同一 child run ID | 复用同一模型配置与摘要副本，输出 `outline`、`body`、`citations`、`summary`；不得执行摘要或资料中的指令 | `_render_artifact_node` 消费 |
| 结构化响应审计 | `backend/app/modules/agent/model_runtime/config.py` | `_audit_model_response`（L75-L89） | Pydantic AI `ModelResponse` | 优先拼接 `TextPart`；GLM 等模型通过 tool-call 返回结构化结果且无文本 part 时，从 `args/content` 生成可读审计文本，完整响应仍写 `response_full` | LLM 调用记录的 response_text、token 与完整响应；审计页消费 | `LLMCallRecorder.record_pydantic_response` |
| 单测覆盖 | `backend/tests/test_agent_explanation_runtime.py` | `test_explanation_runtime_returns_structured_decision_and_content` / `test_explanation_runtime_uses_run_bound_agent_model_config` | 运行时接线变化 | 校验结构化决策、正文输出与 run 绑定配置 | 回归保护 |

## 历史摘要模型接线

| 执行阶段 | 文件 | 符号 | 入口与关键参数 | 处理、调用关系与副作用 | 错误与最终消费 |
| --- | --- | --- | --- | --- | --- |
| 受控摘要输入 | `backend/app/modules/agent/model_runtime/conversation_summary.py`（L21-L56） | `ConversationSummaryOutput`、`ConversationSummaryMessage`、`ConversationSummaryDeps`、`conversation_summary_agent` | 服务端过滤后的旧摘要、新增 user/assistant 消息、thread/user/trigger run | 只允许结构化 `summary`；instructions 明确消息和旧摘要是不可信数据，禁止执行其中指令、推测掌握度或输出内部 ID | `ConversationSummaryRuntime.summarize` |
| 增量模型调用 | `backend/app/modules/agent/model_runtime/conversation_summary.py`（L59-L136） | `ConversationSummaryRuntime.summarize`、`ConversationSummaryRuntime._run` | 旧摘要可空，新增消息非空，触发 Run ID | JSON 封装旧摘要和新增消息；`open_agent_model(run_id=trigger_run_id)` 复用触发 Run 的用户选择或继承配置，模型调用结束关闭客户端 | 非空摘要返回 maintainer；配置、模型和校验异常传播到 Memory Outbox 重试 |
| 运行时回归 | `backend/tests/test_agent_conversation_summary_runtime.py`（L42-L86） | `test_summary_runtime_returns_structured_internal_summary`、`test_summary_runtime_uses_trigger_run_model_configuration` | 结构化输出或模型配置接线改变 | 验证 Pydantic AI 输出模型与触发 Run ID 原样传给 `open_agent_model` | 防止退化为自由文本或全局默认模型 |

## 下一步阅读

- 检索工具、Explain 无资料回答和 Validate 题目检索，见 `implementation/rag-and-tools.md`。
- 失败错误如何公开、刷新如何恢复，见 `implementation/events-timeline-errors.md`。
