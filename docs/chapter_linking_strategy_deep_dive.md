# 匹配策略深度设计

## 一、现状分析

### 1.1 数据流

```
PDF → MinerU 解析 → DocumentSection (标题树)
                         ↓
              [章节映射服务] → 向量检索 CanonicalChapter
                         ↓
              DocumentSectionMapping (section → canonical_chapter)
                   ↓ (review_status='approved')
       [实体抽取] → 读取 mapping → 填充 primary_chapter_id
                         ↓
              KnowledgePoint/Question (primary_chapter_id 可能为空)
```

### 1.2 关键发现

**已有机制（部分工作）**:
- ✅ `DocumentSectionMapping` 表存在，记录 section → chapter 映射
- ✅ 抽取时会读取映射，填充 `primary_chapter_id`
- ✅ 如果有映射，会创建 `KnowledgePointChapterLink`

**问题**:
- ❌ 映射可能缺失（文档没跑章节映射）
- ❌ 映射可能未审核（`review_status='pending'`）
- ❌ 映射可能不准确（需要向量兜底）
- ❌ 历史数据没有 `primary_chapter_id`（需要补建）

### 1.3 数据完整性检查

需要确认:
1. **映射覆盖率**: 多少文档有 DocumentSectionMapping？
2. **映射审核率**: 多少映射是 `approved` 状态？
3. **实体关联率**: 多少知识点/题目有 `primary_chapter_id`？

---

## 二、匹配策略设计（4层策略）

### 策略 1: 直接读取 primary_chapter_id (最快)

```python
if entity.primary_chapter_id:
    # 已有关联，直接使用
    return [{
        "chapter_id": entity.primary_chapter_id,
        "relevance": 1.0,
        "source": "existing",
        "is_primary": True
    }]
```

**适用**: 实体已经在抽取时建立了关联

---

### 策略 2: 文档映射查询 (规则匹配)

```python
async def _match_by_document_mapping(entity):
    """
    通过文档section映射查找章节
    
    流程:
    1. entity.source_document_id → Document
    2. 查询该文档的所有 DocumentSectionMapping (review_status='approved')
    3. 根据 entity 的来源 blocks，找到所在 section
    4. 返回该 section 映射的 canonical_chapter_id
    
    问题: 如果 entity 跨多个 section 怎么办？
    解决: 取第一个 block 所在的 section 作为主章节
    """
    # 1. 查询实体的来源 blocks
    source_links = await db.execute(
        select(EntitySourceLink)
        .where(EntitySourceLink.entity_id == entity.id, 
               EntitySourceLink.entity_type == entity_type)
        .order_by(EntitySourceLink.block_order)
        .limit(1)  # 只看第一个 block
    )
    first_link = source_links.scalar_one_or_none()
    if not first_link:
        return None
    
    # 2. 获取 block 的 page_no
    block = await db.get(DocumentBlock, first_link.block_id)
    if not block:
        return None
    
    # 3. 查询该页所在的 DocumentSection
    sections = await db.execute(
        select(DocumentSection)
        .where(
            DocumentSection.document_id == entity.source_document_id,
            DocumentSection.page_start <= block.page_no,
            DocumentSection.page_end >= block.page_no
        )
        .order_by(DocumentSection.level.desc())  # 优先取最深层级的 section
        .limit(1)
    )
    section = sections.scalar_one_or_none()
    if not section:
        return None
    
    # 4. 查询该 section 的 approved 映射
    mapping = await db.execute(
        select(DocumentSectionMapping)
        .where(
            DocumentSectionMapping.document_section_id == section.id,
            DocumentSectionMapping.review_status == 'approved'
        )
        .order_by(DocumentSectionMapping.confidence.desc())
        .limit(1)
    )
    mapping = mapping.scalar_one_or_none()
    if not mapping:
        return None
    
    return {
        "chapter_id": mapping.canonical_chapter_id,
        "relevance": float(mapping.confidence),
        "source": "document_mapping",
        "is_primary": True,
        "mapping_type": mapping.mapping_type
    }
```

**适用**: 文档已经跑过章节映射且审核通过

**限制**: 
- 需要 EntitySourceLink 记录（实体 → block 的关联）
- 需要 DocumentSection 覆盖该 page
- 需要 DocumentSectionMapping 审核通过

---

### 策略 3: 向量检索 (语义匹配)

```python
async def _match_by_vector_search(entity, entity_type):
    """
    用实体内容在 canonical_chapter segments 中检索
    
    查询构造:
    - knowledge_point: title + content (前500字)
    - question: content + options (前500字)
    
    过滤:
    - entity_type = "canonical_chapter"
    - subject_id = entity.subject_id
    
    聚合:
    - 一个章节可能有多个 segment (title + content)
    - 取该章节所有 segment 的最高分作为章节得分
    
    阈值:
    - score >= 0.75: 建立关联
    - score >= 0.85: 标记为 is_primary
    
    返回:
    - 最多 top-3 章节
    """
    from app.services.embedding_service import get_embedding_service_from_settings
    from app.db.qdrant import qdrant_manager, COLLECTION_KNOWLEDGE_SEGMENTS
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    
    # 1. 构造查询文本
    if entity_type == "knowledge_point":
        query_text = f"{entity.title}\n{(entity.content or '')[:500]}"
    else:  # question
        options_text = "\n".join([
            f"{opt.get('key', '')}. {opt.get('text', '')}" 
            for opt in (entity.options or [])[:4]
        ])
        query_text = f"{entity.content[:300]}\n{options_text[:200]}"
    
    # 2. 生成 embedding
    embedding_service = await get_embedding_service_from_settings(db)
    query_vector = await embedding_service.embed_text(query_text)
    
    # 3. Qdrant 检索
    results = qdrant_manager.search(
        collection_name=COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
            FieldCondition(key="subject_id", match=MatchValue(value=entity.subject_id)),
        ]),
        limit=10  # 多取一些，后续聚合去重
    )
    
    # 4. 聚合到 chapter_id（一个章节可能有 title + content 两个 segment）
    chapter_scores = {}
    for hit in results:
        chapter_id = hit.payload["entity_id"]
        # 取该章节所有 segment 的最高分
        chapter_scores[chapter_id] = max(
            chapter_scores.get(chapter_id, 0), 
            hit.score
        )
    
    # 5. 过滤 + 排序
    candidates = [
        {
            "chapter_id": cid,
            "relevance": score,
            "source": "vector_search",
            "is_primary": (i == 0 and score >= 0.85),  # 最高分且超过 0.85 → 主章节
        }
        for i, (cid, score) in enumerate(
            sorted(chapter_scores.items(), key=lambda x: -x[1])
        )
        if score >= 0.75  # 阈值过滤
    ]
    
    return candidates[:3]  # 最多 3 个相关章节
```

**适用**: 前两个策略都失败时的兜底方案

**优点**:
- 不依赖文档结构
- 利用大纲增强字段（enhanced_description + keywords）提升准确率
- 能发现语义相关的章节（如题目考"红黑树"，能关联到"二叉查找树"章节）

**缺点**:
- 需要先构建 canonical_chapter segments
- 依赖 embedding 质量

---

### 策略 4: LLM 推理 (最后兜底)

```python
async def _match_by_llm(entity, entity_type, candidate_chapters):
    """
    当向量检索也失败时，用 LLM 推理
    
    Prompt:
    你是 408 考研知识点分类专家。下面是一道题目/知识点，以及候选的大纲章节列表。
    请判断该题目/知识点最可能属于哪个章节。
    
    题目/知识点:
    {entity.content}
    
    候选章节:
    1. 数据结构 > 线性表 (描述: ...)
    2. 数据结构 > 树 > 二叉树 (描述: ...)
    ...
    
    只输出章节编号，不要解释。如果都不合适，输出 0。
    
    策略:
    - 先用向量检索取 top-10 低分候选（0.5 < score < 0.75）
    - 让 LLM 从中选择最合适的
    - LLM 返回的章节 relevance = 0.7（比向量低，标识 LLM 推理）
    """
    # 实现省略...
```

**适用**: 向量检索分数都低于 0.75 但又有一些候选时

**权衡**: LLM 调用成本高，仅作为最后兜底

---

## 三、综合匹配流程

```python
async def link_entity_to_chapters(entity, entity_type):
    """
    综合 4 层策略匹配章节
    
    返回:
    {
        "linked_count": N,
        "primary_chapter": {...},  # is_primary=True 的章节
        "related_chapters": [...], # 其他相关章节
        "strategy_used": "existing / document_mapping / vector_search / llm"
    }
    """
    results = []
    strategy_used = None
    
    # 策略 1: 直接读取
    if entity.primary_chapter_id:
        results = [{"chapter_id": entity.primary_chapter_id, "relevance": 1.0, 
                    "source": "existing", "is_primary": True}]
        strategy_used = "existing"
    
    # 策略 2: 文档映射
    if not results:
        mapping_result = await _match_by_document_mapping(entity, entity_type)
        if mapping_result:
            results = [mapping_result]
            strategy_used = "document_mapping"
    
    # 策略 3: 向量检索
    if not results:
        vector_results = await _match_by_vector_search(entity, entity_type)
        if vector_results:
            results = vector_results
            strategy_used = "vector_search"
    
    # 策略 4: LLM 推理（可选，暂不实现）
    # if not results:
    #     llm_result = await _match_by_llm(entity, entity_type, low_score_candidates)
    #     if llm_result:
    #         results = [llm_result]
    #         strategy_used = "llm"
    
    # 没有任何匹配
    if not results:
        return {
            "linked_count": 0,
            "primary_chapter": None,
            "related_chapters": [],
            "strategy_used": "none"
        }
    
    # 写入关联表
    primary = None
    related = []
    
    for res in results:
        # 创建关联记录
        if entity_type == "knowledge_point":
            link = KnowledgePointChapterLink(
                knowledge_point_id=entity.id,
                canonical_chapter_id=res["chapter_id"],
                is_primary=res.get("is_primary", False),
                relevance=res["relevance"],
                source=res["source"],
                created_by="system"
            )
        else:  # question
            link = QuestionChapterLink(
                question_id=entity.id,
                canonical_chapter_id=res["chapter_id"],
                is_primary=res.get("is_primary", False),
                relevance=res["relevance"],
                source=res["source"],
                created_by="system"
            )
        
        db.add(link)
        
        # 分类
        chapter = await db.get(CanonicalChapter, res["chapter_id"])
        chapter_info = {
            "id": chapter.id,
            "name": chapter.name,
            "outline_code": chapter.outline_code,
            "relevance": res["relevance"],
            "source": res["source"]
        }
        
        if res.get("is_primary"):
            primary = chapter_info
        else:
            related.append(chapter_info)
    
    await db.commit()
    
    return {
        "linked_count": len(results),
        "primary_chapter": primary,
        "related_chapters": related,
        "strategy_used": strategy_used
    }
```

---

## 四、边界情况处理

### 4.1 跨章节知识点

**问题**: 一个知识点可能跨多个章节（如"排序算法"在"数据结构"和"算法设计"都有）

**解决**:
- 向量检索自然会返回多个高分章节
- 取最高分的作为 `is_primary=True`
- 其他高分章节作为相关章节（`is_primary=False`）

### 4.2 综合题

**问题**: 一道题考查多个知识点，跨多个章节

**解决**:
- 向量检索取 top-3
- 所有 score >= 0.75 的都建立关联
- 最高分的标记为 `is_primary=True`

### 4.3 映射冲突

**问题**: 文档映射说属于章节 A，向量检索说属于章节 B

**解决**:
- **优先文档映射**（如果 review_status='approved' 且 confidence >= 0.8）
- 向量检索结果作为**相关章节**补充

### 4.4 无法匹配

**问题**: 所有策略都失败

**解决**:
- 不建立关联（`primary_chapter_id` 保持 NULL）
- 记录日志，供人工审核
- 前端展示"未关联章节"，提供手动关联按钮

---

## 五、性能优化

### 5.1 批量处理

```python
async def batch_link_document(document_id):
    """
    批量处理一个文档下的所有实体
    
    优化:
    1. 一次查询该文档的所有 DocumentSectionMapping（缓存）
    2. 批量查询所有实体的 EntitySourceLink
    3. 向量检索时批量生成 embedding（批处理 API）
    4. 批量写入关联表
    """
```

### 5.2 缓存映射

```python
# 文档级缓存
mapping_cache = {}  # section_id → canonical_chapter_id

async def _get_section_mapping_cached(section_id):
    if section_id not in mapping_cache:
        mapping = await db.execute(...)
        mapping_cache[section_id] = mapping
    return mapping_cache[section_id]
```

### 5.3 并发控制

```python
# 避免向量检索过载
import asyncio

async def batch_vector_search(entities):
    semaphore = asyncio.Semaphore(5)  # 最多 5 个并发
    
    async def _search_one(entity):
        async with semaphore:
            return await _match_by_vector_search(entity)
    
    return await asyncio.gather(*[_search_one(e) for e in entities])
```

---

## 六、数据质量监控

### 6.1 关联质量指标

```python
{
    "total_entities": 1000,
    "linked_entities": 850,
    "link_rate": 0.85,
    
    "by_strategy": {
        "existing": 100,
        "document_mapping": 400,
        "vector_search": 350,
        "llm": 0
    },
    
    "by_relevance": {
        "high (>=0.9)": 600,
        "medium (0.75-0.9)": 200,
        "low (<0.75)": 50  # 需要人工审核
    },
    
    "multi_chapter": 120,  # 关联多个章节的实体
    "no_match": 150  # 无法匹配的实体
}
```

### 6.2 告警规则

- ⚠️ 关联率 < 70%: 映射缺失或向量质量差
- ⚠️ low relevance > 10%: 阈值设置过低
- ⚠️ no_match > 20%: 大纲覆盖不全或实体质量差

---

## 七、总结

### 优先级

**P0 (必须实现)**:
- ✅ 策略 1: 直接读取 primary_chapter_id
- ✅ 策略 2: 文档映射查询
- ✅ 策略 3: 向量检索

**P1 (可选)**:
- ⏸️ 策略 4: LLM 推理（成本高，暂不实现）

### 预期效果

- 关联率 **80%+**（策略 1+2+3 组合）
- 准确率 **90%+**（规则优先 + 向量兜底）
- 处理速度: 单实体 **< 200ms**（文档映射缓存 + 向量检索优化）

### 下一步

1. ✅ 数据表增强（添加 relevance/source 字段）
2. ✅ 实现 ChapterLinkService（3层策略）
3. ✅ 集成审核流程
4. ✅ 编写单元测试
5. ✅ 批量补建历史数据
