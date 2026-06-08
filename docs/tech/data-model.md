# 数据模型设计

## 概述

408考研智能学习平台采用 **MySQL + Neo4j + ChromaDB** 的多数据库架构：

| 数据库 | 用途 | 存储内容 |
|--------|------|----------|
| **MySQL** | 主存储 | 学科、章节、知识点、题目、做题记录、管理员用户 |
| **Neo4j** | 图数据库 | 知识点关联关系（前置依赖、相似、对比） |
| **ChromaDB** | 向量数据库 | 知识点语义搜索、向量嵌入 |
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
