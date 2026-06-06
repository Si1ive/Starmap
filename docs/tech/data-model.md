# 数据模型设计

## 概述

StarMap 采用 **MySQL + Neo4j + ChromaDB** 的多数据库架构：

| 数据库 | 用途 | 存储内容 |
|--------|------|----------|
| **MySQL** | 主存储 | 人物、作品、关系、爬虫任务、日志等结构化数据 |
| **Neo4j** | 图数据库 | 人物关系网络、图遍历查询 |
| **ChromaDB** | 向量数据库 | 语义搜索、向量嵌入 |
| **Redis** | 缓存 | 会话、热点数据、搜索结果缓存 |

---

## MySQL 数据模型

### 数据库选型理由

- **结构化数据存储**：人物属性、作品信息等适合关系型数据库
- **事务支持**：批量导入、数据更新需要ACID保证
- **查询效率**：列表查询、分页、筛选等操作MySQL更优
- **数据完整性**：外键约束、唯一索引保证数据质量
- **运维成熟**：备份、恢复、监控工具完善

### 表结构

#### 1. persons（人物表）

```sql
CREATE TABLE persons (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识，如 person_001',
    name VARCHAR(100) NOT NULL COMMENT '中文名',
    name_en VARCHAR(100) COMMENT '英文名',
    avatar VARCHAR(500) COMMENT '头像URL',
    gender ENUM('male', 'female', 'unknown') COMMENT '性别',
    birth_date DATE COMMENT '出生日期',
    birth_place VARCHAR(200) COMMENT '出生地',
    nationality VARCHAR(50) COMMENT '国籍',
    height DECIMAL(5,2) COMMENT '身高(cm)',
    summary TEXT COMMENT '简介',
    biography LONGTEXT COMMENT '详细传记',
    popularity_score DECIMAL(5,2) COMMENT '知名度评分 0-100',
    categories JSON COMMENT '分类标签，如 ["singer", "actor"]',
    
    -- 数据状态
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '数据状态',
    data_quality_score DECIMAL(3,2) COMMENT '数据质量评分',
    
    -- 爬取信息
    crawl_source VARCHAR(50) COMMENT '数据来源：wikipedia, douban',
    crawl_url VARCHAR(500) COMMENT '原始爬取URL',
    crawl_task_id VARCHAR(32) COMMENT '关联的爬取任务ID',
    raw_data JSON COMMENT '保留原始爬取数据（清洗前）',
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 索引
    INDEX idx_name (name),
    INDEX idx_name_en (name_en),
    INDEX idx_nationality (nationality),
    INDEX idx_status (status),
    INDEX idx_birth_date (birth_date),
    INDEX idx_crawl_source (crawl_source),
    INDEX idx_created_at (created_at),
    FULLTEXT INDEX ft_summary (summary, biography)  -- 全文搜索
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人物表';
```

#### 2. works（作品表）

```sql
CREATE TABLE works (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    title VARCHAR(200) NOT NULL COMMENT '标题',
    title_en VARCHAR(200) COMMENT '英文标题',
    type ENUM('album', 'movie', 'tv', 'drama', 'book', 'single', 'ep') COMMENT '类型',
    release_date DATE COMMENT '发布日期',
    genre VARCHAR(100) COMMENT '流派/类型',
    rating DECIMAL(3,1) COMMENT '评分 0-10',
    poster VARCHAR(500) COMMENT '海报URL',
    summary TEXT COMMENT '简介',
    
    -- 数据状态
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending',
    
    -- 爬取信息
    crawl_source VARCHAR(50),
    crawl_url VARCHAR(500),
    crawl_task_id VARCHAR(32),
    raw_data JSON,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_title (title),
    INDEX idx_type (type),
    INDEX idx_release_date (release_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='作品表';
```

#### 3. person_works（人物-作品关联表）

```sql
CREATE TABLE person_works (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    person_id VARCHAR(32) NOT NULL COMMENT '人物ID',
    work_id VARCHAR(32) NOT NULL COMMENT '作品ID',
    role VARCHAR(100) COMMENT '饰演角色/职位',
    role_type ENUM('actor', 'director', 'singer', 'composer', 'producer', 'writer') COMMENT '角色类型',
    is_lead BOOLEAN DEFAULT FALSE COMMENT '是否主演/主唱',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE,
    FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE,
    UNIQUE KEY uk_person_work_role (person_id, work_id, role_type),
    INDEX idx_person_id (person_id),
    INDEX idx_work_id (work_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人物作品关联表';
```

#### 4. person_relations（人物关系表）

```sql
CREATE TABLE person_relations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_id VARCHAR(32) NOT NULL COMMENT '源人物ID',
    target_id VARCHAR(32) NOT NULL COMMENT '目标人物ID',
    relation_type ENUM('MARRIED_TO', 'COLLABORATED_WITH', 'MENTOR_OF', 'RELATIVE', 'FRIEND') 
        COMMENT '关系类型',
    properties JSON COMMENT '关系属性，如 {start_date, end_date, status, work_id}',
    confidence DECIMAL(3,2) DEFAULT 1.0 COMMENT '关系可信度 0-1',
    source VARCHAR(50) COMMENT '数据来源：wikipedia, manual, inferred',
    
    -- 验证状态
    is_verified BOOLEAN DEFAULT FALSE COMMENT '是否人工验证',
    verified_by VARCHAR(32) COMMENT '验证人',
    verified_at TIMESTAMP NULL COMMENT '验证时间',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (source_id) REFERENCES persons(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES persons(id) ON DELETE CASCADE,
    UNIQUE KEY uk_relation (source_id, target_id, relation_type),
    INDEX idx_source_id (source_id),
    INDEX idx_target_id (target_id),
    INDEX idx_relation_type (relation_type),
    INDEX idx_confidence (confidence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人物关系表';
```

#### 5. crawl_tasks（爬虫任务表）

```sql
CREATE TABLE crawl_tasks (
    id VARCHAR(32) PRIMARY KEY COMMENT '任务ID',
    name VARCHAR(200) COMMENT '任务名称',
    task_type ENUM('full', 'incremental', 'targeted', 'health_check', 'cleanup') COMMENT '任务类型',
    source VARCHAR(50) COMMENT '数据源：wikipedia, douban',
    source_id VARCHAR(32) COMMENT '爬取源ID',
    target_count INT COMMENT '计划爬取数量',
    completed_count INT DEFAULT 0 COMMENT '已完成数量',
    success_count INT DEFAULT 0 COMMENT '成功数量',
    failed_count INT DEFAULT 0 COMMENT '失败数量',
    total_requests INT DEFAULT 0 COMMENT '总请求数',
    status ENUM('pending', 'running', 'completed', 'failed', 'stopped') DEFAULT 'pending',
    progress DECIMAL(5,2) DEFAULT 0 COMMENT '进度 0-100',
    config JSON COMMENT '任务配置',
    error_message TEXT COMMENT '错误信息',
    
    -- 时间
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_by VARCHAR(32) COMMENT '创建人',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_status (status),
    INDEX idx_task_type (task_type),
    INDEX idx_source (source),
    INDEX idx_source_id (source_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='爬虫任务表';
```

#### 6. crawl_logs（爬虫日志表）

```sql
CREATE TABLE crawl_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(32) NOT NULL COMMENT '任务ID',
    source_id VARCHAR(32) COMMENT '爬取源ID',
    level ENUM('INFO', 'WARNING', 'ERROR', 'DEBUG') DEFAULT 'INFO',
    stage VARCHAR(50) COMMENT '阶段：execution/fetch/parse/validate/store/sync',
    
    -- 资源信息
    resource_url VARCHAR(500) COMMENT '爬取URL',
    resource_name VARCHAR(200) COMMENT '资源名称',
    resource_type ENUM('person', 'work', 'page') COMMENT '资源类型',
    
    -- 操作信息
    action VARCHAR(50) COMMENT '操作：download, parse, store, skip',
    status ENUM('success', 'failed', 'retry', 'pending') COMMENT '状态',
    duration_ms INT COMMENT '耗时(ms)',
    
    -- 详情
    message TEXT COMMENT '日志消息',
    error_type VARCHAR(50) COMMENT '错误类型：timeout, 404, anti_crawl, parse_error',
    error_detail TEXT COMMENT '错误详情',
    retry_count INT DEFAULT 0 COMMENT '重试次数',
    details JSON COMMENT '详细日志信息',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_task_id (task_id),
    INDEX idx_source_id (source_id),
    INDEX idx_level (level),
    INDEX idx_status (status),
    INDEX idx_resource_type (resource_type),
    INDEX idx_error_type (error_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='爬虫日志表';
```

#### 7. crawl_statistics（爬取统计表）

```sql
CREATE TABLE crawl_statistics (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(32) COMMENT '任务ID（可选，全局统计为NULL）',
    stat_date DATE COMMENT '统计日期',
    
    -- 统计维度
    source VARCHAR(50) COMMENT '数据源',
    resource_type VARCHAR(50) COMMENT '资源类型',
    
    -- 计数
    total_attempts INT DEFAULT 0 COMMENT '总尝试数',
    success_count INT DEFAULT 0 COMMENT '成功数',
    failed_count INT DEFAULT 0 COMMENT '失败数',
    retry_count INT DEFAULT 0 COMMENT '重试数',
    
    -- 性能
    avg_duration_ms INT COMMENT '平均耗时(ms)',
    max_duration_ms INT COMMENT '最大耗时(ms)',
    min_duration_ms INT COMMENT '最小耗时(ms)',
    
    -- 错误分布（JSON格式）
    error_distribution JSON COMMENT '{timeout: 5, 404: 3, ...}',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_stat (task_id, stat_date, source, resource_type),
    INDEX idx_stat_date (stat_date),
    INDEX idx_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='爬取统计表';
```

#### 8. admin_users（管理员用户表）

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='管理员用户表';
```

#### 9. audit_logs（审计日志表）

```sql
CREATE TABLE audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(32) COMMENT '操作用户',
    action VARCHAR(100) COMMENT '操作：CREATE/UPDATE/DELETE/LOGIN',
    resource_type VARCHAR(50) COMMENT '资源类型：person/work/relation',
    resource_id VARCHAR(32) COMMENT '资源ID',
    old_values JSON COMMENT '修改前的值',
    new_values JSON COMMENT '修改后的值',
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_user_id (user_id),
    INDEX idx_resource (resource_type, resource_id),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审计日志表';
```

---

## Neo4j 图模型

### 节点类型

#### Person（人物节点）

```cypher
(:Person {
  id: string,              // 与MySQL persons.id一致
  name: string,            // 中文名
  name_en: string,         // 英文名
  category: string,        // 主要分类
  popularity_score: float  // 知名度
})
```

**说明**：Neo4j中只存储人物的核心属性，详细属性在MySQL中查询。

#### Work（作品节点）

```cypher
(:Work {
  id: string,       // 与MySQL works.id一致
  title: string,    // 标题
  type: string      // 类型
})
```

### 关系类型

#### 人物-人物关系

```cypher
// 婚姻关系
(:Person)-[:MARRIED_TO {
  start_date: date,
  end_date: date,
  status: string
}]->(:Person)

// 合作关系
(:Person)-[:COLLABORATED_WITH {
  work_id: string,
  times: int
}]->(:Person)

// 师徒关系
(:Person)-[:MENTOR_OF]->(:Person)

// 亲属关系
(:Person)-[:RELATIVE {
  type: string
}]->(:Person)
```

#### 人物-作品关系

```cypher
(:Person)-[:ACTED_IN {
  role: string,
  is_lead: boolean
}]->(:Work)

(:Person)-[:DIRECTED]->(:Work)
(:Person)-[:SINGS]->(:Work)
(:Person)-[:COMPOSED]->(:Work)
```

### 索引

```cypher
// 唯一约束
CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE;

// 性能索引
CREATE INDEX person_name IF NOT EXISTS FOR (p:Person) ON (p.name);
CREATE INDEX work_title IF NOT EXISTS FOR (w:Work) ON (w.title);
```

---

## ChromaDB 向量模型

### 集合设计

| 集合名称 | 用途 | 元数据 |
|---------|------|--------|
| `persons` | 人物语义搜索 | person_id, name, categories |
| `works` | 作品语义搜索 | work_id, title, type |
| `knowledge` | 知识库问答 | source, type |

### 向量数据格式

```python
# 人物向量
{
    "id": "person_001",
    "text": "周杰伦，1979年出生于台湾，华语流行乐男歌手...",
    "embedding": [0.1, 0.2, ...],  # 1536维
    "metadata": {
        "person_id": "person_001",
        "name": "周杰伦",
        "categories": ["singer", "actor"]
    }
}

# 作品向量
{
    "id": "work_001",
    "text": "《七里香》是周杰伦2004年发行的专辑...",
    "embedding": [0.1, 0.2, ...],
    "metadata": {
        "work_id": "work_001",
        "title": "七里香",
        "type": "album"
    }
}
```

---

## 数据流

### 数据采集流程

```
维基百科页面
    ↓
HTML下载
    ↓
HTML解析（BeautifulSoup）
    ↓
原始数据提取
    ↓
数据清洗（规则+LLM）
    ↓
实体识别（NER）
    ↓
关系抽取
    ↓
数据验证
    ↓
MySQL导入（主存储）
    ↓
Neo4j同步（关系网络）
    ↓
向量生成（Embedding）
    ↓
ChromaDB导入（语义搜索）
```

### 查询流程

```
用户查询
    ↓
查询类型判断
    ├─ 直接查询（按名字/分类） → MySQL SQL查询
    ├─ 关系查询（配偶/合作） → Neo4j Cypher
    ├─ 语义搜索 → ChromaDB向量检索
    └─ 对话 → Agent Chain（多数据库聚合）
    ↓
结果聚合
    ↓
缓存存储（Redis）
    ↓
返回用户
```

---

## MySQL ↔ Neo4j 同步机制

### 同步策略

| 数据操作 | 同步方式 | 说明 |
|---------|---------|------|
| 人物创建 | 异步 | 写入MySQL后，后台任务同步到Neo4j |
| 人物更新 | 异步 | 更新MySQL后，延迟同步到Neo4j |
| 关系创建 | **同步** | 必须保证图数据库一致性 |
| 关系删除 | **同步** | 必须保证图数据库一致性 |
| 批量导入 | 异步 | 使用队列批量同步 |

### 同步服务

```python
# app/services/sync_service.py
class Neo4jSyncService:
    """MySQL到Neo4j的同步服务"""
    
    async def sync_person(self, person_id: str):
        """同步人物到Neo4j"""
        person = await mysql.get_person(person_id)
        await neo4j.merge_person(
            id=person.id,
            name=person.name,
            name_en=person.name_en,
            category=person.categories[0] if person.categories else None,
            popularity_score=person.popularity_score
        )
    
    async def sync_relation(self, relation_id: int):
        """同步关系到Neo4j"""
        relation = await mysql.get_person_relation(relation_id)
        await neo4j.merge_relation(
            source=relation.source_id,
            target=relation.target_id,
            type=relation.relation_type,
            properties=relation.properties
        )
    
    async def sync_batch(self, person_ids: List[str]):
        """批量同步"""
        for person_id in person_ids:
            await self.sync_person(person_id)
```

### 数据一致性保证

1. **写入顺序**：必须先写MySQL，再同步Neo4j
2. **失败重试**：同步失败进入死信队列，定时重试
3. **数据校验**：定期比对MySQL和Neo4j数据量
4. **全量同步**：提供手动触发全量同步的API

---

## 数据质量规则

### 必填字段

| 实体 | 必填字段 |
|------|---------|
| Person | id, name, summary |
| Work | id, title, type |
| Relation | source_id, target_id, relation_type |

### 验证规则

```python
# 人物数据验证
def validate_person(data):
    assert data['id'].startswith('person_')
    assert len(data['name']) >= 2
    assert data['popularity_score'] is None or 0 <= data['popularity_score'] <= 100
    assert data['gender'] in ['male', 'female', None]
    return True

# 关系数据验证
def validate_relationship(data):
    assert data['source_id'] != data['target_id']  # 不能自环
    assert data['relation_type'] in VALID_RELATION_TYPES
    assert data['confidence'] is None or 0 <= data['confidence'] <= 1
    return True
```

### 数据清洗规则

1. **去重**：相同ID只保留一条
2. **标准化**：日期统一为ISO格式
3. **截断**：文本字段超过长度限制时截断
4. **过滤**：删除明显错误的数据（如未来日期）
5. **补全**：通过LLM补充缺失的摘要信息

---

## 缓存策略

### Redis 键规范

```
starmap:person:{person_id}           # 人物详情缓存
starmap:person:list:{hash}           # 人物列表缓存
starmap:work:{work_id}               # 作品详情缓存
starmap:search:{query_hash}          # 搜索结果缓存
starmap:relation:{person_id}:{depth} # 关系图谱缓存
starmap:session:{session_id}         # 会话状态缓存
starmap:llm:{query_hash}             # LLM响应缓存
starmap:crawler:stats:{task_id}      # 爬取统计缓存
```

### TTL 配置

| 数据类型 | TTL | 说明 |
|---------|-----|------|
| 人物详情 | 1小时 | 频繁访问的人物 |
| 人物列表 | 5分钟 | 搜索列表缓存 |
| 作品详情 | 1小时 | 作品信息 |
| 搜索结果 | 5分钟 | 搜索关键词缓存 |
| 关系图谱 | 10分钟 | 人物关系网络 |
| 会话状态 | 1小时 | 对话上下文 |
| LLM响应 | 30分钟 | 相同问题缓存 |
| 爬取统计 | 1分钟 | 实时统计 |
