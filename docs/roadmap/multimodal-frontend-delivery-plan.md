# 多模态语料入库与检索 - 前端交付任务单

> 版本：v1.1  
> 日期：2026-06-11  
> 状态：执行中  
> 读者：Frontend / PM / Backend

---

## 1. 目标

前端要解决的不是“把接口数据列出来”，而是让管理员能看见、审核、追溯、调试整条语料链路。

必须交付：

1. 语料文件管理
2. 解析任务与文档详情
3. 页 / block / asset 查看
4. 知识点审核
5. 题目审核
6. section 映射审核
7. 关系审核
8. 检索调试页
9. 问答引用展示升级

---

## 2. 页面范围

建议新增路由：

- `/admin/ingest/files`
- `/admin/ingest/parse-runs`
- `/admin/ingest/documents/:id`
- `/admin/ingest/documents/:id/blocks`
- `/admin/review/sections`
- `/admin/review/knowledge`
- `/admin/review/questions`
- `/admin/review/relations`
- `/admin/retrieval/debug`

复用并改造：

- `/admin/knowledge/*`
- `/admin/questions/*`
- `/admin/conversations/*`

---

## 3. Phase 划分

## 3.1 Phase A：类型与 API 封装

任务：

- `FE-A1` 新增 `src/types/corpus.ts`
- `FE-A2` 新增 `src/types/retrieval.ts`
- `FE-A3` 新增 `src/api/corpus.ts`
- `FE-A4` 新增 `src/api/retrieval.ts`
- `FE-A5` 更新现有 `question` / `knowledge` 类型

验收：

- 所有新接口有稳定 TS 类型

## 3.2 Phase B：语料与解析管理页

任务：

- `FE-B1` 语料文件列表
- `FE-B2` 文件扫描弹窗
- `FE-B3` 解析任务列表
- `FE-B4` 文档详情页
- `FE-B5` 文档块列表与过滤
- `FE-B6` 文档 section 树与章节映射面板

验收：

- 能从 UI 扫描、查看解析状态、进入文档详情

## 3.3 Phase C：审核页

任务：

- `FE-C1` 知识点审核列表
- `FE-C2` 题目审核列表
- `FE-C3` section 映射审核页
- `FE-C4` 关系审核页
- `FE-C5` 审核详情抽屉
- `FE-C6` approve/reject 操作
- `FE-C7` 来源引用回跳到 block

验收：

- 管理员可以基于来源片段审核题目和知识点

## 3.4 Phase D：检索调试页

任务：

- `FE-D1` 查询输入与 filters 表单
- `FE-D2` 展示 query understanding
- `FE-D3` 展示 sparse/dense/relation/rerank 结果
- `FE-D4` 展示 source refs 与页码
- `FE-D5` 支持 question / knowledge / mixed 模式切换

验收：

- 能直观看到为什么一条查询命中了哪些题

## 3.5 Phase E：问答引用升级

任务：

- `FE-E1` 会话详情展示 citations
- `FE-E2` 支持“仅查知识点 / 仅查题目”
- `FE-E3` 展示易混点 / 前置点 / 对比点
- `FE-E4` 支持跳转到来源页或 block

验收：

- 问答结果可解释、可追溯

---

## 4. 任务明细

## 4.1 API 与类型

| 任务ID | 内容 | 依赖 | 验收 |
|--------|------|------|------|
| `FE-TYPE-01` | `CorpusFile`/`ParseRun`/`DocumentBlock`/`DocumentSection` 类型 | API 契约 | 类型可编译 |
| `FE-TYPE-02` | `RetrievalFilters`/`QuestionSearchItem`/`KnowledgeSearchItem`/`RelationOptions` 类型 | API 契约 | 类型可编译 |
| `FE-API-01` | `scanCorpusFiles` 等 API | 后端接口 | 请求成功 |
| `FE-API-02` | `searchQuestions`/`searchKnowledge`/`searchMixed` API | 后端接口 | 请求成功 |
| `FE-API-03` | `reviewSectionMappings`/`reviewRelations` API | 后端接口 | 请求成功 |

## 4.2 页面任务

| 任务ID | 页面 | 关键能力 |
|--------|------|----------|
| `FE-PAGE-01` | 语料文件列表 | 状态筛选、批量扫描 |
| `FE-PAGE-02` | 解析任务列表 | 状态、耗时、失败原因 |
| `FE-PAGE-03` | 文档详情页 | 基本信息、页统计、资产预览、原生标题树、章节映射 |
| `FE-PAGE-04` | block 页 | page/block_type/review_status 过滤 |
| `FE-PAGE-05` | section 映射审核页 | 候选章节、置信度、审核 |
| `FE-PAGE-06` | 知识点审核页 | 审核、来源引用、章节归属、关系入口 |
| `FE-PAGE-07` | 题目审核页 | 结构化字段、题型、年份、学科筛选、章节归属 |
| `FE-PAGE-08` | 关系审核页 | relation_type、证据、方向、审核 |
| `FE-PAGE-09` | 检索调试页 | filters + debug 结果 |

## 4.3 组件任务

建议新增组件：

- `SourceRefList`
- `DocumentBlockPreview`
- `AssetPreview`
- `SectionTree`
- `ChapterMappingPanel`
- `ChapterLinkTagList`
- `RelationEdgeList`
- `ReviewStatusTag`
- `RetrievalDebugPanel`
- `FilterBuilder`

---

## 5. 页面交互要求

## 5.1 语料文件列表

列建议：

- 文件名
- 类型
- 来源类型
- 处理状态
- 文档类型
- 更新时间
- 操作

操作建议：

- 触发解析
- 查看解析记录
- 进入文档详情

## 5.2 文档详情页

必须展示：

- 文档基本信息
- 解析统计
- 页缩略图
- 资产预览
- block 数量统计
- 原生标题树
- 标准章节映射
- “抽取知识点/题目”操作
- “重建索引”操作

## 5.3 block 审核页

必须支持：

- 按页切换
- 按 block 类型过滤
- 查看 bbox / 文本 / Markdown / LaTeX / HTML table
- 跳转到关联资产

## 5.4 题目审核页

必须支持：

- `exam_scope`
- `exam_year`
- `subject_id`
- `question_type`
- `review_status`

展示内容：

- 题干
- 选项
- 答案
- 解析
- topic_terms
- 知识点绑定
- 主章节与关联章节
- 来源页码与引用片段

## 5.5 section 映射审核页

必须支持：

- 左侧原生标题树
- 右侧候选标准章节
- `mapping_type`
- `confidence`
- approve / reject / 手工改绑

## 5.6 关系审核页

必须支持：

- `relation_type`
- `directionality`
- source / target 知识点
- evidence
- approve / reject / 修改关系类型

## 5.5 检索调试页

必须展示四层结果：

1. query understanding
2. filters
3. sparse / dense hits
4. relation hits
5. reranked hits

不允许只展示最终结果，否则无法排查检索问题。

---

## 6. 与后端联调顺序

1. 先联调 `corpus files`
2. 再联调 `parse runs`
3. 再联调 `documents/blocks/sections`
4. 再联调 `section mapping review`
5. 再联调 `knowledge/question review`
6. 再联调 `relation review`
7. 再联调 `retrieval debug`
8. 最后联调 `chat citations`

---

## 7. 测试要求

1. 路由与权限测试
2. 列表筛选与分页测试
3. 审核状态操作测试
4. debug 结果展示测试
5. source ref 跳转测试
6. section 映射审核测试
7. 关系审核测试

---

## 8. 完成定义

前端完成标准：

1. 管理员可从 UI 管理语料文件和解析任务
2. 能查看文档 block、图、表、公式等多模态内容
3. 能审核 section 映射、知识点、题目和关系
4. 能调试题目和知识点检索
5. 问答结果可展示 citations、易混点和前置点
