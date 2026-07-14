# 408 平台 API 契约

> 版本：v2.0  
> 日期：2026-06-11  
> 适用范围：管理端、后端、Scrapy Service、数据库模型

专项接口设计：

- [多模态语料入库与检索 API 契约](./multimodal-retrieval-contract.md)

补充设计：

- PDF 解析器的系统级切换方案见 [技术文档](../tech/pdf-parser-switching-design.md)

## 1. 契约原则

1. 当前项目为 408 考研学习平台，接口语义必须围绕学科、章节、知识点、题目、语料和检索。
2. 所有字段使用 `snake_case`。
3. 管理端接口统一挂载在 `/api/v1/admin/*`。
4. 分页统一使用 `page`、`page_size`、`total`、`total_pages`。
5. 时间统一返回 ISO 8601 字符串。
6. 文档必须与 `backend/app/api/admin.py`、`backend/app/api/chat.py` 和 `frontend-admin/src/api/*` 保持一致。

## 2. 通用响应

### 成功响应

```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "request_id": "req_abc123"
}
```

### 分页响应

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "total_pages": 0
}
```

## 3. 主要资源

### 认证

除登录外，所有 `/api/v1/admin/*` HTTP 接口都要求请求头：

```text
Authorization: Bearer <token>
```

管理员登录从 `admin_users` 表校验账号状态和密码，令牌过期或账号停用后返回
HTTP `401`。实时日志 WebSocket 使用同一令牌，可通过 `Authorization` 请求头或
`?token=<token>` 传入。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/admin/auth/login` | 登录 |
| POST | `/api/v1/admin/auth/logout` | 登出 |
| GET | `/api/v1/admin/auth/me` | 当前用户 |
| GET/POST/PUT/DELETE | `/api/v1/admin/users*` | 管理员账号管理（需 `user:manage` 或超级管理员） |

### 看板

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/dashboard/stats` | 统计总览 |
| GET | `/api/v1/admin/dashboard/charts` | 图表数据 |

### 学科与章节

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/subjects` | 学科列表 |
| GET | `/api/v1/admin/subjects/{subject_id}/chapters` | 章节列表 |

### 知识点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/knowledge/points` | 知识点列表 |
| GET | `/api/v1/admin/knowledge/points/{point_id}` | 知识点详情 |
| PUT | `/api/v1/admin/knowledge/points/{point_id}` | 编辑知识点 |
| POST | `/api/v1/admin/knowledge/ingest` | 触发 PDF 入库任务 |
| GET | `/api/v1/admin/knowledge/ingest/tasks` | 入库任务列表 |

### 题目

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/questions` | 题目列表 |
| GET | `/api/v1/admin/questions/{question_id}` | 题目详情 |
| PUT | `/api/v1/admin/questions/{question_id}` | 编辑题目 |

### 爬虫 / 采集

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/crawler/config` | 获取实际生效的 Scrapy 运行配置 |
| PUT | `/api/v1/admin/crawler/config` | 校验并更新 Scrapy 运行配置 |
| GET | `/api/v1/admin/crawler/tasks` | 任务列表 |
| POST | `/api/v1/admin/crawler/tasks` | 创建任务 |
| POST | `/api/v1/admin/crawler/tasks/{task_id}/start` | 启动任务 |
| POST | `/api/v1/admin/crawler/tasks/{task_id}/stop` | 停止任务 |
| DELETE | `/api/v1/admin/crawler/tasks/{task_id}` | 删除任务 |
| GET | `/api/v1/admin/crawler/sources` | 数据源列表 |
| POST | `/api/v1/admin/crawler/sources` | 创建数据源 |
| POST | `/api/v1/admin/crawler/sources/defaults` | 初始化默认数据源 |
| GET | `/api/v1/admin/crawler/schedules` | 定时任务列表 |
| GET | `/api/v1/admin/crawler/logs` | 爬虫日志 |

### 语料与解析

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/admin/corpus/files/scan` | 扫描语料文件 |
| GET | `/api/v1/admin/corpus/files` | 文件列表 |
| GET | `/api/v1/admin/corpus/files/{file_id}` | 文件详情 |
| POST | `/api/v1/admin/corpus/files/{file_id}/parse` | 触发解析 |
| GET | `/api/v1/admin/corpus/parse-runs` | 解析记录 |
| GET | `/api/v1/admin/corpus/documents/{document_id}` | 文档详情 |
| GET | `/api/v1/admin/corpus/documents/{document_id}/blocks` | 文档块 |
| GET | `/api/v1/admin/corpus/documents/{document_id}/sections` | 原生标题树 |
| POST | `/api/v1/admin/corpus/documents/{document_id}/extract-sections` | 抽取原生章节 |
| POST | `/api/v1/admin/corpus/documents/{document_id}/map-chapters` | 标准章节映射 |
| POST | `/api/v1/admin/corpus/documents/{document_id}/extract-entities` | 抽取知识点与题目 |

说明：

- 当前激活的 PDF 解析器不在入库页切换，而是通过 `/api/v1/admin/settings` 维护系统级单活配置。
- 新环境默认 `MinerU`，`Docling` 作为性能优先备选；当激活解析器不可用时，`parse` 应返回明确错误提示，不做自动 fallback。
- `pdf_parser` 现支持两种部署位置：
  - `local`：访问本机 Podman 中的解析服务，默认读取 `local_service_endpoint`
  - `remote`：把解析请求转发到 `remote_service_endpoint` 指向的 HTTP 服务，并沿用同一解析协议与健康检查

### 运行监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/monitor/api` | API 调用量、错误率、QPS、接口排行和延迟分位数 |

API 延迟使用可合并的固定桶直方图统计 P50/P95/P99。迁移前的历史行只有 P95 采样值，因此 P50/P99 在没有直方图样本时返回 `null`，同时通过 `coverage_percent` 返回当前窗口的直方图覆盖率。

### 审核与检索

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/review/sections` | 章节映射审核列表 |
| GET | `/api/v1/admin/review/knowledge` | 知识点审核列表 |
| GET | `/api/v1/admin/review/questions` | 题目审核列表 |
| GET | `/api/v1/admin/review/relations` | 知识关系审核列表 |
| GET | `/api/v1/admin/review/stats` | 审核统计 |
| POST | `/api/v1/admin/segments/build` | 构建全部 segment |
| POST | `/api/v1/admin/segments/build/knowledge` | 构建知识点 segment |
| POST | `/api/v1/admin/segments/build/questions` | 构建题目 segment |
| POST | `/api/v1/admin/segments/build/chapters` | 构建大纲章节 segment |
| POST | `/api/v1/admin/search` | 搜索 |
| POST | `/api/v1/admin/search/with-relations` | 带关系扩展搜索 |
| POST | `/api/v1/admin/search/with-outline` | 大纲辅助查询扩展搜索 |
| POST | `/api/v1/admin/search/dual-path` | 向量与章节双路召回 |
| POST | `/api/v1/admin/search/chapter-expansion` | 查询章节结构与审核关系扩展 |

`/admin/search`、`/admin/search/with-outline` 的结构化过滤在 dense、sparse 和
hybrid 模式下保持一致，支持 `subject_id`、`chapter_ids`、`exam_year`、
`exam_scope`、`difficulty`、`question_type`、`answer_source` 和 `tags`。

### 系统设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/settings` | 读取系统设置与 PDF 解析器运行状态 |
| PUT | `/api/v1/admin/settings` | 更新系统设置中的 PDF 解析器单活配置 |
| GET | `/api/v1/admin/settings/pdf-parser/history` | 查看 PDF 解析器切换审计历史 |

### 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat` | RAG 问答 |
| GET | `/api/v1/chat/{session_id}/history` | 会话历史 |

## 4. 关键数据体示例

### `CrawlerSource`

当前代码中的默认源以 `GitHub` 为主：

```json
{
  "id": "src_001",
  "name": "GitHub",
  "code": "github",
  "type": "code_hosting",
  "base_url": "https://github.com",
  "config": {
    "spider_key": "github",
    "default_file_types": ["pdf"]
  },
  "request_interval": 1.0,
  "daily_limit": 5000,
  "concurrent_limit": 3,
  "status": "active"
}
```

### `CrawlerTask`

```json
{
  "id": "task_xxx",
  "name": "导入 408 PDF 语料",
  "task_type": "targeted",
  "source_id": "src_001",
  "status": "pending",
  "config": {
    "spider_type": "knowledge",
    "source": "github",
    "keywords": ["408", "pdf"],
    "subject_id": "subj_ds",
    "chapter_id": "ch_ds_01"
  }
}
```

### `KnowledgePoint`

```json
{
  "id": "kp_xxx",
  "subject_id": "subj_ds",
  "chapter_id": "ch_ds_01",
  "primary_chapter_id": "cc_ds_01",
  "title": "线性表的定义",
  "content": "线性表是具有相同数据类型的 n 个数据元素的有限序列。",
  "difficulty": "easy",
  "exam_frequency": "high",
  "review_status": "approved",
  "source_document_id": "doc_xxx"
}
```

### `Question`

```json
{
  "id": "q_xxx",
  "subject_id": "subj_os",
  "chapter_id": "ch_os_03",
  "primary_chapter_id": "cc_os_03",
  "type": "choice",
  "content": "下列关于进程与线程的说法，正确的是？",
  "difficulty": "medium",
  "exam_scope": "408",
  "exam_year": 2024,
  "review_status": "approved"
}
```

## 5. 文档边界

- 本文件描述当前管理端与问答主链接口
- 多模态字段定义与更完整示例，统一参考 `docs/api/multimodal-retrieval-contract.md`
