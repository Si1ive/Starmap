# 数据模型设计

## 概述

当前 408 平台的数据模型以 `backend/app/models/mysql_models.py` 为准，主链采用：

- `MySQL`：业务事实源
- `Qdrant`：检索索引
- `Redis`：缓存、会话、任务与日志通道

## MySQL 业务主模型

### 408 核心业务表

| 表名 | 作用 |
|------|------|
| `subjects` | 四门 408 学科 |
| `chapters` | 兼容旧接口的章节表 |
| `canonical_chapters` | 标准章节体系 |
| `knowledge_points` | 知识点实体 |
| `questions` | 题目实体 |
| `user_question_records` | 做题记录 |
| `admin_users` | 管理员账号 |

### 采集与任务表

| 表名 | 作用 |
|------|------|
| `crawl_tasks` | 爬虫 / 入库任务 |
| `crawl_logs` | 任务日志 |
| `crawl_sources` | 数据源配置 |
| `crawl_source_stats` | 数据源统计 |
| `crawl_schedules` | 定时任务 |
| `crawl_schedule_runs` | 定时执行记录 |
| `downloaded_files` | 下载文件记录 |

### 多模态语料表

| 表名 | 作用 |
|------|------|
| `corpus_files` | 语料文件注册 |
| `parse_runs` | 解析执行记录 |
| `documents` | 文档主表 |
| `document_pages` | 文档页 |
| `document_blocks` | 文档块 |
| `document_assets` | 图、表、公式等资产 |
| `document_sections` | 文档原生标题树 |
| `document_section_mappings` | 原生标题到标准章节映射 |

### 检索与审核表

| 表名 | 作用 |
|------|------|
| `knowledge_point_chapter_links` | 知识点章节关联 |
| `question_chapter_links` | 题目章节关联 |
| `entity_source_links` | 实体来源引用 |
| `knowledge_relations` | 知识点关系 |
| `retrieval_segments` | 检索段落 |
| `audit_logs` | 审计日志 |

## 重点实体

### `knowledge_points`

当前知识点实体除基础字段外，还包含：

- `primary_chapter_id`
- `source_document_id`
- `canonical_title`
- `topic_terms`
- `aliases`
- `review_status`
- `review_notes`

知识点已经是正式业务实体，而不是简单抓取结果。

### `questions`

当前题目实体包含：

- `primary_chapter_id`
- `source_document_id`
- `exam_scope`
- `paper_name`
- `question_no`
- `topic_terms`
- `review_status`

题目模型已围绕 408 真题 / 练习题管理设计。

### `retrieval_segments`

`retrieval_segments` 是写入 Qdrant 之前的检索中间层，关键字段包括：

- `entity_type`
- `entity_id`
- `document_id`
- `segment_type`
- `content_text`
- `context_text`
- `page_no`
- `subject_id`
- `chapter_ids`
- `qdrant_point_id`

## Qdrant 索引模型

当前代码中的默认 collection：

| collection | 说明 |
|------------|------|
| `knowledge_segments` | 知识点 segment 检索 |
| `question_segments` | 题目 segment 检索 |

Qdrant payload 至少应覆盖：

- `entity_type`
- `entity_id`
- `document_id`
- `subject_id`
- `chapter_ids`
- `segment_type`
- `page_no`

## 主要关系

### 语料到实体

```text
corpus_files
  -> parse_runs
  -> documents
     -> document_pages
     -> document_blocks
     -> document_assets
     -> document_sections

documents
  -> knowledge_points
  -> questions
  -> entity_source_links
  -> retrieval_segments
```

### 实体到索引

```text
knowledge_points / questions
  -> retrieval_segments
  -> Qdrant points
```

### 章节映射

```text
subjects
  -> canonical_chapters
  -> chapters

knowledge_points / questions
  -> primary_chapter_id
  -> *_chapter_links
```

## 文档边界

- 本文件描述当前主数据设计
- 若未来引入额外读模型或增强索引，应单独补充适用范围
