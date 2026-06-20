# 章节关联功能使用指南

## 一、功能概述

语料（题目/知识点）审核通过后，**自动建立与大纲章节的关联**，实现知识网络互联。

### 核心价值

✅ **自动化**: 审核通过即自动关联，无需人工标注  
✅ **智能匹配**: 3 层策略（existing → document_mapping → vector_search）  
✅ **质量追溯**: 记录 relevance 和 source，可审核优化  
✅ **知识互联**: 章节 ↔ 知识点 ↔ 题目 三方互通  

---

## 二、使用流程

### 2.1 自动关联（推荐）

**触发时机**: 知识点/题目审核通过

```python
# 前端调用审核 API
POST /api/v1/admin/knowledge/{kp_id}/review
{
    "review_status": "approved",
    "review_notes": "内容准确"
}

# 后端自动执行:
# 1. 更新审核状态 → commit
# 2. 富化（生成摘要/别名）
# 3. 关联大纲章节 ← 自动触发

# 响应包含关联结果:
{
    "code": 0,
    "data": {
        "id": "...",
        "review_status": "approved",
        "enrich": {...},
        "chapter_link": {
            "linked_count": 2,
            "primary_chapter": {
                "id": "...",
                "name": "哈希表",
                "relevance": 0.92,
                "source": "vector_search"
            },
            "related_chapters": [
                {
                    "id": "...",
                    "name": "数据结构基础",
                    "relevance": 0.78,
                    "source": "vector_search"
                }
            ],
            "strategy_used": "vector_search"
        }
    }
}
```

### 2.2 手动关联（补建历史数据）

**场景**: 历史数据没有自动关联，需要补建

```bash
# 单个知识点
POST /api/v1/admin/knowledge/{kp_id}/link-chapters

# 单个题目
POST /api/v1/admin/questions/{question_id}/link-chapters

# 批量关联文档下所有实体
POST /api/v1/admin/documents/{document_id}/link-chapters
# 响应:
{
    "knowledge_points": {"linked": 15, "failed": 2},
    "questions": {"linked": 8, "failed": 1}
}
```

### 2.3 查询章节关联的实体

```bash
# 查看"哈希表"章节下的所有知识点和题目
GET /api/v1/admin/chapters/{chapter_id}/entities?page=1&page_size=20

# 响应:
{
    "code": 0,
    "data": {
        "knowledge_points": [
            {
                "id": "...",
                "title": "链地址法解决哈希冲突",
                "relevance": 0.92,
                "source": "vector_search",
                "is_primary": true
            }
        ],
        "questions": [
            {
                "id": "...",
                "content": "设计一个基于开放寻址的哈希表...",
                "type": "综合应用题",
                "relevance": 0.88,
                "source": "vector_search",
                "is_primary": true
            }
        ]
    }
}
```

---

## 三、匹配策略详解

### 策略 1: existing（最快）

**触发**: 实体已有 `primary_chapter_id`

```python
if entity.primary_chapter_id:
    return existing_chapter
```

**适用**: 
- 抽取时已通过 DocumentSectionMapping 填充
- 人工已标注章节

**特点**:
- `relevance = 1.0`
- `source = "existing"`
- `is_primary = True`

---

### 策略 2: document_mapping（规则匹配）

**触发**: 策略 1 失败 + 实体有来源文档

**流程**:
```
entity → EntitySourceLink → block → page_no
  ↓
DocumentSection (该页所在的section)
  ↓
DocumentSectionMapping (review_status='approved')
  ↓
canonical_chapter_id
```

**示例**:
```
文档: "2023年计算机统考大纲.pdf"
  ↓ 解析
DocumentSection: "第一章 数据结构 > 1.5 哈希表" (page_start=12, page_end=15)
  ↓ 映射
DocumentSectionMapping: section → CanonicalChapter("哈希表", confidence=0.95)
  ↓ 抽取
KnowledgePoint: "链地址法" (来源 page=13)
  ↓ 审核通过 → 关联
策略2匹配: "链地址法" → "哈希表" (relevance=0.95, source="document_mapping")
```

**优点**:
- 准确率高（基于文档结构）
- 速度快（数据库查询）

**限制**:
- 需要 DocumentSectionMapping 审核通过
- 依赖 EntitySourceLink 记录

---

### 策略 3: vector_search（语义匹配）

**触发**: 策略 1、2 都失败

**流程**:
```python
# 1. 构造查询文本
if entity_type == "knowledge_point":
    query = f"{entity.title}\n{entity.content[:500]}"
else:  # question
    query = f"{entity.content[:300]}\n{options[:200]}"

# 2. 生成 embedding
vector = await embedding_service.embed_text(query)

# 3. Qdrant 检索
results = qdrant_manager.search(
    collection=KNOWLEDGE_SEGMENTS,
    query_vector=vector,
    filter={
        "entity_type": "canonical_chapter",
        "subject_id": entity.subject_id
    },
    limit=10
)

# 4. 聚合到章节（一个章节可能有 title + content 两个 segment）
chapter_scores = {}
for hit in results:
    chapter_id = hit.payload["entity_id"]
    chapter_scores[chapter_id] = max(chapter_scores[chapter_id], hit.score)

# 5. 过滤 + 排序
candidates = [
    (chapter_id, score)
    for chapter_id, score in sorted(chapter_scores.items(), key=-score)
    if score >= 0.75  # 阈值
][:3]  # top-3
```

**示例**:
```
KnowledgePoint:
  title: "红黑树的旋转操作"
  content: "红黑树通过左旋和右旋保持平衡..."
  
  ↓ embedding

CanonicalChapter segments (已包含 enhanced_description + keywords):
  - "二叉查找树" (enhanced: "...常见变种包含红黑树、AVL树...")
    keywords: ["BST", "平衡树", "红黑树", "AVL"]
    → score: 0.88 ✅
  
  - "树的基本概念"
    → score: 0.72 ❌ (低于阈值)

  ↓ 匹配成功

关联: "红黑树的旋转操作" → "二叉查找树" (relevance=0.88, source="vector_search")
```

**优点**:
- 不依赖文档结构
- 能发现语义相关（如"红黑树" → "二叉查找树"）
- 利用大纲增强字段提升准确率

**阈值**:
- `score >= 0.75`: 建立关联
- `score >= 0.85`: 标记为主章节（`is_primary=True`）

---

## 四、关联质量指标

### 4.1 source 字段

| source | 说明 | 准确率 | 速度 |
|--------|------|--------|------|
| `existing` | 已有关联 | 最高（人工/规则） | 最快 |
| `document_mapping` | 文档映射 | 高（0.8-0.95） | 快 |
| `vector_search` | 向量检索 | 中高（0.75-0.95） | 中 |
| `manual` | 人工标注 | 最高 | - |

### 4.2 relevance 分布

```sql
-- 查询关联质量分布
SELECT 
    source,
    CASE 
        WHEN relevance >= 0.9 THEN 'high'
        WHEN relevance >= 0.75 THEN 'medium'
        ELSE 'low'
    END AS quality,
    COUNT(*) AS count
FROM knowledge_point_chapter_links
GROUP BY source, quality
ORDER BY source, quality;
```

**预期分布**:
- `high (>=0.9)`: 60%+
- `medium (0.75-0.9)`: 30%+
- `low (<0.75)`: < 10%（需要人工审核）

### 4.3 监控告警

```python
# 关联率监控
link_rate = linked_entities / total_entities
if link_rate < 0.7:
    alert("关联率过低！检查: 1)映射缺失 2)向量质量 3)大纲覆盖")

# 低分关联监控
low_relevance_count = count(relevance < 0.75)
if low_relevance_count / total > 0.1:
    alert("低分关联过多！可能需要调整阈值或人工审核")
```

---

## 五、测试验证

### 5.1 单元测试

```python
import pytest
from app.services.chapter_link_service import ChapterLinkService

@pytest.mark.asyncio
async def test_link_knowledge_point_vector_search(db):
    """测试向量检索匹配"""
    # 1. 准备大纲章节（含增强字段）
    chapter = CanonicalChapter(
        id=gen_id(),
        name="哈希表",
        subject_id=SUBJECT_DS,
        enhanced_description="哈希表是基于哈希函数的键值对存储结构。常考冲突解决方法（链地址法、开放寻址法）。",
        keywords=["散列表", "Hash Table", "冲突解决", "链地址法"],
        status="active"
    )
    db.add(chapter)
    await db.commit()
    
    # 2. 构建 segment
    await SegmentService(db).build_canonical_chapter_segments(
        subject_id=SUBJECT_DS, rebuild=True
    )
    
    # 3. 创建知识点
    kp = KnowledgePoint(
        id=gen_id(),
        title="链地址法解决哈希冲突",
        content="链地址法是解决哈希冲突的常用方法，每个桶维护一个链表...",
        subject_id=SUBJECT_DS,
        review_status="approved"
    )
    db.add(kp)
    await db.commit()
    
    # 4. 执行关联
    service = ChapterLinkService(db)
    result = await service.link_knowledge_point_to_chapters(kp.id)
    
    # 5. 验证
    assert result["linked_count"] >= 1
    assert result["primary_chapter"]["id"] == chapter.id
    assert result["primary_chapter"]["relevance"] >= 0.75
    assert result["strategy_used"] == "vector_search"
    
    # 6. 验证数据库
    link = await db.execute(
        select(KnowledgePointChapterLink).where(
            KnowledgePointChapterLink.knowledge_point_id == kp.id
        )
    )
    link = link.scalar_one()
    assert link.canonical_chapter_id == chapter.id
    assert link.source == "vector_search"
    assert link.is_primary == True
```

### 5.2 端到端测试

```bash
# 1. 上传大纲 PDF
POST /api/v1/admin/outlines/upload-parse
# 得到 document_id_outline

# 2. 入库大纲（含增强字段）
POST /api/v1/admin/outlines/import-from-llm
# 得到 outline_id，章节包含 enhanced_description + keywords

# 3. 构建大纲章节 segments
POST /api/v1/admin/segments/build
{
    "subject_id": "...",
    "entity_types": ["canonical_chapter"]
}

# 4. 上传试卷 PDF
POST /api/v1/admin/corpus/upload
# 得到 document_id_exam

# 5. 抽取题目
POST /api/v1/admin/documents/{document_id_exam}/extract-entities

# 6. 审核题目（自动关联）
POST /api/v1/admin/questions/{question_id}/review
{
    "review_status": "approved"
}

# 响应应包含 chapter_link 字段:
{
    "chapter_link": {
        "linked_count": 1,
        "primary_chapter": {"name": "哈希表", "relevance": 0.88},
        "strategy_used": "vector_search"
    }
}

# 7. 验证章节关联
GET /api/v1/admin/chapters/{chapter_id}/entities
# 应该能看到刚才审核通过的题目
```

---

## 六、FAQ

### Q1: 为什么有的实体没有关联到章节？

**可能原因**:
1. **大纲未入库**: 检查是否已上传并入库大纲
2. **segment 未构建**: 调用 `/segments/build` 构建大纲章节 segments
3. **向量检索分数过低**: 所有候选章节 score < 0.75
4. **学科不匹配**: 实体的 subject_id 与大纲章节不一致

**解决**:
```bash
# 检查大纲章节是否存在
GET /api/v1/admin/outlines/{outline_id}/chapters

# 检查 segment 是否构建
SELECT COUNT(*) FROM retrieval_segments WHERE entity_type='canonical_chapter';

# 手动触发关联
POST /api/v1/admin/knowledge/{kp_id}/link-chapters
```

### Q2: 如何提升关联准确率？

**方法**:
1. **完善大纲增强字段**: 确保 LLM 生成了高质量的 `enhanced_description` 和 `keywords`
2. **富化后再关联**: 审核流程默认先富化（生成 summary），再关联，利用富化内容提升匹配
3. **调整阈值**: 如果误匹配多，提高阈值（如 0.75 → 0.80）
4. **人工标注**: 对低分关联（relevance < 0.8）进行人工审核

### Q3: 一个实体可以关联多个章节吗？

**可以！** 向量检索返回 top-3 相关章节:
- 最高分且 score >= 0.85 → `is_primary=True`（主章节）
- 其他 score >= 0.75 → `is_primary=False`（相关章节）

**示例**: "排序算法稳定性"可能关联:
- 主章节: "排序算法"（relevance=0.92）
- 相关: "算法复杂度分析"（relevance=0.78）

### Q4: 如何批量补建历史数据？

```bash
# 方案1: 按文档批量
POST /api/v1/admin/documents/{document_id}/link-chapters

# 方案2: 按学科批量（需自己实现或用脚本）
GET /api/v1/admin/knowledge?subject_id={subject_id}&review_status=approved
# 遍历调用
POST /api/v1/admin/knowledge/{kp_id}/link-chapters
```

**注意**: 批量操作耗时较长（向量检索），建议:
- 分批处理（每批 100-200 个）
- 监控日志和错误率
- 在低峰期执行

---

## 七、总结

### ✅ 已实现

1. **3 层匹配策略**: existing → document_mapping → vector_search
2. **自动关联**: 审核通过自动触发
3. **质量追溯**: 记录 relevance + source
4. **API 支持**: 手动触发 + 批量关联 + 查询
5. **数据库字段**: 关联表增强字段

### 🎯 关键指标

- **关联率**: 预期 80%+
- **准确率**: 预期 90%+（规则 + 向量组合）
- **处理速度**: 单实体 < 200ms

### 📊 监控项

- 关联率（linked / total）
- source 分布（existing / document_mapping / vector_search）
- relevance 分布（high / medium / low）
- 无法匹配的实体数

### 🔜 后续优化

1. **LLM 推理兜底**: 低分候选让 LLM 选择
2. **关联学习**: 根据人工反馈调整阈值
3. **图谱构建**: 章节-知识点-题目三元组
4. **学习路径**: 根据关联自动生成学习路径
