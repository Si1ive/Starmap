# 大纲考点检索与跨章节关联设计

> 版本：v1.3  
> 日期：2026-06-25  
> 状态：部分已实现（详见第 7 节 Implemented / Open Decisions）  
> 读者：Backend / Data

> **v1.3 关键变更**：确立 `ChapterRelation` 表为跨章「语义关联」的唯一真相源。
> 结构派生关联（同章兄弟 / 父 / 子）改为在线计算、不入表。
> `expand_related_chapters()` 由「在线编排器」重新定位为「离线构建器」——
> 它的产出落入 `ChapterRelation` 并走审核，检索时只读 `review_status="approved"` 的关系。
> 详见 5.6、6.3。

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

### 2.3 前置修复（已完成）

以下两个基础设施缺口在 v1.2 设计时尚未修复，现已落地，记录于此供追溯：

1. `RetrievalSegment.entity_type` Enum 已扩展为 `Enum("knowledge_point", "question", "canonical_chapter")`（`mysql_models.py:1380`），考点 segment 可正常写入。
2. Qdrant `_PAYLOAD_INDEXES` 已包含 `"entity_type": PayloadSchemaType.KEYWORD`（`qdrant.py:113`），按 `entity_type` 过滤不再全表扫描。

后续章节默认这两项已就绪。

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
  ├── scope_expansion（在线计算，见 5.7）
  └── semantic_relations（读 ChapterRelation 已审核行，见 5.7）
```

> **dense / sparse 应分别用扩展 query 和原始 query。** dense 检索吃 `expanded_query`（弥补短查询语义稀疏），sparse 检索应保留**原始 query**——把考点的 `enhanced_description`（上百字学科文本）灌进 LIKE 的关键词集合会引入大量噪声词，稀释精确匹配。
>
> ⚠️ **实现差距（Open Decision）**：当前 `RetrievalService.search_with_outline_expansion`（`retrieval_service.py:130`）把 `expanded_query` 同时喂给了 dense 和 sparse 两路，与此处设计不符。收口时应让 sparse 路回退到原始 query（或仅叠加考点 keywords，不叠加 enhanced_description）。另外建议 chapter filter 只取高置信度 top-1/top-2，而非全部 top-k，避免多考点命中时把候选集扩成混杂主题。

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

**结论：这条链路可以用纯结构化检索完成——但"可行"是有前提的，不是无条件成立。**

纯结构化链路的可行性完全依赖 link 表的质量，以下三个前提必须同时满足，否则只是理论可行而非工程可行：

1. **`QuestionChapterLink` 和 `KnowledgePointChapterLink` 足够完整**——题目/知识点都已建立考点关联，缺链就漏召回；
2. **审核流已把主章节（`is_primary`）修准**——主考点选错，整条展开都偏；
3. **删除/重审会同步清理旧 link**——题目改判考点后，旧链不清理会召回到错误考点下。

冷启动期这三条往往都不满足，此时结构化链路需要 3.6 节的大纲 Query 扩展和向量检索兜底，不能单独支撑。

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

> **命名说明（Open Decision）**：当前实现叫 `retrieve_by_exam_point()`（`outline_retrieval_service.py:264`），但它的入参其实是 `question_id`，名实不符。一旦后续要支持"用户直接命中考点、不经过题目"的入口，这层抽象会卡住。建议拆成两个函数：`retrieve_by_question(question_id)`（先 题→考点 再展开）和 `retrieve_by_chapters(chapter_ids)`（直接从考点展开），前者调用后者。下面的示例沿用现名，但应理解为 `retrieve_by_question` 的逻辑。

```python
async def retrieve_by_exam_point(  # → 建议更名 retrieve_by_question
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

### 5.2 关联在「考点」这一层建立——不在知识点层

> **v1.3 重大决策**：跨章关联**只在考点（CanonicalChapter）层建立**，不再依赖知识点关系图（`KnowledgeRelation`）做桥接。

**为什么砍掉知识点级关联**：

1. **展示粒度错配**：用户理解世界的单位是"考点/知识块"（如"Cache 的地址映射"），不是原子知识点。"考点A ↔ 考点B + reason"比"知识点x ↔ 知识点y"更可读，关联理由也更完整。
2. **底层数据不可信**：`KnowledgeRelation` 的关系类型（`common_confusion`/`contrast_with` 等）当前是**字面规则 + N² embedding 堆出来的**（`relation_service.py:226` 的 `_detect_relations` 靠标题字符级 Jaccard 和关键词命中，`_build_semantic_edges` 靠两两 cosine），没有语义理解，relation_type 标签准确性很低，不能直接展示给用户。
3. **N² 成本**：知识点级关系是全库两两比对（两遍 N² 双循环），知识点上千时 CPU 成本失控；考点数量小一两个数量级，且关联用 LLM 挑选（O(N) 调用），成本可控。
4. **冗余**：拿到考点后，顺 `KnowledgePointChapterLink` / `QuestionChapterLink` 就能 JOIN 出该考点下所有知识点和题目。考点关联已经间接覆盖了"相关知识点"，不需要再单独维护知识点关联。

**保留的考点级关联来源**（按可靠性排序，都落 `ChapterRelation` 表）：

```
来源 1: scope expansion —— 结构派生（不入表，在线算，见 5.7）
  → 同 parent_id 的兄弟考点 / 父考点 / 子考点
  → 零误判，但无法跨学科

来源 2: LLM 显式交叉引用（source_type="llm"，主力）
  → 大纲导入时，基于全科目考点目录标注 cross_references
  → 输出 target_chapter_id（可精确 JOIN）+ relation_type + reason
  → LLM 单对判断关系（易混/前置/对比）准确率高，是主力来源

来源 3: Embedding 语义相似度（source_type="embedding"，兜底）
  → 考点 segment 两两 cosine，超阈值建候选边
  → 仅作冷启动兜底：LLM 标注尚未覆盖时填充
  → 误报较高，需审核或 LLM 二次确认
```

> 关于 KnowledgeRelation / knowledge_bridge 的移除，见 5.4。

### 5.3 来源 1：结构派生（scope expansion）

已在 4.3 节坑 2 中详述。核心逻辑：

- 同 `parent_id` → 兄弟考点（大概率强关联）
- 同 `subject_id` + 同 `level` → 同级考点（关联性中等）
- 父子关系 → 包含关系（子考点是父考点的细化）

这一层的优势是**零误判**（结构化数据不会错），劣势是**无法跨学科**。它属于 scope expansion，**永远在线计算、不入 ChapterRelation 表**（见 5.7）。

### 5.4 为什么移除知识点级关联（knowledge_bridge）

v1.2 设计了一条"知识点关系图桥接"路径：考点A → 知识点X →（KnowledgeRelation 边）→ 知识点Y → 考点B，以此推断考点A 与 考点B 关联。本版**移除这条路径**，理由如下。

**根因：底层的 `KnowledgeRelation` 质量不可信。** 核查 `RelationService`（`relation_service.py`）后确认，知识点之间的关系边是这样建出来的：

- `_detect_relations`（`relation_service.py:226`）：纯**字面规则**。`common_confusion` 靠标题的字符级 Jaccard 相似度（`_string_similarity`，`:293` 按单字算交并比）；`contrast_with` 靠内容里出现"vs/对比/区别"等词；`prerequisite` 靠内容出现"前置/先修"且提到对方标题。没有任何语义理解。
- `_build_semantic_edges`（`relation_service.py:164`）：**全库 N² 两两 embedding cosine**，超 0.82 建 `similar_to` 边。不传 `subject_id` 时是全库所有知识点两比对。

这导致两个硬伤：

1. **关系类型标签基本是假的。** "标题字面像"不等于"易混淆"，"文中有'区别'二字"不等于"与对方构成对比"。展示给用户的 `relation_type` 不可信。
2. **N² 成本与噪声。** `_build_semantic_edges` 在 N 上千时做 N² 次纯 Python cosine，CPU 成本陡增；且大量"词面相似但实际无关"的误报涌入审核队列，这正是审核成本爆炸的真正来源。

**用考点级关联替代，而非修复它。** 与其投入成本修一条劣质的知识点关系图，不如直接在**考点层面**建关联——考点数量远少于知识点（百级 vs 千级），且 LLM 在考点层面标注关联（5.5 节）质量高、可解释。一旦有了考点级关联，用户要看"相关内容"时，顺着考点的 link 表就能精确拿到对应知识点和题目（4.4 节），不需要知识点之间再单独连边。

> **决策**：`KnowledgeRelation` 表和 `find_cross_chapter_relations()` 作为**跨章关联来源**被移除。跨章关联统一收敛到考点级（`ChapterRelation`）。`search_with_relations` 的知识点扩展功能一并废弃——它价值低且建立在劣质边上。

### 5.5 主来源：LLM 显式交叉引用

考点级关联的**主来源**——让 LLM 在生成 `enhanced_description` 时，基于**全科目考点摘要目录**主动标注跨章关联。这是质量最高、可解释、可审核的一路，绝大多数跨章关联应由它产出。

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

### 5.6 兜底来源：考点级 Embedding 相似度

LLM cross_references 是"宁缺毋滥"的——它只标注强关联，必然有遗漏。对于 LLM 没标到、但语义上确实相关的考点对，用**考点级 embedding 相似度**兜底补网。

**关键设计原则**：embedding 相似度**不直接作为检索结果返回给用户**，而是作为**建关系的信号**写入 `ChapterRelation` 表（`source_type="embedding"`），经过审核后才会出现在检索结果里。

这样做的原因：
- 关系一旦写入就是持久化的、可审核的、可追溯的
- 审核通过的边可以在后续所有检索中复用，不需要每次都算相似度
- 审核不通过的边被标记为 `rejected`，不会再次出现

> **注意**：v1.2 把 embedding 建边做在**知识点级**（`RelationService._build_semantic_edges`，全库 N² 两两 cosine，落 `KnowledgeRelation`）。本版**移除知识点级 embedding 建边**（理由见 5.4），改为只在**考点级**做——考点数量比知识点少一两个量级，N² 成本可控，且产出直接落 `ChapterRelation`、语义粒度更适合展示。

**实现**：直接用考点 segment 的 embedding 在 Qdrant 中找最近邻考点：

```python
async def fallback_chapter_similarity(
    db: AsyncSession,
    chapter_id: str,
    top_k: int = 5,
) -> List[tuple[str, float]]:
    """
    考点级 embedding 兜底：用章节 segment 的 embedding 找最相似的其他考点。
    产出写入 ChapterRelation（source_type="embedding", review_status="pending"）。

    返回: [(target_chapter_id, cosine_score), ...]
    """
    from app.services.embedding_service import get_embedding_service_from_settings
    from app.db.qdrant import qdrant_manager

    chapter = await db.get(CanonicalChapter, chapter_id)
    if not chapter:
        return []

    embedding = await get_embedding_service_from_settings(db)
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

**这套逻辑统一落在 `ChapterRelation` 表上。** 该表已实现（`mysql_models.py:1325`），是考点间**语义关系的唯一真相源**：

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

关于真相源的边界，见下一节 5.7 的统一约定——这是本版文档相对 v1.2 最重要的修正。

### 5.7 关联结果的二分：scope expansion vs semantic relation（核心约定）

v1.2 把"同章兄弟"和"跨章语义关联"混在同一个 `RelatedChapter` 返回类型里（`outline_retrieval_service.py:68`），这导致语义污染：sibling 是**结构派生**，不是推断出来的关系。本版强制把关联结果拆成两类，各自有不同的真相源和生命周期：

| 维度 | scope expansion（范围展开） | semantic relation（语义关联） |
|------|----------------------------|------------------------------|
| 来源 | sibling / parent / child | llm_cross_reference / embedding |
| 本质 | 考点树的结构派生 | 推断出来的考点间关系 |
| 真相源 | **不持久化**，每次在线由 `parent_id` 实时计算 | **ChapterRelation 表（唯一真相源）** |
| 审核 | 不需要（结构不会错） | 需要，检索只读 `review_status="approved"` 的行 |
| 失效风险 | 无（树一改自动反映） | 持久化数据，需重建/重审同步 |

**为什么 scope expansion 不入 ChapterRelation 表**：

- sibling/parent/child 完全可由 `parent_id` 推导，持久化进表是冗余；
- 考点树一旦调整（新增/移动/删除子考点），表里的 sibling 行会立刻 stale，反而要额外维护一致性；
- 它零误判，没有"审核"的意义。

**为什么 semantic relation 必须以 ChapterRelation 为唯一真相源**：

- llm_cross_reference、embedding 都是**推断**，有误报，必须可审核、可追溯；
- 审核动作（approve/reject）只有落在一张表上、且检索只读这张表，才能真正生效；
- 检索结果可复用审核结论，不必每次在线重算相似度。

#### 真相源约定（必须遵守）

1. **语义关联的唯一真相源是 `ChapterRelation` 表。** 检索扩展只读 `review_status="approved"` 的行，不在线重算 llm/embedding。
2. **scope expansion 永远在线计算**，不写入任何表。
3. **`ChapterRelation` 的写入只有一个入口**：离线构建器 `/chapter-relations/build`。它聚合 LLM cross_references（主）+ embedding 兜底（次）两类来源，全部以 `pending` 落库，走审核后才 `approved`。检索侧任何时候都不在线推断关系。

#### 当前代码与本约定的差距（Open Decisions，见第 7 节）

- `expand_related_chapters()`（`outline_retrieval_service.py:507`）目前**不读 ChapterRelation 表**，在线重算并直接返回。这意味着审核中心对 `/search/chapter-expansion` 的结果**零影响**——审核动作没有接进检索回路。这是本版要收口的头号问题：在线侧改为读 `ChapterRelation WHERE review_status='approved'`，`expand_related_chapters` 降级为离线构建器的内部实现。
- `KnowledgeRelation` / `find_cross_chapter_relations`（knowledge_bridge）整层移除——理由见 5.4。跨章关联不再经知识点桥接，统一收敛到考点级。

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
  ├── 2b. scope_expansion（在线计算，不入表）:
  │       考点 → expand_chapter_scope() → 兄弟/父/子考点
  └── 2c. semantic_relations（读 ChapterRelation 表，review_status="approved"）:
          考点 → ChapterRelation → 关联考点（llm / embedding / manual 来源）

Phase 3: 内容召回（双路归并，详见 6.4）
  ├── 路 A 语义直接召回（带分数，第一梯队）:
  │     expanded_query embedding → Qdrant 搜 knowledge_point + question segment
  │     → 命中项自带 cosine 分数
  └── 路 B 考点结构化展开（补网，第二梯队，设上限）:
        Phase 2 定位到的 chapter_ids → link 表 JOIN 取同考点知识点/题目
        → 无分数，作为上下文补充

Phase 4: 归并与返回
  ├── 4a. 路 A 与路 B 按 entity_id 去重（同一项以路 A 的分数为准）
  ├── 4b. 分层排序: 路 A 命中在前（按分数）→ 路 B 补充在后（按考点分组，截断上限）
  ├── 4c. 跨章关联(semantic_relations) 与 scope_expansion 分两区返回，不与内容混排
  └── 4d. 标注每项来源: vector_hit / chapter_expansion / cross_reference
```

> 注意 Phase 2 的两类展开有本质区别（详见 5.7）：scope_expansion 是结构派生、每次在线计算、不持久化；semantic_relations 一律读 `ChapterRelation` 表的已审核行，**不再在检索路径上在线推导**。这样审核中心对关系的 approve/reject 才会真正影响检索结果。

### 6.2 检索模式选择

| 用户意图 | 检索模式 | 说明 |
|---------|---------|------|
| "2018年408计网TCP的题" | 结构化过滤 + 精确匹配 | 年份/科目/关键词都很明确 |
| "操作系统里进程调度相关的知识点" | 语义检索考点 → 结构化展开 | 先定位考点，再展开内容 |
| "Cache和虚拟内存有什么关系" | 语义检索 + 跨章关联扩展 | 需要跨章节关联 |
| "二叉树遍历有哪些考法" | 考点 keywords 匹配 → 同考点内容召回 | 考点名明确 |

### 6.3 跨章关联的两个阶段：离线构建 + 在线读取

按 5.7 的真相源约定，跨章语义关联拆成两个互不重叠的阶段。**检索路径只读表，不在线推导。**

#### 阶段 A：离线构建器（写 ChapterRelation）

`build_chapter_relations` 负责把语义关联来源归一化落到 `ChapterRelation` 表，统一进审核队列。它聚合两类语义来源（注意：**不含 sibling**，sibling 属于 scope_expansion，永远在线算、不入表；也**不含 knowledge_bridge**，知识点级关联已移除，见 5.4）：

| 来源 | source_type | 产出方式 | confidence |
|------|-------------|---------|-----------|
| LLM 显式标注 | `llm` | `CanonicalChapter.cross_references`（经 `validate_cross_references`） | 0.9 |
| Embedding 相似度 | `embedding` | `fallback_chapter_similarity()`（考点级 N² 兜底） | cosine score |

```python
async def build_chapter_relations(
    db: AsyncSession,
    subject_id: Optional[str] = None,
    outline_id: Optional[str] = None,
) -> dict:
    """
    离线构建器：把 LLM / embedding 两类语义关联
    归一化写入 ChapterRelation（review_status="pending"），进审核队列。

    幂等：同一 (source, target, relation_type) 已存在则跳过。
    sibling/parent/child 不在此处理——它们是 scope_expansion，在线计算。
    knowledge_bridge 已移除——跨章关联只在考点级建立（见 5.4）。
    """
    chapters = await _load_active_chapters(db, subject_id, outline_id)
    chapter_ids = {ch.id for ch in chapters}

    for chapter in chapters:
        # 来源 1: LLM cross_references（双向各写一条）
        for ref in await validate_cross_references(db, chapter.cross_references or []):
            target_id = ref["target_chapter_id"]
            if target_id not in chapter_ids:
                continue
            for src, tgt in [(chapter.id, target_id), (target_id, chapter.id)]:
                await _upsert_chapter_relation(
                    db, src, tgt,
                    relation_type=ref.get("relation_type", "similar_to"),
                    confidence=0.9, source_type="llm",
                    evidence_text=ref.get("reason"),
                )

        # 来源 2: embedding 兜底（仅当该考点无 LLM 标注时，避免噪声淹没高质量标注）
        if not chapter.cross_references:
            for target_id, score in await fallback_chapter_similarity(db, chapter.id, top_k=3):
                if target_id not in chapter_ids:
                    continue
                await _upsert_chapter_relation(
                    db, chapter.id, target_id,
                    relation_type="similar_to",
                    confidence=score, source_type="embedding",
                    evidence_text=f"语义相似度 {score:.4f}",
                )

    await db.commit()
    return {"chapters_processed": len(chapters)}
```

> **相对 v1.2 的核心修正**：v1.2 把跨章关联做成在线四层（sibling / llm / knowledge_bridge / embedding），既与审核表脱节、又混入了不可信的知识点桥接。本版收敛为：sibling 剥离到 scope_expansion（在线算）；knowledge_bridge 整层移除（5.4）；只有 llm + embedding 两类语义关联落 `ChapterRelation`，经审核后供在线读取。

#### 阶段 B：在线读取器（读 ChapterRelation + 在线算 scope）

检索时不再调用任何在线推导逻辑，而是分两路取数后分组返回：

```python
async def expand_related_chapters(
    db: AsyncSession,
    chapter_ids: List[str],
    max_results: int = 10,
) -> Dict[str, Dict[str, list]]:
    """
    在线读取器：每个 chapter_id 返回两类关联，互不混排。

    返回: {
        chapter_id: {
            "scope_expansion":    [{chapter_id, relation}],        # 在线算，结构派生
            "semantic_relations": [{chapter_id, source_type,       # 读表，已审核
                                     relation_type, confidence, evidence_text}],
        }
    }
    """
    out: Dict[str, Dict[str, list]] = {}
    for chapter_id in chapter_ids:
        # 路 1: scope_expansion —— 在线计算，不读表
        scope = await expand_chapter_scope(db, [chapter_id], upward_levels=0)

        # 路 2: semantic_relations —— 只读 ChapterRelation 已审核行
        rows = (await db.execute(
            select(ChapterRelation).where(
                ChapterRelation.source_chapter_id == chapter_id,
                ChapterRelation.review_status == "approved",
            ).order_by(ChapterRelation.confidence.desc()).limit(max_results)
        )).scalars().all()

        out[chapter_id] = {
            "scope_expansion": [
                {"chapter_id": cid, "relation": "sibling_or_ancestor"}
                for cid in scope if cid != chapter_id
            ],
            "semantic_relations": [
                {
                    "chapter_id": r.target_chapter_id,
                    "source_type": r.source_type,
                    "relation_type": r.relation_type,
                    "confidence": float(r.confidence or 0),
                    "evidence_text": r.evidence_text,
                }
                for r in rows
            ],
        }
    return out
```

**关键点**：

- **审核生效**：semantic_relations 只取 `review_status="approved"`，审核员 reject 的关系不再出现在检索结果中——这修复了 v1.2 审核与检索脱节的问题
- **职责单一**：在线读取器零推导，所有"建关系"的逻辑（LLM/embedding）都在离线构建器里，由调度或管理端手动触发
- **scope 与 semantic 不混排**：前端分两区展示，scope 是"同章/上下层"，semantic 是"跨章关联"，可靠性语义不同（见 5.7）
- **冷启动**：初期 ChapterRelation 为空时，semantic_relations 自然为空，scope_expansion 仍可用；随大纲导入跑构建器 + 审核后逐步填充

### 6.4 内容召回：向量直接命中 + 考点结构化展开的双路分层归并

Phase 3 的内容召回是**召回率的主战场**。本节定义两路召回如何归并，这是本版相对 v1.2 的关键补强。

#### 两路召回

| | 路 A：向量直接命中 | 路 B：考点结构化展开 |
|---|---|---|
| 机制 | `expanded_query` embedding → Qdrant 检索 `knowledge_point` / `question` segment | 命中内容 → 其考点 → 同考点 link 表 JOIN 拉取知识点/题目 |
| 是否带分数 | 有（cosine 相似度） | 无（只是"与命中项同属一个考点"） |
| 强项 | 精确，命中用户真正问的 | 补网：捞向量没召回但同考点的内容 |
| 风险 | 短查询/同义词可能漏召回（靠 Phase 0 大纲扩展缓解） | 一个考点下可能挂几十个知识点，全拉进来会引入噪声 |

路 B 之所以成立，是因为它**先收敛到"考点"这个有界锚点再展开**，而不是顺着关键词无边界扩散——考点就是天然的主题边界，防止主题漂移。

#### 归并纪律（必须遵守）

1. **分层不混排**：路 A（向量命中）是第一梯队，按 cosine 分数排序；路 B（结构化展开）是第二梯队，作为补充上下文排在路 A 之后。**严禁 1:1 平铺混排**——否则路 B 的几十条无分数内容会把路 A 的精确命中淹没，召回率上去了精确率塌掉。
2. **路 B 设上限**：每个考点最多带 N 条展开内容（建议 N≤10），按"是否被路 A 也命中">"is_primary link">"更新时间"排序截断。
3. **JOIN 为主，关键词为辅**：一旦定位到考点，拉同考点内容走 **link 表 JOIN（精确）**，不要再用关键词去搜——关键词重搜会把"先根遍历 vs 前序遍历"的同义词问题又引回来。关键词 LIKE 只用于**补网**：捞那些还没建 link、但 `sparse_text` 里提到该术语的内容。
4. **去重**：路 A 和路 B 命中同一实体时，保留路 A 的分数版本，标注"双路命中"（可作为加权信号）。

```python
async def merge_dual_path_recall(
    db: AsyncSession,
    expanded_query: str,
    chapter_ids: List[str],      # Phase 2 展开后的考点范围
    subject_ids: List[str],
    limit: int = 20,
    per_chapter_cap: int = 10,
) -> List[dict]:
    """
    双路分层归并：向量直接命中（第一梯队）+ 考点结构化展开（第二梯队）。

    归并纪律见 6.4：分层不混排、路 B 设上限、JOIN 为主关键词为辅、去重保分数版。
    """
    # 路 A: 向量直接命中（带分数，第一梯队）
    vector_hits = await retrieval_service.search(
        query=expanded_query,
        subject_id=subject_ids[0] if subject_ids else None,
        chapter_ids=chapter_ids,
        entity_type=None,            # knowledge_point + question 都召回
        mode="hybrid",
        limit=limit,
    )
    seen_entity_ids = {h.entity_id for h in vector_hits}

    # 路 B: 考点结构化展开（无分数，第二梯队，JOIN 为主）
    scope_items: List[dict] = []
    for cid in chapter_ids:
        # 同考点知识点 / 题目，走 link 表 JOIN
        kps = await _join_knowledge_points_by_chapter(db, cid, limit=per_chapter_cap)
        qs = await _join_questions_by_chapter(db, cid, limit=per_chapter_cap)
        for item in kps + qs:
            if item["entity_id"] in seen_entity_ids:
                continue            # 已被路 A 精确命中，去重
            scope_items.append({**item, "source": "scope_expansion", "score": None})

    # 分层归并：路 A 在前（按分数），路 B 在后（补充上下文）
    tier1 = [{
        "entity_id": h.entity_id, "entity_type": h.entity_type,
        "score": h.score, "source": "vector",
        "dual_hit": h.entity_id in seen_entity_ids,
    } for h in sorted(vector_hits, key=lambda x: x.score, reverse=True)]

    return (tier1 + scope_items)[:limit]
```

> **为什么这样能提召回率而不牺牲精确率**：向量路保证"用户真正问的"排在最前且有分数；结构化路在向量漏召回时补上同考点的相关内容，但被限制在第二梯队 + per-chapter 上限内，不会反客为主。这正是 graph-RAG / parent-child retrieval 的标准做法。

---

## 7. 实施状态与待决项

本节不再是 roadmap——下列大部分能力已落地。分两部分：已实现（Implemented）和待决/缺口（Open Decisions / Remaining Gaps）。

### 7.1 已实现（Implemented）

| 能力 | 位置 | 状态 |
|------|------|------|
| `RetrievalSegment.entity_type` 含 `canonical_chapter` | `mysql_models.py:1380` | ✅ Enum 已含三值 |
| Qdrant `entity_type` payload 索引 | `qdrant.py:113` | ✅ `_PAYLOAD_INDEXES` 已含 |
| 考点 segment 写入 | `SegmentService.build_canonical_chapter_segments()` | ✅ 端点 `admin.py:4220` |
| Phase 0 大纲 Query 扩展 | `expand_query_with_outline()`（`outline_retrieval_service.py:81`） | ✅ 端点 `/search/with-outline` |
| 考点树展开 | `expand_chapter_scope()`（`:187`） | ✅ |
| 题 → 考点 → 知识结构化展开 | `retrieve_by_exam_point()`（`:264`） | ✅ 注：输入为 question_id，命名待澄清（见 7.2） |
| embedding 兜底（考点级） | `fallback_chapter_similarity()`（`:472`） | ✅ |
| ~~知识点关系图桥接~~ | `find_cross_chapter_relations()`（`:371`） | ⚠️ 已实现但**本版决定移除**（见 5.4，底层 KnowledgeRelation 质量不可信）——待清理 |
| `CanonicalChapter.cross_references` 字段 + 入库校验 | `validate_cross_references()`（`:603`） | ✅ |
| `ChapterRelation` 表 | `mysql_models.py:1325` | ✅ 含索引 + 唯一约束 |
| ChapterRelation 构建/查询/审核/批删端点 | `admin.py:4466/4571/4646/4687` | ✅ 审核中心已建 |
| 跨章关联编排 | `expand_related_chapters()`（`:507`）+ `/search/chapter-expansion` | ⚠️ 已实现但**在线重算、不读 ChapterRelation**——见 7.2 缺口 1 |

### 7.2 待决项 / 缺口（Open Decisions / Remaining Gaps）

| # | 缺口 | 现状 | 目标 |
|---|------|------|------|
| 1 | **审核不生效**：`expand_related_chapters()` 在线重算，不读 ChapterRelation 表，审核员的 approve/reject 对 `/search/chapter-expansion` 结果零影响 | 在线编排器与审核表脱节 | 在线侧改为读 `ChapterRelation WHERE review_status='approved'`（见 6.3 在线读取器）；`expand_related_chapters` 降级为离线构建器内部实现 |
| 2 | **移除知识点级关联**：`KnowledgeRelation` / `find_cross_chapter_relations()`（knowledge_bridge）底层质量不可信（见 5.4），跨章关联收敛到考点级 | 在线编排仍含 knowledge_bridge 层；`search_with_relations` 仍依赖 KnowledgeRelation | 从 `expand_related_chapters` 和构建器中移除 knowledge_bridge；废弃 `search_with_relations` 的知识点扩展 |
| 3 | **scope 与 semantic 混排**：`RelatedChapter` 把 sibling 和语义关系塞进同一返回类型 | 语义污染 | 按 5.7 拆为 `scope_expansion`（在线算，不入表）+ `semantic_relations`（读表），见 6.3 |
| 4 | `retrieve_by_exam_point()` 名实不符：名为"按考点取"，实为输入 question_id | — | 拆为 `retrieve_by_question(question_id)` / `retrieve_by_chapters(chapter_ids)` |
| 5 | **双路分层归并待落地**：Phase 3 内容召回的向量路 + 结构化路归并（6.4），当前 `search_with_outline_expansion` 只有向量路 | 召回率未充分利用考点结构 | 实现 `merge_dual_path_recall()`：路 A 向量命中（第一梯队带分数）+ 路 B 考点 link JOIN（第二梯队设上限），见 6.4 |
| 6 | query 扩写策略待调优：多考点命中时拼成混杂大串，100 字截断为拍脑袋 | minor | dense 用 expanded、sparse 保留原始 query + keywords boost；chapter filter 仅取高置信 top-1/2（需先确认 `search_with_outline_expansion` 实现） |
| 7 | 大纲导入 LLM prompt 接入 cross_references 标注 | prompt 待落地 | 5.5 节完整 prompt（含全科目考点目录） |
| 8 | 关系图可视化 / 审核面板 | ✅ 已有 ChapterRelations 管理页 | 持续完善 |

> **缺口 1/2/3 是同一收口的三个面**：把语义关系单一真相源定为 ChapterRelation，在线只读 approved；sibling/上下层拆到 scope 在线算；knowledge_bridge 整层移除，跨章关联收敛到考点级。这是下一步代码改动的核心，建议先文档后代码。

---

## 8. 关键设计决策汇总

| 决策 | 结论 | 理由 |
|------|------|------|
| 大纲考点是否入向量库 | 入，但不单独建 collection | 考点是检索链路的第一级，写入 `knowledge_segments` 统一管理 |
| 短查询 vs 长文档语义不对称 | 大纲辅助 Query 扩展，不依赖 HyDE | 大纲是官方考点零幻觉；~50ms vs HyDE 的 1~2s；零 token 成本 |
| 题→考点→内容能否纯结构化 | 可以，但有 3 个坑 | 同义词（靠 keywords 穷举）、粒度（靠树展开）、跨章（靠考点级 ChapterRelation） |
| 跨章关联怎么做 | scope（结构）+ semantic（语义）二分 | scope 在线推导不入表；semantic 两来源（llm/embedding）统一落 ChapterRelation |
| 跨章关联建在哪一级 | 考点级（CanonicalChapter），移除知识点级桥接 | 考点是天然展示粒度；KnowledgeRelation 关系类型是字面规则产出，不可信（见 5.4） |
| 内容召回如何提召回率 | 向量直接命中 + 考点结构化展开双路分层归并 | 分层不混排、路 B 设上限、JOIN 为主关键词为辅（见 6.4） |
| 知识点/题目是否入向量库 | 入 | 用户 query 对不上考点关键词的场景多，需向量语义召回到具体知识点/题目 |
| LLM cross_references 使用 chapter_id 还是字符串 | chapter_id | 精确 JOIN，避免 LLM 编造章节名导致的模糊匹配错误 |
| LLM prompt 是否需要考点目录上下文 | 需要 | 不给目录 LLM 会凭训练数据编造不存在的考点名 |
| Embedding 相似度的角色 | 建关系的信号 → 落 ChapterRelation 待审 | 需要审核、持久化、可追溯；不直接作为在线检索结果 |
| 语义关系的唯一真相源 | ChapterRelation 表 | 在线检索只读 `review_status='approved'`；审核动作对检索生效（修复 v1.2 脱节问题） |
| sibling/上下层是否入 ChapterRelation | 不入 | 结构可推导，入表会随树修改 stale；永远在线算（scope_expansion） |
| 冷启动策略 | ChapterRelation 空 → semantic 为空，scope 仍可用 | 随大纲导入跑构建器 + 审核逐步填充 semantic |

---

## 9. 与现有文档的关系

- 本文档是 [multimodal-ingestion-retrieval-design.md](./multimodal-ingestion-retrieval-design.md) 的补充，聚焦于大纲考点在检索体系中的角色
- 数据结构以 [data-model.md](./data-model.md) 和 `mysql_models.py` 为准
- 检索策略继承 [multimodal-ingestion-retrieval-design.md](./multimodal-ingestion-retrieval-design.md) 第 7 节的分路检索设计
- 知识点关系网络继承同文档第 5.4 节的关系类型定义
