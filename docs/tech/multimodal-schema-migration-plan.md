# 408 多模态语料库数据结构与迁移实施清单

> 版本：v1.1  
> 日期：2026-06-11  
> 状态：可开发  
> 读者：Backend / Data / DBA / PM

---

## 1. 文档目标

本文档将 [多模态入库与检索实施设计](./multimodal-ingestion-retrieval-design.md) 进一步细化为数据库与索引层的可执行方案，覆盖：

1. MySQL 新增表和现有表扩展
2. Alembic 迁移顺序
3. Qdrant collection 规划
4. 索引与唯一约束
5. 与现有代码的兼容策略
6. 分阶段上线与回滚原则

---

## 2. 实施原则

1. `MySQL` 是业务事实源，`Qdrant` 不是事实源。
2. 任何可筛选的核心字段都必须有独立列，不能只埋在 `tags` 或 `metadata_json` 里。
3. 任何可引用的内容都必须能回溯到 `document_blocks` 或 `document_assets`。
4. `questions` 和 `knowledge_points` 继续保留为 canonical entity，不直接承担原始解析层职责。
5. 新能力上线必须兼容当前管理端已有的 `knowledge_points`、`questions`、`CrawlTask`、`DownloadedFile`。
6. 知识点关系边是业务事实的一部分，不能只存在于临时缓存、prompt 或图数据库副本中。

---

## 3. 目标数据模型总览

## 3.1 分层模型

```text
download/ 文件
    ↓
corpus_files
    ↓
parse_runs
    ↓
documents
    ├─ canonical_chapters
    ├─ document_sections
    ├─ document_section_mappings
    ├─ document_pages
    ├─ document_blocks
    └─ document_assets
    ↓
knowledge_points / questions
    ├─ knowledge_point_chapter_links
    └─ question_chapter_links
    ↓
knowledge_relations
    ↓
entity_source_links
    ↓
retrieval_segments
    ↓
Qdrant collections
```

## 3.2 与现有表关系

当前已有相关模型位置：

- [backend/app/models/mysql_models.py](/Users/golfzhang/Documents/project/my-agent/backend/app/models/mysql_models.py:401)
- [backend/app/models/mysql_models.py](/Users/golfzhang/Documents/project/my-agent/backend/app/models/mysql_models.py:453)
- [backend/app/models/mysql_models.py](/Users/golfzhang/Documents/project/my-agent/backend/app/models/mysql_models.py:530)

处理原则：

- `DownloadedFile` 保留，但后续只作为下载记录，不作为最终语料注册表
- 新增 `corpus_files` 承担“统一语料文件注册”职责
- `documents` 表是 `corpus_files` 的结构化产物
- `knowledge_points` 与 `questions` 通过 `source_document_id` 和 `entity_source_links` 关联到来源内容

---

## 4. MySQL 新增表设计

以下 SQL 为目标结构草案，最终以 Alembic 迁移为准。

## 4.1 `corpus_files`

```sql
CREATE TABLE corpus_files (
    id VARCHAR(32) PRIMARY KEY COMMENT '语料文件ID',
    source_type ENUM('crawler', 'manual', 'upload', 'import') NOT NULL COMMENT '来源类型',
    source_ref VARCHAR(255) NULL COMMENT '来源引用，例如 task_id 或 batch_id',
    file_name VARCHAR(255) NOT NULL COMMENT '文件名',
    file_ext VARCHAR(20) NOT NULL COMMENT '扩展名',
    local_path VARCHAR(500) NOT NULL COMMENT '本地路径',
    storage_uri VARCHAR(500) NULL COMMENT '对象存储URI，可为空',
    sha256 VARCHAR(64) NOT NULL COMMENT '文件哈希',
    file_size BIGINT NULL COMMENT '文件大小',
    mime_type VARCHAR(100) NULL COMMENT 'MIME类型',
    language VARCHAR(20) NULL COMMENT '文档主语言',
    doc_type ENUM('textbook', 'past_exam', 'mock_exam', 'notes', 'other') DEFAULT 'other' COMMENT '文档业务类型',
    version INT NOT NULL DEFAULT 1 COMMENT '同源版本号',
    status ENUM('pending', 'parsing', 'parsed', 'extracting', 'indexed', 'failed', 'archived') DEFAULT 'pending' COMMENT '处理状态',
    error_detail TEXT NULL COMMENT '失败原因',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_corpus_files_sha256 (sha256),
    KEY idx_corpus_files_status (status),
    KEY idx_corpus_files_source_type (source_type),
    KEY idx_corpus_files_doc_type (doc_type)
) COMMENT='统一语料文件注册表';
```

说明：

- `sha256` 唯一，用于去重
- `source_ref` 不做唯一约束，因为同一批次可能有多个文件
- `status` 是全流程状态，不是单次解析状态

## 4.2 `parse_runs`

```sql
CREATE TABLE parse_runs (
    id VARCHAR(32) PRIMARY KEY COMMENT '解析任务ID',
    corpus_file_id VARCHAR(32) NOT NULL COMMENT '语料文件ID',
    parser_name VARCHAR(50) NOT NULL COMMENT '解析器名称',
    parser_version VARCHAR(50) NOT NULL COMMENT '解析器版本',
    parse_mode ENUM('primary', 'fallback', 'retry', 'manual_fix') DEFAULT 'primary' COMMENT '解析模式',
    status ENUM('running', 'success', 'failed', 'partial') DEFAULT 'running' COMMENT '执行状态',
    page_count INT NULL COMMENT '识别页数',
    block_count INT NULL COMMENT '识别块数',
    asset_count INT NULL COMMENT '识别资产数',
    confidence DECIMAL(5,4) NULL COMMENT '整体置信度',
    error_detail TEXT NULL COMMENT '错误信息',
    metrics_json JSON NULL COMMENT '耗时与质量指标',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_parse_runs_corpus_file FOREIGN KEY (corpus_file_id) REFERENCES corpus_files(id) ON DELETE CASCADE,
    KEY idx_parse_runs_corpus_file_id (corpus_file_id),
    KEY idx_parse_runs_status (status)
) COMMENT='文档解析执行记录';
```

## 4.3 `documents`

```sql
CREATE TABLE documents (
    id VARCHAR(32) PRIMARY KEY COMMENT '文档ID',
    corpus_file_id VARCHAR(32) NOT NULL COMMENT '文件ID',
    latest_parse_run_id VARCHAR(32) NULL COMMENT '最新成功解析ID',
    title VARCHAR(255) NULL COMMENT '文档标题',
    doc_type ENUM('textbook', 'past_exam', 'mock_exam', 'notes', 'other') DEFAULT 'other' COMMENT '文档类型',
    subject_id VARCHAR(32) NULL COMMENT '主学科ID',
    source_label VARCHAR(255) NULL COMMENT '展示来源',
    exam_scope VARCHAR(50) NULL COMMENT '例如408',
    exam_year INT NULL COMMENT '真题年份',
    paper_name VARCHAR(255) NULL COMMENT '试卷名',
    language VARCHAR(20) NULL COMMENT '文档语言',
    page_count INT NULL COMMENT '页数',
    document_markdown LONGTEXT NULL COMMENT '展示Markdown',
    document_json JSON NULL COMMENT '结构化文档对象',
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '业务状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_documents_corpus_file FOREIGN KEY (corpus_file_id) REFERENCES corpus_files(id) ON DELETE CASCADE,
    KEY idx_documents_subject_id (subject_id),
    KEY idx_documents_exam_year (exam_year),
    KEY idx_documents_doc_type (doc_type),
    KEY idx_documents_status (status)
) COMMENT='正规化文档主表';
```

## 4.3A `canonical_chapters`

```sql
CREATE TABLE canonical_chapters (
    id VARCHAR(32) PRIMARY KEY COMMENT '标准章节ID',
    subject_id VARCHAR(32) NOT NULL COMMENT '学科ID',
    parent_id VARCHAR(32) NULL COMMENT '父章节ID',
    name VARCHAR(255) NOT NULL COMMENT '标准章节名称',
    aliases JSON NULL COMMENT '别名列表',
    description TEXT NULL COMMENT '章节描述',
    sort_order INT DEFAULT 0 COMMENT '排序序号',
    status ENUM('active', 'inactive') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_cc_subject (subject_id),
    KEY idx_cc_parent (parent_id),
    KEY idx_cc_status (status)
) COMMENT='标准章节体系表';
```

## 4.3B `document_sections`

```sql
CREATE TABLE document_sections (
    id VARCHAR(32) PRIMARY KEY COMMENT '文档原生section ID',
    document_id VARCHAR(32) NOT NULL COMMENT '文档ID',
    parent_section_id VARCHAR(32) NULL COMMENT '父section ID',
    title VARCHAR(255) NOT NULL COMMENT '原生标题',
    level INT NOT NULL COMMENT '标题层级',
    section_path VARCHAR(1000) NULL COMMENT '原生路径',
    page_start INT NULL COMMENT '起始页',
    page_end INT NULL COMMENT '结束页',
    block_start_id VARCHAR(32) NULL COMMENT '起始block',
    block_end_id VARCHAR(32) NULL COMMENT '结束block',
    topic_terms JSON NULL COMMENT '主题术语',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_ds_document (document_id),
    KEY idx_ds_parent (parent_section_id),
    KEY idx_ds_document_level (document_id, level)
) COMMENT='文档原生标题树表';
```

## 4.3C `document_section_mappings`

```sql
CREATE TABLE document_section_mappings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    document_section_id VARCHAR(32) NOT NULL COMMENT '原生section ID',
    canonical_chapter_id VARCHAR(32) NOT NULL COMMENT '标准章节ID',
    mapping_type ENUM('exact', 'partial', 'related') DEFAULT 'related' COMMENT '映射类型',
    confidence DECIMAL(5,4) NULL COMMENT '映射置信度',
    build_method ENUM('rule', 'llm', 'manual') DEFAULT 'llm' COMMENT '构建方式',
    review_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending' COMMENT '审核状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_dsm_section (document_section_id),
    KEY idx_dsm_chapter (canonical_chapter_id),
    KEY idx_dsm_review_status (review_status)
) COMMENT='文档section与标准章节映射表';
```

## 4.4 `document_pages`

```sql
CREATE TABLE document_pages (
    id VARCHAR(32) PRIMARY KEY COMMENT '页ID',
    document_id VARCHAR(32) NOT NULL COMMENT '文档ID',
    page_no INT NOT NULL COMMENT '页码，从1开始',
    page_image_path VARCHAR(500) NULL COMMENT '页截图路径',
    width INT NULL COMMENT '宽度',
    height INT NULL COMMENT '高度',
    rotation INT NULL COMMENT '旋转角度',
    ocr_text LONGTEXT NULL COMMENT '页级OCR文本',
    layout_json JSON NULL COMMENT '布局信息',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_document_pages_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    UNIQUE KEY uk_document_pages_doc_page (document_id, page_no),
    KEY idx_document_pages_document_id (document_id)
) COMMENT='文档页表';
```

## 4.5 `document_assets`

```sql
CREATE TABLE document_assets (
    id VARCHAR(32) PRIMARY KEY COMMENT '资产ID',
    document_id VARCHAR(32) NOT NULL COMMENT '文档ID',
    page_no INT NOT NULL COMMENT '页码',
    asset_type ENUM('figure', 'table', 'formula', 'page_crop', 'other') NOT NULL COMMENT '资产类型',
    file_path VARCHAR(500) NOT NULL COMMENT '资产文件路径',
    thumbnail_path VARCHAR(500) NULL COMMENT '缩略图路径',
    bbox JSON NULL COMMENT '坐标',
    caption_text TEXT NULL COMMENT '图表标题',
    ocr_text TEXT NULL COMMENT '图内OCR结果',
    metadata_json JSON NULL COMMENT '扩展元数据',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_document_assets_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    KEY idx_document_assets_document_page (document_id, page_no),
    KEY idx_document_assets_type (asset_type)
) COMMENT='文档图表公式资产表';
```

## 4.6 `document_blocks`

```sql
CREATE TABLE document_blocks (
    id VARCHAR(32) PRIMARY KEY COMMENT '块ID',
    document_id VARCHAR(32) NOT NULL COMMENT '文档ID',
    page_id VARCHAR(32) NULL COMMENT '页ID',
    page_no INT NOT NULL COMMENT '页码',
    block_type VARCHAR(50) NOT NULL COMMENT '块类型',
    order_no INT NOT NULL COMMENT '页内顺序',
    bbox JSON NULL COMMENT '坐标',
    content_text LONGTEXT NULL COMMENT '纯文本',
    content_md LONGTEXT NULL COMMENT 'Markdown表示',
    content_json JSON NULL COMMENT '结构化表示',
    latex LONGTEXT NULL COMMENT '公式LaTeX',
    html_table LONGTEXT NULL COMMENT '表格HTML',
    asset_id VARCHAR(32) NULL COMMENT '关联资产ID',
    confidence DECIMAL(5,4) NULL COMMENT '识别置信度',
    review_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending' COMMENT '审核状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_document_blocks_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    KEY idx_document_blocks_document_page (document_id, page_no),
    KEY idx_document_blocks_type (block_type),
    KEY idx_document_blocks_review_status (review_status)
) COMMENT='文档块表';
```

## 4.7 `entity_source_links`

```sql
CREATE TABLE entity_source_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    entity_type ENUM('knowledge', 'question') NOT NULL COMMENT '实体类型',
    entity_id VARCHAR(32) NOT NULL COMMENT '实体ID',
    document_id VARCHAR(32) NOT NULL COMMENT '文档ID',
    block_id VARCHAR(32) NOT NULL COMMENT '来源块ID',
    page_no INT NOT NULL COMMENT '页码',
    quote_text TEXT NULL COMMENT '引用文本',
    quote_role VARCHAR(50) NULL COMMENT '引用角色，例如stem/answer/definition',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_entity_source_links_entity (entity_type, entity_id),
    KEY idx_entity_source_links_document (document_id, page_no),
    KEY idx_entity_source_links_block_id (block_id)
) COMMENT='业务实体到来源块的映射表';
```

## 4.8 `retrieval_segments`

```sql
CREATE TABLE retrieval_segments (
    id VARCHAR(32) PRIMARY KEY COMMENT '检索单元ID',
    entity_type ENUM('knowledge', 'question', 'question_explanation', 'document') NOT NULL COMMENT '实体类型',
    entity_id VARCHAR(32) NOT NULL COMMENT '业务实体ID',
    document_id VARCHAR(32) NULL COMMENT '文档ID',
    segment_role VARCHAR(50) NOT NULL COMMENT '片段角色',
    subject_id VARCHAR(32) NULL COMMENT '学科ID',
    chapter_id VARCHAR(32) NULL COMMENT '章节ID',
    content_text LONGTEXT NOT NULL COMMENT '检索主文本',
    content_md LONGTEXT NULL COMMENT '展示文本',
    context_text LONGTEXT NULL COMMENT '上下文化增强文本',
    keyword_text LONGTEXT NULL COMMENT '稀疏检索文本',
    metadata_json JSON NULL COMMENT '扩展元数据',
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_retrieval_segments_entity (entity_type, entity_id),
    KEY idx_retrieval_segments_subject_chapter (subject_id, chapter_id),
    KEY idx_retrieval_segments_role (segment_role),
    KEY idx_retrieval_segments_status (status)
) COMMENT='统一检索单元表';
```

说明：

- `chapter_id` 保留为主章节过滤字段
- 多章节、映射章节、关系提示、易混知识点摘要进入 `metadata_json`
- 实体与章节的稳定多对多关系通过 link 表维护

## 4.9 `knowledge_relations`

```sql
CREATE TABLE knowledge_relations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_knowledge_id VARCHAR(32) NOT NULL COMMENT '起点知识点ID',
    target_knowledge_id VARCHAR(32) NOT NULL COMMENT '终点知识点ID',
    relation_type ENUM(
        'prerequisite',
        'contains',
        'part_of',
        'similar_to',
        'contrast_with',
        'common_confusion',
        'used_in'
    ) NOT NULL COMMENT '关系类型',
    directionality ENUM('directed', 'undirected') DEFAULT 'directed' COMMENT '关系方向性',
    strength DECIMAL(5,4) NULL COMMENT '关系强度',
    confidence DECIMAL(5,4) NULL COMMENT '构建置信度',
    source_document_id VARCHAR(32) NULL COMMENT '来源文档ID',
    evidence_json JSON NULL COMMENT '证据块与页码',
    build_method ENUM('rule', 'llm', 'manual', 'import') DEFAULT 'llm' COMMENT '构建方式',
    review_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending' COMMENT '审核状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_kr_source (source_knowledge_id),
    KEY idx_kr_target (target_knowledge_id),
    KEY idx_kr_type (relation_type),
    KEY idx_kr_review_status (review_status),
    KEY idx_kr_source_target_type (source_knowledge_id, target_knowledge_id, relation_type)
) COMMENT='知识点关系边表';
```

## 4.10 `knowledge_point_chapter_links`

```sql
CREATE TABLE knowledge_point_chapter_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    knowledge_point_id VARCHAR(32) NOT NULL COMMENT '知识点ID',
    canonical_chapter_id VARCHAR(32) NOT NULL COMMENT '标准章节ID',
    link_role ENUM('primary', 'secondary', 'related') DEFAULT 'secondary' COMMENT '归属角色',
    confidence DECIMAL(5,4) NULL COMMENT '归属置信度',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_kpcl_kp (knowledge_point_id),
    KEY idx_kpcl_chapter (canonical_chapter_id),
    KEY idx_kpcl_role (link_role)
) COMMENT='知识点章节关联表';
```

## 4.11 `question_chapter_links`

```sql
CREATE TABLE question_chapter_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    question_id VARCHAR(32) NOT NULL COMMENT '题目ID',
    canonical_chapter_id VARCHAR(32) NOT NULL COMMENT '标准章节ID',
    link_role ENUM('primary', 'secondary', 'related') DEFAULT 'secondary' COMMENT '归属角色',
    confidence DECIMAL(5,4) NULL COMMENT '归属置信度',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_qcl_question (question_id),
    KEY idx_qcl_chapter (canonical_chapter_id),
    KEY idx_qcl_role (link_role)
) COMMENT='题目章节关联表';
```

---

## 5. 现有表扩展设计

## 5.1 `knowledge_points`

建议新增字段：

```sql
ALTER TABLE knowledge_points
    ADD COLUMN canonical_title VARCHAR(255) NULL COMMENT '标准标题' AFTER title,
    ADD COLUMN summary TEXT NULL COMMENT '摘要' AFTER content,
    ADD COLUMN aliases JSON NULL COMMENT '别名列表' AFTER summary,
    ADD COLUMN topic_terms JSON NULL COMMENT '主题术语' AFTER aliases,
    ADD COLUMN modality_flags JSON NULL COMMENT '多模态标记' AFTER topic_terms,
    ADD COLUMN confusion_point_ids JSON NULL COMMENT '易混知识点ID列表' AFTER modality_flags,
    ADD COLUMN primary_chapter_id VARCHAR(32) NULL COMMENT '主归属标准章节ID' AFTER chapter_id,
    ADD COLUMN source_document_id VARCHAR(32) NULL COMMENT '来源文档ID' AFTER source,
    ADD COLUMN source_page_start INT NULL COMMENT '来源起始页' AFTER source_page,
    ADD COLUMN source_page_end INT NULL COMMENT '来源结束页' AFTER source_page_start,
    ADD COLUMN review_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending' COMMENT '审核状态' AFTER status,
    ADD COLUMN review_notes TEXT NULL COMMENT '审核备注' AFTER review_status;
```

建议索引：

```sql
ALTER TABLE knowledge_points
    ADD KEY idx_kp_source_document_id (source_document_id),
    ADD KEY idx_kp_review_status (review_status),
    ADD KEY idx_kp_primary_chapter_id (primary_chapter_id);
```

## 5.2 `questions`

建议新增字段：

```sql
ALTER TABLE questions
    ADD COLUMN exam_scope VARCHAR(50) NULL COMMENT '考试范围，例如408' AFTER source,
    ADD COLUMN paper_name VARCHAR(255) NULL COMMENT '试卷名' AFTER exam_scope,
    ADD COLUMN question_no VARCHAR(50) NULL COMMENT '题号' AFTER paper_name,
    ADD COLUMN source_type ENUM('past_exam', 'textbook_example', 'mock_exam', 'practice', 'other') DEFAULT 'other' COMMENT '题目来源类型' AFTER question_no,
    ADD COLUMN topic_terms JSON NULL COMMENT '主题术语' AFTER knowledge_point_ids,
    ADD COLUMN aliases JSON NULL COMMENT '别名词' AFTER topic_terms,
    ADD COLUMN modality_flags JSON NULL COMMENT '多模态标记' AFTER aliases,
    ADD COLUMN primary_chapter_id VARCHAR(32) NULL COMMENT '主归属标准章节ID' AFTER chapter_id,
    ADD COLUMN source_document_id VARCHAR(32) NULL COMMENT '来源文档ID' AFTER status,
    ADD COLUMN source_page_start INT NULL COMMENT '来源起始页' AFTER source_document_id,
    ADD COLUMN source_page_end INT NULL COMMENT '来源结束页' AFTER source_page_start,
    ADD COLUMN review_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending' COMMENT '审核状态' AFTER source_page_end,
    ADD COLUMN review_notes TEXT NULL COMMENT '审核备注' AFTER review_status;
```

建议索引：

```sql
ALTER TABLE questions
    ADD KEY idx_q_exam_scope (exam_scope),
    ADD KEY idx_q_paper_name (paper_name),
    ADD KEY idx_q_question_no (question_no),
    ADD KEY idx_q_source_type (source_type),
    ADD KEY idx_q_source_document_id (source_document_id),
    ADD KEY idx_q_review_status (review_status),
    ADD KEY idx_q_primary_chapter_id (primary_chapter_id),
    ADD KEY idx_q_exam_scope_year_subject (exam_scope, exam_year, subject_id);
```

## 5.3 `downloaded_files`

当前定义位置：

- [backend/app/models/mysql_models.py](/Users/golfzhang/Documents/project/my-agent/backend/app/models/mysql_models.py:530)

保留原则：

- 不删除
- 继续作为“下载来源记录”
- 新增可选关联字段，打通 `corpus_files`

建议扩展：

```sql
ALTER TABLE downloaded_files
    ADD COLUMN corpus_file_id VARCHAR(32) NULL COMMENT '统一语料文件ID' AFTER local_path;
```

---

## 6. Qdrant 设计

## 6.1 collection 规划

建议首期至少建立两个 collection：

1. `knowledge_segments`
2. `question_segments`

后续可选：

3. `question_explanation_segments`
4. `document_page_segments`
5. `asset_segments`

## 6.2 vector 规划

每条记录建议包含：

- `dense_vector`
- `sparse_vector`

后续可选：

- `late_interaction_multivector`

## 6.3 payload 标准

每个 point 至少写入：

```json
{
  "segment_id": "seg_001",
  "entity_type": "question",
  "entity_id": "q_001",
  "document_id": "doc_001",
  "segment_role": "stem",
  "subject_id": "subj_cn",
  "chapter_id": "ch_cn_04",
  "chapter_ids": ["ch_cn_04", "ch_cn_05"],
  "knowledge_point_ids": ["kp_001", "kp_002"],
  "has_relation_edges": true,
  "has_confusion_edges": true,
  "relation_keywords": ["流量控制", "拥塞控制", "滑动窗口"],
  "question_type": "choice",
  "difficulty": "medium",
  "exam_scope": "408",
  "exam_year": 2018,
  "paper_name": "2018年全国硕士研究生招生考试408",
  "question_no": "12",
  "topic_terms": ["tcp", "流量控制"],
  "modality_flags": ["has_figure"],
  "source_type": "past_exam",
  "page_no": 16,
  "status": "active"
}
```

## 6.4 payload 索引优先级

Qdrant payload 索引优先建立：

1. `entity_type`
2. `subject_id`
3. `chapter_id`
4. `question_type`
5. `difficulty`
6. `exam_scope`
7. `exam_year`
8. `source_type`
9. `status`
10. `has_confusion_edges`

## 6.5 检索字段分层

| 类型 | 存储位置 | 说明 |
|------|----------|------|
| 核心过滤字段 | MySQL 列 + Qdrant payload | 必须双写 |
| 扩展标签 | MySQL JSON + Qdrant payload | 可用于过滤或展示 |
| 检索文本 | MySQL retrieval_segments + Qdrant vectors | 用于召回 |
| 页面/引用信息 | MySQL | 用于回溯与展示 |

---

## 7. Alembic 迁移顺序

推荐拆成 8 个 revision，不建议一个 revision 塞完所有改动。

## 7.1 Revision 1：新增语料文件与解析表

目标：

- `corpus_files`
- `parse_runs`
- `documents`

命名建议：

- `add_corpus_file_pipeline_tables`

## 7.2 Revision 2：新增章节映射、页、块、资产表

目标：

- `canonical_chapters`
- `document_sections`
- `document_section_mappings`
- `document_pages`
- `document_blocks`
- `document_assets`

命名建议：

- `add_document_structure_and_layout_tables`

## 7.3 Revision 3：扩展 knowledge_points / questions / downloaded_files

目标：

- 给现有业务表加字段与索引

命名建议：

- `extend_knowledge_and_question_for_multimodal`

## 7.4 Revision 4：新增章节 link、实体引用、segment 与关系表

目标：

- `knowledge_point_chapter_links`
- `question_chapter_links`
- `entity_source_links`
- `retrieval_segments`
- `knowledge_relations`

命名建议：

- `add_entity_source_segments_and_relations`

## 7.5 Revision 5：补充历史数据与章节映射回填脚本

目标：

- 将已有 `DownloadedFile` 补注册进 `corpus_files`
- 将已有 `knowledge_points` / `questions` 补 `source_document_id`
- 将已有 `chapters` 迁移或映射为 `canonical_chapters`
- 回填 `primary_chapter_id`
- 生成初版 chapter link

说明：

- 这一步建议使用独立脚本，不直接写在 Alembic upgrade 中

## 7.6 Revision 6：章节映射构建脚本

目标：

- 为新旧文档生成 `document_sections`
- 为 `document_sections` 生成初版 `document_section_mappings`
- 为实体推导附属章节 link

说明：

- 建议使用独立脚本，不直接写在 Alembic upgrade 中
- 低置信度映射必须进入审核队列

## 7.7 Revision 7：关系构建与关系回填脚本

目标：

- 为已存在知识点生成初版 `knowledge_relations`
- 回填 `confusion_point_ids`
- 为 `retrieval_segments` 写入关系增强 metadata

说明：

- 建议使用独立脚本，不直接写在 Alembic upgrade 中
- 首版允许 rule + LLM 混合生成，但必须带 `review_status`

## 7.8 Revision 8：可选兼容清理

目标：

- 在完成新链路稳定后，清理旧字段或标记废弃字段

说明：

- 首期不要删除老字段

---

## 8. 数据回填策略

## 8.1 已有下载文件回填

来源：

- `downloaded_files`
- `download/` 目录

步骤：

1. 读取 `downloaded_files.local_path`
2. 验证文件是否存在
3. 生成 `sha256`
4. 注册到 `corpus_files`
5. 建立 `downloaded_files.corpus_file_id`

## 8.2 已有知识点与题目回填

目标：

- 老数据不能丢
- 允许以低保真模式进入新体系

策略：

1. 若老数据能映射到原始文档，则补 `source_document_id`
2. 若无法映射，则先挂到 `legacy_import` 文档
3. 为老数据生成基础 `retrieval_segments`
4. 后续允许人工重新绑定来源

---

## 9. 代码改造落点

## 9.1 后端模型

新增或修改位置建议：

- `backend/app/models/mysql_models.py`
- 新增 `backend/app/db/qdrant.py`
- 新增 `backend/app/services/corpus_service.py`
- 新增 `backend/app/services/document_parse_service.py`
- 新增 `backend/app/services/segment_service.py`

## 9.2 现有接口兼容

当前已有 PDF 入库入口：

- [backend/app/api/admin.py](/Users/golfzhang/Documents/project/my-agent/backend/app/api/admin.py:1932)

兼容要求：

1. 短期内保留 `/knowledge/ingest`
2. 内部转为调用 `corpus file register + parse pipeline`
3. 新增批量入库接口，不替换旧接口时先标记 deprecated

## 9.3 现有检索链兼容

当前向量入口：

- [backend/app/db/qdrant.py](/Users/golfzhang/Documents/project/my-agent/backend/app/db/qdrant.py:1)

接入策略：

1. 统一由 `Qdrant` 承担主检索链
2. `ChatService`、`RetrievalService`、`SegmentService` 以 `Qdrant` 为准
3. 旧文档与旧实现描述不再作为当前架构依据

---

## 10. 上线策略

## 10.1 开发环境

- 全量启用新表
- 全量启用 Qdrant collection
- 允许数据重建

## 10.2 测试环境

- 先跑 20 份代表性文档
- 完成回填验证
- 完成检索 debug 验证

## 10.3 生产环境

按以下顺序：

1. 发布数据库迁移
2. 发布注册与解析服务
3. 发布 segment 构建任务
4. 发布 Qdrant collection 初始化
5. 发布新检索接口
6. 发布前端检索页与审核页
7. 最后切换 RAG 主检索链

---

## 11. 回滚策略

1. 数据表新增类迁移优先保证可回滚
2. 不在首期删除旧表或旧字段
3. 新检索链上线前，优先保证 `Qdrant` 数据可重建、可回放
4. 任何回滚都不删除 `corpus_files`、`documents`、`document_blocks` 数据

---

## 12. 工程任务拆分

## 12.1 Backend

- 建模并提交 Alembic revision 1-4
- 封装 `QdrantClient`
- 实现回填脚本
- 实现 segment builder
- 实现 dual-write 或阶段性 write path

## 12.2 Data

- 输出 block type 标注说明
- 定义 topic_terms 规范
- 定义题目 source_type 规范
- 定义文档 doc_type 规范

## 12.3 DBA / Reviewer

- 审核索引命中路径
- 审核 JSON 字段是否过度膨胀
- 审核长文本字段与分页策略

---

## 13. 验收清单

迁移完成后，至少满足：

1. 可以从 `download/` 注册文件到 `corpus_files`
2. 可以从一份 PDF 落出 `documents/pages/blocks/assets`
3. 可以创建 `retrieval_segments`
4. `questions` 支持 `exam_scope + exam_year + subject_id` 的结构化过滤
5. 老数据不因迁移丢失
6. 新旧检索链可并行验证
