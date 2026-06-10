# 408 多模态语料入库与检索实施设计

> 版本：v1.0  
> 日期：2026-06-09  
> 状态：执行基线  
> 读者：Backend / Data / Frontend / PM

---

## 1. 文档目标

本文档定义 408 考研学习平台下一阶段的核心能力建设路线：

1. 将 `download/` 目录下的 PDF、DOCX、PPTX 等文件转化为可检索、可展示、可追溯的结构化语料
2. 支持从复杂文档中抽取两类核心实体：`知识点` 与 `题目`
3. 支持面向题目与知识点的分流检索，而不是把所有内容混在一个向量库里检索
4. 支持图、表、公式、文本等多模态内容的保真展示与引用
5. 为后续工程实现提供明确的数据结构、服务边界、API 草案、阶段计划和验收标准

本文档是工程团队的执行基线。后续开发以本文档为准，若有偏离，必须在 `docs/DECISIONS.md` 中记录。

配套细化文档：

- [多模态数据结构与迁移清单](./multimodal-schema-migration-plan.md)
- [多模态语料入库与检索 API 契约](../api/multimodal-retrieval-contract.md)

---

## 2. 设计结论

### 2.1 总体结论

本项目不采用“整份 PDF 切块后直接入向量库”的常规轻量 RAG 方案，而采用五层结构：

1. `原始文件层`：保留下载文件、来源、版本、哈希、处理状态
2. `文档正规化层`：保留页、块、版面顺序、公式、表格、图片、坐标
3. `业务实体层`：生成知识点、题目等标准化实体
4. `检索单元层`：面向检索构建 segment，而不是直接拿业务实体做召回
5. `索引层`：将 segment 写入向量库和关键词索引，支持过滤、混合检索和重排

### 2.2 技术路线结论

- 主存储：`MySQL`
- 检索缓存与异步任务状态：`Redis`
- 图谱增强：`Neo4j`，不作为首期阻塞项
- 目标向量库：`Qdrant`
- 现有 `ChromaDB`：保留为过渡方案，不作为终局检索底座
- 文档解析主路线：`Docling`
- 复杂页 fallback：`MinerU` 或云端文档理解服务

### 2.3 为什么目标向量库选择 Qdrant

`Milvus` 并非不可用，但从本项目当前阶段和问题形态看，`Qdrant` 更适合作为目标向量库。

核心原因如下：

1. 本项目的首要矛盾不是超大规模分布式吞吐，而是复杂过滤检索质量
2. 题目检索必须先做结构化过滤，再做 sparse/dense 检索，再做 rerank
3. 后续需要支持 `dense + sparse hybrid`、payload 过滤、按实体类型分路、多模态扩展、late interaction
4. `Qdrant` 在 payload filter、hybrid search、multivector 方向更贴合本项目落地需求

结论不是“Milvus 不好”，而是：

- 如果系统很快进入亿级向量、重分布式扩容、强集群吞吐阶段，再重新评估 `Milvus`
- 在当前阶段，先把“过滤、召回、重排、引用、展示”闭环做对，优先级高于“极致规模”

### 2.4 题目检索的核心原则

对于“找 2018 年 408 真题中关于计算机网络 TCP 的题目”这类请求，不能只依赖语义向量检索。

正确策略是：

1. 查询理解：抽取结构化条件
2. 条件过滤：先缩小候选集
3. 候选召回：在候选集内做 sparse/dense 混合检索
4. 结果精排：rerank
5. 结构化返回：题目原文、选项、答案、解析、来源页码、引用块

因此，题目与知识点都必须具备：

- 独立结构化字段
- 扩展标签字段
- 检索 segment
- 向量表示

不能只依赖单个 `tags` JSON 字段。

---

## 3. 目标架构

## 3.1 端到端流程

```text
download/ 文件
    ↓
文件注册与去重
    ↓
解析任务分发
    ↓
文档正规化
    ├─ 页级信息
    ├─ block 级信息
    ├─ 图/表/公式资产
    └─ Markdown/HTML/JSON 表示
    ↓
实体抽取
    ├─ 知识点抽取
    └─ 题目抽取
    ↓
segment 构建与上下文化增强
    ↓
索引写入
    ├─ MySQL canonical data
    ├─ Qdrant dense/sparse vectors
    ├─ Redis cache
    └─ Neo4j relations（后置）
    ↓
检索服务
    ├─ 题目检索
    ├─ 知识点检索
    ├─ 混合检索
    └─ RAG 问答
    ↓
前端展示
    ├─ 可还原内容
    ├─ 来源引用
    └─ 题目/知识点分离展示
```

## 3.2 分层职责

| 层 | 职责 | 不能承担的职责 |
|----|------|----------------|
| 原始文件层 | 存储文件来源、哈希、版本、状态 | 不能直接作为检索数据 |
| 文档正规化层 | 保留版面和多模态结构 | 不能直接作为业务展示对象 |
| 业务实体层 | 输出知识点、题目等标准实体 | 不能替代检索 segment |
| 检索单元层 | 组织召回文本、上下文、元数据 | 不能替代原始来源存储 |
| 索引层 | 实现 dense/sparse/过滤/重排 | 不能成为唯一事实来源 |

---

## 4. 文档解析设计

## 4.1 输入文件范围

首期支持：

- `pdf`
- `docx`
- `pptx`

后续扩展：

- `html`
- `md`
- 图片型扫描件

## 4.2 文件注册

`download/` 下的文件不直接被 spider 消费，而是先进入文件注册流程。

注册逻辑：

1. 扫描 `download/`
2. 计算 `sha256`
3. 判断是否已处理
4. 写入文件注册表
5. 进入待解析队列

必须支持：

- 同名不同内容文件区分
- 同内容多来源去重
- 重跑解析但保留历史版本

## 4.3 解析器策略

### 主解析器

默认使用 `Docling`，原因：

- 对 PDF / DOCX / PPTX 的统一转换能力更适合作为主干
- 输出结构化文档对象，便于保留版面顺序、标题、段落、列表、表格
- 便于后续同时生成 Markdown 和结构化 JSON

### fallback 解析器

以下场景走 fallback：

- 扫描型 PDF
- 公式密集页
- 表格复杂页
- 图片题较多的页
- 主解析器置信度过低

fallback 方案：

- `MinerU`
- 云端文档理解服务

## 4.4 正规化输出

每一份文档最终都要输出以下内容：

1. `document_markdown`
2. `document_json`
3. `page-level blocks`
4. `block bbox`
5. `figure assets`
6. `table html/json`
7. `formula latex/text`

## 4.5 block 类型

`document_blocks.block_type` 取值建议：

- `title`
- `heading`
- `paragraph`
- `list`
- `table`
- `table_caption`
- `figure`
- `figure_caption`
- `formula`
- `code`
- `question_stem`
- `question_option`
- `question_answer`
- `question_explanation`
- `example`
- `summary`
- `unknown`

---

## 5. 业务实体抽取设计

## 5.1 知识点抽取原则

知识点不是纯文本 chunk，而是结构化学习单元。抽取时必须遵循语义边界：

- 章节标题
- 小节标题
- 概念定义
- 性质/结论
- 方法/步骤
- 对比关系
- 例题说明

知识点实体至少包含：

- 标题
- 标准正文
- 学科
- 章节
- 难度
- 考频
- 关键术语
- 关联知识点
- 来源页码与 block 引用
- 多模态引用

## 5.2 题目抽取原则

题目必须被视为原子实体，不能切碎后再在回答阶段拼接。

题目实体至少包含：

- 题干
- 选项
- 标准答案
- 解析
- 题型
- 难度
- 来源信息
- 真题年份
- 题号
- 所属学科/章节
- 关联知识点
- 关键词与主题术语
- 多模态引用

## 5.3 题目与知识点的关系

题目和知识点必须解耦存储，但可以建立双向关联：

- 题目关联多个知识点
- 知识点可反查相关题目
- 解析 segment 可同时挂到题目和知识点

首期不要求自动关系抽取 100% 正确，但必须预留人工校正入口。

---

## 6. 数据结构设计

## 6.1 总体原则

- `MySQL` 存 canonical data 和管理字段
- `Qdrant` 存检索向量和 payload
- `Redis` 存缓存、任务状态、检索中间结果
- `Neo4j` 存知识点图关系，后置实现

## 6.2 新增 MySQL 表

### 6.2.1 `corpus_files`

用途：文件注册表

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | varchar(32) | 文件ID |
| `source_type` | varchar(32) | 来源类型，crawler/manual/upload |
| `source_ref` | varchar(255) | 来源引用，如 repo/task/manual batch |
| `file_name` | varchar(255) | 文件名 |
| `file_ext` | varchar(20) | 扩展名 |
| `local_path` | varchar(500) | 本地路径 |
| `sha256` | varchar(64) | 文件哈希 |
| `file_size` | bigint | 文件大小 |
| `mime_type` | varchar(100) | MIME |
| `language` | varchar(20) | 文档主语言 |
| `status` | enum | pending/parsing/parsed/failed/archived |
| `version` | int | 同源版本号 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 6.2.2 `parse_runs`

用途：每次解析执行记录

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | varchar(32) | 解析任务ID |
| `corpus_file_id` | varchar(32) | 文件ID |
| `parser_name` | varchar(50) | docling/mineru/... |
| `parser_version` | varchar(50) | 解析器版本 |
| `status` | enum | running/success/failed/partial |
| `confidence` | decimal(5,4) | 整体置信度 |
| `error_detail` | text | 异常信息 |
| `started_at` | datetime | 开始时间 |
| `completed_at` | datetime | 完成时间 |

### 6.2.3 `documents`

用途：正规化后的文档主记录

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | varchar(32) | 文档ID |
| `corpus_file_id` | varchar(32) | 文件ID |
| `parse_run_id` | varchar(32) | 最新成功解析ID |
| `title` | varchar(255) | 文档标题 |
| `doc_type` | varchar(50) | textbook/past_exam/mock/notes |
| `subject_id` | varchar(32) | 学科ID |
| `source_label` | varchar(255) | 展示来源 |
| `page_count` | int | 页数 |
| `document_markdown` | longtext | 展示友好版本 |
| `document_json` | json | 结构化版本 |
| `status` | enum | active/pending/deleted |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 6.2.4 `document_pages`

用途：页级元数据

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | varchar(32) | 页ID |
| `document_id` | varchar(32) | 文档ID |
| `page_no` | int | 页码 |
| `page_image_path` | varchar(500) | 页渲染图路径 |
| `width` | int | 宽度 |
| `height` | int | 高度 |
| `ocr_text` | longtext | 页级 OCR 文本 |
| `layout_json` | json | 版面信息 |

### 6.2.5 `document_blocks`

用途：文档 block 级原子内容

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | varchar(32) | block ID |
| `document_id` | varchar(32) | 文档ID |
| `page_id` | varchar(32) | 页ID |
| `page_no` | int | 页码冗余 |
| `block_type` | varchar(50) | block 类型 |
| `order_no` | int | 页内顺序 |
| `bbox` | json | 坐标 |
| `content_text` | longtext | 纯文本 |
| `content_md` | longtext | Markdown |
| `content_json` | json | 结构化表示 |
| `latex` | longtext | 公式 LaTeX |
| `html_table` | longtext | 表格 HTML |
| `asset_id` | varchar(32) | 关联资产 |
| `confidence` | decimal(5,4) | block 置信度 |

### 6.2.6 `document_assets`

用途：图、表截图、公式图等资产

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | varchar(32) | 资产ID |
| `document_id` | varchar(32) | 文档ID |
| `page_no` | int | 页码 |
| `asset_type` | varchar(50) | figure/table/formula/page_crop |
| `file_path` | varchar(500) | 存储路径 |
| `thumbnail_path` | varchar(500) | 缩略图路径 |
| `caption_text` | text | 标题说明 |
| `ocr_text` | text | 图内 OCR |
| `metadata` | json | 扩展信息 |

### 6.2.7 `entity_source_links`

用途：业务实体与来源块映射

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | bigint | 自增ID |
| `entity_type` | varchar(20) | knowledge/question |
| `entity_id` | varchar(32) | 业务实体ID |
| `document_id` | varchar(32) | 文档ID |
| `block_id` | varchar(32) | 来源 block |
| `page_no` | int | 页码 |
| `quote_text` | text | 引用片段 |
| `quote_role` | varchar(50) | stem/answer/explanation/definition/... |

### 6.2.8 `retrieval_segments`

用途：统一检索单元表

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | varchar(32) | segment ID |
| `entity_type` | varchar(20) | knowledge/question/question_explanation/document |
| `entity_id` | varchar(32) | 业务实体ID |
| `document_id` | varchar(32) | 文档ID |
| `segment_role` | varchar(50) | summary/body/stem/explanation/formula/table_caption |
| `subject_id` | varchar(32) | 学科ID |
| `chapter_id` | varchar(32) | 章节ID |
| `content_text` | longtext | 主检索文本 |
| `content_md` | longtext | 展示文本 |
| `context_text` | longtext | 上下文化增强文本 |
| `keyword_text` | longtext | 关键词文本，供 sparse 检索 |
| `metadata_json` | json | 扩展元数据 |
| `status` | enum | active/pending/deleted |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

## 6.3 对现有业务表的扩展

现有 `knowledge_points` 与 `questions` 表继续保留，但建议扩展字段。

当前定义位置：

- [backend/app/models/mysql_models.py](/Users/golfzhang/Documents/project/my-agent/backend/app/models/mysql_models.py:401)
- [backend/app/models/mysql_models.py](/Users/golfzhang/Documents/project/my-agent/backend/app/models/mysql_models.py:453)

### 6.3.1 `knowledge_points` 扩展字段

建议新增：

- `canonical_title`
- `summary`
- `aliases`
- `topic_terms`
- `modality_flags`
- `source_document_id`
- `source_page_start`
- `source_page_end`
- `review_status`
- `review_notes`

### 6.3.2 `questions` 扩展字段

建议新增：

- `exam_scope`，如 `408`
- `paper_name`
- `question_no`
- `source_type`，如 `past_exam` / `textbook_example` / `mock`
- `topic_terms`
- `aliases`
- `modality_flags`
- `source_document_id`
- `source_page_start`
- `source_page_end`
- `review_status`
- `review_notes`

## 6.4 标签体系设计

标签只做补充，不做核心过滤主键。

### 6.4.1 题目固定字段

题目必须具备独立字段：

- `subject_id`
- `chapter_id`
- `knowledge_point_ids`
- `type`
- `difficulty`
- `exam_scope`
- `exam_year`
- `paper_name`
- `question_no`
- `source_type`
- `status`

### 6.4.2 题目扩展标签

`topic_terms` 示例：

- `tcp`
- `三次握手`
- `流量控制`
- `拥塞控制`
- `滑动窗口`

`modality_flags` 示例：

- `has_figure`
- `has_table`
- `has_formula`
- `has_code`

## 6.5 Qdrant payload 设计

`Qdrant` 中每个 point 的 payload 至少包含：

| 字段 | 说明 |
|------|------|
| `segment_id` | segment ID |
| `entity_type` | knowledge/question/... |
| `entity_id` | 业务实体ID |
| `segment_role` | stem/explanation/body/... |
| `subject_id` | 学科 |
| `chapter_id` | 章节 |
| `knowledge_point_ids` | 关联知识点 |
| `question_type` | 题型 |
| `difficulty` | 难度 |
| `exam_scope` | 408 等 |
| `exam_year` | 真题年份 |
| `paper_name` | 试卷名 |
| `topic_terms` | 主题术语 |
| `modality_flags` | 多模态标记 |
| `source_type` | 真题/教材/模拟题 |
| `page_no` | 页码 |
| `status` | 状态 |

---

## 7. 检索策略设计

## 7.1 检索分路

系统至少支持四类检索入口：

1. `知识点检索`
2. `题目检索`
3. `混合检索`
4. `RAG 问答`

不能把这四类请求全部发到同一条召回链上。

## 7.2 查询理解

查询进入系统后先经过 `Query Understanding`，输出：

- `intent_type`
- `entity_target`
- `structured_filters`
- `semantic_query`
- `keywords`
- `must_terms`

### 示例

用户请求：

`我要找 2018 年 408 考研中关于计算机网络中 TCP 的题目`

解析结果：

```json
{
  "intent_type": "retrieve_question",
  "entity_target": "question",
  "structured_filters": {
    "exam_year": 2018,
    "exam_scope": "408",
    "subject_id": "subj_cn"
  },
  "keywords": ["TCP", "计算机网络"],
  "must_terms": ["TCP"],
  "semantic_query": "2018年408真题中关于TCP机制的题目"
}
```

## 7.3 检索模式

### 模式 A：`filter_only`

适用：

- 条件非常强
- 候选集小
- 用户要精确筛题

例子：

- 2018 年 408 计网 TCP 真题
- 操作系统 进程同步 判断题

### 模式 B：`filter + sparse`

适用：

- 术语、题号、公式符号敏感
- 关键词匹配重要

### 模式 C：`filter + dense + sparse`

适用：

- 既有结构化条件，又有语义模糊表达

### 模式 D：`filter + dense + sparse + rerank`

适用：

- 开放式复杂查询
- 混合知识点与题目召回
- 最终要用于 RAG 生成

## 7.4 推荐召回链

### 题目检索链

1. Query Understanding
2. 结构化过滤
3. sparse 检索
4. dense 检索
5. 融合
6. rerank
7. 返回题目实体

### 知识点检索链

1. Query Understanding
2. 结构化过滤
3. dense 为主，sparse 为辅
4. rerank
5. 返回知识点实体

### RAG 问答链

1. Query Understanding
2. 判断优先检索对象：知识点 / 题目 / 混合
3. 多路召回
4. 引用去重与聚合
5. 生成回答
6. 返回答案 + citation

## 7.5 为什么不能只按业务实体入向量库

如果直接把 `knowledge_points.content` 或 `questions.content` 整体写入向量库，会出现：

1. 粒度过粗，召回不稳定
2. 无法区分题干、解析、选项的重要性
3. 无法对公式、表格说明、图片说明做独立检索
4. 无法灵活做题目/知识点双路召回

因此必须引入 `retrieval_segments`。

## 7.6 contextual enrichment

每个 segment 入库前都要生成一份上下文化增强文本：

- 原始 segment 内容
- 所属文档标题
- 所属章节
- 实体类型
- 该段在文档中的角色

示例：

```text
这是一道来自 2018 年 408 真题、计算机网络章节、主题为 TCP 拥塞控制 的题目解析片段。

片段内容：
...
```

此文本用于 dense embedding，不直接用于前端展示。

---

## 8. 多模态展示设计

## 8.1 展示目标

前端最终必须能够区分并还原：

- 纯文本内容
- 题目题干与选项
- 公式
- 表格
- 图片
- 来源页码与原始截图

## 8.2 展示字段

前端实体接口至少需要返回：

- `content_md`
- `content_json`
- `assets`
- `source_refs`
- `page_refs`
- `modality_flags`

## 8.3 公式展示

公式推荐同时存：

1. `latex`
2. `plain text verbalization`
3. `source crop`

前端优先渲染 `latex`，失败时降级为纯文本。

## 8.4 表格展示

表格推荐同时存：

1. `html_table`
2. `table_json`
3. `linearized_text`

策略：

- 检索用 `linearized_text`
- 展示用 `html_table`
- 数据处理用 `table_json`

---

## 9. 服务边界与模块拆分

## 9.1 后端新增模块建议

建议在 `backend/app/services/` 下新增：

- `corpus_service.py`
- `document_parse_service.py`
- `entity_extraction_service.py`
- `segment_service.py`
- `retrieval_service.py`
- `rerank_service.py`
- `review_service.py`

建议在 `backend/app/db/` 下新增：

- `qdrant.py`

建议在 `backend/app/api/admin.py` 基础上逐步拆分：

- `api/admin_ingest.py`
- `api/admin_knowledge.py`
- `api/admin_questions.py`
- `api/admin_retrieval.py`

## 9.2 阶段性复用现有能力

现有 PDF 入库入口可作为过渡任务入口，位置如下：

- [backend/app/api/admin.py](/Users/golfzhang/Documents/project/my-agent/backend/app/api/admin.py:1923)

但后续必须升级为：

- 面向 `corpus_files`
- 支持目录扫描
- 支持多文件批次
- 支持解析结果审核
- 支持重建索引

## 9.3 前端新增页面建议

管理端新增：

- 语料文件列表
- 解析任务列表
- 文档详情页
- block 查看页
- 题目审核页
- 知识点审核页
- 检索调试页

---

## 10. API 草案

## 10.1 入库管理

### `POST /api/v1/admin/corpus/files/scan`

用途：扫描 `download/` 并注册文件

请求：

```json
{
  "root_path": "download",
  "file_types": ["pdf", "docx", "pptx"],
  "batch_label": "2026-06-09-download-bootstrap"
}
```

### `POST /api/v1/admin/corpus/files/{id}/parse`

用途：触发单文件解析

### `POST /api/v1/admin/corpus/parse-runs/{id}/extract`

用途：根据解析结果抽取知识点与题目

### `POST /api/v1/admin/corpus/documents/{id}/index`

用途：重建 segment 与向量索引

## 10.2 检索接口

### `POST /api/v1/retrieval/questions/search`

请求：

```json
{
  "query": "2018年408计算机网络TCP题目",
  "filters": {
    "exam_year": 2018,
    "exam_scope": "408",
    "subject_id": "subj_cn"
  },
  "mode": "hybrid",
  "top_k": 20
}
```

### `POST /api/v1/retrieval/knowledge/search`

用途：知识点检索

### `POST /api/v1/retrieval/mixed/search`

用途：题目 + 知识点混合检索

## 10.3 调试接口

### `POST /api/v1/admin/retrieval/debug`

返回：

- query 理解结果
- 过滤条件
- dense 命中
- sparse 命中
- rerank 前后结果

该接口是首期必须实现的工程调试能力。

---

## 11. 开发流程与阶段安排

## 11.1 Phase 0：方案落地与技术预研

目标：

- 锁定数据结构
- 跑通解析器 PoC
- 确认 Qdrant 与 Chroma 过渡方案

任务：

- Data：准备 20 份代表性样本文件
- Backend：完成表设计与 client 封装 PoC
- Frontend：设计文档详情与审核页原型
- PM：确定验收集和优先级

验收：

- 20 份样本完成结构化解析对比
- 明确主解析器与 fallback 策略

## 11.2 Phase 1：文档正规化层

目标：

- 完成 `download/ -> corpus_files -> documents -> blocks`

任务：

- 扫描注册
- 解析任务
- block 与资产落库
- Markdown/JSON 双表示

验收：

- 90% 样本文件成功产出 block 数据
- 页码、顺序、公式、表格可回显

## 11.3 Phase 2：实体抽取层

目标：

- 从 block 抽取知识点与题目

任务：

- 知识点抽取
- 题目抽取
- entity-source mapping
- 审核队列

验收：

- 题目实体完整率 >= 90%
- 知识点标题与正文边界错误率 < 10%

## 11.4 Phase 3：检索层

目标：

- 实现题目/知识点分路检索

任务：

- segment 构建
- Qdrant payload 设计
- dense/sparse/hybrid
- rerank
- debug 接口

验收：

- 结构化题目检索支持年份/学科/题型过滤
- Top-10 召回可解释、可回放

## 11.5 Phase 4：RAG 问答层

目标：

- 基于分路检索构建最终问答

任务：

- 多路召回
- citation 聚合
- 回答生成
- 失败降级

验收：

- 回答必须附来源
- 用户可切换“仅看题目”或“仅看知识点”

## 11.6 Phase 5：多模态增强与图谱层

目标：

- 支持图片题、公式题、图谱推荐

任务：

- page-level / asset-level retrieval
- late interaction 或 multivector 检索
- 知识点关系图谱增强

---

## 12. 角色分工建议

## 12.1 Backend

- 设计并实现 MySQL 新表
- 设计 Qdrant client 与索引写入
- 实现查询理解、检索编排、rerank、debug API
- 实现审核、重建索引、任务状态接口

## 12.2 Data

- 维护解析规则、术语词表、章节映射
- 定义题型/主题词/标签体系
- 标注评测集
- 校验解析和抽取质量

## 12.3 Frontend

- 实现文档查看、block 查看、题目/知识点审核
- 实现结构化检索页面
- 支持公式、表格、图片的保真展示
- 支持引用回跳到页码和截图

## 12.4 PM

- 确定优先样本集
- 定义验收查询集
- 管理阶段边界
- 控制不要在 Phase 1 就过早追求图谱和复杂 Agent

---

## 13. 验收指标

## 13.1 解析层指标

- 文件解析成功率
- 页级顺序正确率
- 公式提取成功率
- 表格还原成功率
- 图片资产关联率

## 13.2 抽取层指标

- 题目完整率
- 知识点边界正确率
- 题目与知识点关联准确率
- 来源引用正确率

## 13.3 检索层指标

- Filter precision
- Recall@5 / Recall@10
- MRR / nDCG
- rerank 提升幅度
- 用户 query 成功率

## 13.4 问答层指标

- citation 命中率
- hallucination rate
- “无相关内容”识别准确率

---

## 14. 风险与约束

1. 扫描型 PDF 会严重影响抽取质量，必须尽早验证 fallback
2. 题目抽取如果没有审核队列，后期质量成本会很高
3. 如果继续直接用 `knowledge_points` 作为唯一检索单元，后续会返工
4. 如果把核心过滤字段放进 `tags` 而不是独立列，后续筛题准确率会失控
5. 如果没有评测集，就无法客观比较解析器、embedding、rerank 策略

---

## 15. 与现有系统的衔接策略

## 15.1 保留

- 现有 `knowledge_points` 和 `questions` 管理页
- 现有 `CrawlTask`、`DownloadedFile`、爬虫队列和任务监控能力
- 现有 Redis / MySQL 基础设施

## 15.2 逐步替换

- `ChromaDB` 从主检索库降级为过渡或兼容方案
- 现有 `ingest_pdf` 从单 PDF 入口升级为文件注册与批处理入口
- 现有 `ChatService` 从单路知识点检索升级为多路检索编排

现有相关代码位置：

- [backend/app/api/admin.py](/Users/golfzhang/Documents/project/my-agent/backend/app/api/admin.py:1932)
- [backend/app/db/chroma.py](/Users/golfzhang/Documents/project/my-agent/backend/app/db/chroma.py:408)
- [backend/app/services/chat_service.py](/Users/golfzhang/Documents/project/my-agent/backend/app/services/chat_service.py:147)

---

## 16. 交付顺序建议

严格按下列顺序开发，不建议跳步：

1. 文件注册与解析落库
2. 文档 block 和资产可视化
3. 知识点与题目抽取
4. 审核与校正
5. segment 构建
6. Qdrant 索引与 hybrid 检索
7. query understanding 与 debug 接口
8. RAG 问答
9. 多模态视觉检索
10. 图谱增强

---

## 17. 本阶段禁止事项

1. 禁止直接把整份 PDF 切块后当最终方案上线
2. 禁止把题目与知识点混在同一检索链中不做分流
3. 禁止只依赖 `tags` 做题目筛选
4. 禁止先做复杂 Agent 编排而不做检索可解释性
5. 禁止没有评测集就切换 embedding / rerank 模型
