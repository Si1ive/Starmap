# 2026-07 记忆失效与删除治理进展

## 2026-07-27：固化临时练习约束的单轮失效边界

- 目标：完成 `MEM-007` 的临时约束收口，证明 difficulty、chapter ordinal 和派生检索参数不会随线程主题继承到下一轮。
- 实现：不新增状态字段；`backend/tests/test_agent_conversation_workflow.py::test_practice_constraints_expire_after_the_current_turn`（L894-L1078）连续执行两个同线程 conversation Run。Turn A 从显式知识点引用生成 hard + 第三章 Snapshot/PracticeBundle，Turn B 只继承主题，新 Snapshot/PracticeBundle/filter 不含旧约束；线程热状态只保留主题确认版本，旧 Snapshot、主题事实与 Artifact 集合不变。
- 验证：TurnUnderstanding、MemorySelector、Conversation workflow 与 Validate 聚焦回归 39 项通过；全部 Agent 回归 203 passed、87 warnings，Python 编译与 `git diff --check` 通过。
- 提交信息：`固化临时练习约束的单轮失效边界`

## 2026-07-27：让线程主题在六个后续轮次后失效

- 目标：推进 `MEM-007`，避免一次旧主题永久控制后续无关请求，同时兼容已经落库但没有确认版本的热状态 JSON。
- 实现：`backend/app/modules/agent/turn_understanding.py::_topic_state_payload`（L539-L554）在显式主题写当前确认版本，继承时保留原版本；`backend/app/modules/agent/context_builder.py::_active_topic_from_state`（L752-L772）在 Router 前只暴露版本差不超过 6 的主题，第 7 轮开始失效，缺标记的旧数据首次兼容，非法标记安全失效。
- 验证：ContextBuilder、Conversation workflow、TurnUnderstanding 聚焦回归 32 项通过；全部 Agent 回归 202 passed、75 warnings，Python 编译与 `git diff --check` 通过。
- 提交信息：`让线程主题按轮次自动失效`
