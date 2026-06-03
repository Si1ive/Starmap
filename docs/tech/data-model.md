# 数据模型设计

## 知识图谱模型

### 实体类型（节点）

#### Person（人物）

```cypher
(:Person {
  id: string,              // 唯一标识，如 "person_001"
  name: string,            // 中文名
  name_en: string,         // 英文名
  avatar: string,          // 头像URL
  gender: string,          // 性别：male/female
  birth_date: date,        // 出生日期
  birth_place: string,     // 出生地
  nationality: string,     // 国籍
  height: float,           // 身高(cm)
  summary: string,         // 简介
  biography: string,       // 详细传记
  popularity_score: float, // 知名度评分 0-100
  created_at: datetime,    // 创建时间
  updated_at: datetime     // 更新时间
})
```

**索引：**
```cypher
CREATE INDEX person_name FOR (p:Person) ON (p.name);
CREATE INDEX person_name_en FOR (p:Person) ON (p.name_en);
CREATE INDEX person_birth_date FOR (p:Person) ON (p.birth_date);
```

#### Work（作品）

```cypher
(:Work {
  id: string,           // 唯一标识
  title: string,        // 标题
  title_en: string,     // 英文标题
  type: string,         // 类型：album/movie/tv/drama/book
  release_date: date,   // 发布日期
  genre: string,        // 流派/类型
  rating: float,        // 评分 0-10
  poster: string,       // 海报URL
  summary: string,      // 简介
  created_at: datetime
})
```

**索引：**
```cypher
CREATE INDEX work_title FOR (w:Work) ON (w.title);
CREATE INDEX work_type FOR (w:Work) ON (w.type);
CREATE INDEX work_release_date FOR (w:Work) ON (w.release_date);
```

#### Company（公司）

```cypher
(:Company {
  id: string,
  name: string,
  name_en: string,
  type: string,        // 类型：record/film/agency
  founded_date: date,
  headquarters: string,
  website: string
})
```

#### Award（奖项）

```cypher
(:Award {
  id: string,
  name: string,
  category: string,    // 奖项类别
  year: int,
  description: string
})
```

### 关系类型（边）

#### 人物-人物关系

```cypher
// 婚姻关系
(:Person)-[:MARRIED_TO {
  start_date: date,    // 结婚日期
  end_date: date,      // 离婚日期（如有）
  status: string       // active/divorced
}]->(:Person)

// 合作关系
(:Person)-[:COLLABORATED_WITH {
  work_id: string,     // 合作作品
  role1: string,       // 人物1的角色
  role2: string,       // 人物2的角色
  times: int           // 合作次数
}]->(:Person)

// 师徒关系
(:Person)-[:MENTOR_OF {
  start_date: date
}]->(:Person)

// 亲属关系
(:Person)-[:RELATIVE {
  type: string         // parent/child/sibling
}]->(:Person)
```

#### 人物-作品关系

```cypher
// 参演
(:Person)-[:ACTED_IN {
  role: string,        // 饰演角色
  is_lead: boolean     // 是否主演
}]->(:Work)

// 导演
(:Person)-[:DIRECTED {
  type: string         // director/assistant
}]->(:Work)

// 演唱/创作
(:Person)-[:SINGS]->(:Work)
(:Person)-[:COMPOSED]->(:Work)
(:Person)-[:WROTE_LYRICS]->(:Work)

// 制作
(:Person)-[:PRODUCED]->(:Work)
```

#### 人物-公司关系

```cypher
(:Person)-[:WORKS_FOR {
  start_date: date,
  end_date: date,
  role: string         // 职位
}]->(:Company)

(:Person)-[:SIGNED_WITH {
  contract_start: date,
  contract_end: date
}]->(:Company)
```

#### 人物-奖项关系

```cypher
(:Person)-[:WON {
  year: int,
  category: string,    // 获奖类别
  work_id: string      // 获奖作品
}]->(:Award)

(:Work)-[:WON {
  year: int,
  category: string
}]->(:Award)
```

### 关系索引

```cypher
CREATE INDEX rel_collaborated FOR ()-[r:COLLABORATED_WITH]-() ON (r.times);
CREATE INDEX rel_married FOR ()-[r:MARRIED_TO]-() ON (r.status);
CREATE INDEX rel_acted FOR ()-[r:ACTED_IN]-() ON (r.is_lead);
```

---

## 向量数据模型

### 人物描述向量

```python
{
  "id": "person_001",
  "text": "周杰伦，1979年出生于台湾，华语流行乐男歌手...",
  "embedding": [0.1, 0.2, ...],  // 1536维向量
  "metadata": {
    "type": "person",
    "categories": ["singer", "actor"]
  }
}
```

### 作品描述向量

```python
{
  "id": "work_001",
  "text": "《七里香》是周杰伦2004年发行的专辑...",
  "embedding": [0.1, 0.2, ...],
  "metadata": {
    "type": "work",
    "work_type": "album"
  }
}
```

---

## 缓存数据模型

### API响应缓存

```
Key: api:persons:search:周杰伦:singer:1:20
Value: {JSON响应}
TTL: 300秒
```

### 会话缓存

```
Key: session:session_123
Value: {
  "messages": [...],
  "context": {...},
  "created_at": "2024-01-01T12:00:00Z"
}
TTL: 3600秒
```

### 热点数据缓存

```
Key: hot:persons
Value: ["person_001", "person_002", ...]
TTL: 600秒
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
Neo4j导入
    ↓
向量生成（Embedding）
    ↓
ChromaDB导入
```

### 查询流程

```
用户查询
    ↓
意图识别（LLM）
    ↓
查询类型判断
    ├─ 直接查询 → Neo4j Cypher
    ├─ 语义搜索 → ChromaDB向量检索
    └─ 对话 → Agent Chain
    ↓
结果生成
    ↓
缓存存储（Redis）
    ↓
返回用户
```

---

## 数据质量规则

### 必填字段

| 实体 | 必填字段 |
|------|---------|
| Person | id, name, summary |
| Work | id, title, type |
| Company | id, name |
| Award | id, name, year |

### 数据验证规则

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
    assert data['type'] in VALID_RELATION_TYPES
    return True
```

### 数据清洗规则

1. **去重**：相同ID只保留一条
2. **标准化**：日期统一为ISO格式
3. **截断**：文本字段超过长度限制时截断
4. **过滤**：删除明显错误的数据（如未来日期）
5. **补全**：通过LLM补充缺失的摘要信息
