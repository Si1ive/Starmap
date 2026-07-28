# 用户端真实模拟考与练习实现

## 适用场景

本文说明用户端“练习”如何从已入库真题创建真实考试会话，如何冻结题面、按服务器时间计时、保存答案、交卷批改、复盘历史，以及如何统计做题量和大纲覆盖。知识薄弱点仍是由错误证据派生的另一个领域，本模块不把一次模拟考直接等同为“已掌握”或“薄弱”。

## 数据事实与所有权

| 数据 | 文件 | 符号 | 代码范围 | 所有权与生命周期 |
| --- | --- | --- | --- | --- |
| 模拟考会话 | `backend/app/modules/practice/models.py` | `PracticeSession` | L23-L51 | `user_id` 是唯一所有者；记录模式、服务器开始/交卷时间、总分和成绩。来源文档删除时只清空引用，历史会话保留 |
| 冻结题目 | `backend/app/modules/practice/models.py` | `PracticeSessionQuestion` | L54-L75 | 会话内题目唯一且顺序唯一；`snapshot_json` 固化题干、选项、答案、解析、来源和章节，题库后续修改不改变历史批改语义 |
| 用户答案 | `backend/app/modules/practice/models.py` | `PracticeAnswer` | L78-L101 | 会话/题目唯一；保存答案、用时、批改结果与得分，随用户会话级联删除 |
| 专注计时 | `backend/app/modules/practice/models.py` | `StudyTimerRecord` | L104-L121 | 每次刷题或休息绑定用户，保存计划时长、实际时长和完成状态；后续学习进度只消费真实计时事实 |

两次前向迁移分别创建事实表和冻结快照：`backend/alembic/versions/20260728_practice_sessions.py::upgrade`（L19-L98）创建会话、题目、答案和计时表；`backend/alembic/versions/20260728_practice_snapshot.py::upgrade`（L18-L45）为可能已存在的会话题回填快照后再收紧为非空。迁移失败会中断升级，禁止用 stamp 跳过。

## 模拟考执行主链

| 执行序号 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `frontend/src/pages/PracticeLibraryPage.tsx` | `PracticeLibraryPage` | L39-L309 | 当前登录用户打开练习页 | 并行加载可见真题、用户历史和覆盖统计；只展示后端真实返回 | 真实真题列表、累计题数、覆盖率和恢复入口 | 用户选择模拟考或 25 分钟练习 |
| 2 | `frontend/src/api/practice.ts` | `createPracticeSession` | L106-L121 | 文档 ID、模式、题数、时限 | 读取当前认证会话并附带 CSRF，发送创建命令 | 用户 API 请求；认证或 CSRF 错误直接显示 | `create_practice_session` |
| 3 | `backend/app/modules/practice/router.py` | `create_practice_session` | L223-L291 | 认证用户、文档、题数和时限 | 先用 `corpus_files.owner_user_id` 验证平台/本人可见性，再读取该文档真实题目；为每题写不可变快照，包含后续曲线使用的主题词和标签 | `practice_sessions` 与 `practice_session_questions` 同事务提交；无权访问返回 404，未抽题返回 409 | 前端进入会话 URL |
| 4 | `backend/app/modules/practice/router.py` | `_session_payload`、`get_practice_session` | L118-L179、L295-L308 | 用户 ID 与会话 ID | `_owned_session` 强制会话所有者；以服务器开始时间计算剩余秒数，到期先自动交卷；未提交时快照答案和解析保持为空 | 当前题面、已存答案和服务器剩余时间 | `PracticePage` |
| 5 | `frontend/src/pages/PracticePage.tsx` | `PracticePage` | L29-L343 | 会话 DTO | 渲染答题卡、题面、选项/文本答案和服务器倒计时；切题或输入失焦时保存 | 当前作答状态；保存失败留在工作区 | `save_practice_answer` |
| 6 | `backend/app/modules/practice/router.py` | `save_practice_answer` | L312-L351 | 会话、题目、答案、累计题目用时 | 加锁并再次核对用户、会话状态、服务器截止时间和题目归属；新增或更新唯一答案 | `practice_answers`；超时自动交卷并返回 409，已交卷拒绝修改 | 继续答题或交卷 |
| 7 | `backend/app/modules/practice/router.py` | `_submit`、`submit_practice_session` | L79-L115、L355-L363 | 当前用户会话 | 幂等交卷；客观答案归一化后与会话快照答案确定性比对，未作答补空答案并计零分 | 固化每题对错/得分和会话总成绩、交卷时间 | 反馈与复盘页 |
| 8 | `frontend/src/pages/PracticePage.tsx` | `PracticePage` | L150-L343 | 已交卷会话 DTO | 显示总分、逐题对错、用户答案、冻结标准答案与解析 | 用户可逐题复盘；不修改历史事实 | 返回练习历史 |

## 历史、统计与番茄钟

| 入口 | 文件 | 符号 | 代码范围 | 输入与处理 | 副作用 / 最终消费 |
| --- | --- | --- | --- | --- | --- |
| 练习历史 | `backend/app/modules/practice/router.py` | `list_practice_history` | L367-L411 | 只查询当前用户；列表加载时也把服务器时间已到的活动会话自动交卷 | 前端“交卷与复盘”列表恢复未完成会话或打开成绩 |
| 覆盖统计 | `backend/app/modules/practice/router.py` | `get_practice_stats` | L415-L452 | 只聚合当前用户已交卷答案；统计总答题、答对、命中过的题目主章节以及 active 大纲章节总数 | `PracticeLibraryPage` 展示真实做题量与大纲覆盖率；空数据返回零而非 mock |
| 开始计时 | `backend/app/modules/practice/router.py` | `start_study_timer` | L456-L477 | 校验 focus/rest 和 1–120 分钟范围，绑定认证用户 | 新增 running `study_timer_records`，前端开始本地逐秒显示 |
| 完成计时 | `backend/app/modules/practice/router.py` | `complete_study_timer` | L481-L508 | 用户 ID 与 timer ID 加锁；重复完成保持幂等 | 保存实际秒数和完成时间，供后续真实学习进度聚合 |

## 当前批改边界

当前自动批改是确定性的答案比对，适合选择、判断、填空及标准答案可直接归一化的题目。主观题不会调用模型冒充人工评分：只有与冻结标准答案归一化后完全一致时才得分，页面明确显示标准答案与解析。后续若增加评分点辅助批改，应单独保存评分规则快照、各评分点命中和“辅助反馈”标记，不能覆盖本次确定性成绩。

## 验证入口

- `backend/tests/test_practice_router.py::test_owned_session_always_filters_by_current_user`：会话查询必须同时携带 session ID 和当前用户 ID。
- `backend/tests/test_practice_router.py::test_submit_grades_against_frozen_snapshot_not_changed_question`：题库答案改变后仍以会话快照批改。
- `backend/tests/test_practice_router.py::test_normalize_answer_supports_objective_question_formats`：选择/判断/填空常见格式归一化。
- 前端执行 `npm run build` 和针对 `api/practice.ts`、两个练习页面的 ESLint；后端执行迁移图、schema guard 与练习定向测试。
