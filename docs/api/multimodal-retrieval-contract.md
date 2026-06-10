# 408 多模态语料入库与检索 API 契约

> 版本：v1.0  
> 日期：2026-06-09  
> 状态：可开发  
> 读者：Backend / Frontend / Data / QA

---

## 1. 文档目标

本文档定义多模态语料入库、审核、检索、调试、问答相关的接口契约和前端数据结构草案。

适用范围：

1. 管理端语料管理页面
2. 管理端解析审核页面
3. 管理端知识点 / 题目审核页面
4. 主站或管理端检索调试页面
5. 后端检索编排与 RAG 服务

---

## 2. 契约原则

1. 所有字段统一 `snake_case`
2. 所有时间字段统一 ISO 8601
3. 所有分页响应统一 `items / total / page / page_size / total_pages`
4. 所有检索接口必须支持 `filters`
5. 所有检索结果必须可回溯到 `source_refs`
6. 题目检索与知识点检索必须分接口，不允许只保留一个混合入口

---

## 3. 枚举定义

## 3.1 文件与解析

| 名称 | 值 |
|------|----|
| `corpus_file_source_type` | `crawler`, `manual`, `upload`, `import` |
| `corpus_file_status` | `pending`, `parsing`, `parsed`, `extracting`, `indexed`, `failed`, `archived` |
| `parse_run_status` | `running`, `success`, `failed`, `partial` |
| `parse_mode` | `primary`, `fallback`, `retry`, `manual_fix` |
| `document_type` | `textbook`, `past_exam`, `mock_exam`, `notes`, `other` |

## 3.2 block 与资产

| 名称 | 值 |
|------|----|
| `block_type` | `title`, `heading`, `paragraph`, `list`, `table`, `table_caption`, `figure`, `figure_caption`, `formula`, `code`, `question_stem`, `question_option`, `question_answer`, `question_explanation`, `example`, `summary`, `unknown` |
| `asset_type` | `figure`, `table`, `formula`, `page_crop`, `other` |
| `review_status` | `pending`, `approved`, `rejected` |

## 3.3 实体与检索

| 名称 | 值 |
|------|----|
| `entity_type` | `knowledge`, `question`, `question_explanation`, `document` |
| `retrieval_mode` | `filter_only`, `sparse`, `dense`, `hybrid`, `hybrid_rerank` |
| `intent_type` | `retrieve_knowledge`, `retrieve_question`, `retrieve_mixed`, `qa`, `compare`, `explain_question` |
| `question_source_type` | `past_exam`, `textbook_example`, `mock_exam`, `practice`, `other` |

---

## 4. 通用数据体

## 4.1 `CorpusFile`

```json
{
  "id": "cf_001",
  "source_type": "crawler",
  "source_ref": "task_001",
  "file_name": "2018_408_tcp.pdf",
  "file_ext": "pdf",
  "local_path": "download/2018_408_tcp.pdf",
  "storage_uri": null,
  "sha256": "ab12...",
  "file_size": 1200345,
  "mime_type": "application/pdf",
  "language": "zh",
  "doc_type": "past_exam",
  "version": 1,
  "status": "parsed",
  "error_detail": null,
  "created_at": "2026-06-09T10:00:00Z",
  "updated_at": "2026-06-09T10:05:00Z"
}
```

## 4.2 `ParseRun`

```json
{
  "id": "pr_001",
  "corpus_file_id": "cf_001",
  "parser_name": "docling",
  "parser_version": "0.1.0",
  "parse_mode": "primary",
  "status": "success",
  "page_count": 24,
  "block_count": 382,
  "asset_count": 16,
  "confidence": 0.9621,
  "error_detail": null,
  "metrics_json": {
    "elapsed_ms": 5210
  },
  "started_at": "2026-06-09T10:00:00Z",
  "completed_at": "2026-06-09T10:00:05Z"
}
```

## 4.3 `Document`

```json
{
  "id": "doc_001",
  "corpus_file_id": "cf_001",
  "latest_parse_run_id": "pr_001",
  "title": "2018年408计算机网络真题",
  "doc_type": "past_exam",
  "subject_id": "subj_cn",
  "source_label": "2018年408/计算机网络",
  "exam_scope": "408",
  "exam_year": 2018,
  "paper_name": "2018年全国硕士研究生招生考试408",
  "language": "zh",
  "page_count": 24,
  "document_markdown": "# ...",
  "document_json": {},
  "status": "active",
  "created_at": "2026-06-09T10:00:00Z",
  "updated_at": "2026-06-09T10:00:05Z"
}
```

## 4.4 `DocumentBlock`

```json
{
  "id": "blk_001",
  "document_id": "doc_001",
  "page_id": "page_016",
  "page_no": 16,
  "block_type": "question_stem",
  "order_no": 7,
  "bbox": {
    "x1": 120,
    "y1": 340,
    "x2": 980,
    "y2": 580
  },
  "content_text": "关于TCP流量控制，下列说法正确的是...",
  "content_md": "关于 TCP 流量控制，下列说法正确的是...",
  "content_json": {},
  "latex": null,
  "html_table": null,
  "asset_id": null,
  "confidence": 0.9821,
  "review_status": "approved",
  "created_at": "2026-06-09T10:00:02Z",
  "updated_at": "2026-06-09T10:00:03Z"
}
```

## 4.5 `DocumentAsset`

```json
{
  "id": "ast_001",
  "document_id": "doc_001",
  "page_no": 16,
  "asset_type": "figure",
  "file_path": "storage/assets/doc_001/ast_001.png",
  "thumbnail_path": "storage/assets/doc_001/ast_001_thumb.png",
  "bbox": {
    "x1": 110,
    "y1": 600,
    "x2": 980,
    "y2": 920
  },
  "caption_text": "TCP窗口变化示意图",
  "ocr_text": "rwnd...",
  "metadata_json": {}
}
```

## 4.6 `SourceRef`

```json
{
  "document_id": "doc_001",
  "block_id": "blk_001",
  "page_no": 16,
  "quote_role": "stem",
  "quote_text": "关于TCP流量控制，下列说法正确的是..."
}
```

## 4.7 `RetrievalSegment`

```json
{
  "id": "seg_001",
  "entity_type": "question",
  "entity_id": "q_001",
  "document_id": "doc_001",
  "segment_role": "stem",
  "subject_id": "subj_cn",
  "chapter_id": "ch_cn_04",
  "content_text": "关于TCP流量控制...",
  "content_md": "关于 TCP 流量控制...",
  "context_text": "这是一道来自2018年408真题、计算机网络章节、主题为TCP流量控制的题目片段...",
  "keyword_text": "TCP 流量控制 窗口 408 2018",
  "metadata_json": {
    "exam_scope": "408",
    "exam_year": 2018,
    "paper_name": "2018年全国硕士研究生招生考试408",
    "topic_terms": ["tcp", "流量控制"]
  },
  "status": "active"
}
```

---

## 5. 管理端 API

## 5.1 文件扫描与注册

### `POST /api/v1/admin/corpus/files/scan`

用途：扫描目录并注册文件

请求：

```json
{
  "root_path": "download",
  "file_types": ["pdf", "docx", "pptx"],
  "batch_label": "bootstrap_20260609",
  "doc_type": "textbook"
}
```

响应：

```json
{
  "registered_count": 12,
  "skipped_count": 4,
  "items": [
    {
      "id": "cf_001",
      "file_name": "ds_book.pdf",
      "status": "pending"
    }
  ]
}
```

## 5.2 文件列表

### `GET /api/v1/admin/corpus/files`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 默认1 |
| `page_size` | int | 否 | 默认20 |
| `status` | string | 否 | 见 `corpus_file_status` |
| `doc_type` | string | 否 | 见 `document_type` |
| `source_type` | string | 否 | 见 `corpus_file_source_type` |
| `keyword` | string | 否 | 文件名搜索 |

响应：`ApiResponse<PaginatedResponse<CorpusFile>>`

## 5.3 单文件解析

### `POST /api/v1/admin/corpus/files/{file_id}/parse`

请求：

```json
{
  "parser": "docling",
  "fallback_enabled": true,
  "force_reparse": false
}
```

响应：

```json
{
  "parse_run_id": "pr_001",
  "status": "running"
}
```

## 5.4 解析任务列表

### `GET /api/v1/admin/corpus/parse-runs`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 默认1 |
| `page_size` | int | 否 | 默认20 |
| `status` | string | 否 | 见 `parse_run_status` |
| `corpus_file_id` | string | 否 | 文件过滤 |

## 5.5 文档详情

### `GET /api/v1/admin/corpus/documents/{document_id}`

响应：

```json
{
  "document": {},
  "pages": [],
  "assets_preview": [],
  "stats": {
    "page_count": 24,
    "block_count": 382,
    "asset_count": 16
  }
}
```

## 5.6 文档块列表

### `GET /api/v1/admin/corpus/documents/{document_id}/blocks`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page_no` | int | 否 | 按页过滤 |
| `block_type` | string | 否 | 按类型过滤 |
| `review_status` | string | 否 | 审核状态 |
| `page` | int | 否 | 分页 |
| `page_size` | int | 否 | 分页 |

## 5.7 触发实体抽取

### `POST /api/v1/admin/corpus/documents/{document_id}/extract`

请求：

```json
{
  "extract_targets": ["knowledge", "question"],
  "force_reextract": false
}
```

响应：

```json
{
  "job_id": "ext_001",
  "status": "running"
}
```

## 5.8 重建索引

### `POST /api/v1/admin/corpus/documents/{document_id}/index`

请求：

```json
{
  "entity_types": ["knowledge", "question"],
  "rebuild_segments": true,
  "rebuild_vectors": true
}
```

---

## 6. 审核 API

## 6.1 知识点审核列表

### `GET /api/v1/admin/review/knowledge`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `review_status` | string | 否 | pending/approved/rejected |
| `subject_id` | string | 否 | 学科 |
| `chapter_id` | string | 否 | 章节 |
| `source_document_id` | string | 否 | 来源文档 |
| `page` | int | 否 | 分页 |
| `page_size` | int | 否 | 分页 |

## 6.2 题目审核列表

### `GET /api/v1/admin/review/questions`

额外支持参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `exam_scope` | string | 否 | 例如408 |
| `exam_year` | int | 否 | 真题年份 |
| `question_type` | string | 否 | 题型 |

## 6.3 审核提交

### `POST /api/v1/admin/review/{entity_type}/{entity_id}`

请求：

```json
{
  "review_status": "approved",
  "review_notes": "题型、页码、知识点绑定已校正"
}
```

---

## 7. 检索 API

## 7.1 查询理解调试

### `POST /api/v1/admin/retrieval/understand`

请求：

```json
{
  "query": "找2018年408计算机网络中关于TCP的题目"
}
```

响应：

```json
{
  "intent_type": "retrieve_question",
  "entity_target": "question",
  "structured_filters": {
    "exam_scope": "408",
    "exam_year": 2018,
    "subject_id": "subj_cn"
  },
  "keywords": ["TCP", "计算机网络"],
  "must_terms": ["TCP"],
  "semantic_query": "2018年408真题中关于TCP的题目"
}
```

## 7.2 题目检索

### `POST /api/v1/retrieval/questions/search`

请求：

```json
{
  "query": "2018年408计算机网络TCP题目",
  "filters": {
    "exam_scope": "408",
    "exam_year": 2018,
    "subject_id": "subj_cn",
    "topic_terms": ["tcp"]
  },
  "mode": "hybrid_rerank",
  "top_k": 20,
  "return_debug": false
}
```

响应：

```json
{
  "items": [
    {
      "question": {
        "id": "q_001",
        "subject_id": "subj_cn",
        "chapter_id": "ch_cn_04",
        "type": "choice",
        "content": "关于TCP流量控制...",
        "options": [
          {"key": "A", "text": "..."}
        ],
        "answer": "B",
        "explanation": "...",
        "difficulty": "medium",
        "source": "2018年408真题",
        "exam_scope": "408",
        "exam_year": 2018,
        "paper_name": "2018年全国硕士研究生招生考试408",
        "question_no": "12",
        "topic_terms": ["tcp", "流量控制"],
        "modality_flags": ["has_figure"]
      },
      "score": 0.9231,
      "source_refs": [
        {
          "document_id": "doc_001",
          "block_id": "blk_001",
          "page_no": 16,
          "quote_role": "stem",
          "quote_text": "关于TCP流量控制..."
        }
      ]
    }
  ],
  "total": 1,
  "query_info": {
    "mode": "hybrid_rerank",
    "intent_type": "retrieve_question"
  }
}
```

## 7.3 知识点检索

### `POST /api/v1/retrieval/knowledge/search`

请求：

```json
{
  "query": "TCP流量控制的核心机制",
  "filters": {
    "subject_id": "subj_cn",
    "chapter_id": "ch_cn_04"
  },
  "mode": "hybrid_rerank",
  "top_k": 10
}
```

## 7.4 混合检索

### `POST /api/v1/retrieval/mixed/search`

请求：

```json
{
  "query": "和TCP拥塞控制相关的知识点和题目",
  "filters": {
    "subject_id": "subj_cn"
  },
  "targets": ["knowledge", "question"],
  "mode": "hybrid_rerank",
  "top_k": 10
}
```

响应：

```json
{
  "knowledge_items": [],
  "question_items": [],
  "query_info": {
    "intent_type": "retrieve_mixed"
  }
}
```

## 7.5 检索调试

### `POST /api/v1/admin/retrieval/debug`

响应必须包含：

1. query understanding 结果
2. 过滤条件
3. sparse 命中
4. dense 命中
5. 融合结果
6. rerank 结果

响应示例：

```json
{
  "query_understanding": {},
  "filters": {},
  "sparse_hits": [],
  "dense_hits": [],
  "merged_hits": [],
  "reranked_hits": []
}
```

---

## 8. RAG 问答接口

## 8.1 对话接口扩展

现有位置：

- [backend/app/api/chat.py](/Users/golfzhang/Documents/project/my-agent/backend/app/api/chat.py:1)

建议请求体扩展为：

```json
{
  "message": "TCP为什么需要流量控制？",
  "session_id": "sess_001",
  "context": {
    "target": "knowledge",
    "subject_id": "subj_cn",
    "chapter_id": "ch_cn_04"
  },
  "retrieval_options": {
    "mode": "hybrid_rerank",
    "targets": ["knowledge"],
    "top_k": 8
  }
}
```

响应体扩展为：

```json
{
  "session_id": "sess_001",
  "message": "TCP流量控制的核心目的是...",
  "type": "answer",
  "sources": [
    {
      "type": "knowledge_base",
      "title": "TCP流量控制",
      "content": "..."
    }
  ],
  "citations": [
    {
      "document_id": "doc_001",
      "block_id": "blk_021",
      "page_no": 18,
      "quote_role": "definition",
      "quote_text": "..."
    }
  ],
  "suggestions": []
}
```

---

## 9. 前端 TypeScript 类型草案

建议新增类型文件：

- `frontend-admin/src/types/corpus.ts`
- `frontend/src/types/retrieval.ts`

## 9.1 管理端类型

```ts
export interface CorpusFile {
  id: string
  source_type: 'crawler' | 'manual' | 'upload' | 'import'
  source_ref?: string
  file_name: string
  file_ext: string
  local_path: string
  storage_uri?: string | null
  sha256: string
  file_size?: number
  mime_type?: string
  language?: string
  doc_type: 'textbook' | 'past_exam' | 'mock_exam' | 'notes' | 'other'
  version: number
  status: 'pending' | 'parsing' | 'parsed' | 'extracting' | 'indexed' | 'failed' | 'archived'
  error_detail?: string | null
  created_at: string
  updated_at: string
}

export interface ParseRun {
  id: string
  corpus_file_id: string
  parser_name: string
  parser_version: string
  parse_mode: 'primary' | 'fallback' | 'retry' | 'manual_fix'
  status: 'running' | 'success' | 'failed' | 'partial'
  page_count?: number
  block_count?: number
  asset_count?: number
  confidence?: number
  error_detail?: string | null
  metrics_json?: Record<string, unknown>
  started_at?: string
  completed_at?: string | null
}

export interface DocumentBlock {
  id: string
  document_id: string
  page_id?: string | null
  page_no: number
  block_type: string
  order_no: number
  bbox?: Record<string, number>
  content_text?: string | null
  content_md?: string | null
  content_json?: Record<string, unknown> | null
  latex?: string | null
  html_table?: string | null
  asset_id?: string | null
  confidence?: number | null
  review_status: 'pending' | 'approved' | 'rejected'
}
```

## 9.2 检索类型

```ts
export interface RetrievalFilters {
  subject_id?: string
  chapter_id?: string
  difficulty?: string
  question_type?: string
  exam_scope?: string
  exam_year?: number
  paper_name?: string
  source_type?: string
  topic_terms?: string[]
  modality_flags?: string[]
}

export interface SourceRef {
  document_id: string
  block_id: string
  page_no: number
  quote_role?: string
  quote_text?: string
}

export interface QuestionSearchItem {
  question: Record<string, unknown>
  score: number
  source_refs: SourceRef[]
}

export interface KnowledgeSearchItem {
  knowledge_point: Record<string, unknown>
  score: number
  source_refs: SourceRef[]
}
```

---

## 10. 页面与接口对应关系

| 页面 | 接口 |
|------|------|
| 语料文件列表 | `GET /admin/corpus/files` |
| 解析任务列表 | `GET /admin/corpus/parse-runs` |
| 文档详情页 | `GET /admin/corpus/documents/{id}` |
| block 审核页 | `GET /admin/corpus/documents/{id}/blocks` |
| 知识点审核页 | `GET /admin/review/knowledge` |
| 题目审核页 | `GET /admin/review/questions` |
| 题目检索调试页 | `POST /retrieval/questions/search` + `POST /admin/retrieval/debug` |
| 知识点检索调试页 | `POST /retrieval/knowledge/search` + `POST /admin/retrieval/debug` |

---

## 11. 联调顺序

1. 先联调 `corpus files`
2. 再联调 `documents/pages/blocks/assets`
3. 再联调 `review`
4. 再联调 `retrieval`
5. 最后联调 `chat/rag`

不要跳过 `admin/retrieval/debug`，否则检索问题无法快速定位。

