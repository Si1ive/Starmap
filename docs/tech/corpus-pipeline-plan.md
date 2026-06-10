# Plan: 语料入库管线完善 — 自动分类 + 本地上传 + Schema 迁移

## Context

Phase 0 和 Phase 1 核心已完成（CorpusFile/ParseRun/Document/DocumentPage/DocumentBlock/DocumentAsset 模型、Docling 解析服务、scan_and_register、API 端点）。现在需要：

1. **两个新需求**：文档自动学科/章节分析 + 本地文件上传
2. **Phase 1 剩余迁移**：Revision 3（扩展 knowledge_points/questions）、Revision 4（entity_source_links/retrieval_segments）
3. **先执行已有迁移**：`alembic upgrade head` 把 Revision 1 & 2 应用到数据库

---

## 当前已完成

| 组件 | 状态 | 位置 |
|------|------|------|
| CorpusFile / ParseRun / Document 模型 | ✅ | `mysql_models.py` |
| DocumentPage / DocumentBlock / DocumentAsset 模型 | ✅ | `mysql_models.py` |
| CorpusService (scan_and_register) | ✅ | `corpus_service.py` |
| DocumentParseService (Docling 落库) | ✅ | `document_parse_service.py` |
| Admin API (scan/detail/parse/document) | ✅ | `admin.py` |
| Alembic 迁移 Revision 1 & 2 | ✅ 代码已写，未应用到 DB | `alembic/versions/` |

---

## 任务清单

### 任务 0：应用已有迁移

```bash
cd backend && source venv/bin/activate
alembic upgrade head
```

验证：`corpus_files`、`parse_runs`、`documents`、`document_pages`、`document_blocks`、`document_assets` 6 张表已在 MySQL 中。

---

### 任务 1：新增 `document_subjects` 关联表 + 迁移

**目的**：支持一个文档覆盖多个学科/多个章节。

**模型** — `mysql_models.py` 新增：

```python
class DocumentSubject(Base):
    """文档-学科-章节关联表"""
    __tablename__ = "document_subjects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(String(32), ForeignKey("documents.id", ondelete="CASCADE"))
    subject_id: Mapped[str] = mapped_column(String(32))
    chapter_id: Mapped[Optional[str]] = mapped_column(String(32))
    confidence: Mapped[Optional[float]] = mapped_column(DECIMAL(3, 2))  # 0.00-1.00
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否主学科
    source: Mapped[str] = mapped_column(Enum("auto", "manual"), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

**迁移** — Revision 3a: `add_document_subjects_table`
- 创建 `document_subjects` 表
- 添加索引：`idx_doc_subjects_document`, `idx_doc_subjects_subject`

**`documents` 表改动**：
- `subject_id` 保留但改为可空（向后兼容，新数据用 document_subjects）
- 新增 `classification_status` 枚举列（`pending/auto/manual/confirmed`，默认 `pending`）

---

### 任务 2：文档自动分类服务 — `document_classify_service.py`

**核心逻辑**：

```
parse_document() 完成后
    → classify_document(document_id)
        → 读取 document_markdown 或 blocks 前 N 页
        → 构造 LLM prompt：列出 408 学科/章节，让 LLM 分析文档覆盖范围
        → 解析 LLM JSON 返回
        → 写入 document_subjects 表
        → 更新 documents.classification_status = 'auto'
```

**LLM Prompt 设计**：

```
你是一个 408 考研文档分类专家。请分析以下文档内容，判断它涉及哪些学科和章节。

学科与章节列表：
{从数据库读取 subjects + chapters}

文档标题：{title}
文档前 5 页内容：
{blocks_text}

请返回 JSON：
{
  "doc_type": "textbook|past_exam|mock_exam|notes|other",
  "subjects": [
    {
      "subject_id": "subj_xx",
      "chapters": [{"chapter_id": "ch_xx_yy", "confidence": 0.95}],
      "is_primary": true
    }
  ]
}
```

**文件**：`backend/app/services/document_classify_service.py`

**API 端点**：
- `POST /admin/corpus/documents/{document_id}/classify` — 手动触发分类
- `PUT /admin/corpus/documents/{document_id}/subjects` — 手动修正分类结果

---

### 任务 3：本地文件上传 API

**后端** — `admin.py` 新增：

```
POST /admin/corpus/files/upload
  - Content-Type: multipart/form-data
  - 字段：file（文件）、doc_type（可选）、subject_id（可选）、chapter_id（可选）
  - 逻辑：
    1. 保存文件到 data/uploads/{yyyy}/{mm}/{filename}
    2. 计算 sha256，去重检查
    3. 注册到 corpus_files（source_type='upload'）
    4. 如果传了 subject_id/chapter_id，直接写 document_subjects（manual）
    5. 返回 corpus_file_id
  - 后续可触发 parse + classify
```

**扩展 CorpusService**：
- 新增 `upload_and_register(file_content, file_name, doc_type, source_type)` 方法
- 复用现有的 sha256 去重逻辑

**上传目录配置** — `backend/app/core/config.py`：
- 新增 `UPLOAD_DIR = "data/uploads"` 配置

---

### 任务 4：parse + classify 联动

修改 `DocumentParseService.parse_document()` 完成后的流程：

```
parse_document(corpus_file_id)
  → Docling 解析
  → 落库 pages/blocks/assets
  → 自动调用 classify_document(document_id)  ← 新增
  → 返回结果
```

或通过 API `POST /admin/corpus/files/{id}/parse` 增加可选参数 `auto_classify=true`（默认 true）。

---

### 任务 5：前端文件上传

**文件**：`frontend-admin/src/pages/Ingest/index.tsx` 或新建 `frontend-admin/src/pages/Corpus/`

改造方案：在现有的 Ingest 页面增加「本地上传」tab，或新建独立的语料库管理页面。

**上传组件**：
- Ant Design `Upload` 组件，支持拖拽
- 多文件批量上传
- 上传后自动触发 parse + classify
- 显示处理进度

**API 调用** — `frontend-admin/src/api/corpus.ts`（已有基础，扩展）：
- `uploadCorpusFile(file, options)` — 上传文件
- `classifyDocument(documentId)` — 触发分类
- `updateDocumentSubjects(documentId, subjects)` — 手动修正

---

### 任务 6：Revision 3 — 扩展 knowledge_points / questions 表

**目的**：给现有业务表加字段，支持多模态语料关联。

**knowledge_points 新增字段**：
- `canonical_title` VARCHAR(255) — 标准标题
- `summary` TEXT — 摘要
- `aliases` JSON — 别名列表
- `topic_terms` JSON — 主题术语
- `modality_flags` JSON — 多模态标记
- `source_document_id` VARCHAR(32) — 来源文档ID
- `source_page_start` INT — 来源起始页
- `source_page_end` INT — 来源结束页
- `review_status` ENUM('pending','approved','rejected') — 审核状态
- `review_notes` TEXT — 审核备注

**questions 新增字段**：
- `exam_scope` VARCHAR(50) — 考试范围（如 408）
- `paper_name` VARCHAR(255) — 试卷名
- `question_no` VARCHAR(50) — 题号
- `source_type` ENUM('past_exam','textbook_example','mock_exam','practice','other')
- `topic_terms` JSON
- `aliases` JSON
- `modality_flags` JSON
- `source_document_id` VARCHAR(32)
- `source_page_start` / `source_page_end` INT
- `review_status` / `review_notes`

**迁移** — Revision 3b: `extend_knowledge_and_question_for_multimodal`

---

### 任务 7：Revision 4 — entity_source_links / retrieval_segments

**entity_source_links** — 业务实体到来源块的映射：
- id, entity_type('knowledge'|'question'), entity_id, document_id, block_id, page_no, quote_text, quote_role

**retrieval_segments** — 统一检索单元：
- id, entity_type, entity_id, document_id, segment_role, subject_id, chapter_id, content_text, content_md, context_text, keyword_text, metadata_json, status

**迁移** — Revision 4: `add_entity_source_and_retrieval_segments`

---

## 实施顺序

```
任务 0  alembic upgrade head          ← 先做，解锁后续开发
  ↓
任务 1  document_subjects 表 + documents 扩展
  ↓
任务 2  document_classify_service.py   ← 核心：自动分类
  ↓
任务 3  本地文件上传 API
  ↓
任务 4  parse + classify 联动
  ↓
任务 5  前端上传页面
  ↓
任务 6  Revision 3 (knowledge_points/questions 扩展)
  ↓
任务 7  Revision 4 (entity_source_links/retrieval_segments)
```

---

## 涉及文件

| 文件 | 操作 | 任务 |
|------|------|------|
| `backend/app/models/mysql_models.py` | 新增 DocumentSubject，修改 Document | 1 |
| `backend/alembic/versions/` | 新增 3 个迁移文件 | 1, 6, 7 |
| `backend/app/services/document_classify_service.py` | 新建 | 2 |
| `backend/app/services/corpus_service.py` | 新增 upload_and_register | 3 |
| `backend/app/api/admin.py` | 新增 upload/classify/subjects 端点 | 2, 3 |
| `backend/app/core/config.py` | 新增 UPLOAD_DIR | 3 |
| `frontend-admin/src/pages/Corpus/` 或 `Ingest/` | 新建/改造上传页面 | 5 |
| `frontend-admin/src/api/corpus.ts` | 新增 upload/classify API | 5 |

---

## 验证

1. `alembic upgrade head` 成功，6 张已有表 + document_subjects 表存在
2. `POST /admin/corpus/files/upload` 上传 PDF，文件保存到 data/uploads/ 并注册到 corpus_files
3. `POST /admin/corpus/files/{id}/parse` 解析后自动触发分类，document_subjects 写入正确映射
4. `GET /admin/corpus/documents/{id}` 返回的详情包含 subjects 列表
5. `PUT /admin/corpus/documents/{id}/subjects` 手动修正分类结果
6. 前端上传页面可以拖拽上传文件并查看处理状态
7. `alembic upgrade head` 执行 Revision 3 & 4，knowledge_points/questions 新字段存在，entity_source_links/retrieval_segments 表创建成功
