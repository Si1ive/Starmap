# 数据模型设计

## 概述

408考研智能学习平台采用 **MySQL + Neo4j + Qdrant + Redis** 的多数据库架构：

| 数据库 | 用途 | 存储内容 |
|--------|------|----------|
| **MySQL** | 主存储 | 学科、章节、知识点、题目、语料文件、文档、解析记录、审核状态 |
| **Neo4j** | 图数据库 | 知识点关联关系（前置依赖、相似、对比） |
| **Qdrant** | 向量数据库 | 多模态语料检索、dense/sparse 向量 |
| **Redis** | 缓存 | 会话、热点数据缓存 |

---

## MySQL 数据模型

### 核心表结构

#### 1. subjects（学科表）

```sql
CREATE TABLE subjects (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    name VARCHAR(50) NOT NULL COMMENT '学科名称',
    code VARCHAR(20) NOT NULL UNIQUE COMMENT '学科编码',
    description TEXT COMMENT '学科描述',
    icon VARCHAR(100) COMMENT '图标标识',
    sort_order INT DEFAULT 0 COMMENT '排序序号',
    status ENUM('active', 'inactive') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_subject_code (code),
    INDEX idx_subject_status (status),
    INDEX idx_subject_sort (sort_order)
) COMMENT='学科表';
```

**种子数据**（408四门学科）：

| ID | 名称 | 编码 |
|----|------|------|
| subj_ds | 数据结构 | data_structure |
| subj_co | 计算机组成原理 | computer_organization |
| subj_os | 操作系统 | operating_system |
| subj_cn | 计算机网络 | computer_network |

#### 2. chapters（章节表）

```sql
CREATE TABLE chapters (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    subject_id VARCHAR(32) NOT NULL COMMENT '所属学科ID',
    name VARCHAR(100) NOT NULL COMMENT '章节名称',
    description TEXT COMMENT '章节描述',
    sort_order INT DEFAULT 0 COMMENT '排序序号',
    status ENUM('active', 'inactive') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    INDEX idx_chapter_subject (subject_id),
    INDEX idx_chapter_sort (subject_id, sort_order)
) COMMENT='章节表';
```

#### 3. knowledge_points（知识点表）

```sql
CREATE TABLE knowledge_points (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    chapter_id VARCHAR(32) NOT NULL COMMENT '所属章节ID',
    subject_id VARCHAR(32) NOT NULL COMMENT '所属学科ID（冗余）',
    title VARCHAR(200) NOT NULL COMMENT '知识点标题',
    content TEXT NOT NULL COMMENT '知识点正文（Markdown）',
    difficulty ENUM('easy', 'medium', 'hard') DEFAULT 'medium' COMMENT '难度',
    exam_frequency ENUM('high', 'medium', 'low', 'never') DEFAULT 'medium' COMMENT '考试频率',
    tags JSON COMMENT '标签列表',
    key_points JSON COMMENT '要点列表',
    related_point_ids JSON COMMENT '关联知识点ID',
    source VARCHAR(100) COMMENT '来源，如 王道2025/第3章',
    source_page VARCHAR(20) COMMENT '来源页码',
    crawl_task_id VARCHAR(32) COMMENT '关联爬取任务ID',
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    INDEX idx_kp_chapter (chapter_id),
    INDEX idx_kp_subject (subject_id),
    INDEX idx_kp_difficulty (difficulty),
    INDEX idx_kp_exam_freq (exam_frequency),
    INDEX idx_kp_status (status),
    INDEX idx_kp_title (title)
) COMMENT='知识点表';
```

#### 4. questions（题目表）

```sql
CREATE TABLE questions (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    subject_id VARCHAR(32) NOT NULL COMMENT '所属学科ID',
    chapter_id VARCHAR(32) NOT NULL COMMENT '所属章节ID',
    type ENUM('choice', 'fill', 'judge', 'short_answer', 'design', 'analysis') NOT NULL COMMENT '题型',
    content TEXT NOT NULL COMMENT '题目正文',
    options JSON COMMENT '选择题选项，格式: [{"key":"A","text":"..."}]',
    answer TEXT NOT NULL COMMENT '标准答案',
    explanation TEXT COMMENT '解析',
    difficulty ENUM('easy', 'medium', 'hard') DEFAULT 'medium' COMMENT '难度',
    source VARCHAR(100) COMMENT '来源，如 2024年408真题',
    exam_year INT DEFAULT 0 COMMENT '真题年份，练习题为0',
    knowledge_point_ids JSON COMMENT '关联知识点ID',
    tags JSON COMMENT '标签',
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
    INDEX idx_q_subject (subject_id),
    INDEX idx_q_chapter (chapter_id),
    INDEX idx_q_type (type),
    INDEX idx_q_difficulty (difficulty),
    INDEX idx_q_exam_year (exam_year),
    INDEX idx_q_status (status)
) COMMENT='题目表';
```

#### 5. user_question_records（做题记录表）

```sql
CREATE TABLE user_question_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(50) NOT NULL COMMENT '用户会话ID',
    question_id VARCHAR(32) NOT NULL COMMENT '题目ID',
    user_answer TEXT COMMENT '用户答案',
    is_correct BOOLEAN COMMENT '是否正确',
    time_spent INT COMMENT '用时（秒）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    INDEX idx_uqr_session (session_id),
    INDEX idx_uqr_question (question_id),
    INDEX idx_uqr_created (created_at)
) COMMENT='用户做题记录表';
```

#### 6. admin_users（管理员用户表）

```sql
CREATE TABLE admin_users (
    id VARCHAR(32) PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('super_admin', 'data_admin', 'operator') DEFAULT 'operator',
    permissions JSON COMMENT '权限列表',
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP NULL,
    last_login_ip VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_username (username),
    INDEX idx_role (role),
    INDEX idx_is_active (is_active)
) COMMENT='管理员用户表';
```

---

## Neo4j 图模型

### 节点类型

#### KnowledgePoint（知识点节点）

```cypher
(:KnowledgePoint {
  id: string,              // 与MySQL knowledge_points.id一致
  title: string,           // 知识点标题
  subject: string,         // 学科名称
  difficulty: string,      // 难度: easy/medium/hard
  exam_frequency: string   // 考频: high/medium/low/never
})
```

### 关系类型

#### 知识点关联关系

```cypher
// 前置依赖
(:KnowledgePoint)-[:PREREQUISITE_OF]->(:KnowledgePoint)

// 相关知识点
(:KnowledgePoint)-[:RELATED_TO]->(:KnowledgePoint)

// 对比关系
(:KnowledgePoint)-[:COMPARED_WITH]->(:KnowledgePoint)
```

### 索引

```cypher
CREATE CONSTRAINT kp_id IF NOT EXISTS FOR (kp:KnowledgePoint) REQUIRE kp.id IS UNIQUE;
CREATE INDEX kp_subject IF NOT EXISTS FOR (kp:KnowledgePoint) ON (kp.subject);
CREATE INDEX kp_difficulty IF NOT EXISTS FOR (kp:KnowledgePoint) ON (kp.difficulty);
```

---

## ChromaDB 向量模型

### 集合设计

| 集合名称 | 用途 | 元数据 |
|---------|------|--------|
| `knowledge_points` | 知识点语义搜索 | point_id, title, subject_id, chapter_id, difficulty, exam_frequency |
| `persons` | 人物语义搜索（旧） | person_id, name, type |
| `knowledge` | 通用知识库（旧） | source, type |

### 向量数据格式

```python
# 知识点向量
{
    "id": "kp_abc123",
    "text": "二叉树的遍历。二叉树的遍历是指按某条搜索路径...",
    "embedding": [0.1, 0.2, ...],  # 向量维度取决于嵌入模型
    "metadata": {
        "point_id": "kp_abc123",
        "title": "二叉树的遍历",
        "subject_id": "subj_ds",
        "chapter_id": "ch_ds_05",
        "difficulty": "medium",
        "exam_frequency": "high"
    }
}
```

---

## 数据流

### PDF 入库流程

```
教材 PDF 文件
    ↓
pdfplumber 文本提取
    ↓
按章节标题分割
    ↓
内容分块（500-2000字）
    ↓
LLM 元数据增强（难度/考频/标签）
    ↓
KnowledgePointItem
    ↓
MySQL 存储（knowledge_points 表）
    ↓
ChromaDB 向量入库（knowledge_points 集合）
    ↓
Neo4j 图谱构建（可选）
```

### RAG 问答流程

```
用户提问
    ↓
ChromaDB 向量检索（top-5 知识点）
    ↓
构建带上下文的 prompt
    ↓
OpenAI API 生成回答
    ↓
返回回答 + 来源引用
```

---

## 缓存策略

### Redis 键规范

```
starmap:session:{session_id}         # 会话状态缓存
starmap:search:{query_hash}          # 搜索结果缓存
starmap:llm:{query_hash}             # LLM响应缓存
```

### TTL 配置

| 数据类型 | TTL | 说明 |
|---------|-----|------|
| 会话状态 | 1小时 | 对话上下文 |
| 搜索结果 | 5分钟 | 搜索关键词缓存 |
| LLM响应 | 30分钟 | 相同问题缓存 |

---

## 多模态语料库数据模型

### 语料文件与解析

#### 7. corpus_files（语料文件注册表）

```sql
CREATE TABLE corpus_files (
    id VARCHAR(32) PRIMARY KEY COMMENT '语料文件ID',
    source_type ENUM('crawler', 'manual', 'upload', 'import') NOT NULL COMMENT '来源类型',
    source_ref VARCHAR(255) COMMENT '来源引用',
    file_name VARCHAR(255) NOT NULL COMMENT '文件名',
    file_ext VARCHAR(20) NOT NULL COMMENT '扩展名',
    local_path VARCHAR(500) NOT NULL COMMENT '本地路径',
    storage_uri VARCHAR(500) COMMENT '对象存储URI',
    sha256 VARCHAR(64) NOT NULL COMMENT '文件哈希',
    file_size BIGINT COMMENT '文件大小',
    mime_type VARCHAR(100) COMMENT 'MIME类型',
    language VARCHAR(20) COMMENT '文档主语言',
    doc_type ENUM('textbook', 'past_exam', 'mock_exam', 'notes', 'other') DEFAULT 'other' COMMENT '文档业务类型',
    version INT DEFAULT 1 COMMENT '同源版本号',
    status ENUM('pending', 'parsing', 'parsed', 'extracting', 'indexed', 'failed', 'archived') DEFAULT 'pending' COMMENT '处理状态',
    error_detail TEXT COMMENT '失败原因',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_corpus_files_sha256 (sha256),
    INDEX idx_corpus_files_status (status),
    INDEX idx_corpus_files_source_type (source_type),
    INDEX idx_corpus_files_doc_type (doc_type)
) COMMENT='统一语料文件注册表';
```

#### 8. parse_runs（文档解析执行记录）

```sql
CREATE TABLE parse_runs (
    id VARCHAR(32) PRIMARY KEY COMMENT '解析任务ID',
    corpus_file_id VARCHAR(32) NOT NULL COMMENT '语料文件ID',
    parser_name VARCHAR(50) NOT NULL COMMENT '解析器名称',
    parser_version VARCHAR(50) NOT NULL COMMENT '解析器版本',
    parse_mode ENUM('primary', 'fallback', 'retry', 'manual_fix') DEFAULT 'primary' COMMENT '解析模式',
    status ENUM('running', 'success', 'failed', 'partial') DEFAULT 'running' COMMENT '执行状态',
    page_count INT COMMENT '识别页数',
    block_count INT COMMENT '识别块数',
    asset_count INT COMMENT '识别资产数',
    confidence DECIMAL(5,4) COMMENT '整体置信度',
    error_detail TEXT COMMENT '错误信息',
    metrics_json JSON COMMENT '耗时与质量指标',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (corpus_file_id) REFERENCES corpus_files(id) ON DELETE CASCADE,
    INDEX idx_parse_runs_corpus_file_id (corpus_file_id),
    INDEX idx_parse_runs_status (status)
) COMMENT='文档解析执行记录';
```

#### 9. documents（正规化文档主表）

```sql
CREATE TABLE documents (
    id VARCHAR(32) PRIMARY KEY COMMENT '文档ID',
    corpus_file_id VARCHAR(32) NOT NULL COMMENT '文件ID',
    latest_parse_run_id VARCHAR(32) COMMENT '最新成功解析ID',
    title VARCHAR(255) COMMENT '文档标题',
    doc_type ENUM('textbook', 'past_exam', 'mock_exam', 'notes', 'other') DEFAULT 'other' COMMENT '文档类型',
    subject_id VARCHAR(32) COMMENT '主学科ID',
    source_label VARCHAR(255) COMMENT '展示来源',
    exam_scope VARCHAR(50) COMMENT '例如408',
    exam_year INT COMMENT '真题年份',
    paper_name VARCHAR(255) COMMENT '试卷名',
    language VARCHAR(20) COMMENT '文档语言',
    page_count INT COMMENT '页数',
    document_markdown TEXT COMMENT '展示Markdown',
    document_json JSON COMMENT '结构化文档对象',
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '业务状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (corpus_file_id) REFERENCES corpus_files(id) ON DELETE CASCADE,
    INDEX idx_documents_corpus_file_id (corpus_file_id),
    INDEX idx_documents_subject_id (subject_id),
    INDEX idx_documents_exam_year (exam_year),
    INDEX idx_documents_doc_type (doc_type),
    INDEX idx_documents_status (status)
) COMMENT='正规化文档主表';
```

### 章节体系

#### 10. canonical_chapters（标准章节表）

```sql
CREATE TABLE canonical_chapters (
    id VARCHAR(32) PRIMARY KEY COMMENT '章节ID',
    subject_id VARCHAR(32) NOT NULL COMMENT '所属学科ID',
    parent_id VARCHAR(32) COMMENT '父章节ID',
    level INT NOT NULL DEFAULT 1 COMMENT '层级：1=一级章节，2=二级章节',
    name VARCHAR(200) NOT NULL COMMENT '标准章节名称',
    code VARCHAR(50) COMMENT '章节编码，如 CH1.2',
    aliases JSON COMMENT '别名列表',
    description TEXT COMMENT '章节描述',
    sort_order INT DEFAULT 0 COMMENT '排序序号',
    status ENUM('active', 'inactive') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES canonical_chapters(id) ON DELETE CASCADE,
    INDEX idx_canonical_chapters_subject (subject_id),
    INDEX idx_canonical_chapters_parent (parent_id),
    INDEX idx_canonical_chapters_level (level)
) COMMENT='标准章节表';
```

#### 11. document_sections（文档原生标题树）

```sql
CREATE TABLE document_sections (
    id VARCHAR(32) PRIMARY KEY COMMENT 'section ID',
    document_id VARCHAR(32) NOT NULL COMMENT '文档ID',
    parent_id VARCHAR(32) COMMENT '父section ID',
    level INT NOT NULL COMMENT '层级深度',
    title VARCHAR(500) NOT NULL COMMENT '原生标题文本',
    section_path VARCHAR(1000) NOT NULL COMMENT '完整路径',
    page_start INT COMMENT '起始页码',
    page_end INT COMMENT '结束页码',
    block_start_id VARCHAR(32) COMMENT '起始block ID',
    block_end_id VARCHAR(32) COMMENT '结束block ID',
    confidence DECIMAL(5,4) COMMENT '识别置信度',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES document_sections(id) ON DELETE CASCADE,
    INDEX idx_document_sections_document (document_id),
    INDEX idx_document_sections_parent (parent_id),
    INDEX idx_document_sections_level (level)
) COMMENT='文档原生标题树';
```

#### 12. document_section_mappings（文档section到标准章节的映射）

```sql
CREATE TABLE document_section_mappings (
    id VARCHAR(32) PRIMARY KEY COMMENT '映射ID',
    document_section_id VARCHAR(32) NOT NULL COMMENT '文档section ID',
    canonical_chapter_id VARCHAR(32) NOT NULL COMMENT '标准章节ID',
    mapping_type ENUM('exact', 'partial', 'related') DEFAULT 'exact' COMMENT '映射类型',
    confidence DECIMAL(5,4) NOT NULL COMMENT '映射置信度',
    review_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending' COMMENT '审核状态',
    review_notes TEXT COMMENT '审核备注',
    reviewed_by VARCHAR(32) COMMENT '审核人',
    reviewed_at TIMESTAMP NULL COMMENT '审核时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (document_section_id) REFERENCES document_sections(id) ON DELETE CASCADE,
    FOREIGN KEY (canonical_chapter_id) REFERENCES canonical_chapters(id) ON DELETE CASCADE,
    INDEX idx_dsm_section (document_section_id),
    INDEX idx_dsm_chapter (canonical_chapter_id),
    INDEX idx_dsm_review_status (review_status),
    INDEX idx_dsm_confidence (confidence)
) COMMENT='文档section到标准章节的映射';
```

### 实体关联

#### 13. knowledge_point_chapter_links（知识点与章节关联表）

```sql
CREATE TABLE knowledge_point_chapter_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    knowledge_point_id VARCHAR(32) NOT NULL COMMENT '知识点ID',
    canonical_chapter_id VARCHAR(32) NOT NULL COMMENT '标准章节ID',
    is_primary BOOLEAN DEFAULT FALSE COMMENT '是否主章节',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id) ON DELETE CASCADE,
    FOREIGN KEY (canonical_chapter_id) REFERENCES canonical_chapters(id) ON DELETE CASCADE,
    UNIQUE KEY uk_kp_chapter_link (knowledge_point_id, canonical_chapter_id),
    INDEX idx_kpcl_knowledge_point (knowledge_point_id),
    INDEX idx_kpcl_chapter (canonical_chapter_id)
) COMMENT='知识点与章节关联表';
```

#### 14. question_chapter_links（题目与章节关联表）

```sql
CREATE TABLE question_chapter_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    question_id VARCHAR(32) NOT NULL COMMENT '题目ID',
    canonical_chapter_id VARCHAR(32) NOT NULL COMMENT '标准章节ID',
    is_primary BOOLEAN DEFAULT FALSE COMMENT '是否主章节',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    FOREIGN KEY (canonical_chapter_id) REFERENCES canonical_chapters(id) ON DELETE CASCADE,
    UNIQUE KEY uk_q_chapter_link (question_id, canonical_chapter_id),
    INDEX idx_qcl_question (question_id),
    INDEX idx_qcl_chapter (canonical_chapter_id)
) COMMENT='题目与章节关联表';
```

#### 15. entity_source_links（实体来源引用表）

```sql
CREATE TABLE entity_source_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    entity_type ENUM('knowledge_point', 'question') NOT NULL COMMENT '实体类型',
    entity_id VARCHAR(32) NOT NULL COMMENT '实体ID',
    document_id VARCHAR(32) NOT NULL COMMENT '来源文档ID',
    page_start INT COMMENT '起始页码',
    page_end INT COMMENT '结束页码',
    block_ids JSON COMMENT '来源block ID列表',
    excerpt_text TEXT COMMENT '来源摘录文本',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    INDEX idx_esl_entity (entity_type, entity_id),
    INDEX idx_esl_document (document_id)
) COMMENT='实体来源引用表';
```

### 知识点关系

#### 16. knowledge_relations（知识点关系表）

```sql
CREATE TABLE knowledge_relations (
    id VARCHAR(32) PRIMARY KEY COMMENT '关系ID',
    source_knowledge_id VARCHAR(32) NOT NULL COMMENT '源知识点ID',
    target_knowledge_id VARCHAR(32) NOT NULL COMMENT '目标知识点ID',
    relation_type ENUM('prerequisite', 'contrast_with', 'common_confusion', 'contains', 'part_of', 'used_in', 'similar_to') NOT NULL COMMENT '关系类型',
    directionality ENUM('directed', 'undirected') DEFAULT 'directed' COMMENT '方向性',
    evidence_text TEXT COMMENT '证据文本',
    evidence_page INT COMMENT '证据页码',
    confidence DECIMAL(5,4) COMMENT '置信度',
    source_type ENUM('rule', 'llm', 'manual', 'term_similarity') DEFAULT 'llm' COMMENT '来源类型',
    review_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending' COMMENT '审核状态',
    review_notes TEXT COMMENT '审核备注',
    reviewed_by VARCHAR(32) COMMENT '审核人',
    reviewed_at TIMESTAMP NULL COMMENT '审核时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (source_knowledge_id) REFERENCES knowledge_points(id) ON DELETE CASCADE,
    FOREIGN KEY (target_knowledge_id) REFERENCES knowledge_points(id) ON DELETE CASCADE,
    INDEX idx_kr_source (source_knowledge_id),
    INDEX idx_kr_target (target_knowledge_id),
    INDEX idx_kr_type (relation_type),
    INDEX idx_kr_review_status (review_status)
) COMMENT='知识点关系表';
```

**关系类型说明**：

| 类型 | 说明 | 示例 |
|------|------|------|
| prerequisite | 先修关系 | 学习"二叉树"前需要先掌握"树的基本概念" |
| contrast_with | 对比关系 | "TCP" vs "UDP" |
| common_confusion | 易混淆 | "进程" vs "线程" |
| contains | 包含 | "数据结构"包含"线性表" |
| part_of | 属于 | "快速排序"属于"排序算法" |
| used_in | 应用于 | "哈希表"应用于"缓存设计" |
| similar_to | 相似 | "广度优先搜索"与"层次遍历" |

### 检索单元

#### 17. retrieval_segments（检索单元表）

```sql
CREATE TABLE retrieval_segments (
    id VARCHAR(32) PRIMARY KEY COMMENT 'segment ID',
    entity_type ENUM('knowledge_point', 'question') NOT NULL COMMENT '实体类型',
    entity_id VARCHAR(32) NOT NULL COMMENT '实体ID',
    document_id VARCHAR(32) COMMENT '来源文档ID',
    segment_type ENUM('content', 'title', 'explanation', 'option') DEFAULT 'content' COMMENT '段落类型',
    content_text TEXT NOT NULL COMMENT '段落文本',
    content_md TEXT COMMENT 'Markdown格式',
    sparse_text TEXT COMMENT '稀疏检索文本',
    context_text TEXT COMMENT '上下文增强文本',
    page_no INT COMMENT '页码',
    subject_id VARCHAR(32) COMMENT '学科ID',
    chapter_ids JSON COMMENT '章节ID列表',
    topic_terms JSON COMMENT '主题术语',
    metadata_json JSON COMMENT '扩展元数据',
    qdrant_point_id VARCHAR(100) COMMENT 'Qdrant point ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL,
    INDEX idx_rs_entity (entity_type, entity_id),
    INDEX idx_rs_document (document_id),
    INDEX idx_rs_subject (subject_id),
    INDEX idx_rs_segment_type (segment_type)
) COMMENT='检索单元表';
```

---

## 多模态数据流

### PDF 入库流程（新）

```
教材/真题 PDF 文件
    ↓
文件扫描注册（corpus_files）
    ↓
Docling 解析（parse_runs）
    ↓
生成 documents/pages/blocks/assets
    ↓
提取原生标题树（document_sections）
    ↓
映射到标准章节（document_section_mappings）
    ↓
抽取知识点/题目（knowledge_points/questions）
    ↓
构建知识点关系（knowledge_relations）
    ↓
构建检索单元（retrieval_segments）
    ↓
写入 Qdrant 向量库
    ↓
审核流程（review_status）
```

### 检索问答流程（新）

```
用户提问
    ↓
Query Understanding（结构化 filters + relation_intent）
    ↓
多路召回：
  - Sparse 检索（关键词匹配）
  - Dense 检索（向量相似度）
  - Relation 检索（关系增强）
    ↓
结果合并与重排
    ↓
构建带 citations 的回答
    ↓
补充易混知识点/前置知识点
    ↓
返回回答 + citations + related_knowledge
```

---

## 服务层设计

### Embedding 服务

**文件**: `backend/app/services/embedding_service.py`

封装 OpenAI text-embedding-ada-002 API，提供文本向量化能力。

| 方法 | 说明 |
|------|------|
| `embed_text(text)` | 单文本向量化，返回 1536 维浮点向量 |
| `embed_batch(texts)` | 批量向量化，自动按 100 条分批，保持顺序 |

**特性**:
- 自动预处理：去除空白、截断超长文本（8000 tokens 上限）
- 空文本返回零向量，避免 API 报错
- 全局单例模式，复用连接

### Segment 构建服务

**文件**: `backend/app/services/segment_service.py`

从已审核的知识点和题目构建检索单元，生成 embedding 并写入 Qdrant。

| 方法 | 说明 |
|------|------|
| `build_all_segments(subject_id, document_id, rebuild)` | 全量构建（知识点 + 题目） |
| `build_knowledge_segments(...)` | 仅构建知识点 segments |
| `build_question_segments(...)` | 仅构建题目 segments |

**Segment 生成规则**:

| 实体类型 | Segment 类型 | 内容 |
|----------|-------------|------|
| 知识点 | `title` | 标题 + 主题术语 |
| 知识点 | `content` | 完整内容 + 上下文增强 |
| 题目 | `title` | 题干（含题号） |
| 题目 | `explanation` | 解析 + 上下文增强 |
| 题目 | `option` | 选项文本（选择题） |

**写入流程**:
1. 查询已审核实体（`review_status == "approved"`）
2. 如 `rebuild=True`，先删除旧 segments（MySQL + Qdrant）
3. 构建 segment 数据，收集待 embedding 文本
4. 批量调用 Embedding 服务生成向量
5. 同时写入 MySQL（RetrievalSegment）和 Qdrant（PointStruct）

### 检索服务

**文件**: `backend/app/services/retrieval_service.py`

提供 dense / sparse / hybrid 三种检索模式，支持章节过滤和关系扩展。

| 方法 | 说明 |
|------|------|
| `search(query, subject_id, chapter_ids, entity_type, mode, limit)` | 统一检索入口 |
| `search_with_relations(query, subject_id, chapter_ids, limit)` | 带关系扩展的检索 |

**检索模式**:

| 模式 | 说明 |
|------|------|
| `dense` | 纯向量检索（Qdrant COSINE 相似度） |
| `sparse` | 关键词匹配（MySQL LIKE + 简单评分） |
| `hybrid` | Dense + Sparse 合并，按 0.7/0.3 权重加权 |

**Qdrant 过滤条件**:
- `subject_id`: 学科过滤（FieldCondition + MatchValue）
- `chapter_ids`: 章节过滤（FieldCondition + MatchAny）

**关系扩展流程**:
1. 先做 hybrid 检索拿到 top-K 知识点
2. 查询这些知识点的已审核关系边（prerequisite, similar_to 等）
3. 将关系关联的知识点也加入结果（默认分数 0.3）

### Chat 服务集成

**文件**: `backend/app/services/chat_service.py`

`process_chat()` 方法已接入检索服务，实现 RAG 模式：

```
用户提问 → RetrievalService.search_with_relations() → 构建上下文 → LLM 生成回答
```

**上下文构建**:
- 主检索结果（primary_results）：按相关性排序，附带来源引用 `[来源: filename 第X页]`
- 关系扩展结果（related_results）：标记为 `[关联知识]`，最多 2 条
- 无检索结果时降级为直接调用 LLM

---

## API 端点

### Segment 构建

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/admin/segments/build` | 全量构建 segments |
| POST | `/admin/segments/build/knowledge` | 构建知识点 segments |
| POST | `/admin/segments/build/questions` | 构建题目 segments |

**参数**:
- `subject_id` (可选): 学科过滤
- `document_id` (可选): 文档过滤
- `rebuild` (可选, 默认 false): 是否先删除旧 segments

### 检索调试

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/admin/search` | 检索调试接口 |
| POST | `/admin/search/with-relations` | 带关系扩展的检索 |

**请求体** (`SearchRequest`):
```json
{
    "query": "什么是二叉树的遍历",
    "subject_id": "subj_ds",
    "chapter_ids": ["ch_1", "ch_2"],
    "entity_type": "knowledge_point",
    "mode": "hybrid",
    "limit": 10
}
```
