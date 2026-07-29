# 用户端需求实现差距审计

> 审计日期：2026-07-28
>
> 范围：资料、模拟考/练习、知识薄弱点、学习进度，以及这些页面的用户归属、真实数据和生产 UI。

## 状态口径

- **已完成**：存在真实持久化/API/页面闭环，并有与风险相匹配的自动化验证。
- **部分完成**：主链可用，但需求文档定义的格式、治理或深度能力尚未全部落地。
- **未完成**：生产页面仍没有对应事实或交互。本文不会用 fixture、静态文案或模型主观输出把它标成完成。

## 审计结论

| 需求域 | 状态 | 已有真实实现与代码锚点 | 仍缺失 / 不应误报 |
| --- | --- | --- | --- |
| 用户私有资料上传与 PDF 阅读 | 部分完成 | `backend/app/modules/library/router.py::upload_library_sources`（L100-L132）校验 PDF 签名、绑定用户并启动解析/抽取/索引；`read_original_pdf`（L186-L214）重新校验 owner 后以内联原件响应。`frontend/src/pages/SourcesPage.tsx::SourcesPage`（L53-L443）消费真实状态并用浏览器 PDF 阅读器打开入库记录 | 当前明确只支持 PDF，产品 PRD 中图片、Markdown、纯文本仍未实现；尚无逐页部分成功说明和文件安全扫描结果 |
| 资料检索授权与用户隔离 | 已完成（访问面） | `backend/app/modules/library/router.py::update_source_retrieval`、`delete_library_source`（L153-L182）仅允许本人资料；`backend/app/modules/retrieval/search_engine.py::RetrievalSearchEngine.hydrate_results`（L286-L328）在 MySQL 水合阶段复核 owner、未删除与检索开关；模拟考选卷复用相同可用性门 | 删除目前是立即撤权和逻辑删除，保留历史外键需要的最小元数据；对象文件和 Qdrant 物理副本的异步清理/可查询进度仍未实现，不能称为物理清除完成 |
| 真实模拟考与练习 | 已完成（客观题主链） | `backend/app/modules/practice/router.py::create_practice_session`（L314-L387）从真实入库试卷冻结题面；`save_practice_answer`（L409-L457）按当前用户、服务器时限和乐观版本保存；`submit_practice_session`（L477-L488）确定性批改。`frontend/src/pages/PracticePage.tsx::PracticePage`（L39-L505）提供会话限时、作答、交卷、成绩与复盘 | 主观题目前只做标准答案精确匹配，未实现评分点辅助反馈；复杂公式/题图展示质量取决于现有抽取结果；不应宣称已完成可靠主观题自动评分 |
| 练习/模拟考区分与提示 | 已完成 | `backend/app/modules/practice/router.py::request_practice_hint`（L257-L311）只允许普通练习使用三级安全提示并记录证据，模拟考返回 409；`frontend/src/pages/PracticeLibraryPage.tsx::PracticeLibraryPage`（L31-L233）提供两种开考入口，已移除独立学习计时 | 暂无用户自定义组卷筛选（章节/题型/难度）；提示是确定性学习脚手架，不是模型生成完整解题过程 |
| 多设备答案冲突 | 已完成 | `backend/app/modules/practice/router.py::_assert_answer_version`、`save_practice_answer`（L75-L83、L409-L456）拒绝旧版本；`frontend/src/pages/PracticePage.tsx::save`、`resolveConflict`（L97-L201）并列展示服务器/本机答案并要求用户选择 | 暂无离线写队列；网络断开期间只保留当前 React 输入，不能宣称支持完整离线编辑 |
| 做题量、大纲覆盖和复盘 | 已完成（当前统计口径） | `backend/app/modules/practice/router.py::get_practice_stats`（L520-L557）只聚合本人已交卷答案和 active 大纲章节；练习历史与成绩页使用冻结题面复盘 | 覆盖率当前按命中过的主章节计算，不是每个大纲考点的细粒度覆盖；专项复盘组卷尚未按薄弱关键词自动选题 |
| 知识薄弱点 | 部分完成 | `backend/app/modules/learning/weaknesses.py::project_weakness_rows`（L37-L128）按冻结关键词聚合本人错误、提示和后续正确证据；`WeaknessService.get`（L131-L161）限定本人已交卷会话；`frontend/src/pages/MistakesPage.tsx::MistakesPage`（L35-L164）已移除 fixture | 当前只使用可验证的“答错”事实，不猜测条件遗漏/概念混淆等错因；用户确认、修改、拒绝错因候选和按簇生成专项练习仍未完成 |
| 真实艾宾浩斯学习进度 | 已完成（曲线主链） | `backend/app/modules/learning/service.py::project_ebbinghaus`（L43-L92）执行 `R=exp(-t/S)`；`LearningProgressService.get`（L99-L152）按相同关键词合并本人题目与知识点证据；`frontend/src/pages/TodayPage.tsx::TodayPage`（L31-L297）绘制后端返回曲线和真实学习活动，不再展示学习时长统计 | 曲线是可解释调度估计，不是心理测量或“掌握”结论；学习计划版本、目标考试日期、阶段计划审批和基于计划的推荐任务仍未实现 |
| 生产页面 mock 清理 | 已完成 | 资料、练习、薄弱点、进度和任务中心均由真实 API/时间线驱动；`frontend/src/components/AppShell.tsx::AppShell`（L33-L239）不再读取固定任务；`frontend/src/App.tsx::App`（L96-L145）只注册真实用户工作区，旧状态画廊、未挂载 Map 页面和 `data/fixtures.ts` 已删除 | `mock_exam` 是模拟考试的真实业务枚举，不是 mock 数据；后续新增页面仍须通过源码扫描和生产路由核对 |

## 后续实施优先级

### P0：发布阻断和真实性

1. 完成全项目桌面/移动 UI 回归，检查溢出、遮挡、空态、错误态和颜色漂移。
2. 运行后端全量测试并修正与当前契约不一致的旧断言；不能带已知失败结束验收。

### P1：本轮需求的深度闭环

1. 资料删除 Outbox：撤权后异步清理原始对象、解析副本和 Qdrant point，并公开清理状态。
2. 薄弱点错因确认：候选必须绑定具体作答证据，支持确认、修改、拒绝和无法判断。
3. 按薄弱关键词创建专项练习，并继续使用冻结题面、服务器限时、版本冲突与确定性批改主链。
4. 学习计划：保存考试目标、计划版本和需确认的调整，再由真实曲线/错误证据生成推荐任务。

### P2：扩展格式与评分深度

1. 用户资料增加图片、Markdown 和纯文本的安全上传、阅读与来源分层。
2. 主观题增加冻结评分点、逐点评价、异议和“AI 辅助反馈”标识；仍不让模型拥有正式最终判定权。

## 验收约束

后续每项仍须满足：所有资源绑定真实用户；跨用户 ID 返回不可枚举的安全错误；前端空数据展示空态而不是
fixture；数据库变更走 Alembic 前向迁移；独立功能完成后测试、`git diff --check` 和中文提交立即落地。
