# 用户端真实模拟考与练习实现

## 适用场景

本文说明用户端“练习”如何从已入库真题创建真实考试会话，如何冻结题面、按服务器限时作答、保存答案、交卷批改、复盘历史，以及如何统计做题量和大纲覆盖。独立学习计时不属于当前练习事实；知识薄弱点仍是由错误证据派生的另一个领域，本模块不把一次模拟考直接等同为“已掌握”或“薄弱”。

## 数据事实与所有权

| 数据 | 文件 | 符号 | 代码范围 | 所有权与生命周期 |
| --- | --- | --- | --- | --- |
| 模拟考会话 | `backend/app/modules/practice/models.py` | `PracticeSession` | L23-L62 | `user_id` 是唯一所有者；记录模式、服务器开始/交卷时间、总分和成绩。来源文档删除时只清空引用，历史会话保留 |
| 冻结题目 | `backend/app/modules/practice/models.py` | `PracticeSessionQuestion` | L65-L88 | 会话内题目唯一且顺序唯一；`snapshot_json` 固化题干、选项、答案、解析、来源和章节，题库后续修改不改变历史批改语义 |
| 用户答案 | `backend/app/modules/practice/models.py` | `PracticeAnswer` | L91-L122 | 会话/题目唯一；保存答案、乐观版本号、已用提示层级、批改结果与得分，随用户会话级联删除 |

四次前向迁移分别创建事实表、冻结快照、并发版本和提示证据：`backend/alembic/versions/20260728_practice_sessions.py::upgrade`（L19-L98）创建会话、题目、答案和历史计时表；`backend/alembic/versions/20260728_practice_snapshot.py::upgrade`（L18-L45）回填冻结题面；`backend/alembic/versions/20260728_practice_answer_version.py::upgrade`（L18-L22）为旧答案回填版本 1；`backend/alembic/versions/20260728_practice_hints.py::upgrade`（L18-L24）增加提示层级证据。当前版本再由 `backend/alembic/versions/20260729_remove_study_timing.py::upgrade`（L19-L22）删除独立计时表和每题耗时字段。迁移失败会中断升级，禁止用 stamp 跳过。

## 模拟考执行主链

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `frontend/src/pages/PracticeLibraryPage.tsx` | `PracticeLibraryPage` | L31-L233 | 当前登录用户打开练习页 | 并行加载可见真题、用户历史和覆盖统计；页面不再提供独立学习计时 | 真实真题列表、累计题数、覆盖率和恢复入口 | 用户选择模拟考或刷题练习 |
| 2 | `frontend/src/api/practice.ts` | `createPracticeSession` | L120-L135 | 文档 ID、模式、题数、会话时限 | 读取当前认证会话并附带 CSRF，发送创建命令 | 用户 API 请求；认证或 CSRF 错误直接显示 | `create_practice_session` |
| 3 | `backend/app/modules/practice/router.py` | `create_practice_session` | L314-L387 | 认证用户、文档、题数和会话时限 | 用 owner、未删除和检索授权验证平台/本人文档，再读取真实题目；为每题写不可变快照，包含曲线使用的主题词和标签 | `practice_sessions` 与 `practice_session_questions` 同事务提交；无权访问返回 404，未抽题返回 409 | 前端进入会话 URL |
| 4 | `backend/app/modules/practice/router.py` | `_session_payload`、`get_practice_session` | L148-L215、L390-L406 | 用户 ID 与会话 ID | `_owned_session` 强制会话所有者；以服务器开始时间计算剩余秒数，到期先自动交卷；未提交时隐藏快照答案，同时返回每题作答版本与提示证据 | 当前题面、已存答案、版本和服务器剩余时间 | `PracticePage` |
| 5 | `frontend/src/pages/PracticePage.tsx` | `PracticePage`、`save`、`resolveConflict` | L39-L505、L98-L190 | 会话 DTO | 渲染题面和服务器倒计时；答案保存只携带当前版本。409 时重新读取服务器答案并以项目样式对照两个版本，用户明确选择保留服务器值或用本机值再次覆盖 | 当前作答状态；冲突不会静默覆盖或自动切题/交卷 | `save_practice_answer` 或继续答题 |
| 5.1 | `frontend/src/index.css` | `.practice-answer-conflict` | L3049-L3119 | 两份冲突答案和两个选择动作 | 使用项目纸张、墨色与琥珀边线；桌面双栏、移动端单栏，不调用浏览器原生确认框 | 可键盘操作的冲突面板 | 用户选择后进入 `resolveConflict` |
| 6 | `backend/app/modules/practice/router.py` | `_assert_answer_version`、`save_practice_answer` | L63-L71、L409-L457 | 会话、题目、答案和 `expected_version` | 锁定用户会话并核对状态、截止时间和题目归属；仅当期望版本等于数据库版本时保存并递增，首次保存要求版本 0 | `practice_answers`；旧版本返回可识别 409，超时自动交卷 | 前端冲突选择或继续答题 |
| 7 | `backend/app/modules/practice/router.py` | `_submit`、`submit_practice_session` | L106-L146、L477-L488 | 当前用户会话 | 幂等交卷；客观答案归一化后与会话快照答案确定性比对，未作答补空答案并计零分 | 固化每题对错/得分和会话总成绩、交卷时间 | 反馈与复盘页 |
| 8 | `frontend/src/pages/PracticePage.tsx` | `PracticePage` | L268-L505 | 已交卷会话 DTO | 显示总分、逐题对错、用户答案、冻结标准答案与解析 | 用户可逐题复盘；不修改历史事实 | 返回练习历史 |

## 分层提示与模拟考边界

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 最终消费 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 安全提示文本 | `backend/app/modules/practice/router.py` | `_practice_hint` | L74-L89 | 冻结题面和 direction/concept/method 层级 | 只读取题型与 `topic_terms` 生成方向、概念或方法提示；不读取 `answer` 与 `explanation`，避免未交卷答案泄漏 | 确定性提示文本 | 提示接口 |
| 提示证据写入 | `backend/app/modules/practice/router.py` | `request_practice_hint` | L257-L311 | 用户会话、题目、层级和期望答案版本 | 仅允许 `mode=practice` 且活动中的本人会话；按乐观版本写入去重后的提示层级，模拟考返回 409 | `PracticeAnswer.hint_levels_used_json` 与新版本；不改变答案和得分 | 作答 DTO、后续学习证据 |
| 提示客户端 | `frontend/src/api/practice.ts` | `requestPracticeHint` | L166-L184 | Session/Question/层级/版本 | 带 CSRF 请求提示并接收新版本与已用层级 | 类型化提示响应 | `PracticePage.showHint` |
| 练习提示交互 | `frontend/src/pages/PracticePage.tsx` | `showHint`、`PracticePage` | L196-L229、L381-L428 | 普通练习当前题 | 只在普通练习显示方向、概念、方法三个紧凑动作；成功后同步答案版本，模拟考不渲染入口 | 当前提示与持久化使用证据 | 用户继续独立作答 |
| 提示视觉 | `frontend/src/index.css` | `.practice-hints` | L13284-L13316 | 提示动作和正文 | 使用项目纸张、墨色和玉色边线，保持提示弱于题干 | 简洁可换行提示块 | 用户端练习页 |

## 历史与统计

| 入口 | 文件 | 符号 | 代码范围 | 输入与处理 | 副作用 / 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 练习历史 | `backend/app/modules/practice/router.py` | `list_practice_history` | L491-L536 | 只查询当前用户；列表加载时也把服务器时限已到的活动会话自动交卷 | 前端“交卷与复盘”列表恢复未完成会话或打开成绩 |
| 覆盖统计 | `backend/app/modules/practice/router.py` | `get_practice_stats` | L539-L577 | 只聚合当前用户已交卷答案；统计总答题、答对、命中过的题目主章节以及 active 大纲章节总数 | `PracticeLibraryPage` 展示真实做题量与大纲覆盖率；空数据返回零而非 mock |

## 当前批改边界

当前自动批改是确定性的答案比对，适合选择、判断、填空及标准答案可直接归一化的题目。主观题不会调用模型冒充人工评分：只有与冻结标准答案归一化后完全一致时才得分，页面明确显示标准答案与解析。后续若增加评分点辅助批改，应单独保存评分规则快照、各评分点命中和“辅助反馈”标记，不能覆盖本次确定性成绩。

## 验证入口

- `backend/tests/test_practice_router.py::test_owned_session_always_filters_by_current_user`：会话查询必须同时携带 session ID 和当前用户 ID。
- `backend/tests/test_practice_router.py::test_submit_grades_against_frozen_snapshot_not_changed_question`：题库答案改变后仍以会话快照批改。
- `backend/tests/test_practice_router.py::test_normalize_answer_supports_objective_question_formats`：选择/判断/填空常见格式归一化。
- `backend/tests/test_practice_router.py::test_answer_version_rejects_stale_multi_device_save`：旧版本保存必须得到 409，不能覆盖较新的答案。
- `backend/tests/test_practice_router.py::test_layered_practice_hints_do_not_expose_frozen_answer`：提示只使用题型与主题词，不能拼入冻结答案或解析。
- 前端执行 `npm run build` 和针对 `api/practice.ts`、两个练习页面的 ESLint；后端执行迁移图、schema guard 与练习定向测试。
