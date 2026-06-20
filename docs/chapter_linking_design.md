# 语料入库关联大纲章节 — 设计方案

## 一、目标

当 PDF 语料入库后，自动建立关联:
- **题目 ↔ 大纲章节**: 题目属于哪个章节
- **知识点 ↔ 大纲章节**: 知识点属于哪个章节

**最终效果**:
1. 从知识点详情页 → 查看所属大纲章节 → 查看该章节下的其他题目
2. 从题目详情页 → 查看所属章节 → 查看该章节的知识点
3. 从大纲章节页 → 查看该章节下的所有知识点和题目

---

## 二、当前状态分析

### 2.1 已有表结构

**KnowledgePointChapterLink** (知识点 ↔ 章节):
```sql
CREATE TABLE knowledge_point_chapter_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    knowledge_point_id VARCHAR(32) NOT NULL,
    canonical_chapter_id VARCHAR(32) NOT NULL,
    is_primary BOOL DEFAULT FALSE,  -- 是否主章节
    created_at DATETIME,
    UNIQUE KEY (knowledge_point_id, canonical_chapter_id)
);
```

**QuestionChapterLink** (题目 ↔ 章节):
```sql
CREATE TABLE question_chapter_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    question_id VARCHAR(32) NOT NULL,
    canonical_chapter_id VARCHAR(32) NOT NULL,
    is_primary BOOL DEFAULT FALSE,
    created_at DATETIME,
    UNIQUE KEY (question_id, canonical_chapter_id)
);
```

### 2.2 缺少字段

当前表**缺少关键字段**:
- ❌ `relevance`: 关联度分数 [0,1]（向量检索返回的相似度）
- ❌ `source`: 关联来源（document_mapping / vector_search / manual）
- ❌ `confidence`: 置信度（规则匹配 = 1.0，向量匹配 = score）

**需要迁移添加**。

### 2.3 现有关联逻辑

查看 `entity_extraction_service.py`:
- 题目/知识点抽取时，会根据 `DocumentSectionMapping` 填充 `chapter_id`
- 但 `chapter_id` 是老的 `Chapter` 表（已废弃），不是 `CanonicalChapter`

**问题**: 抽取的实体没有关联到大纲章节！

---

## 三、设计方案

### 3.1 触发时机

**方案: 审核通过后自动关联**（与富化流程一致）

```python
# review_service.py
async def review_knowledge_point(kp_id, review_status):
    # ... 原有逻辑
    await db.commit()
    
    if review_status == "approved":
        # 1. 富化（已有）
        await EnrichmentService(db).enrich_knowledge_point(kp_id)
        
        # 2. 关联大纲章节（新增）
        await ChapterLinkService(db).link_knowledge_point_to_chapters(kp_id)
```

### 3.2 匹配策略

**混合策略: 规则优先 + 向量兜底**

```python
async def link_knowledge_point_to_chapters(kp_id):
    """
    为知识点匹配大纲章节
    
    策略:
    1. 规则匹配(快速):
       - 如果知识点有 chapter_id（文档映射），检查是否有对应 CanonicalChapter
       - 或者检查文档的 DocumentSectionMapping 是否已映射到 CanonicalChapter
    
    2. 向量检索(兜底):
       - 用知识点的 title + content 生成 query embedding
       - 在 canonical_chapter segments 中检索 top-3
       - score >= 0.75 的候选建立关联
    
    3. 写入关联:
       - KnowledgePointChapterLink(
           knowledge_point_id=kp_id,
           canonical_chapter_id=chapter_id,
           relevance=score,
           source='document_mapping' / 'vector_search',
           is_primary=(规则匹配 or 最高分)
         )
    
    返回:
        {
            "linked_count": N,
            "primary_chapter": {...},
            "related_chapters": [...]
        }
    """
```

### 3.3 实现文件

**新建服务**: `app/services/chapter_link_service.py`

```python
class ChapterLinkService:
    """语料 ↔ 大纲章节关联服务"""
    
    async def link_knowledge_point_to_chapters(kp_id) -> Dict
    async def link_question_to_chapters(question_id) -> Dict
    async def _match_by_document_mapping(entity) -> Optional[str]
    async def _match_by_vector_search(entity, entity_type) -> List[Tuple[str, float]]
    async def batch_link_document(document_id) -> Dict
```

### 3.4 数据流

```
PDF 解析 → 实体抽取 → 审核通过
                          ↓
                    [ChapterLinkService]
                          ↓
            ┌─────────────┴─────────────┐
            │                           │
    规则匹配                     向量检索
  (DocumentSectionMapping)   (canonical_chapter segments)
            │                           │
            └─────────────┬─────────────┘
                          ↓
            KnowledgePointChapterLink / QuestionChapterLink
                    (relevance + source)
                          ↓
            前端展示: 知识点/题目所属章节
```

---

## 四、实施步骤

### 步骤 1: 数据表增强

**迁移**: 为 `KnowledgePointChapterLink` 和 `QuestionChapterLink` 添加字段

```sql
ALTER TABLE knowledge_point_chapter_links
    ADD COLUMN relevance DECIMAL(5,4) DEFAULT 1.0 COMMENT '关联度 [0,1]',
    ADD COLUMN source ENUM('document_mapping', 'vector_search', 'manual') DEFAULT 'manual' COMMENT '关联来源',
    ADD COLUMN created_by VARCHAR(50) COMMENT '创建方式（system/user）';

ALTER TABLE question_chapter_links
    ADD COLUMN relevance DECIMAL(5,4) DEFAULT 1.0,
    ADD COLUMN source ENUM('document_mapping', 'vector_search', 'manual') DEFAULT 'manual',
    ADD COLUMN created_by VARCHAR(50);
```

### 步骤 2: 实现 ChapterLinkService

**文件**: `app/services/chapter_link_service.py`

核心方法:
1. `link_knowledge_point_to_chapters(kp_id)`
2. `link_question_to_chapters(question_id)`
3. `_match_by_vector_search(entity, entity_type)` — 调用 retrieval_service 在 canonical_chapter segments 检索

### 步骤 3: 集成到审核流程

修改 `review_service.py`:
- `review_knowledge_point` 审核通过后调用 `ChapterLinkService`
- `review_question` 审核通过后调用 `ChapterLinkService`

### 步骤 4: API 端点

**新增/修改**:
```
POST /admin/knowledge/{kp_id}/link-chapters  # 手动触发关联
POST /admin/questions/{q_id}/link-chapters   # 手动触发关联
POST /admin/documents/{doc_id}/link-chapters # 批量关联文档下所有实体

GET /admin/knowledge/{kp_id}  # 返回 linked_chapters
GET /admin/questions/{q_id}   # 返回 linked_chapters
GET /admin/chapters/{chapter_id}/entities  # 返回该章节下的知识点和题目
```

### 步骤 5: 前端展示

**知识点/题目详情页**:
```tsx
<Card title="所属章节">
  {linkedChapters.map(ch => (
    <Tag 
      color={ch.is_primary ? 'blue' : 'default'}
      onClick={() => navigate(`/admin/chapters/${ch.id}`)}
    >
      {ch.name} ({(ch.relevance * 100).toFixed(0)}%)
      {ch.source === 'vector_search' && <Tooltip title="AI 匹配">🤖</Tooltip>}
    </Tag>
  ))}
</Card>
```

**大纲章节详情页**:
```tsx
<Tabs>
  <TabPane tab="知识点" key="kp">
    {knowledgePoints.map(kp => <KnowledgePointCard {...kp} />)}
  </TabPane>
  <TabPane tab="题目" key="q">
    {questions.map(q => <QuestionCard {...q} />)}
  </TabPane>
</Tabs>
```

---

## 五、关键技术细节

### 5.1 向量检索匹配

```python
async def _match_by_vector_search(entity, entity_type):
    """
    用实体内容在 canonical_chapter segments 中检索
    
    返回: [(chapter_id, relevance), ...]
    """
    # 1. 构造查询文本
    if entity_type == "knowledge_point":
        query_text = f"{entity.title}\n{entity.content[:500]}"
    else:  # question
        query_text = f"{entity.content}\n{''.join([opt.text for opt in entity.options[:4]])}"
    
    # 2. 生成 embedding
    embedding = await embedding_service.embed_text(query_text)
    
    # 3. Qdrant 检索（只查 canonical_chapter）
    results = qdrant_manager.search(
        collection_name=COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=embedding,
        query_filter=Filter(must=[
            FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
            FieldCondition(key="subject_id", match=MatchValue(value=entity.subject_id)),
        ]),
        limit=5
    )
    
    # 4. 聚合到 chapter_id（一个章节可能有多个 segment）
    chapter_scores = {}
    for hit in results:
        chapter_id = hit.payload["entity_id"]
        chapter_scores[chapter_id] = max(chapter_scores.get(chapter_id, 0), hit.score)
    
    # 5. 过滤低分 + 排序
    return [(cid, score) for cid, score in sorted(chapter_scores.items(), key=lambda x: -x[1]) if score >= 0.75]
```

### 5.2 规则匹配（文档映射）

```python
async def _match_by_document_mapping(entity):
    """
    检查文档section映射是否已关联到 CanonicalChapter
    
    流程:
    1. entity.source_document_id → Document
    2. Document.sections → DocumentSection (找entity所在section)
    3. DocumentSection → DocumentSectionMapping
    4. DocumentSectionMapping.canonical_chapter_id → CanonicalChapter
    
    返回: canonical_chapter_id or None
    """
    # 实现逻辑...
```

### 5.3 主章节判定

**规则**:
1. 规则匹配的章节 → `is_primary=True`（优先级最高）
2. 向量匹配时，取 `relevance` 最高的 → `is_primary=True`
3. 其他向量匹配的章节 → `is_primary=False`（相关章节）

---

## 六、验证步骤

### 1. 单元测试

```python
async def test_link_knowledge_point():
    # 1. 创建测试大纲章节（含 enhanced_description + keywords）
    chapter = CanonicalChapter(
        id=uuid4().hex,
        name="哈希表",
        enhanced_description="哈希表是基于哈希函数的键值对存储结构。常考冲突解决方法。",
        keywords=["散列表", "Hash Table", "冲突解决"]
    )
    
    # 2. 构建 segment
    await SegmentService(db).build_canonical_chapter_segments(rebuild=True)
    
    # 3. 创建知识点
    kp = KnowledgePoint(
        id=uuid4().hex,
        title="链地址法解决哈希冲突",
        content="链地址法是解决哈希冲突的常用方法...",
        subject_id=chapter.subject_id,
        review_status="approved"
    )
    await db.commit()
    
    # 4. 执行关联
    result = await ChapterLinkService(db).link_knowledge_point_to_chapters(kp.id)
    
    # 5. 验证
    assert result["linked_count"] >= 1
    assert result["primary_chapter"]["id"] == chapter.id
    assert result["primary_chapter"]["relevance"] >= 0.75
```

### 2. 端到端测试

1. 上传包含"哈希表"章节的大纲 PDF → 入库
2. 上传包含哈希表题目的试卷 PDF → 抽取题目
3. 审核通过题目 → 自动关联到"哈希表"章节
4. 查看题目详情 → 显示所属章节
5. 查看"哈希表"章节详情 → 显示关联题目

---

## 七、优化方向

### 短期（1-2周）

1. **批量关联**: 对历史数据补建关联（`batch_link_document`）
2. **关联审核**: 前端展示关联质量，支持人工调整
3. **统计报表**: 每个章节关联了多少题目/知识点

### 中期（1个月）

1. **关联强度学习**: 根据人工反馈调整 relevance 阈值
2. **多章节支持**: 一个知识点可能跨多个章节
3. **关联推荐**: 基于已关联实体推荐未关联实体

### 长期（2-3个月）

1. **知识图谱**: 章节-知识点-题目三元组构建图谱
2. **学习路径**: 根据关联自动生成学习路径
3. **个性化推荐**: 根据用户错题推荐相关章节知识点

---

## 八、总结

### 核心价值

✅ **自动化关联**: 审核通过即自动建立章节关联，无需人工标注
✅ **混合策略**: 规则快速精准 + 向量兜底召回
✅ **关联质量**: 记录 relevance 和 source，可追溯可优化
✅ **三方互联**: 章节 ↔ 知识点 ↔ 题目 形成知识网络

### 技术亮点

- 大纲增强（enhanced_description + keywords）提升匹配准确率
- 向量检索 + 规则匹配混合策略
- 审核通过自动触发，不阻塞抽取流程
- 支持批量补建历史数据

### 工作量估计

| 步骤 | 工作量 | 优先级 |
|------|--------|--------|
| 数据表增强 | 0.5h | P0 |
| ChapterLinkService | 4h | P0 |
| 集成审核流程 | 1h | P0 |
| API 端点 | 2h | P1 |
| 前端展示 | 3h | P1 |
| 批量补建工具 | 2h | P2 |

**总计**: 约 12-15 小时（2-3 个工作日）
