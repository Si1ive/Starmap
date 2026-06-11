# 多模态入库与检索 - 执行清单

> 版本：v1.0  
> 日期：2026-06-11  
> 状态：可执行  
> 读者：PM / Backend / Frontend / Data / QA

---

## 1. 文档目的

本清单将现有方案进一步细化到“工程师拿到后可以直接拆分开发”的粒度，覆盖：

1. 开发顺序
2. 后端实现项
3. 前端页面与交互项
4. 数据与审核作业项
5. 联调节点
6. 验收清单
7. 里程碑与责任矩阵
8. 接口对齐检查点

---

## 2. 总体开发顺序

严格按以下顺序推进：

1. 数据库与基础表结构
2. 文件注册、解析、block/asset 落库
3. 文档原生标题树提取
4. 标准章节体系初始化
5. 标题树到标准章节映射
6. 知识点 / 题目抽取
7. 知识点关系构建
8. segment 构建与 Qdrant 入库
9. 检索与 debug
10. 问答编排
11. 管理端审核与调试页

跳过顺序会导致返工，尤其不能在章节映射未确定前就固化实体唯一章节归属。

---

## 2.1 里程碑定义

### `M1` 解析可见

完成标准：

- `corpus_files`
- `parse_runs`
- `documents/pages/blocks/assets`
- `document_sections`

产出物：

- 文件扫描页
- 解析任务页
- 文档详情页

### `M2` 章节可映射

完成标准：

- `canonical_chapters`
- `document_section_mappings`
- section 映射审核流

产出物：

- section 映射审核页
- 标准章节初始化数据

### `M3` 实体可审核

完成标准：

- `knowledge_points`
- `questions`
- `entity_source_links`
- `primary_chapter_id`
- chapter links

产出物：

- 知识点审核页
- 题目审核页

### `M4` 关系可解释

完成标准：

- `knowledge_relations`
- 关系审核流
- debug 中 relation hits

产出物：

- 关系审核页
- relation-aware retrieval

### `M5` 问答可落地

完成标准：

- `retrieval_segments`
- `Qdrant`
- `chat citations`
- `related_knowledge`

产出物：

- 检索调试页
- 问答增强展示

---

## 3. 后端执行清单

## 3.0 责任矩阵

| 模块 | 主责 | 协作 | 交付物 |
|------|------|------|--------|
| schema / migration | Backend | Data / PM | Alembic + 回填脚本 |
| parser / section tree | Backend | Data | `documents` / `document_sections` |
| canonical chapters | Data | PM / Backend | 标准章节表 |
| section mapping | Backend | Data / PM | `document_section_mappings` |
| entity extraction | Backend | Data | `knowledge_points` / `questions` |
| relation extraction | Backend | Data | `knowledge_relations` |
| admin review UI | Frontend | Backend / PM | 审核页面 |
| retrieval / debug | Backend | Frontend / QA | search + debug API |
| acceptance / regression | QA | PM / 全员 | 验收报告 |

## 3.1 数据库与迁移

### `BE-S1` 建表顺序

必须按以下顺序：

1. `corpus_files`
2. `parse_runs`
3. `documents`
4. `canonical_chapters`
5. `document_sections`
6. `document_section_mappings`
7. `document_pages`
8. `document_blocks`
9. `document_assets`
10. `knowledge_point_chapter_links`
11. `question_chapter_links`
12. `entity_source_links`
13. `knowledge_relations`
14. `retrieval_segments`

### `BE-S2` 旧表兼容策略

- `knowledge_points.chapter_id` 与 `questions.chapter_id` 暂不删除
- 新增 `primary_chapter_id`
- 旧接口默认继续返回 `chapter_id`
- 新接口逐步补充 `primary_chapter_id` 与 `chapter_ids`

### `BE-S3` 回填顺序

1. `chapters -> canonical_chapters`
2. `downloaded_files -> corpus_files`
3. 老 `knowledge_points/questions` 回填 `source_document_id`
4. 老 `chapter_id` 回填为 `primary_chapter_id`
5. 回填章节 link
6. 回填关系边
7. 回填 segments

## 3.2 解析链路

### `BE-P1` 文件扫描接口

实现要求：

- 支持 `root_path`
- 支持 `file_types`
- 支持 `doc_type`
- 支持 `batch_label`
- 返回注册数、跳过数、失败数

### `BE-P2` 解析任务状态机

状态流转必须固定：

- `pending -> parsing -> parsed`
- `parsed -> extracting -> indexed`
- 任意阶段失败 -> `failed`

禁止出现：

- `parsed` 但无 `documents`
- `indexed` 但无 `retrieval_segments`

### `BE-P3` 文档原生标题树提取

输出规则：

- 识别 `title/heading`
- 生成层级 `level`
- 生成 `section_path`
- 关联页码区间
- 关联 block 起止

低质量文档要求：

- 即使层级不完整，也必须生成尽量可用的 section 列表
- 缺失父级时允许平铺，但要打低置信度标记

## 3.3 章节映射链路

### `BE-CM1` 标准章节初始化

首批由数据侧提供：

- 学科
- 一级章节
- 二级章节
- 别名

### `BE-CM2` section 映射算法

首版推荐三段式：

1. 规则匹配：别名、关键词、术语词表
2. 向量匹配：section 标题 + 主题术语
3. LLM 判别：对 top 候选做最终选择

### `BE-CM3` 映射审核规则

自动通过条件建议：

- `confidence >= 0.90`

人工审核条件建议：

- `0.60 <= confidence < 0.90`

自动拒绝或待补充：

- `confidence < 0.60`

## 3.4 实体抽取链路

### `BE-E1` 知识点抽取

每条知识点必须产出：

- `title`
- `canonical_title`
- `content`
- `subject_id`
- `primary_chapter_id`
- `chapter_links`
- `topic_terms`
- `aliases`
- `source refs`

### `BE-E2` 题目抽取

每条题目必须产出：

- `type`
- `content`
- `options`
- `answer`
- `explanation`
- `subject_id`
- `primary_chapter_id`
- `chapter_links`
- `exam_scope`
- `exam_year`
- `paper_name`
- `question_no`
- `knowledge_point_ids`
- `source refs`

## 3.5 关系构建链路

### `BE-R1` 首版关系来源

允许以下来源混合：

- 规则抽取
- 术语相似度
- LLM 抽取
- 人工补录

### `BE-R2` 关系优先级

首期优先保证：

1. `common_confusion`
2. `contrast_with`
3. `prerequisite`

次优先：

4. `contains`
5. `part_of`
6. `used_in`
7. `similar_to`

### `BE-R3` 关系审核要求

必须支持：

- 查看来源证据
- 修改关系类型
- 修改方向
- approve / reject

## 3.6 检索与问答

### `BE-Q1` knowledge search

必须支持：

- `subject_id`
- `chapter_id`
- `chapter_match_mode`
- `relation_options`

返回必须包含：

- 主命中知识点
- `related_knowledge`
- `source_refs`

### `BE-Q2` question search

必须支持：

- `exam_scope`
- `exam_year`
- `subject_id`
- `chapter_id`
- `chapter_match_mode`
- `topic_terms`

### `BE-Q3` retrieval debug

必须分层输出：

1. `query_understanding`
2. `filters`
3. `sparse_hits`
4. `dense_hits`
5. `relation_hits`
6. `merged_hits`
7. `reranked_hits`

### `BE-Q4` chat 编排

问答编排必须支持：

- 仅知识点
- 仅题目
- 混合
- 关系增强讲解
- citations

## 3.7 接口级开发清单

### `API-G1` 语料与解析

| 接口 | 负责人 | 依赖 | 输入重点 | 输出重点 | 验收 |
|------|--------|------|----------|----------|------|
| `POST /api/v1/admin/corpus/files/scan` | Backend | `corpus_files` | `root_path` `file_types` `doc_type` | `registered_count` `skipped_count` | 可扫描并注册 |
| `GET /api/v1/admin/corpus/files` | Backend | `corpus_files` | `status` `doc_type` `keyword` | 分页 `CorpusFile` | 可筛选 |
| `POST /api/v1/admin/corpus/files/{file_id}/parse` | Backend | `parse_runs` | `parser` `fallback_enabled` | `parse_run_id` `status` | 可触发解析 |
| `GET /api/v1/admin/corpus/parse-runs` | Backend | `parse_runs` | `status` `corpus_file_id` | 分页 `ParseRun` | 可查看执行状态 |
| `GET /api/v1/admin/corpus/documents/{document_id}` | Backend | `documents` | `document_id` | 文档详情 | 可回显基本信息 |
| `GET /api/v1/admin/corpus/documents/{document_id}/blocks` | Backend | `document_blocks` | `page_no` `block_type` `review_status` | block 列表 | 可过滤 |

### `API-G2` section 与映射

| 接口 | 负责人 | 依赖 | 输入重点 | 输出重点 | 验收 |
|------|--------|------|----------|----------|------|
| `GET /api/v1/admin/corpus/documents/{document_id}/sections` | Backend | `document_sections` | `document_id` | section tree | 可展示树结构 |
| `GET /api/v1/admin/review/sections` | Backend | `document_section_mappings` | `review_status` `subject_id` | 待审映射列表 | 可筛选 |
| `POST /api/v1/admin/review/sections/{mapping_id}` | Backend | `document_section_mappings` | `review_status` `canonical_chapter_id` `mapping_type` | 回写结果 | 可审核与改绑 |

### `API-G3` 实体与关系审核

| 接口 | 负责人 | 依赖 | 输入重点 | 输出重点 | 验收 |
|------|--------|------|----------|----------|------|
| `GET /api/v1/admin/review/knowledge` | Backend | `knowledge_points` | `review_status` `subject_id` `chapter_id` | 待审知识点 | 可筛选 |
| `GET /api/v1/admin/review/questions` | Backend | `questions` | `review_status` `exam_scope` `exam_year` | 待审题目 | 可筛选 |
| `POST /api/v1/admin/review/{entity_type}/{entity_id}` | Backend | 审核回写 | `review_status` `review_notes` | 回写结果 | 可审核 |
| `GET /api/v1/admin/review/relations` | Backend | `knowledge_relations` | `relation_type` `review_status` | 关系边列表 | 可筛选 |
| `POST /api/v1/admin/review/relations/{relation_id}` | Backend | `knowledge_relations` | `review_status` `relation_type` `directionality` | 回写结果 | 可审核与改类型 |

### `API-G4` 检索与问答

| 接口 | 负责人 | 依赖 | 输入重点 | 输出重点 | 验收 |
|------|--------|------|----------|----------|------|
| `POST /api/v1/admin/retrieval/understand` | Backend | query understanding | `query` | `structured_filters` `relation_intent` | 可解析查询 |
| `POST /api/v1/retrieval/questions/search` | Backend | retrieval | `filters` `mode` | `items` `query_info` | 可筛题 |
| `POST /api/v1/retrieval/knowledge/search` | Backend | retrieval + relations | `filters` `relation_options` | `items` `related_knowledge` | 可返回关系增强结果 |
| `POST /api/v1/retrieval/mixed/search` | Backend | retrieval | `targets` `filters` | mixed 结果 | 可混合检索 |
| `POST /api/v1/admin/retrieval/debug` | Backend | retrieval debug | `query` `filters` | `sparse_hits` `dense_hits` `relation_hits` | 可调试 |
| `POST /api/v1/chat` | Backend | chat orchestration | `message` `retrieval_options` | `citations` `related_knowledge` | 可回答并带引用 |

---

## 4. 前端执行清单

## 4.1 必增页面

### `FE-P1` 语料文件页

必须支持：

- 文件扫描
- 状态筛选
- 文档类型筛选
- 触发解析
- 跳转解析记录

### `FE-P2` 文档详情页

必须新增区域：

- 文档信息
- 页统计
- 资产预览
- 原生标题树
- 映射章节列表
- 抽取按钮
- 重建索引按钮

### `FE-P3` section 映射审核页

新增页面建议：

- `/admin/review/sections`

必须支持：

- 查看原生标题树
- 查看候选标准章节
- 调整映射类型
- approve / reject

### `FE-P4` 知识点审核页

必须新增：

- `primary_chapter_id`
- `chapter_ids`
- `related_knowledge`
- 关系边入口

### `FE-P5` 题目审核页

必须新增：

- `primary_chapter_id`
- `chapter_ids`
- 知识点绑定
- 来源跳转

### `FE-P6` 关系审核页

新增页面建议：

- `/admin/review/relations`

必须支持：

- 按 `relation_type` 过滤
- 查看 source / target 知识点
- 查看证据
- 改关系类型
- 改方向
- approve / reject

### `FE-P7` 检索调试页

必须新增面板：

- query understanding
- structured filters
- sparse hits
- dense hits
- relation hits
- rerank hits

## 4.2 关键组件

建议拆分：

- `SectionTree`
- `ChapterMappingReviewPanel`
- `ChapterLinkTagList`
- `RelationEdgeList`
- `RelationReviewDrawer`
- `RetrievalDebugSteps`

## 4.3 问答页增强

问答结果必须展示：

- 主答案
- citations
- 易混知识点
- 前置知识点
- 相关题目入口

---

## 5. 数据侧执行清单

## 5.1 标准章节体系

数据侧必须输出：

- 每学科一级章节
- 每学科二级章节
- 别名
- 常见教材中不同叫法

## 5.2 section 映射标注集

至少准备：

- 200 条 `document section -> canonical chapter` 标注样本

字段建议：

- `sample_id`
- `document_title`
- `section_title`
- `section_path`
- `subject_id`
- `canonical_chapter_id`
- `mapping_type`

## 5.3 关系标注集

至少准备：

- 200 条知识点关系标注样本

字段建议：

- `source_knowledge_id`
- `target_knowledge_id`
- `relation_type`
- `directionality`
- `evidence_text`

首批重点保证：

- `common_confusion`
- `contrast_with`
- `prerequisite`

## 5.4 查询评测集扩展

必须增加以下查询类型：

1. 跨章节知识点查询
2. 易混知识点区分查询
3. 前置知识点查询
4. 章节覆盖查询
5. 基于背景标签的题目筛选查询

---

## 6. 联调检查点

## 6.1 检查点 A：解析完成

检查：

- 文档可入库
- block 可查看
- section 树可查看

## 6.2 检查点 B：映射完成

检查：

- section 映射可写入
- 低置信度进入审核
- 知识点能拿到主章节

## 6.3 检查点 C：关系完成

检查：

- 关系边可写入
- 关系证据可回看
- 关系审核可回写

## 6.4 检查点 D：检索完成

检查：

- `chapter_match_mode` 生效
- `relation_options` 生效
- debug 可看到 relation hits

## 6.5 检查点 E：问答完成

检查：

- 回答带 citations
- 回答可补充易混点
- 回答可补充前置点

---

## 6.6 接口与数据体对齐检查点

以下检查点在每个里程碑结束时都必须执行一次。

### `ALIGN-01` 章节字段对齐

必须核对：

- `chapter_id`
- `primary_chapter_id`
- `chapter_ids`
- `chapter_match_mode`

要求：

- 后端模型、API 文档、前端类型三方一致
- 不允许后端返回了 `primary_chapter_id`，前端类型缺失
- 不允许前端依赖 `chapter_ids`，后端实际未返回

### `ALIGN-02` section 映射字段对齐

必须核对：

- `document_section_id`
- `canonical_chapter_id`
- `mapping_type`
- `confidence`
- `review_status`

要求：

- section 映射审核页只展示契约中存在的字段
- 审核提交接口字段名必须与 API 契约一致

### `ALIGN-03` 关系字段对齐

必须核对：

- `source_knowledge_id`
- `target_knowledge_id`
- `relation_type`
- `directionality`
- `evidence_json`

要求：

- 枚举值必须完全一致
- 前端筛选项不能出现文档未定义枚举

### `ALIGN-04` 检索调试字段对齐

必须核对：

- `query_understanding`
- `filters`
- `sparse_hits`
- `dense_hits`
- `relation_hits`
- `merged_hits`
- `reranked_hits`

要求：

- debug 页必须逐层消费这些字段
- 不允许只消费最终结果

### `ALIGN-05` 问答增强字段对齐

必须核对：

- `citations`
- `related_knowledge`
- `relation_type`
- `reason`

要求：

- 问答接口返回什么，前端就展示什么
- 不允许前端自己猜测关系类型文案

---

## 6.7 审核状态机

所有审核对象统一采用三态：

- `pending`
- `approved`
- `rejected`

适用对象：

- `document_blocks`
- `document_section_mappings`
- `knowledge_points`
- `questions`
- `knowledge_relations`

### `REVIEW-01` 通用规则

- 新抽取或新构建的数据默认 `pending`
- 自动高置信度通过的数据也必须可回退到人工审核
- `rejected` 不能直接进入索引发布链
- `approved` 才允许进入生产检索主链

### `REVIEW-02` section 映射审核

流转建议：

- `pending -> approved`
- `pending -> rejected`
- `approved -> pending`（人工回退复审）
- `rejected -> pending`（修正后重审）

### `REVIEW-03` 关系审核

额外要求：

- 修改 `relation_type` 或 `directionality` 后必须自动回到 `pending`
- 证据不足的关系默认不允许直接 `approved`

### `REVIEW-04` 实体审核

额外要求：

- 知识点或题目章节归属被改动时，必须触发：
  - chapter links 重算
  - segment 重建
  - relation 复核标记

---

## 6.8 验收口径

### `AC-01` 解析验收

通过条件：

- 文档可注册
- 解析成功率达到阶段目标
- page / block / asset / section 都可回显

### `AC-02` 章节映射验收

通过条件：

- section tree 可稳定生成
- section mapping 可审核
- `primary_chapter_id` 可稳定生成
- 扩展章节 link 可写入

### `AC-03` 关系验收

通过条件：

- `common_confusion`、`contrast_with`、`prerequisite` 三类关系可生成
- 每条关系可追溯证据
- 关系审核后能回写

### `AC-04` 检索验收

通过条件：

- `chapter_match_mode=strict` 与 `expanded` 结果有可解释差异
- knowledge search 能返回 `related_knowledge`
- debug 能返回 `relation_hits`

### `AC-05` 问答验收

通过条件：

- 回答带 citations
- 回答能补充易混点或前置点
- 返回内容与实际 relation edges 一致

---

## 7. 验收清单

上线前必须逐项勾选：

- 10 份样本文档完成解析
- 10 份文档都有 `document_sections`
- 80% section 映射达到可接受准确率
- 题目和知识点都能生成主章节 + 附属章节
- 易混关系、对比关系、先修关系可查
- knowledge search 返回 `related_knowledge`
- retrieval debug 返回 `relation_hits`
- chat 返回 citations 和关系增强补充

---

## 8. 建议排期

## Week 1

- Backend：完成 `M1`
- Frontend：完成文件页、解析页、文档详情页骨架
- Data：完成标准章节初版和样本文档台账
- QA：准备解析验收用例

## Week 2

- Backend：完成 `M2`
- Frontend：完成 section 映射审核页
- Data：完成 section 映射标注集首批
- QA：验证章节映射准确率与审核流

## Week 3

- Backend：完成 `M3`
- Frontend：完成知识点/题目审核页增强
- Data：完成题目 / 知识点标注样本
- QA：验证抽取质量与来源回溯

## Week 4

- Backend：完成 `M4`
- Frontend：完成关系审核页与 debug 页
- Data：完成关系标注集首批
- QA：验证 relation hits 和关系审核回写

## Week 5

- Backend：完成 `M5`
- Frontend：完成问答增强展示
- Data：补齐查询评测集
- QA：跑全链路回归和上线验收
