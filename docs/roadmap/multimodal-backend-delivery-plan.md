# 多模态语料入库与检索 - 后端交付任务单

> 版本：v1.1  
> 日期：2026-06-11  
> 状态：执行中  
> 读者：Backend / PM / Reviewer

---

## 1. 目标

后端交付目标不是“把 PDF 接进来”，而是完成以下闭环：

1. `download/` 文件注册、去重、解析、落库
2. 生成 `documents/pages/blocks/assets`
3. 构建 `canonical_chapters`、`document_sections`、章节映射
4. 抽取 `knowledge_points`、`questions`
5. 构建 `knowledge_relations`
6. 构建 `retrieval_segments`
7. 写入 `Qdrant`
8. 提供检索、调试、审核、问答接口

配套设计文档：

- [多模态入库与检索实施设计](../tech/multimodal-ingestion-retrieval-design.md)
- [多模态数据结构与迁移清单](../tech/multimodal-schema-migration-plan.md)
- [多模态语料入库与检索 API 契约](../api/multimodal-retrieval-contract.md)

---

## 2. 交付边界

## 2.1 本阶段必须完成

- MySQL 新表和字段迁移
- `Qdrant` client 与 collection 初始化
- 文件注册和解析任务编排
- 文档 block / asset 落库
- 标准章节体系与文档章节映射
- 实体抽取任务编排
- 知识点关系构建与审核
- segment 构建与索引写入
- 检索 API 与 debug API
- `ChatService` 接入新检索编排

## 2.2 本阶段不阻塞上线

- 视觉检索
- Neo4j 图谱增强
- 多模型 A/B routing
- 复杂 Agent 工作流

---

## 3. 模块拆分

建议新增或改造的模块：

| 模块 | 作用 |
|------|------|
| `app/db/qdrant.py` | Qdrant 连接、collection 初始化、payload 读写 |
| `app/services/corpus_service.py` | 文件扫描、注册、去重、状态流转 |
| `app/services/document_parse_service.py` | 调度 Docling / fallback 解析器 |
| `app/services/document_store_service.py` | 文档、页、块、资产落库 |
| `app/services/chapter_mapping_service.py` | 标准章节维护、原生标题树映射 |
| `app/services/entity_extraction_service.py` | 知识点与题目抽取 |
| `app/services/relation_service.py` | 知识点关系构建、审核、邻域扩展 |
| `app/services/segment_service.py` | segment 构建与上下文化增强 |
| `app/services/retrieval_service.py` | 结构化过滤、sparse/dense/hybrid 检索 |
| `app/services/rerank_service.py` | 重排服务 |
| `app/services/review_service.py` | 审核状态变更与回写 |
| `app/api/admin_*` | 管理端语料、审核、调试接口 |

---

## 4. Phase 划分

## 4.1 Phase A：数据库与基础设施

目标：

- 完成 schema 与 Qdrant 基础层

任务：

- `BE-A1` 新增 Alembic revisions
- `BE-A2` 扩展 `knowledge_points` / `questions` / `downloaded_files`
- `BE-A2.5` 新增 `knowledge_relations`
- `BE-A3` 新增 `qdrant.py`
- `BE-A4` 配置 `.env` 新变量
- `BE-A5` 编写 collection 初始化脚本

产出：

- 可执行数据库迁移
- 可连接的 Qdrant client

验收：

- 本地可完成 `alembic upgrade`
- Qdrant 中可创建 `knowledge_segments` 和 `question_segments`

## 4.2 Phase B：文件注册与解析落库

目标：

- 跑通 `corpus_files -> parse_runs -> documents/pages/blocks/assets`

任务：

- `BE-B1` 实现目录扫描注册
- `BE-B2` 实现 `sha256` 去重
- `BE-B3` 实现解析任务状态机
- `BE-B4` 接入 Docling 主解析器
- `BE-B5` 落库文档、页、块、资产
- `BE-B6` 生成 `document_sections`
- `BE-B7` 失败记录与重试

产出：

- `/admin/corpus/files/scan`
- `/admin/corpus/files/{id}/parse`
- `/admin/corpus/documents/{id}`
- `/admin/corpus/documents/{id}/sections`

验收：

- 能从 10 份文件稳定产出 block 数据
- 每份文件可查看页数、block 数、资产数
- 每份文件可查看原生标题树

## 4.3 Phase C：实体抽取与审核

目标：

- 从 block 生成 canonical 知识点与题目

任务：

- `BE-C1` 定义抽取输入输出 DTO
- `BE-C2` 实现标准章节映射流程
- `BE-C3` 实现知识点抽取流程
- `BE-C4` 实现题目抽取流程
- `BE-C5` 建立 `entity_source_links`
- `BE-C6` 构建初版 `knowledge_relations`
- `BE-C7` 支持 `review_status`
- `BE-C8` 实现审核接口

产出：

- `/admin/corpus/documents/{id}/extract`
- `/admin/review/knowledge`
- `/admin/review/questions`

验收：

- 题目实体能保留题干、选项、答案、解析、来源
- 知识点实体能保留标题、正文、来源与关联信息
- 文档 section 能映射到标准章节，低置信度映射可审核
- 易混点、前置点、对比点可形成初版关系边

## 4.4 Phase D：segment 与检索

目标：

- 完成检索单元构建与 hybrid 检索

任务：

- `BE-D1` 设计 segment builder
- `BE-D2` 实现 contextual enrichment
- `BE-D3` 生成 sparse 文本
- `BE-D4` 叠加 relation-aware contextual enrichment
- `BE-D5` 向 Qdrant 写入 dense/sparse
- `BE-D6` 实现 question search
- `BE-D7` 实现 knowledge search
- `BE-D8` 实现 mixed search
- `BE-D9` 实现 retrieval debug

产出：

- `/retrieval/questions/search`
- `/retrieval/knowledge/search`
- `/retrieval/mixed/search`
- `/admin/retrieval/debug`

验收：

- 支持 `exam_scope + exam_year + subject_id + topic_terms` 筛题
- 知识点检索能返回关系增强结果
- debug 接口可看到过滤、召回、重排过程

## 4.5 Phase E：RAG 接入

目标：

- 用新检索链替代当前单路知识点检索

任务：

- `BE-E1` 改造 query understanding
- `BE-E2` 按 target 路由检索
- `BE-E3` 聚合 citations
- `BE-E4` 更新 `ChatService`
- `BE-E5` 保留 Chroma fallback

产出：

- `/chat` 扩展版

验收：

- 问答可选择仅查知识点或题目
- 返回结果带 `citations`

---

## 5. 任务明细

## 5.1 数据库任务

| 任务ID | 内容 | 依赖 | 验收 |
|--------|------|------|------|
| `BE-DB-01` | 建 `corpus_files` / `parse_runs` / `documents` | 无 | 表结构可迁移 |
| `BE-DB-02` | 建 `canonical_chapters` / `document_sections` / `document_section_mappings` / `document_pages` / `document_blocks` / `document_assets` | `BE-DB-01` | 外键、索引正确 |
| `BE-DB-03` | 扩展 `knowledge_points` / `questions` | `BE-DB-01` | 旧接口不报错 |
| `BE-DB-04` | 建 `knowledge_point_chapter_links` / `question_chapter_links` / `entity_source_links` / `retrieval_segments` / `knowledge_relations` | `BE-DB-02` `BE-DB-03` | 可插入测试数据 |
| `BE-DB-05` | 回填脚本 | `BE-DB-01` | 老数据可映射 |

## 5.2 解析任务

| 任务ID | 内容 | 依赖 | 验收 |
|--------|------|------|------|
| `BE-PARSE-01` | 扫描 `download/` 注册文件 | `BE-DB-01` | 能返回注册结果 |
| `BE-PARSE-02` | 文件去重 | `BE-PARSE-01` | 同 hash 不重复注册 |
| `BE-PARSE-03` | Docling 集成 | `BE-PARSE-01` | 输出 Markdown/JSON |
| `BE-PARSE-04` | block/asset 持久化 | `BE-PARSE-03` | 文档详情可读 |
| `BE-PARSE-05` | 原生标题树提取 | `BE-PARSE-03` | 可生成 `document_sections` |
| `BE-PARSE-06` | 失败重试与状态流转 | `BE-PARSE-04` `BE-PARSE-05` | 有失败记录与重试入口 |

## 5.3 抽取任务

| 任务ID | 内容 | 依赖 | 验收 |
|--------|------|------|------|
| `BE-EXTRACT-01` | 定义抽取中间模型 | `BE-PARSE-04` | DTO 可单测 |
| `BE-EXTRACT-02` | 标准章节映射 | `BE-PARSE-05` | 可写入 `document_section_mappings` |
| `BE-EXTRACT-03` | 知识点抽取 | `BE-EXTRACT-01` `BE-EXTRACT-02` | 能写入 `knowledge_points` |
| `BE-EXTRACT-04` | 题目抽取 | `BE-EXTRACT-01` `BE-EXTRACT-02` | 能写入 `questions` |
| `BE-EXTRACT-05` | 来源引用回写 | `BE-EXTRACT-03` `BE-EXTRACT-04` | 有 `entity_source_links` |
| `BE-EXTRACT-06` | 知识点关系构建 | `BE-EXTRACT-03` | 能写入 `knowledge_relations` |
| `BE-EXTRACT-07` | 审核状态支持 | `BE-EXTRACT-02` `BE-EXTRACT-03` `BE-EXTRACT-04` `BE-EXTRACT-06` | 可 approve/reject |

## 5.4 检索任务

| 任务ID | 内容 | 依赖 | 验收 |
|--------|------|------|------|
| `BE-RET-01` | Qdrant dual collection 初始化 | `BE-A3` | collection 可用 |
| `BE-RET-02` | segment builder | `BE-EXTRACT-02` `BE-EXTRACT-03` | 生成 `retrieval_segments` |
| `BE-RET-03` | relation-aware enrichment | `BE-RET-02` `BE-EXTRACT-05` | segment 含关系提示 |
| `BE-RET-04` | dense/sparse 入库 | `BE-RET-03` | point 可检索 |
| `BE-RET-05` | question search | `BE-RET-04` | 可按年份/学科筛题 |
| `BE-RET-06` | knowledge search | `BE-RET-04` | 可按主章节或扩展章节搜知识点并返回易混点 |
| `BE-RET-07` | mixed search | `BE-RET-05` `BE-RET-06` | 混合返回 |
| `BE-RET-08` | debug API | `BE-RET-07` | 返回完整调试信息 |

## 5.5 问答任务

| 任务ID | 内容 | 依赖 | 验收 |
|--------|------|------|------|
| `BE-CHAT-01` | 查询理解扩展 | `BE-RET-05` `BE-RET-06` | 有结构化 filters 与 relation_intent |
| `BE-CHAT-02` | 多路召回编排 | `BE-CHAT-01` | 支持 knowledge/question |
| `BE-CHAT-03` | 关系增强编排 | `BE-CHAT-02` | 可补充易混点和对比点 |
| `BE-CHAT-04` | citation 聚合 | `BE-CHAT-03` | 返回来源片段 |
| `BE-CHAT-05` | ChatService 切换新链路 | `BE-CHAT-04` | 主问答链可用 |

---

## 6. API 实现顺序

严格按以下顺序：

1. `POST /admin/corpus/files/scan`
2. `GET /admin/corpus/files`
3. `POST /admin/corpus/files/{id}/parse`
4. `GET /admin/corpus/parse-runs`
5. `GET /admin/corpus/documents/{id}`
6. `GET /admin/corpus/documents/{id}/blocks`
7. `POST /admin/corpus/documents/{id}/extract`
8. `GET /admin/review/knowledge`
9. `GET /admin/review/questions`
10. `POST /admin/retrieval/understand`
11. `POST /retrieval/questions/search`
12. `POST /retrieval/knowledge/search`
13. `POST /retrieval/mixed/search`
14. `POST /admin/retrieval/debug`
15. `POST /chat`

---

## 7. 测试要求

## 7.1 单元测试

- parser adapter mock 测试
- corpus file 状态机测试
- segment builder 测试
- relation builder 测试
- relation expansion 测试
- chapter mapping builder 测试
- structured filter builder 测试
- retrieval debug 结果组装测试

## 7.2 集成测试

- 单文件入库
- 单文档抽题
- 题目检索
- 知识点检索
- chat 引用回传

## 7.3 验收查询集

至少覆盖：

1. `2018年408计算机网络TCP题目`
2. `操作系统进程同步判断题`
3. `数据结构中关于二叉树遍历的知识点`
4. `解释一道关于拥塞控制的题`
5. `TCP流量控制和拥塞控制有什么区别`
6. `学习滑动窗口前需要先掌握什么`
7. `这个知识点涉及哪些章节`

---

## 8. 风险

1. 若 parser 输出不稳定，先保住 block 落库，不要阻塞 schema 与接口开发
2. 若 dense embedding 模型选型未定，先把 payload/filter/debug 打通
3. 若抽取质量不稳，优先上审核流，不要直接追求全自动

---

## 9. 完成定义

后端完成标准：

1. 新表迁移可执行
2. 10 份样本文档能形成 `documents/pages/blocks/assets`
3. 题目与知识点能独立抽取并审核
4. 知识点关系边可生成、审核、查询
5. 题目检索支持结构化过滤 + hybrid
6. `/admin/retrieval/debug` 可用于排查问题
7. `/chat` 新链路返回 citations，并可补充易混知识点
