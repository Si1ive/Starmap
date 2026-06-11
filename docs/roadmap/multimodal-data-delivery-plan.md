# 多模态语料入库与检索 - 数据交付任务单

> 版本：v1.1  
> 日期：2026-06-11  
> 状态：执行中  
> 读者：Data / PM / Backend

---

## 1. 目标

数据侧的核心职责不是“跑解析器”，而是定义语料标准、标签体系、评测集和审核规则，保证系统后续能持续提高质量。

必须交付：

1. 样本文档集
2. 文档分类规范
3. topic terms / aliases / modality flags 规范
4. 标准章节体系与标题映射规范
5. 题目与知识点标注规范
6. 知识点关系标注规范
7. 检索评测集
8. 审核作业流

---

## 2. 样本集准备

## 2.1 样本覆盖要求

首批样本至少 20 份，必须覆盖：

- 教材类 PDF
- 真题类 PDF
- 模拟题类 PDF
- 含图页
- 含公式页
- 含表格页
- 扫描质量较差页

## 2.2 样本台账字段

建议维护 `sample_corpus_registry.csv`：

- `sample_id`
- `file_name`
- `doc_type`
- `subject`
- `chapter`
- `section_style`
- `contains_figure`
- `contains_formula`
- `contains_table`
- `contains_questions`
- `quality_level`
- `remark`

---

## 3. 规范交付

## 3.1 文档分类规范

必须定义：

- `doc_type`
- `source_type`
- `question_source_type`

## 3.2 topic terms 规范

每个学科至少输出：

- 一级主题
- 二级主题
- 常见英文术语
- 常见缩写
- 同义词

例如计网：

- `tcp`
- `udp`
- `流量控制`
- `拥塞控制`
- `三次握手`
- `四次挥手`
- `滑动窗口`

## 3.3 modality flags 规范

定义：

- `has_figure`
- `has_table`
- `has_formula`
- `has_code`
- `has_options`

## 3.4 block 类型判定规范

输出一份 `block-type-guideline.md`，至少说明：

- `question_stem` 与 `paragraph` 的边界
- `question_explanation` 与 `summary` 的边界
- `formula` 与 `paragraph` 的边界
- `figure_caption` 与 `paragraph` 的边界

## 3.5 标准章节体系规范

每个学科必须输出：

- 一级标准章节
- 二级标准章节
- 常见别名
- 常见教材标题变体

例如计网中同一知识域可能出现：

- `TCP`
- `TCP协议`
- `传输控制协议`
- `TCP 传输控制`

这些不能被当成不同标准章节。

## 3.6 文档标题映射规范

每条 section 映射至少标注：

- `document_title`
- `section_title`
- `section_path`
- `subject_id`
- `canonical_chapter_id`
- `mapping_type`
- `confidence_label`

`mapping_type` 建议取值：

- `exact`
- `partial`
- `related`

## 3.7 知识点关系标注规范

首期必须支持：

- `prerequisite`
- `contrast_with`
- `common_confusion`

每条关系至少标注：

- `source_knowledge_id`
- `target_knowledge_id`
- `relation_type`
- `directionality`
- `evidence_text`
- `evidence_page`

---

## 4. 标注与评测集

## 4.1 章节映射评测集

至少 200 条 section 映射样本，标注字段：

- `sample_id`
- `document_id`
- `document_title`
- `section_title`
- `section_path`
- `subject_id`
- `canonical_chapter_id`
- `mapping_type`

## 4.2 题目抽取评测集

至少 200 条题目样本，标注字段：

- `question_id`
- `subject_id`
- `chapter_id`
- `type`
- `exam_scope`
- `exam_year`
- `paper_name`
- `question_no`
- `topic_terms`
- `knowledge_point_ids`
- `source_page_start`
- `source_page_end`

## 4.3 知识点抽取评测集

至少 200 条知识点样本，标注字段：

- `knowledge_point_id`
- `subject_id`
- `chapter_id`
- `canonical_title`
- `topic_terms`
- `source_page_start`
- `source_page_end`
- `related_point_ids`

## 4.4 知识点关系评测集

至少 200 条关系样本，标注字段：

- `source_knowledge_id`
- `target_knowledge_id`
- `relation_type`
- `directionality`
- `expected_result`

## 4.5 检索评测集

至少 100 条查询，每条标注：

- `query`
- `intent_type`
- `entity_target`
- `structured_filters`
- `expected_ids`

覆盖查询类型：

1. 精确筛题
2. 章节内知识点检索
3. 术语检索
4. 混合检索
5. 开放式问答
6. 跨章节知识点检索
7. 易混知识点区分
8. 前置知识点查询

---

## 5. 审核作业流

## 5.1 审核优先级

优先审核顺序：

1. 真题题目
2. 高频知识点
3. 低置信度章节映射
4. 易混知识点关系
5. 带图带公式题目
6. 教材知识点

## 5.2 审核动作

每条实体至少支持：

- `approve`
- `reject`
- `edit`
- `rebind source`
- `retag`

## 5.3 审核输出

审核后必须回写：

- `review_status`
- `review_notes`
- 修正后的字段

---

## 6. 与后端协作

数据侧需明确输出给后端：

1. 词表
2. 文档分类表
3. 标准章节表
4. section 映射标注样本
5. block 类型标注样本
6. 题目 / 知识点评测集
7. 关系评测集
8. 查询评测集

后端返还给数据侧：

1. parser 产出样本
2. 抽取结果样本
3. 检索结果与 debug 数据

---

## 7. 与前端协作

数据侧需协助定义：

- 审核页需要哪些字段
- 哪些字段必须可编辑
- 哪些字段只读
- topic_terms 编辑方式
- source ref 展示方式
- section 映射候选展示方式
- 关系证据展示方式

---

## 8. 完成定义

数据侧完成标准：

1. 20 份代表性样本文档准备完成
2. 文档、章节、题目、知识点、topic terms、关系规范齐全
3. 200 条章节映射评测集完成
4. 200 条题目评测集完成
5. 200 条知识点评测集完成
6. 200 条关系评测集完成
7. 100 条检索查询评测集完成
8. 审核规则可供前后端直接实现
