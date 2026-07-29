# 真实学习进度与艾宾浩斯投影

## 目标与事实边界

学习进度不是前端静态曲线，也不是模型写入的主观百分数。本实现只消费当前用户已经交卷的真实题目答案和 Agent 评分形成的知识点掌握证据，不再把用户主动开启的计时或停留时长当作学习事实。题目与知识点不建立两套记忆语义：规范化后相同的关键词进入同一条轨迹。

当前保持率是基于证据的调度估计，不等于“已经掌握”。页面同时展示证据数、最近学习时间、记忆强度和建议复习时间，使用户能理解数值来源。

## 证据读取与用户隔离

| 执行阶段 | 文件 | 符号 | 代码范围 | 入口与参数 | 处理与副作用 | 错误传播 / 最终消费 |
| --- | --- | --- | --- | --- | --- | --- |
| HTTP 入口 | `backend/app/modules/learning/router.py` | `get_learning_progress` | L16-L21 | 已认证学习用户和数据库 Session | 只把认证对象的 UUID 传给投影服务；无写库副作用 | 未登录返回 401；服务错误沿统一 API 错误链返回用户端 |
| 题目证据 | `backend/app/modules/learning/service.py` | `LearningProgressService._load_question_evidence` | L187-L227 | 当前用户 UUID | 只连接该用户已交卷会话和非空答案；优先读开考时冻结的 `topic_terms` / `tags`，再回退题库字段；正确质量为 1，错误质量为 0.25 | 返回 `LearningEvidence`；查询失败中止本次投影，不产生部分写入 |
| 做题总量 | `backend/app/modules/learning/service.py` | `LearningProgressService._question_totals` | L229-L247 | 当前用户 UUID | 独立统计已交卷非空答案和正确数，避免一道题多个关键词导致重复计数 | 总题数、正确数与真实正确率由 `get` 汇总 |
| 知识点证据 | `backend/app/modules/learning/service.py` | `LearningProgressService._load_mastery_evidence` | L249-L283 | 当前用户 UUID 转 Agent 领域 32 位 hex | 读取 `user_learning_mastery` 和真实知识点标题、主题词、别名；聚合证据数转为有上限的重复权重 | 与题目证据按关键词归并；没有评分时间的聚合不进入曲线 |
| 关键词归一化 | `backend/app/modules/learning/service.py` | `normalize_keyword`、`LearningProgressService._keywords` | L37-L39、L285-L295 | 题目主题词/标签或知识点主题词/别名/标题 | 去除空白和常用分隔符、统一小写、限制 2–40 字并按实体最多取 6 个；不调用模型，不猜测语义同义词 | 完全相同的规范化关键词合并；无关键词证据仍计入做题总量但不伪造轨迹 |

## 艾宾浩斯计算

核心实现在 `backend/app/modules/learning/service.py::project_ebbinghaus`（L42-L92）。输入必须至少有一条按时间发生的 `LearningEvidence`，空输入直接报错。

每个关键词维护记忆强度 `S`（小时），任意时刻距离最近证据 `t` 小时的保持率为：

`R(t) = exp(-t / S)`

第一次证据按质量建立 12–36 小时初始强度。后续正确或高质量证据先计算复习前保持率，再按 `S × (1.35 + 0.75 × quality + 0.25 × R_before)` 增强，最大限制为 180 天；错误或低质量证据按 `S × (0.45 + 0.35 × quality)` 衰减，最小保留 6 小时。聚合知识点证据的重复权重最多按 20 次计算，避免历史计数无限放大曲线。

建议复习阈值固定为 55%，因此下一次建议时间为 `last_at - S × ln(0.55)`。返回曲线以“现在”为零点，计算未来 0、1、2、4、7、14、30 天的保持率。所有时间都来自服务器传入的 `now`；前端不重新发明算法。

## 汇总与前端消费

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出 / 最终消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 总投影 | `backend/app/modules/learning/service.py` | `LearningProgressService.get` | L99-L152 | 当前用户与可注入的计算时刻 | 合并题目/知识点证据，逐关键词算强度和曲线；汇总真实题量、正确率和最近学习活动，不计算学习时长 | `summary`、`topics`、`recent_activities`；保持率低于 55% 标记 due |
| API 客户端 | `frontend/src/api/learning.ts` | `getLearningProgress` | L84-L98 | 登录 Cookie | 读取统一 envelope；非 2xx 或无 data 转为可显示错误 | `TodayPage` |
| 学习进度页 | `frontend/src/pages/TodayPage.tsx` | `TodayPage` | L31-L297 | 真实进度 DTO | 展示总关键词、到期数、真实题量/正确率；按选中关键词绘制后端曲线点，并展示证据来源、复习时间、全部轨迹和最近活动 | 空数据引导真实练习；加载/错误/窄屏均使用同一项目视觉语言 |

## 知识薄弱点与练习的边界

知识薄弱点不是另一套模拟题列表，也不凭一次错误直接宣称“未掌握”。它只把当前用户已交卷的作答证据按与
学习曲线相同的规范化关键词分簇，展示原题、错误次数、提示使用和下一次验证时间；真正刷题、服务器限时交卷和
批改仍在练习工作区完成。

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出 / 最终消费 |
| --- | --- | --- | --- | --- | --- | --- |
| 快照关键词 | `backend/app/modules/learning/weaknesses.py` | `_snapshot_keywords` | L18-L34 | 会话冻结题面和当前题库对象 | 优先取冻结 `topic_terms/tags`，规范化后最多四个；只有完全无有效词时才回退章节，避免一次错误重复进入“未标注”簇 | 解释性关键词；无写库副作用 |
| 薄弱点投影 | `backend/app/modules/learning/weaknesses.py` | `project_weakness_rows` | L37-L128 | 当前用户作答行和服务器时刻 | 按关键词统计真实错误/作答次数，保留冻结题面、来源、提示层级和原会话；一次后续正确只进入“待间隔验证”，不能直接标记已解决 | summary、clusters 与错误时间线 |
| 用户隔离查询 | `backend/app/modules/learning/weaknesses.py` | `WeaknessService.get` | L131-L161 | 当前用户 UUID | 只联接该用户已交卷会话和非空答案；草稿、其他用户和未批改答案不进入投影 | 只读投影；SQL 错误传播且不返回部分假数据 |
| HTTP 入口 | `backend/app/modules/learning/router.py` | `get_learning_weaknesses` | L24-L29 | 已认证学习用户 | 只传认证对象 UUID 给 `WeaknessService` | `/api/v1/app/learning/weaknesses` |
| 前端契约 | `frontend/src/api/learning.ts` | `WeaknessEvidence`、`WeaknessCluster`、`LearningWeaknesses`、`getLearningWeaknesses` | L33-L65、L83-L97 | 登录 Cookie | 约束错误证据、状态和汇总 DTO；失败转用户可见错误 | `MistakesPage` |
| 薄弱点页面 | `frontend/src/pages/MistakesPage.tsx` | `MistakesPage` | L35-L164 | 当前用户真实薄弱点 DTO | 提供加载、重试、零错题空态、到期队列、关键词簇和时间线；点击证据进入原练习成绩复盘，不构造不存在的练习 ID | 用户核对错误事实或进入真实练习/复盘 |

## 验证

- `backend/tests/test_learning_progress.py::test_keyword_normalization_merges_question_and_knowledge_labels`：题目和知识点的格式差异能归并。
- `backend/tests/test_learning_progress.py::test_ebbinghaus_retention_declines_monotonically_without_new_evidence`：没有新证据时未来保持率严格不增加。
- `backend/tests/test_learning_progress.py::test_spaced_correct_recall_extends_strength_more_than_an_error`：间隔正确回忆比错误证据产生更长强度和更高保持率。
- `backend/tests/test_learning_progress.py::test_projection_rejects_empty_evidence`：没有证据时不生成伪曲线。
- `backend/tests/test_learning_progress.py::test_question_totals_are_scoped_to_current_user_and_submitted_sessions`：汇总 SQL 必须同时限定当前用户和已交卷状态，不能串号或把草稿计入进度。
- `backend/tests/test_learning_weaknesses.py::test_weakness_projection_groups_real_wrong_answers_and_preserves_evidence`：相同关键词错误正确归簇且保留冻结题面与提示证据。
- `backend/tests/test_learning_weaknesses.py::test_weakness_projection_does_not_mark_one_later_correct_answer_resolved`：一次后续正确只能等待间隔验证，不能伪造“已解决”。
- `backend/tests/test_learning_weaknesses.py::test_weakness_service_filters_submitted_answers_by_current_user`：SQL 必须同时限定当前用户和已交卷状态。
- 前端通过生产构建和 `api/learning.ts`、`TodayPage.tsx` 定向 ESLint。
