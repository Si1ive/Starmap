# 大纲考点检索与跨章节关联设计

> 版本：v1.2  
> 日期：2026-06-24  
> 状态：设计稿（已校验修正，已加入大纲辅助 Query 扩展）  
> 读者：Backend / Data

---

## 1. 问题定义

大纲（`ExamOutline` + `CanonicalChapter`）已存入 MySQL，包含多层级考点、关键词（`keywords`）、LLM 增强描述（`enhanced_description`）、复习指导（`exam_guidance`）。本文档回答四个核心问题：

1. 大纲考点是否需要单独存入 Qdrant 向量库？
2. 用户 query 通常只有几个字，如何解决短查询 vs 长文档的语义不对称问题？
3. "用户问一道题 → 定位考点 → 找到该考点所有相关知识"这条链路能否纯结构化检索完成？有什么坑？
4. 跨章节、跨科目的考点关联如何建立？纯语义相似度够不够？

---

## 2. 现状盘点

### 2.1 已就绪的基础设施

| 组件 | 位置 | 能力 |
|------|------|------|
| `CanonicalChapter` | MySQL | 三层级考点树（level 1/2/3），含 `keywords`、`enhanced_description`、`outline_code`、`parent_id` |
| `ExamOutline` / `ExamOutlineSubject` | MySQL | 大纲元信息 + 科目关联 + 考察目标 |
| `KnowledgePointChapterLink` | MySQL | 知识点 ↔ 考点多对多关联（`is_primary` 区分主次） |
| `QuestionChapterLink` | MySQL | 题目 ↔ 考点多对多关联 |
| `QuestionKnowledgeLink` | MySQL | 题目 ↔ 知识点关联（`source`: llm/vector/rule/manual） |
| `KnowledgeRelation` | MySQL | 知识点间关系图（7 种关系类型 + embedding 相似度边） |
| `RetrievalSegment` | MySQL + Qdrant | 统一检索单元，`entity_type` 含 `canonical_chapter` |
| `ChapterLinkService` | Python | 语料 → 考点 3 层匹配（existing → document_mapping → vector_search） |
| `RelationService` | Python | 知识点关系自动构建（术语 Jaccard + embedding cosine） |
| `RetrievalService` | Python | dense/sparse/hybrid 检索 + `search_with_relations` 关系扩展 |
| `EnrichmentService` | Python | 题目/知识点 LLM 富化 + 考点标签回连知识点 |

### 2.2 当前数据流

```
用户问题
  → RetrievalService.search(query, chapter_ids=[...])
    → Qdrant dense search（knowledge_segments / question_segments）
    → MySQL sparse search（关键词 LIKE）
    → 合并去重排序
  → RetrievalService.search_with_relations(query)
    → 主检索 top-K 知识点
    → KnowledgeRelation 图扩展关联知识点
    → QuestionKnowledgeLink 反查关联题目
```

### 2.3 当前代码与设计的不一致——必须先修

`segment_service.py:288` 已经写入了 `entity_type="canonical_chapter"` 的 segment，但 `RetrievalSegment.entity_type` 的 SQLAlchemy Enum 定义为 `Enum("knowledge_point", "question")`（`mysql_models.py:1327`）。在 MySQL strict mode 下这会导致插入失败。

同理，`ChapterLinkService._match_by_vector_search` 在 Qdrant 中按 `entity_type="canonical_chapter"` 过滤，但 `qdrant.py:112` 的 `_PAYLOAD_INDEXES` 没有包含 `entity_type` 字段的索引。数据量增大后每次检索都会做 payload 全扫描。

**这两个是实施本文档方案的前置条件，必须在任何其他开发之前修复：**

1. `mysql_models.py:1327` → `Enum("knowledge_point", "question", "canonical_chapter")`
2. `qdrant.py:112` 的 `_PAYLOAD_INDEXES` → 新增 `"entity_type": PayloadSchemaType.KEYWORD`

---

## 3. 问题一：大纲考点是否需要存入向量库？

### 3.1 结论：需要向量化，但不需要单独建 collection

大纲考点（`CanonicalChapter`）的向量化存储是必要的，但它的角色远不止"被检索对象"——它是检索链路的第一级。具体来说：

- 考点的 `enhanced_description` + `keywords` 应写入 `knowledge_segments` collection，`entity_type="canonical_chapter"`
- 不需要为考点单独建 collection（如 `outline_chapters`）
- 用户 query 到达后，**先检索大纲定位考点，再以考点为中心展开内容检索**——而不是直接用 query 去搜知识点

### 3.2 考点的向量在系统中的三个用途

#### 用途 A：反向匹配——题/知识点 → 考点（已实现）

当一道题或知识点没有 `chapter_id` 时，用其内容的 embedding 去 Qdrant 中检索 `entity_type="canonical_chapter"` 的 segment，找到最匹配的考点。

`ChapterLinkService._match_by_vector_search`（`chapter_link_service.py:247`）已实现此逻辑：

```python
# 当前代码路径
ChapterLinkService._match_by_vector_search(entity, entity_type)
  → embedding_service.embed_text(query_text)
  → qdrant_manager.search(
      collection_name="knowledge_segments",
      query_filter=Filter(must=[
          FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
          FieldCondition(key="subject_id", match=MatchValue(value=entity.subject_id)),
      ]),
      limit=10
    )
  → 聚合到 chapter_id，过滤 score >= 0.75，取 top-3
```

#### 用途 B：语义检索考点——用户自然语言 → 考点列表（待实现）

当用户用自然语言描述一个概念（如"操作系统里那种多个进程抢资源的问题"），系统需要找到对应的考点（"进程同步与互斥"）。这需要：

1. 用户 query → embedding
2. 在 `knowledge_segments` 中检索 `entity_type="canonical_chapter"` 的 segment
3. 返回考点列表 + 该考点下的知识点和题目

### 3.3 为什么不需要单独建 collection

考点的 segment 和其他知识片段（知识点、题目解析等）存在同一个 collection 中有两个好处：

1. **统一过滤**：`subject_id`、`chapter_ids` 等 payload 字段在同一个 collection 中统一索引，检索时不需要跨 collection 合并
2. **混合召回**：用户查询时，可以在一次检索中同时召回考点描述和相关知识点，按 score 自然排序

### 3.4 考点 segment 的写入时机与内容

**写入时机**：大纲导入（`OutlineIngestionRun`）完成后，为每个 `CanonicalChapter` 生成 segment。

`SegmentService.build_canonical_chapter_segments`（`segment_service.py:225`）已实现此逻辑，每考点生成 2 个 segment：

| segment_type | 内容 | 用途 |
|-------------|------|------|
| `title` | name + keywords + aliases | 精确/关键词匹配、sparse 检索 |
| `content` | enhanced_description + description | 语义检索、dense embedding |

**payload**：

```json
{
  "segment_id": "<uuid>",
  "entity_type": "canonical_chapter",
  "entity_id": "<chapter_id>",
  "segment_type": "title|content",
  "subject_id": "<subject_id>",
  "chapter_ids": ["<chapter_id>"]
}
```

### 3.5 考点 segment 不需要存什么

- **不需要存 `exam_guidance`**（复习指导）：这是给前端展示用的，不是检索目标
- **不需要存子考点列表**：子考点通过 `parent_id` 在 MySQL 中查询，不需要冗余到 Qdrant
- **不需要存关联知识点 ID 列表**：关联关系通过 link 表维护，Qdrant payload 不宜过重

### 3.6 用途 C：大纲辅助 Query 扩展——解决短查询 vs 长文档的语义不对称（核心设计）

这是本文档最重要的设计决策。

#### 问题本质

RAG 系统中存在经典的**短查询 vs 长文档语义不对称问题**：

```
用户 query: "Cache 地址映射"（5 个字，语义信息密度低）
       vs
检索目标:  几百字的 enhanced_description / 知识点内容（语义分布在长文本中）
```

直接拿 5 个字的 query embedding 去搜几百字的文档，两者的向量可能不在同一个语义子空间——这就是为什么很多 RAG 系统面对简短中文问题召回率很差。

#### 业界解法对比

| 方案 | 思路 | 问题 |
|------|------|------|
| **HyDE**（Hypothetical Document Embedding） | LLM 生成假设答案 → 用假设答案的 embedding 检索 | LLM 可能编造概念；多一次 LLM 调用（+1~2s）；消耗 token |
| **Query Rewrite** | LLM 把短问题扩写成完整检索语句 | 增强效果弱于 HyDE；仍需 LLM 调用 |
| **大纲扩展**（本项目方案） | 先检索大纲考点 → 用考点描述 + keywords 扩写 query | 零幻觉（大纲是官方考点）；~50ms 延迟；零 token 成本 |

#### 大纲扩展为什么是本项目的最优解

大纲天然就是领域知识图谱——每个考点包含了：

- `keywords`：官方术语 + 别名，用户用语 → 学科标准用语的关键映射
- `enhanced_description`：用学科语言写的核心内容描述
- `outline_code` + `subject_id`：精确的结构化定位信息

当用户问"Cache 地址映射"时，大纲检索会命中：

```
考点: "Cache 的地址映射" (计组, score=0.92)
  keywords:    [Cache, 地址映射, 直接映射, 全相联映射, 组相联映射]
  enhanced:    "Cache 地址映射是指 CPU 访问主存时将主存地址转换为
               Cache 地址的硬件机制，主要包括直接映射、全相联映射和
               组相联映射三种方式..."
  subject_id:  "computer_organization"
```

一次检索就获得了：
1. **关键词扩展**：用户只说了"地址映射"，大纲补充了"直接映射 / 全相联映射 / 组相联映射"
2. **语义扩展**：`enhanced_description` 用学科语言精确描述了用户想问的内容
3. **结构化过滤条件**：`subject_id` 可直接缩小候选集

#### 大纲扩展 vs HyDE 的精确对比

| 维度 | HyDE（LLM 编答案） | 大纲扩展（本项目） |
|------|-------------------|-------------------|
| 准确性 | LLM 可能编造不存在的概念 | 大纲是官方考点，零幻觉 |
| 领域对齐 | 通用模型文本风格不可控 | 大纲描述本身就是领域语言 |
| 结构化信息 | 只有一段文本 | 附带 subject_id / chapter_id / keywords |
| 延迟 | 多一次 LLM 调用，+1~2s | 大纲 segment 已在 Qdrant 中，+~50ms |
| 成本 | 每次检索消耗 LLM token | 零额外成本（大纲 segment 已在入库时生成） |
| 可解释性 | 黑盒——用户不知道为什么要这样扩展 | 白盒——用户看到"已定位考点：Cache 的地址映射" |

#### 完整链路

```
用户 query: "Cache 地址映射怎么做"

Phase 0: 大纲定位 + Query 扩展 （新增，~50ms）
  ├── query embedding → Qdrant 搜 entity_type="canonical_chapter"
  ├── 命中 top-3 考点，每个考点带有:
  │   ├── keywords: 术语列表（直接映射 / 全相联映射 / 组相联映射...）
  │   ├── enhanced_description: 学科语言描述
  │   ├── subject_id: 所属科目
  │   └── chapter_id: 考点 ID
  ├── 用命中考点扩写 query:
  │   原文:  "Cache 地址映射"
  │   扩展后: "Cache 地址映射 直接映射 全相联映射 组相联映射
  │            Cache的地址映射是指CPU访问主存时将主存地址转换为
  │            Cache地址的硬件机制..."
  └── 从命中考点提取结构化过滤条件: subject_id, chapter_ids

Phase 1: 内容检索（用扩展后的 query + 结构化过滤）
  ├── 扩展 query embedding → Qdrant dense search
  │     (subject_id + chapter_ids 已过滤候选集)
  ├── 原始 query 做 sparse search（关键词 LIKE）
  └── 合并排序

Phase 2: 考点展开（基于 Phase 0 定位的考点）
  ├── 同章兄弟考点（Layer 1）
  └── 跨章关联考点（Layer 2 / Layer 3）
```

#### 实现

```python
async def expand_query_with_outline(
    db: AsyncSession,
    query: str,
    top_k: int = 3,
) -> OutlineExpansionResult:
    """
    Phase 0: 用大纲考点扩展用户 query。

    流程：
    1. query embedding → Qdrant 检索 entity_type="canonical_chapter" 的 segment
    2. 聚合到 chapter_id，取 top-K 考点
    3. 用考点 keywords + enhanced_description 扩写 query
    4. 提取结构化过滤条件

    返回:
    {
        "expanded_query": "扩展后的查询文本（拼接了考点描述和关键词）",
        "subject_ids": ["computer_organization"],
        "chapter_ids": ["chap_001", "chap_002"],
        "matched_chapters": [
            {"chapter_id": "chap_001", "name": "Cache的地址映射", "score": 0.92, "keywords": [...]},
            {"chapter_id": "chap_002", "name": "Cache的基本工作原理", "score": 0.85, "keywords": [...]},
        ],
    }
    """
    from app.services.embedding_service import get_embedding_service_from_settings
    from app.db.qdrant import qdrant_manager
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    embedding = await get_embedding_service_from_settings(db)
    query_vector = await embedding.embed_text(query)

    # Step 1: Qdrant 检索考点 segment
    # 只搜 title segment（包含 keywords，匹配更精确）
    # 不搜 content segment（enhanced_description 语义匹配兜底）
    title_hits = qdrant_manager.search(
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
            FieldCondition(key="segment_type", match=MatchValue(value="title")),
        ]),
        limit=top_k * 2,
    )
    content_hits = qdrant_manager.search(
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
            FieldCondition(key="segment_type", match=MatchValue(value="content")),
        ]),
        limit=top_k * 2,
    )

    # Step 2: 合并 title + content 命中，聚合到 chapter_id
    chapter_scores: Dict[str, float] = {}
    for hit in title_hits + content_hits:
        ch_id = hit.payload.get("entity_id")
        if not ch_id:
            continue
        # title segment 权重 ×1.2（keywords 匹配更可靠）
        weight = 1.2 if hit.payload.get("segment_type") == "title" else 1.0
        chapter_scores[ch_id] = max(
            chapter_scores.get(ch_id, 0),
            hit.score * weight,
        )

    # 过滤低分
    top_chapters = sorted(
        [(cid, s) for cid, s in chapter_scores.items() if s >= 0.7],
        key=lambda x: -x[1],
    )[:top_k]

    if not top_chapters:
        # 没有命中任何考点，回退到原始 query
        return OutlineExpansionResult(
            expanded_query=query,
            subject_ids=[],
            chapter_ids=[],
            matched_chapters=[],
        )

    # Step 3: 从 MySQL 加载考点完整信息
    top_ids = [cid for cid, _ in top_chapters]
    chapters = (await db.execute(
        select(CanonicalChapter).where(CanonicalChapter.id.in_(top_ids))
    )).scalars().all()
    chapter_map = {ch.id: ch for ch in chapters}

    # 构建扩展 query
    query_parts = [query]  # 原始 query 保留

    for cid, score in top_chapters:
        ch = chapter_map.get(cid)
        if not ch:
            continue

        # 拼接 keywords（术语扩展）
        if ch.keywords:
            query_parts.append(" ".join(ch.keywords[:8]))  # 最多 8 个关键词

        # 拼接 enhanced_description（语义扩展，限制 100 字避免过拟合）
        if ch.enhanced_description:
            query_parts.append(ch.enhanced_description[:100])

    expanded_query = " ".join(query_parts)

    # Step 4: 提取结构化过滤条件
    subject_ids = list({
        chapter_map[cid].subject_id
        for cid, _ in top_chapters
        if chapter_map.get(cid) and chapter_map[cid].subject_id
    })

    matched_chapters = [
        {
            "chapter_id": cid,
            "name": chapter_map[cid].name if chapter_map.get(cid) else "",
            "outline_code": chapter_map[cid].outline_code if chapter_map.get(cid) else "",
            "score": round(score, 4),
            "keywords": chapter_map[cid].keywords if chapter_map.get(cid) else [],
        }
        for cid, score in top_chapters
        if chapter_map.get(cid)
    ]

    return OutlineExpansionResult(
        expanded_query=expanded_query[:2000],  # 限制总长度，避免超出 embedding 模型的 token 窗口
        subject_ids=subject_ids,
        chapter_ids=top_ids,
        matched_chapters=matched_chapters,
    )
```

#### 无命中时的降级

当 query 中没有可识别的考点术语时（比如纯粹的结构化查询"2018 年 408 真题第 15 题"），大纲检索会返回低分结果，被 `score >= 0.7` 过滤掉。此时 `expanded_query` 退化为原始 query，不影响后续检索——结构化匹配（题号/年份）仍然能正常工作。

这也意味着：**大纲扩展是检索质量的增强器，不是阻塞器**。即使大纲检索失败，系统仍能通过原始 query 的 sparse/dense 检索返回结果。

---

## 4. 问题二：题 → 考点 → 相关知识的结构化检索链路

### 4.1 目标链路

```
用户问题
  → 定位题目（Question）
    → QuestionChapterLink → CanonicalChapter（考点）
    → QuestionKnowledgeLink → KnowledgePoint（知识点）
  → 以考点为中心展开
    → 同考点下的其他题目（QuestionChapterLink）
    → 同考点下的其他知识点（KnowledgePointChapterLink）
    → 同 parent_id 的兄弟考点（CanonicalChapter.parent_id）
    → 兄弟考点下的题目和知识点
```

### 4.2 纯结构化检索的可行性分析

这条链路的核心操作都是 SQL JOIN，不需要向量检索：

```sql
-- Step 1: 题目 → 考点
SELECT cc.* FROM canonical_chapters cc
JOIN question_chapter_links qcl ON qcl.canonical_chapter_id = cc.id
WHERE qcl.question_id = :question_id;

-- Step 2: 考点 → 同考点其他题目
SELECT q.* FROM questions q
JOIN question_chapter_links qcl ON qcl.question_id = q.id
WHERE qcl.canonical_chapter_id = :chapter_id
AND q.id != :original_question_id;

-- Step 3: 考点 → 同考点知识点
SELECT kp.* FROM knowledge_points kp
JOIN knowledge_point_chapter_links kpcl ON kpcl.knowledge_point_id = kp.id
WHERE kpcl.canonical_chapter_id = :chapter_id;

-- Step 4: 兄弟考点（同一父节点）
SELECT * FROM canonical_chapters
WHERE parent_id = (SELECT parent_id FROM canonical_chapters WHERE id = :chapter_id)
AND id != :chapter_id;

-- Step 5: 兄弟考点下的题目和知识点（重复 Step 2-3）
```

**结论：这条链路完全可以用纯结构化检索完成。**

### 4.3 三个坑及解法

#### 坑 1：关键词匹配的召回率——同义词问题

**场景**：用户说"先根遍历"，但考点 keywords 里只有"前序遍历"。

**根因**：结构化匹配（`keywords` JSON 数组的精确/子串匹配）无法处理同义词。

**解法**：在考点入库时做**写入时穷举**，而非检索时模糊。

在大纲导入的 LLM prompt 中，要求为每个考点生成丰富的别名：

```
对考点"二叉树遍历"，请生成 keywords，包含：
- 中文标准名：二叉树遍历
- 中文同义词：树的遍历、二叉树的遍历、遍历二叉树
- 中文俗称/简称：遍历
- 英文术语：Binary Tree Traversal
- 英文缩写：BTT
- 具体算法名（如适用）：前序遍历、中序遍历、后序遍历、层序遍历、Preorder、Inorder、Postorder、Level-order
```

用户说"先根遍历"时，虽然不在 keywords 中，但 "先根遍历" 作为 "Preorder" 的中文别名，在 keywords 穷举充分的情况下可被命中。

**兜底**：如果 keywords 匹配失败，降级为 `enhanced_description` 的向量检索（用途 A）。

#### 坑 2：章节粒度过细导致漏召回

**场景**：一道题关联了三级考点"1.2.3 平衡二叉树"，但用户问的内容涉及整个"1.2 二叉树"节下的多个三级考点。

**根因**：只通过 `QuestionChapterLink` 拿到一个三级考点，然后只在该考点范围内展开。

**解法**：展开时沿考点树向上爬，逐级扩展范围。

```
当前考点: level=3, parent_id = <二级考点ID>
  → 查询 parent_id 的所有子节点（即所有兄弟三级考点）
  → 查询父考点本身（如果它有直接关联的内容）
  → 可选：继续上爬到 level=1
```

实现逻辑（已修正重复查询问题——原版在循环内外对同一批兄弟节点查询了两次）：

```python
async def expand_chapter_scope(
    db: AsyncSession,
    chapter_ids: List[str],
    upward_levels: int = 1,
) -> List[str]:
    """
    沿考点树向上扩展，返回范围内所有考点 ID。

    算法：
    1. 收集起点章节的兄弟节点（同 parent_id）
    2. 逐级向上爬：每爬一级，把当前父节点和它的所有子节点加入结果
    3. 设置 upward_levels=0 时只展开兄弟，不爬树

    循环内外的查询不会重复：循环外查询的是"当前这一级"的兄弟，
    进入循环后 current 变成 parent，查的是"上一级"的兄弟，天然不重叠。
    """
    result = set(chapter_ids)

    # 批量加载所有起点章节
    chapters = (await db.execute(
        select(CanonicalChapter).where(
            CanonicalChapter.id.in_(chapter_ids),
            CanonicalChapter.status == "active",
        )
    )).scalars().all()

    if not chapters:
        return list(result)

    # 收集各起点的 parent_id，批量查兄弟
    parent_ids = {ch.parent_id for ch in chapters if ch.parent_id}
    if parent_ids:
        siblings = (await db.execute(
            select(CanonicalChapter.id).where(
                CanonicalChapter.parent_id.in_(parent_ids),
                CanonicalChapter.status == "active",
            )
        )).scalars().all()
        result.update(siblings)
        result.update(parent_ids)  # 父考点本身也加入

    if upward_levels <= 0:
        return list(result)

    # 从每个起点向上一级，批量收集祖 parent_id
    current_parents = parent_ids
    visited_parents = set(current_parents)

    for _ in range(upward_levels):
        if not current_parents:
            break

        # 批量查父节点
        parents = (await db.execute(
            select(CanonicalChapter).where(
                CanonicalChapter.id.in_(list(current_parents)),
                CanonicalChapter.status == "active",
            )
        )).scalars().all()

        next_parent_ids = set()
        for parent in parents:
            result.add(parent.id)
            if parent.parent_id and parent.parent_id not in visited_parents:
                next_parent_ids.add(parent.parent_id)
                visited_parents.add(parent.parent_id)

        # 批量查祖节点的所有子节点（含新兄弟）
        if next_parent_ids:
            cousins = (await db.execute(
                select(CanonicalChapter.id).where(
                    CanonicalChapter.parent_id.in_(list(next_parent_ids)),
                    CanonicalChapter.status == "active",
                )
            )).scalars().all()
            result.update(cousins)

        current_parents = next_parent_ids

    return list(result)
```

#### 坑 3：跨章节关联的结构化检索完全失效

**场景**：用户问了一道"计算机组成原理"中关于 Cache 的题，但"操作系统"中的"虚拟内存"与 Cache 的地址映射机制高度相关。

**根因**：结构化检索只能沿考点树（`parent_id`）和 link 表（`*_chapter_links`）展开，无法跨越 `subject_id` 的边界。

**解法**：这正是需要向量检索 + 关系图谱的场景，详见第 5 节。

### 4.4 结构化检索的推荐实现

```python
async def retrieve_by_exam_point(
    db: AsyncSession,
    question_id: str,
    expand_to_siblings: bool = True,
    expand_upward_levels: int = 1,
) -> Dict[str, Any]:
    """
    从一道题出发，围绕考点展开所有相关知识。

    返回:
    {
        "question": {...},
        "primary_chapter": {...},
        "chapters": [...],              # 所有展开的考点
        "questions_by_chapter": {...},  # chapter_id → [Question]
        "knowledge_points_by_chapter": {...},  # chapter_id → [KnowledgePoint]
    }
    """
    # Step 1: 题目 → 考点（批量）
    chapter_links = (await db.execute(
        select(QuestionChapterLink).where(
            QuestionChapterLink.question_id == question_id
        )
    )).scalars().all()
    chapter_ids = [link.canonical_chapter_id for link in chapter_links]

    # Step 2: 扩展考点范围
    all_chapter_ids = set(chapter_ids)
    if expand_to_siblings:
        expanded = await expand_chapter_scope(db, chapter_ids, expand_upward_levels)
        all_chapter_ids.update(expanded)

    # Step 3: 批量收集范围内的题目和知识点
    questions = (await db.execute(
        select(Question).join(QuestionChapterLink).where(
            QuestionChapterLink.canonical_chapter_id.in_(list(all_chapter_ids)),
            Question.id != question_id,
            Question.review_status == "approved",
        )
    )).scalars().all()

    knowledge_points = (await db.execute(
        select(KnowledgePoint).join(KnowledgePointChapterLink).where(
            KnowledgePointChapterLink.canonical_chapter_id.in_(list(all_chapter_ids)),
            KnowledgePoint.review_status == "approved",
        )
    )).scalars().all()

    # Step 4: 按考点分组返回
    return {
        "question": ...,
        "primary_chapter": ...,
        "chapters": await _load_chapters(db, all_chapter_ids),
        "questions_by_chapter": _group_by_chapter(questions),
        "knowledge_points_by_chapter": _group_by_chapter(knowledge_points),
    }
```

---

## 5. 问题三：跨章节、跨科目的深层次考点关联

### 5.1 为什么纯语义相似度不够

如果只是把两个考点的 `enhanced_description` 做 embedding，然后算 cosine similarity：

- "Cache 的地址映射" vs "虚拟内存的地址映射" → cosine 可能很高（共享"地址映射"这个词）
- 但 cosine 只能告诉你**它们表述相似**，不能告诉你**它们是什么关系**

你不知道：
- 哪个是另一个的前置知识？
- 它们是容易混淆的对比关系，还是同一概念在不同上下文中的表述？
- 用户应该先学哪个？

**cosine similarity 是信号，不是关系。**

### 5.2 四层关联策略

跨章节考点关联不能靠单一手段，需要四层策略叠加，从精确到模糊逐层降级：

```
Layer 1: 结构化关联（确定性高，覆盖面窄）
  → 同 parent_id 的兄弟考点（零误判，无法跨学科）
  → 同 subject_id 的考点树遍历

Layer 2: 知识点关系图桥接（确定性中，覆盖面中）
  → 考点A → KnowledgePointChapterLink → 知识点X
  → 考点B → KnowledgePointChapterLink → 知识点Y
  → KnowledgeRelation(X, Y) 存在边
  → ∴ 考点A 与 考点B 存在间接关联
  → 注意：系统初期大部分考点尚无关联知识点，需兜底

Layer 3: LLM 显式交叉引用（确定性高，覆盖面由 prompt 决定）
  → 在生成 enhanced_description 时标注 cross_references
  → 输入中包含全科目考点摘要目录，LLM 基于实际考点列表标注
  → 输出 chapter_id（非人读字符串），可精确 JOIN
  → 包含关联理由（reason），不只是相似度分数

Layer 4: Embedding 语义相似度（确定性低，覆盖面广）
  → 作为建关系的信号，不直接作为检索结果
  → 超阈值 → 自动创建 KnowledgeRelation（source_type="embedding"）
  → 待人工审核
  → 当 Layer 2 因冷启动无法产出结果时，可降级为直接按章节 embedding 相似度排序
```

### 5.3 Layer 1：结构化关联

已在 4.3 节坑 2 中详述。核心逻辑：

- 同 `parent_id` → 兄弟考点（大概率强关联）
- 同 `subject_id` + 同 `level` → 同级考点（关联性中等）
- 父子关系 → 包含关系（子考点是父考点的细化）

这一层的优势是**零误判**（结构化数据不会错），劣势是**无法跨学科**。

### 5.4 Layer 2：知识点关系图桥接

这是当前架构下最重要的跨章节关联机制。

**逻辑链**：

```
考点A（计组-Cache）
  → KnowledgePointChapterLink → 知识点"Cache 地址映射"
考点B（OS-虚拟内存）
  → KnowledgePointChapterLink → 知识点"虚拟内存地址映射"

KnowledgeRelation(
  source="Cache 地址映射",
  target="虚拟内存地址映射",
  relation_type="similar_to",
  evidence_text="语义相似度 0.88",
  source_type="embedding"
)

∴ 考点A 与 考点B 存在间接关联（通过知识点桥接）
```

**冷启动问题**：系统初期，大部分考点还没有关联知识点（知识点尚未入库或尚未建立关联），BFS 图遍历的起点集合 S 为空，Layer 2 将返回空。此时应跳过 Layer 2，直接使用 Layer 3（LLM cross_references）和 Layer 4（embedding 直接相似度）作为跨章关联来源。

**实现**（已修正 N+1 查询——原版在 BFS 循环内逐节点查询关系，现改为批量查询）：

```python
async def find_cross_chapter_relations(
    db: AsyncSession,
    chapter_id: str,
    max_depth: int = 2,
    min_confidence: float = 0.7,
) -> List[CrossChapterRelation]:
    """
    通过知识点关系图找到与指定考点关联的其他考点。

    算法：
    1. 考点 → KnowledgePointChapterLink → 该考点下的所有知识点（起点集合 S）
    2. 如果 S 为空（冷启动），直接返回空列表
    3. 从 S 出发，沿 KnowledgeRelation 边做 BFS（max_depth 跳），每层批量查询
    4. 收集到达的知识点集合 T
    5. T → KnowledgePointChapterLink → 关联的考点集合 C
    6. 排除原考点，按关系路径强度排序

    性能：O(levels × batch_size) 次 SQL，每层 1 次批量查询，
    而非 O(Σ|frontier|) 次逐节点查询。
    """
    from sqlalchemy import or_

    # Step 1: 考点 → 知识点（批量）
    kp_links = (await db.execute(
        select(KnowledgePointChapterLink).where(
            KnowledgePointChapterLink.canonical_chapter_id == chapter_id
        )
    )).scalars().all()
    start_kp_ids = {link.knowledge_point_id for link in kp_links}

    if not start_kp_ids:
        # 冷启动：该考点尚无关联知识点
        return []

    # Step 2: BFS 逐层批量查询
    visited: Dict[str, float] = {kp_id: 1.0 for kp_id in start_kp_ids}
    paths: Dict[str, List[RelationHop]] = {}
    frontier = list(start_kp_ids)

    for depth in range(max_depth):
        if not frontier:
            break

        # 批量查询当前层所有节点的关系边（一次 SQL）
        rows = (await db.execute(
            select(KnowledgeRelation).where(
                or_(
                    KnowledgeRelation.source_knowledge_id.in_(frontier),
                    KnowledgeRelation.target_knowledge_id.in_(frontier),
                ),
                KnowledgeRelation.review_status == "approved",
                KnowledgeRelation.confidence >= min_confidence,
            )
        )).scalars().all()

        next_frontier = []
        for rel in rows:
            # 确定邻居方向
            if rel.source_knowledge_id in frontier:
                from_kp = rel.source_knowledge_id
                neighbor = rel.target_knowledge_id
            else:
                from_kp = rel.target_knowledge_id
                neighbor = rel.source_knowledge_id

            if neighbor in start_kp_ids:
                continue  # 不回退到起点集合

            edge_confidence = float(rel.confidence or 0.5)
            cumulative = visited[from_kp] * edge_confidence

            if neighbor not in visited or cumulative > visited[neighbor]:
                visited[neighbor] = cumulative
                paths[neighbor] = paths.get(from_kp, []) + [RelationHop(
                    from_kp=from_kp,
                    to_kp=neighbor,
                    relation_type=rel.relation_type,
                    confidence=edge_confidence,
                )]
                if neighbor not in next_frontier:
                    next_frontier.append(neighbor)

        frontier = next_frontier

    # Step 3: 到达的知识点 → 考点（批量）
    reached_kp_ids = set(visited.keys()) - start_kp_ids
    if not reached_kp_ids:
        return []

    chapter_links = (await db.execute(
        select(KnowledgePointChapterLink).where(
            KnowledgePointChapterLink.knowledge_point_id.in_(list(reached_kp_ids)),
            KnowledgePointChapterLink.canonical_chapter_id != chapter_id,
        )
    )).scalars().all()

    # Step 4: 聚合到考点，按最强路径排序
    chapter_scores: Dict[str, CrossChapterRelation] = {}
    for link in chapter_links:
        score = visited.get(link.knowledge_point_id, 0)
        if link.canonical_chapter_id not in chapter_scores or \
           score > chapter_scores[link.canonical_chapter_id].score:
            chapter_scores[link.canonical_chapter_id] = CrossChapterRelation(
                target_chapter_id=link.canonical_chapter_id,
                score=score,
                via_knowledge_point_id=link.knowledge_point_id,
                path=paths.get(link.knowledge_point_id, []),
            )

    return sorted(chapter_scores.values(), key=lambda r: r.score, reverse=True)
```

**关键设计决策**：

- 只用 `review_status == "approved"` 的关系边，避免未审核的低质量关系污染结果
- 用累计置信度（路径上各边 confidence 的乘积）作为排序依据，路径越长置信度越低
- 保留完整路径（`paths`），便于前端展示关联推理链："考点A → 知识点X → [similar_to] → 知识点Y → 考点B"
- BFS 每层 1 次批量 SQL，而非逐节点查询，避免 N+1 问题
- 冷启动时优雅降级，返回空列表，由上层编排逻辑接管

### 5.5 Layer 3：LLM 显式交叉引用

这是最有效的跨章节关联手段——让 LLM 在生成 `enhanced_description` 时，基于**全科目考点摘要目录**主动标注跨章关联。

**关键改进**：原版设计中 LLM 只能看到当前考点的信息，只能靠训练数据猜测其他科目的考点名，容易编造不存在的考点、写错考点名导致无法解析。修正后的 prompt 提供一份所有科目的考点摘要目录作为参考上下文。

**Prompt 设计**（在大纲导入的增强阶段使用）：

```text
你是一个 408 考研大纲分析专家。请为以下考点生成增强描述，并标注跨章节关联。

## 全科目考点目录（供关联标注参考）

{all_chapters_catalog}
<!-- 格式：
数据结构 (data_structure)
  CH1.1 线性表 (chap_xxx_001)
    CH1.1.1 顺序表 (chap_xxx_002)
    CH1.1.2 链表 (chap_xxx_003)
  CH1.2 栈和队列 (chap_xxx_004)
    ...

计算机组成原理 (computer_organization)
  CH2.1 计算机系统概述 (chap_yyy_001)
    ...

操作系统 (operating_system)
  ...

计算机网络 (computer_network)
  ...
-->

## 当前考点

- 科目：{subject_name}
- 章节路径：{chapter_path}
- 考点名称：{name}
- 大纲原文：{description}

请输出 JSON：
{
  "enhanced_description": "2-3 句增强描述，包含核心内容、常见考法、易混点",
  "keywords": ["关键词1", "关键词2", ...],

  "cross_references": [
    {
      "target_chapter_id": "chap_yyy_042",
      "relation_type": "similar_to",
      "reason": "Cache 地址映射和虚拟内存地址映射都涉及地址转换机制，但映射粒度和失效处理策略不同，408 考试中常将两者对比出题"
    }
  ]
}

要求：
1. cross_references 只标注确实存在强关联的跨章节考点，宁缺毋滥
2. target_chapter_id 必须从上方考点目录中选择，不得编造
3. relation_type 取值为 similar_to / prerequisite / contrast_with / common_confusion
4. reason 必须具体说明关联原因，不能只写"两者相关"
5. 如果没有跨章节关联，返回空数组 []
```

**为什么必须用 `chapter_id` 而非人读字符串**：

| 方式 | 问题 |
|------|------|
| `"target_subject": "操作系统"` + `"target_chapter_path": "内存管理 > 虚拟内存"` | LLM 可能编造不存在的章节路径，解析时需模糊匹配，可能匹配到错误考点 |
| `"target_chapter_id": "chap_yyy_042"` | 直接从目录中选择，精确匹配，零歧义 |

LLM 从给定的考点目录中选择 ID，而不是靠记忆编造。即使 LLM 选错了 ID，也能在人工审核阶段发现并修正。

**存储**：在 `CanonicalChapter` 表新增 JSON 字段 `cross_references`：

```python
# mysql_models.py - CanonicalChapter 新增字段
cross_references: Mapped[Optional[List[dict]]] = mapped_column(
    JSON,
    comment="LLM 标注的跨章节考点关联。每项含 target_chapter_id/relation_type/reason。target_chapter_id 可直接 JOIN canonical_chapters"
)
```

**入库时的校验**：

```python
async def validate_cross_references(
    db: AsyncSession,
    cross_refs: List[dict],
) -> List[dict]:
    """校验 LLM 输出的 cross_references：确保 target_chapter_id 真实存在。"""
    if not cross_refs:
        return []

    target_ids = [ref["target_chapter_id"] for ref in cross_refs]
    existing = (await db.execute(
        select(CanonicalChapter.id).where(
            CanonicalChapter.id.in_(target_ids),
            CanonicalChapter.status == "active",
        )
    )).scalars().all()
    existing_set = set(existing)

    valid = [ref for ref in cross_refs if ref["target_chapter_id"] in existing_set]
    if len(valid) < len(cross_refs):
        logger.warning(
            "cross_references 包含无效 chapter_id，已过滤",
            total=len(cross_refs), valid=len(valid),
            invalid_ids=[ref["target_chapter_id"] for ref in cross_refs
                         if ref["target_chapter_id"] not in existing_set],
        )
    return valid
```

**为什么这比 embedding 相似度好**：

| 维度 | Embedding Cosine | LLM Cross References |
|------|-----------------|---------------------|
| 关系类型 | 不知道 | 明确标注（similar_to / prerequisite / ...） |
| 关联理由 | 没有 | 有具体 reason |
| 方向性 | 无向 | 有向（如 prerequisite） |
| 可审核 | 只能看分数 | 可人工确认/修正 reason |
| 覆盖面 | 广（所有配对都能算） | 窄（LLM 只标注确实重要的） |
| 误报率 | 高（词面相似但实际无关） | 低（LLM 基于考点目录选择，有语义理解） |
| 目标精度 | 依赖向量质量 | chapter_id 精确匹配，不会指错考点 |

### 5.6 Layer 4：Embedding 语义相似度——作为建关系的信号

这一层已在 `RelationService._build_semantic_edges`（`relation_service.py:164`）中实现：

```python
# 当前代码逻辑
RelationService._build_semantic_edges(kp_list):
  1. 对每个知识点取 summary/title + topic_terms → embedding
  2. 两两计算 cosine similarity
  3. 超阈值（0.82）且尚无关系的配对 → 创建 similar_to 关系边
  4. source_type = "embedding", review_status = "pending"
```

**关键设计原则**：embedding 相似度**不直接作为检索结果返回给用户**，而是作为**建关系的信号**写入 `KnowledgeRelation` 表，经过审核后成为可信的关系边。

这样做的原因：
- 关系一旦写入就是持久化的、可审核的、可追溯的
- 审核通过的边可以在后续所有检索中复用，不需要每次都算相似度
- 审核不通过的边被标记为 `rejected`，不会再次出现

**冷启动时的降级使用**：当 Layer 2 因无关联知识点而返回空、且 Layer 3 的 `cross_references` 也未覆盖时，可临时使用章节 embedding 的直接相似度作为兜底：

```python
async def fallback_chapter_similarity(
    db: AsyncSession,
    chapter_id: str,
    top_k: int = 5,
) -> List[tuple[str, float]]:
    """
    冷启动兜底：直接用章节 segment 的 embedding 计算相似度。
    仅在 Layer 2 和 Layer 3 均无产出时使用。

    返回: [(target_chapter_id, cosine_score), ...]
    """
    from app.services.embedding_service import get_embedding_service_from_settings
    from app.db.qdrant import qdrant_manager

    # 用源章节的 segment 作为 query
    embedding = await get_embedding_service_from_settings(db)

    # 获取源章节信息（用于构造查询文本）
    chapter = await db.get(CanonicalChapter, chapter_id)
    if not chapter:
        return []

    query_text = f"{chapter.name} {chapter.enhanced_description or ''}"
    query_vector = await embedding.embed_text(query_text)

    results = qdrant_manager.search(
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
        ]),
        limit=top_k + 1,  # +1 因为会命中自己
    )

    # 排除自身，过滤低分
    pairs = []
    for hit in results:
        if hit.payload.get("entity_id") == chapter_id:
            continue
        if hit.score < 0.75:
            continue
        pairs.append((hit.payload["entity_id"], hit.score))
    return pairs[:top_k]
```

**扩展**：同样的逻辑可以应用于考点-考点关系。如果未来需要直接在考点之间建关系，可以新增 `ChapterRelation` 表：

```sql
CREATE TABLE chapter_relations (
    id VARCHAR(32) PRIMARY KEY,
    source_chapter_id VARCHAR(32) NOT NULL,
    target_chapter_id VARCHAR(32) NOT NULL,
    relation_type ENUM('similar_to', 'prerequisite', 'contrast_with', 'common_confusion'),
    confidence DECIMAL(5,4),
    source_type ENUM('llm', 'embedding', 'manual'),
    evidence_text TEXT,
    review_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_chapter_id) REFERENCES canonical_chapters(id),
    FOREIGN KEY (target_chapter_id) REFERENCES canonical_chapters(id)
);
```

但在当前阶段，通过知识点桥接（Layer 2）已经能间接表达考点间的关系，暂不需要单独的 `ChapterRelation` 表。

---

## 6. 端到端检索流程设计

### 6.1 用户问一道题时的完整链路

```
输入: 用户问题 Q（自然语言）

Phase 0: 大纲定位 + Query 扩展（新增，~50ms，零 LLM 成本）
  ├── Q embedding → Qdrant 搜 entity_type="canonical_chapter"
  ├── 命中 top-3 考点，提取:
  │   ├── keywords → 术语扩展（用户用语 → 学科标准术语）
  │   ├── enhanced_description → 语义扩展（学科语言描述）
  │   └── subject_id + chapter_ids → 结构化过滤条件
  └── 产出: expanded_query + subject_ids + chapter_ids

Phase 1: 问题定位
  ├── 1a. 结构化匹配: Q 中的题号/年份/试卷名 → Question 精确查找
  ├── 1b. 语义匹配: expanded_query embedding → Qdrant → top-K 题目
  └── 1c. 关键词匹配: Q 中的术语 → CanonicalChapter.keywords → 定位考点

Phase 2: 考点展开（如果 Phase 0/1 定位到了题目或考点）
  ├── 2a. 题目 → QuestionChapterLink → 考点列表
  ├── 2b. 考点 → expand_chapter_scope() → 兄弟考点（Layer 1，同章）
  ├── 2c. 考点 → CanonicalChapter.cross_references → 关联考点（Layer 3，跨章）
  └── 2d. 考点 → find_cross_chapter_relations() → 关联考点（Layer 2，跨章）

Phase 3: 内容召回
  ├── 3a. 在展开的考点范围内检索知识点（RetrievalService.search + chapter_ids filter）
  ├── 3b. 在展开的考点范围内检索题目（同上）
  └── 3c. 通过 KnowledgeRelation 扩展关联知识点（search_with_relations）

Phase 4: 排序与返回
  ├── 4a. 按考点分组
  ├── 4b. 按关联来源分层排序: 同章 > cross_references > 图桥接 > embedding 兜底
  └── 4c. 标注关联来源（同章/cross_references/图桥接/embedding相似度）
```

### 6.2 检索模式选择

| 用户意图 | 检索模式 | 说明 |
|---------|---------|------|
| "2018年408计网TCP的题" | 结构化过滤 + 精确匹配 | 年份/科目/关键词都很明确 |
| "操作系统里进程调度相关的知识点" | 语义检索考点 → 结构化展开 | 先定位考点，再展开内容 |
| "Cache和虚拟内存有什么关系" | 语义检索 + 跨章关联扩展 | 需要跨章节关联 |
| "二叉树遍历有哪些考法" | 考点 keywords 匹配 → 同考点内容召回 | 考点名明确 |

### 6.3 跨章关联编排逻辑——层叠降级策略

这是关联扩展的核心编排函数，定义了各层的调用顺序和降级条件：

```python
async def expand_related_chapters(
    db: AsyncSession,
    chapter_ids: List[str],
    user_query: Optional[str] = None,
    max_results: int = 10,
) -> Dict[str, List[RelatedChapter]]:
    """
    跨章关联编排：层叠降级策略。

    对每个 chapter_id，按以下优先级收集关联考点：
    1. Layer 1 (结构化): 同 parent_id 兄弟考点 —— 零误判，优先
    2. Layer 3 (LLM标注): cross_references —— 精确标注，高质量
    3. Layer 2 (关系图桥接): find_cross_chapter_relations() —— 中置信度
    4. Layer 4 (embedding兜底): fallback_chapter_similarity() —— 低置信度，仅兜底

    去重规则：同一 target_chapter_id 只保留最高优先级来源的结果。

    返回: {chapter_id: [RelatedChapter(source, score, relation_type, reason), ...]}
    """
    result: Dict[str, Dict[str, RelatedChapter]] = {
        cid: {} for cid in chapter_ids
    }

    for chapter_id in chapter_ids:
        chapter = await db.get(CanonicalChapter, chapter_id)
        if not chapter:
            continue
        seen = result[chapter_id]

        # ---- Layer 1: 结构化关联（同章兄弟） ----
        if chapter.parent_id:
            siblings = (await db.execute(
                select(CanonicalChapter).where(
                    CanonicalChapter.parent_id == chapter.parent_id,
                    CanonicalChapter.id != chapter_id,
                    CanonicalChapter.status == "active",
                )
            )).scalars().all()
            for sib in siblings:
                if sib.id not in seen:
                    seen[sib.id] = RelatedChapter(
                        chapter_id=sib.id,
                        source="sibling",
                        score=1.0,
                        relation_type="similar_to",
                    )

        # ---- Layer 3: LLM 显式标注 ----
        if chapter.cross_references:
            for ref in chapter.cross_references:
                target_id = ref.get("target_chapter_id")
                if target_id and target_id not in seen:
                    seen[target_id] = RelatedChapter(
                        chapter_id=target_id,
                        source="llm_cross_reference",
                        score=0.9,
                        relation_type=ref.get("relation_type", "similar_to"),
                        reason=ref.get("reason"),
                    )

        # ---- Layer 2: 知识点关系图桥接 ----
        try:
            bridged = await find_cross_chapter_relations(db, chapter_id)
            for br in bridged:
                if br.target_chapter_id not in seen:
                    seen[br.target_chapter_id] = RelatedChapter(
                        chapter_id=br.target_chapter_id,
                        source="knowledge_bridge",
                        score=br.score,
                        relation_type=br.path[-1].relation_type if br.path else "similar_to",
                    )
        except Exception as e:
            logger.warning("关系图桥接失败，跳过", chapter_id=chapter_id, error=str(e))

        # ---- Layer 4: embedding 兜底（仅冷启动） ----
        if len(seen) == 0:
            try:
                sims = await fallback_chapter_similarity(db, chapter_id, top_k=3)
                for target_id, score in sims:
                    if target_id not in seen:
                        seen[target_id] = RelatedChapter(
                            chapter_id=target_id,
                            source="embedding_fallback",
                            score=score,
                            relation_type="similar_to",
                        )
            except Exception as e:
                logger.warning("embedding 兜底失败", chapter_id=chapter_id, error=str(e))

    # 按 score 降序，取 top max_results
    return {
        cid: sorted(entries.values(), key=lambda r: r.score, reverse=True)[:max_results]
        for cid, entries in result.items()
    }
```

**关键点**：

- Layer 2 在图桥接为空（冷启动）时被跳过，不阻塞后续层
- Layer 4 仅在前面所有层都无产出时触发，作为最后的兜底
- 每个关联都标注 `source`，前端可以据此展示不同的可靠性标记
- 同 `target_chapter_id` 的去重策略是"高优先级来源优先"而非"高分优先"——因为结构化关联的确定性远高于任何向量分数

---

## 7. 实施路线

### 7.0 前置修复（P0，必须先做）

| 任务 | 说明 |
|------|------|
| 修复 `RetrievalSegment.entity_type` Enum | `mysql_models.py:1327` → `Enum("knowledge_point", "question", "canonical_chapter")` |
| 添加 Qdrant payload `entity_type` 索引 | `qdrant.py:112` → `"entity_type": PayloadSchemaType.KEYWORD` |
| Alembic 迁移 | 生成 migration 修改 `retrieval_segments.entity_type` 列定义 |

### 7.1 短期（当前即可做，无需新表）

| 任务 | 说明 | 优先级 |
|------|------|--------|
| 考点 segment 写入 Qdrant | `SegmentService.build_canonical_chapter_segments()` 已实现，确认调用链路完整 | P0 |
| 实现 `expand_query_with_outline()` | 大纲辅助 Query 扩展，Phase 0 核心能力（3.6 节） | P0 |
| 实现 `retrieve_by_exam_point()` | 从题出发的结构化展开（4.4 节） | P0 |
| 实现 `expand_chapter_scope()` | 沿考点树向上扩展，批量查询版（4.3 节坑 2） | P0 |
| 验证 `_match_by_vector_search` | 确认考点 segment 能被 ChapterLinkService 检索到（前提：entity_type 索引已建） | P1 |

### 7.2 中期（需要开发新字段 + 新表）

| 任务 | 说明 | 优先级 |
|------|------|--------|
| `CanonicalChapter.cross_references` 字段 | JSON 字段 + Alembic 迁移 | P1 |
| 大纲导入 LLM prompt 加入考点目录 + cross_references 标注 | 5.5 节完整 prompt，包含全科目考点目录 | P1 |
| `cross_references` 入库校验 | 检查 `target_chapter_id` 是否真实存在（5.5 节 validate 函数） | P1 |
| 实现 `find_cross_chapter_relations()` | 知识点关系图桥接，批量查询版（5.4 节） | P1 |
| 实现 `expand_related_chapters()` | 跨章关联编排降级逻辑（6.3 节） | P1 |
| 检索结果标注关联来源 | 前端展示 `source` 字段区分"同章" / "LLM标注" / "图桥接" / "embedding兜底" | P2 |

### 7.3 远期（视需求决定）

| 任务 | 说明 | 优先级 |
|------|------|--------|
| `ChapterRelation` 表 | 考点间直接关系表（如果桥接方案覆盖不足） | P3 |
| 关系图可视化 | 管理端展示考点-知识点-考点关联图 | P3 |
| `cross_references` 人工审核面板 | 管理端可查看/编辑/确认 LLM 标注的跨章关联 | P3 |

---

## 8. 关键设计决策汇总

| 决策 | 结论 | 理由 |
|------|------|------|
| 大纲考点是否入向量库 | 入，但不单独建 collection | 考点是检索链路的第一级，写入 `knowledge_segments` 统一管理 |
| 短查询 vs 长文档语义不对称 | 大纲辅助 Query 扩展，不依赖 HyDE | 大纲是官方考点零幻觉；~50ms vs HyDE 的 1~2s；零 token 成本 |
| 题→考点→内容能否纯结构化 | 可以，但有 3 个坑 | 同义词（靠 keywords 穷举）、粒度（靠树展开）、跨章（靠关系图） |
| 跨章关联怎么做 | 四层叠降 | 结构化 → LLM 标注 → 知识点桥接 → embedding 兜底 |
| LLM cross_references 使用 chapter_id 还是字符串 | chapter_id | 精确 JOIN，避免 LLM 编造章节名导致的模糊匹配错误 |
| LLM prompt 是否需要考点目录上下文 | 需要 | 不给目录 LLM 会凭训练数据编造不存在的考点名 |
| Embedding 相似度的角色 | 建关系的信号 + 冷启动兜底 | 需要审核、持久化、可追溯；检索时仅在前层无产出时降级使用 |
| BFS 图遍历性能 | 每层 1 次批量 SQL | 避免 N+1 查询，O(levels) 次 DB 调用 |
| 是否需要 ChapterRelation 表 | 当前不需要 | 知识点桥接 + LLM cross_references 已能覆盖 |
| 冷启动策略 | Layer 2 空 → 跳过 → Layer 4 兜底 | 初期无知识点关联时，靠 embedding 相似度暂时支撑 |

---

## 9. 与现有文档的关系

- 本文档是 [multimodal-ingestion-retrieval-design.md](./multimodal-ingestion-retrieval-design.md) 的补充，聚焦于大纲考点在检索体系中的角色
- 数据结构以 [data-model.md](./data-model.md) 和 `mysql_models.py` 为准
- 检索策略继承 [multimodal-ingestion-retrieval-design.md](./multimodal-ingestion-retrieval-design.md) 第 7 节的分路检索设计
- 知识点关系网络继承同文档第 5.4 节的关系类型定义
