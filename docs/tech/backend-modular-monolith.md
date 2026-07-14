# 后端模块化单体演进方案

## 结论

项目已经使用 FastAPI、SQLAlchemy 2.x、Pydantic、Alembic、Redis 和 Qdrant，
并不是缺少开发框架。当前需要继续处理的主要问题是：

- 部分 Service 同时负责流程编排、解析规则、数据库写入和外部服务调用
- ORM 模型集中在单个大文件，变更影响范围不直观
- 自动化测试数量不足，且存在与当前 408 业务不一致的旧测试

目标采用模块化单体，而不是立即拆微服务。模块化单体保留本地事务、简单部署和
低运维成本，同时通过明确的业务域边界提高可靠性和可维护性。

## 目标结构

```text
app/
  api/
    schemas.py                 # 跨模块通用 HTTP Schema
  infrastructure/
    ai/                        # 跨业务域共享的 LLM 与 Embedding 外部适配器
  modules/
    catalog/                   # 学科、章节目录
      router.py
      schemas.py               # 模块需要时再创建
      service.py
    chat/                      # 公共问答与后台会话管理
    content/                   # 题目、知识点及人工审核记录
    corpus/                    # 文件、解析、实体抽取任务
    dashboard/                 # 后台跨领域统计读模型
    retrieval/                 # Segment、召回、章节扩展
    crawler/                   # 爬取源、任务、调度、日志
    monitoring/                # 运行指标、服务日志、LLM 与召回监控
    operations/                # 配置、用户与审计
  models/                      # ORM 注册入口和逐步拆分后的模型
```

每个模块按需要包含以下层次，不要求机械地创建空文件：

1. `router.py`：HTTP 参数、鉴权、状态码和响应转换
2. `schemas.py`：该模块的 Pydantic 输入输出契约
3. `service.py`：用例编排和事务边界
4. `domain.py` 或纯函数文件：复杂且可独立测试的业务规则
5. `repository.py`：只有查询复杂、复用明显或需要替换存储时才引入

SQLAlchemy `AsyncSession` 已承担事务工作单元职责。简单模块可以直接在 Service
中使用 Session，避免只转发 ORM 调用的空壳 Repository。

## 依赖规则

- Router 可以依赖本模块的 Schema 和 Service
- Service 可以依赖 ORM、基础设施适配器和其他模块公开的应用接口
- 纯业务规则不能依赖 FastAPI、数据库连接或外部 API
- 模块之间禁止导入对方的 Router
- 后台业务路由必须直接归属对应模块，不再设置集中式 `admin.py`
- 原 URL 在迁移期保持不变，避免前端和第三方调用方同时迁移

## 分阶段迁移

### 阶段 1：建立模块骨架

- 抽出通用 API 响应 Schema
- 迁移学科/章节目录路由
- 增加路由路径、方法和重复注册契约测试

状态：已完成。

### 阶段 2：内容与审核

- 迁移题目、知识点管理及其审核接口
- 将“是否可用”和“是否人工审核”拆成两个独立维度
- 入库后默认可用，审核只记录人工结论和备注

状态：已完成。题目与知识点路由位于 `app/modules/content`，原 URL 保持不变。

- 题目、知识点和知识关系的审核查询、审核写入及审核后索引重建已迁移到
  `app/modules/content/review_service.py`，`app/services/review_service.py`
  已删除
- 知识关系审核、删除及审核统计接口已迁移到
  `app/modules/content/relation_review_router.py`，并修复关系 `batch-delete`
  被动态 relation 路由截获的问题
- 题目答案/解析、考点回连和知识点摘要富化已迁移到
  `app/modules/content/enrichment_service.py`，三条富化端点也已迁入内容模块，
  `app/services/enrichment_service.py` 已删除

内容状态约定：

- `status=active`：内容可用于管理、章节关联、富化、分段和检索
- `status=pending`：显式暂停使用，不代表待人工审核
- `status=deleted`：软删除
- `review_status`：人工核验结论，只用于审计和筛选，不控制内容发布
- `review_notes`、`reviewed_by`、`reviewed_at`：保留人工核验记录

实体抽取写入的题目和知识点默认 `status=active`、
`review_status=pending`。审核通过或拒绝都不会自动改变 `status`，
也不会隐式触发富化或章节关联。

### 阶段 3：语料流水线

- 迁移语料文件、解析任务和实体抽取路由
- 把抽取 Service 拆成编排、规则修复、持久化三个职责

状态：已完成。

- 阶段 3A 已完成：语料文件登记、上传、查询、删除及解析任务路由已迁移到
  `app/modules/corpus`
- 语料文件扫描、注册、SHA256 去重及列表查询已迁移到
  `app/modules/corpus/file_service.py`，`app/services/corpus_service.py`
  已删除
- 原 `/api/v1/admin/corpus/*` URL 保持不变，并增加模块归属与重复路由契约测试
- 解析任务在后台派发前先持久化 `ParseRun` 和语料 `parsing` 状态
- 上传改为安全文件名、分块写入、可配置大小限制，并清理重复或失败的临时副本
- 阶段 3B 已完成：文档块、标题树、页对比、章节映射、内容总览和实体抽取端点
  已迁移到 `app/modules/corpus`
- 文档原生标题树提取和查询已迁移到
  `app/modules/corpus/document_section_service.py`，标题识别与题目误判过滤规则位于
  `app/modules/corpus/section_heading.py`，旧 Service 文件已删除
- 文档解析编排已迁移到 `app/modules/corpus/document_parse_service.py`，
  页面、块、资产持久化和文档详情查询位于
  `app/modules/corpus/document_store.py`，旧 Service 文件已删除
- 文档解析公共契约位于 `app/modules/corpus/parser_types.py`，嵌入式 MinerU
  适配位于 `mineru_parser.py`，HTTP 服务客户端位于 `parser_service_client.py`，
  运行时选择与探活位于 `parser_runtime.py`
- 主后端、独立 parser 进程及测试均直接依赖上述语料模块；旧
  `app/services/document_parsers.py` 和后续过渡聚合文件
  `app/modules/corpus/document_parsers.py` 均已删除
- 实体抽取任务使用文档行锁避免并发重复创建，运行记录先落库再派发后台任务
- PDF 页渲染移入线程池，避免同步转换阻塞 FastAPI 事件循环
- 阶段 3C 已完成：题目选项完整性、题号连续性、综合诊断和确定性规则修复已迁移到
  `app/modules/corpus/question_validation.py`
- LLM 兜底修复、三题上下文提示、选项来源核验和修复审计已迁移到
  `app/modules/corpus/question_llm_repair.py`
- bbox 页面统计、单双栏阅读顺序、题目边界、选项恢复和跨页合并已迁移到
  `app/modules/corpus/question_layout.py`；A-D 标记识别、内联选项定位、MinerU
  粘连选项恢复和选项文本切分进一步拆分到
  `app/modules/corpus/question_option_rules.py`，bbox 坐标兼容、页面间距统计、
  双栏检测和阅读顺序拆分到
  `app/modules/corpus/question_layout_geometry.py`；题干、选项、媒体、题号和题目组
  分类规则拆分到 `app/modules/corpus/question_group_content.py`，并保留布局分组器
  的兼容委托接口
- 抽取数量、页级保存结果、题号连续性和规则/LLM 修复历史摘要已迁移到
  `app/modules/corpus/extraction_diagnostics.py`
- 题目入库、选项标准化、原卷答案回连和实体来源查询已迁移到
  `app/modules/corpus/entity_persistence.py`
- 知识点入库、实体级联清理及抽取实体 ID 生成也已收敛到该持久化模块
- 已审核 section 映射加载及跨页最近章节回退已迁移到
  `app/modules/corpus/document_mapping.py`
- 题目来源/年份/标签元数据、分组字典构建及 LLM 粘连切分已迁移到
  `app/modules/corpus/question_builder.py`
- 无调用方且绕过统一校验/修复/持久化的旧版题目提取备用路径已移除
- 题目组装、规则/LLM 修复、最终校验、保存及诊断汇总编排已迁移到
  `app/modules/corpus/question_pipeline.py`
- 语料详情的实体查询、章节分组和重提取状态组装由
  `app/modules/corpus/content_overview.py` 负责；入库质量检查、问题明细和评分规则已
  拆分到纯业务模块 `app/modules/corpus/quality_gate.py`
- 标题驱动的知识点分组、章节映射和保存编排已迁移到
  `app/modules/corpus/knowledge_pipeline.py`
- 文档加载、block 分类、题目/知识点分流、答案回连和事务提交已迁移到
  `app/modules/corpus/entity_extraction_pipeline.py`
- Block 类型分类、文档来源元信息识别和 MinerU 文本清洗已迁移到
  `app/modules/corpus/block_classifier.py`、`document_meta_service.py` 和
  `text_cleaning.py`，对应的旧 Service 文件已删除
- 后台抽取运行状态、失败恢复和抽取后索引已由
  `app/modules/corpus/extraction_tasks.py` 的 `EntityExtractionRunExecutor`
  负责，corpus 模块不再反向依赖旧 Service
- `app.modules.corpus` 包初始化不再隐式加载 Router，避免领域规则反向触发接口层和
  抽取任务加载
- 实体抽取调用方和测试已直接依赖编排、布局、修复、诊断及持久化模块，
  `app/services/entity_extraction_service.py` 兼容门面已删除

### 阶段 4：检索与关系

- 迁移 Segment、向量召回、章节关联和关系构建
- 为检索过滤条件和索引一致性增加集成测试

状态：进行中。

- Segment 构建、普通检索、关系扩展、大纲扩展、双路召回和章节扩展接口已迁移到
  `app/modules/retrieval`
- 原 `/api/v1/admin/segments/*` 和 `/api/v1/admin/search*` URL 保持不变
- 检索编排实现已迁移到 `app/modules/retrieval/service.py`，
  `app/services/retrieval_service.py` 已删除
- Qdrant 过滤条件、MySQL 稀疏召回、稠密/稀疏命中合并和来源文档补全已从检索
  编排服务拆分到 `app/modules/retrieval/search_engine.py`；检索编排不再直接承载
  存储查询细节
- 已审核知识关系查询、关联知识点 Segment 补全和题目回连已从检索编排服务拆分到
  `app/modules/retrieval/relation_expansion.py`；`RetrievalService` 仅保留主检索和
  关系扩展结果编排
- Segment 生成与重建编排已迁移到
  `app/modules/retrieval/segment_service.py`；知识点、题目和标准章节的检索文本、
  结构化元数据及 Qdrant payload 构造已拆分到
  `app/modules/retrieval/segment_factory.py`，MySQL/Qdrant 双写、回滚和提交后旧向量
  清理则由 `app/modules/retrieval/segment_store.py` 负责，
  `app/services/segment_service.py` 已删除
- 知识点、题目和标准章节已统一通过 `SegmentStore` 写入，重建时不再提前删除
  标准章节旧向量，避免新索引写入失败后丢失可用检索数据
- 大纲 Query 向量扩展与结构化过滤条件提取已拆分到
  `app/modules/retrieval/outline_query_expansion.py`；章节树范围扩展、题目到章节
  展开及关联题目/知识点召回已拆分到
  `app/modules/retrieval/chapter_scope_retrieval.py`；跨章向量相似召回、已审核关系读取
  和交叉引用校验已拆分到
  `app/modules/retrieval/chapter_relation_retrieval.py`，
  `app/modules/retrieval/outline_service.py` 和
  `app/services/outline_retrieval_service.py` 均已删除
- 知识点标题、术语和内容关键词的纯规则关系检测已拆分到
  `app/modules/retrieval/relation_detector.py`；Embedding 文本构建、余弦计算和 Top-N
  语义候选筛选已拆分到 `app/modules/retrieval/semantic_relation_detector.py`；
  候选查询、关系去重落库和审核由 `app/modules/retrieval/relation_service.py` 负责，
  `app/services/relation_service.py` 已删除
- `POST /api/v1/admin/relations/build` 已迁移到检索模块路由，关系重建入口与
  `RelationService` 归属保持一致
- 语料实体的章节解析、关联写入和历史题目章节回填已迁移到
  `app/modules/catalog/chapter_link_service.py`，
  `app/services/chapter_link_service.py` 已删除；关键词打分和向量召回策略进一步拆分到
  `app/modules/catalog/chapter_matcher.py`，知识点/题目章节关联的查重、更新和新增持久化
  位于 `app/modules/catalog/chapter_link_store.py`，实体来源 block 到已审核 section
  映射的章节解析位于 `app/modules/catalog/document_chapter_resolver.py`，历史题目章节
  归属筛选、解析、legacy 兼容与 dry-run 回填位于
  `app/modules/catalog/question_chapter_backfill.py`
- 知识点、题目和整份文档的手动章节关联入口，以及章节下实体查询接口已迁移到
  `app/modules/catalog/chapter_link_router.py`，保持原
  `/api/v1/admin/*/link-chapters` 与 `/chapters/{chapter_id}/entities` 路径不变
- 标准章节树维护、文档 section 映射、映射审核和章节归属诊断已迁移到
  `app/modules/catalog`；其中标准章节树维护位于 `canonical_chapter_service.py`，
  section 映射与审核位于 `chapter_mapping_service.py`，
  section 标题/path 的章节索引、包含关系和关键词评分规则位于
  `section_mapping_rules.py`，
  页级、块级和 section 级章节归属查询编排位于 `chapter_diagnostics_service.py`，
  section 覆盖选择、映射优先级、相邻页回退和问题分级规则位于
  `chapter_diagnostics_rules.py`，
  `app/services/chapter_mapping_service.py` 已删除
- 标准章节初始化和树形/平铺查询接口已迁移到 `app/modules/catalog/router.py`，
  原 `/api/v1/admin/canonical-chapters*` 路径和响应保持不变
- 前端仍在调用的 section 映射审核兼容接口已迁移到
  `app/modules/catalog/section_review_router.py`；保留 `/api/v1/admin/review/sections*`
  路径和 deprecated 标记，并修复 `batch-delete` 被动态 mapping 路由截获的问题；
  等待前端完成新审核流程替换后再删除
- 标准章节关系的构建、分页查询、审核和删除接口已迁移到
  `app/modules/catalog/chapter_relation_router.py`，原
  `/api/v1/admin/chapter-relations*` 路径、参数和响应保持不变
- 标准章节到旧章节 ID 的兼容解析已迁移到
  `app/modules/catalog/chapter_compat.py`，旧 Service 文件已删除
- 考试大纲导入、章节树入库、复习指导生成和大纲 LLM 结构化拆分已迁移到
  `app/modules/catalog/outline_import_service.py` 与
  `outline_llm_service.py`；文本/JSON 格式识别、编号提取和层级树构建进一步拆分到
  `outline_parser.py`；LLM 返回的截断 JSON 修复、章节字段清洗和章节树遍历分别拆分到
  `outline_llm_parser.py` 与 `outline_tree.py`；大纲专用 LLM 客户端统一复用
  `app/infrastructure/ai/llm_client.py`；科目边界识别和超长章节分块拆分到
  `outline_segmentation.py`；骨架拆分、节点增强、目标提取和复习指导 Prompt 集中到
  `outline_prompts.py`；章节复习指导生成迁移到 `outline_guidance_service.py`，
  大纲 LLM 运行时配置集中到 `outline_llm_runtime.py`；大纲列表、章节树和科目摘要查询
  迁移到 `outline_query_service.py`；文档原生标题到大纲章节树的顺序转换迁移到
  `outline_document_sections.py`；大纲元信息、默认版本互斥和递归章节树 upsert 统一到
  `outline_persistence.py`；LLM 多科目结果入库、任务统计和科目级保存点隔离迁移到
  `outline_llm_import_service.py`，对应的旧 Service 文件已删除
- 考试大纲列表、预览、导入、PDF 异步解析、任务查询和删除接口已迁移到
  `app/modules/catalog/outline_router.py`；任务详情、列表序列化和删除维护进一步迁移到
  `outline_run_service.py`；文件上传、固定 MinerU 解析、文档复用、LLM 拆分和后台任务
  状态维护迁移到 `outline_parse_service.py`；大纲及其章节树删除迁移到
  `outline_maintenance_service.py`；上传目录统一使用
  `settings.CORPUS_UPLOAD_DIR`，不再依赖路由文件所在层级推导路径
- 题目/知识点与文档图片、表格、公式的资产关联已迁移到
  `app/modules/content/entity_assets.py`，语料持久化改为显式依赖该模块，
  旧 Service 文件已删除
- 文档资产元数据和文件读取接口已迁移到
  `app/modules/content/asset_router.py`，原 `/api/v1/admin/assets/{asset_id}*`
  路径和 404 响应语义保持不变
- sparse/hybrid 的 MySQL 关键词召回已与 dense 的 Qdrant payload 过滤保持一致，
  学科、章节、年份、考试范围、难度、题型、答案来源和标签均在截断候选前过滤

### 阶段 5：运营域

- 迁移爬虫、监控、设置、用户和审计接口
- 清理旧测试并建立可作为发布门禁的全量测试基线

状态：进行中。

- 管理员认证和用户管理已迁移到 `app/modules/operations`
- 登录改为读取 `admin_users`，所有后台接口使用签名 JWT 并在请求时重新校验账号状态
- 当前 PBKDF2 密码格式兼容旧 bcrypt，旧哈希登录成功后自动升级
- 非开发环境启动时强制校验 `ADMIN_JWT_SECRET`，避免默认密钥进入生产
- 系统运行配置、MinerU 部署配置、爬虫配置校验和配置审计已迁移到
  `app/modules/operations/settings_service.py`，各业务模块直接依赖运营配置接口，
  `app/services/system_settings_service.py` 已删除；爬虫默认值、运行参数校验、代理地址
  规则和审计脱敏进一步拆分到 `app/modules/operations/crawler_settings.py`，系统配置
  默认值、递归合并、增量输入清洗和持久化描述拆分到
  `app/modules/operations/system_settings_rules.py`；MinerU 部署参数归一化、变更判断、
  远程地址校验和审计快照拆分到
  `app/modules/operations/pdf_parser_settings.py`
- `/api/v1/admin/settings*` 配置查询、保存、MinerU 配置历史及 LLM 连通性测试
  接口已迁移到 `app/modules/operations/settings_router.py`；原 URL、管理员鉴权、
  API Key 脱敏和响应行为保持不变
- OpenAI 兼容 LLM 与 Embedding 客户端已迁移到 `app/infrastructure/ai`，由语料、
  内容、目录、检索、聊天和运营配置模块共享；两个旧 `app/services/*.py` 文件已删除
- 公共问答编排和 `/api/v1/chat*` 路由已迁移到 `app/modules/chat`，最后一个旧
  `app/services/chat_service.py` 已删除，空的 `app/services` 兼容目录同步移除
- 后台会话列表、详情和删除接口已迁移到 `app/modules/chat/admin_router.py`，
  原 `/api/v1/admin/conversations*` 路径和管理员鉴权保持不变
- 看板核心数量及学科、难度、题型分布查询已迁移到 `app/modules/dashboard`，
  两条 `/api/v1/admin/dashboard/*` 只读接口保持原统计口径与鉴权不变
- LLM 调用记录、聚合统计和向量召回质量日志已迁移到
  `app/modules/monitoring`，对应管理接口保持 `/api/v1/admin/monitor/*`
  不变，`app/services/llm_call_recorder.py` 与
  `app/services/vector_recall_recorder.py` 已删除
- API 延迟统计、数据库状态、服务日志查询与归档、系统资源采集和日志异步入库已迁移到
  `app/modules/monitoring`；相关端点已从 `app/api/admin.py` 迁出，
  `app/services/monitor_service.py`、`db_log_sink.py`、
  `system_metrics_collector.py` 以及 `app/middleware/api_stats.py` 已删除
- 无任何运行时调用且与现有爬虫统计查询重复的
  `app/services/stats_collector.py` 已删除；爬虫源统计继续由实际在用的服务负责
- 爬取源、任务执行、定时调度、文件统计、爬虫日志、Scrapy Redis Bridge 和
  WebSocket 日志处理实现已迁移到 `app/modules/crawler`；应用生命周期、调度器、
  管理接口和测试已直接依赖爬虫模块，对应 7 个旧 `app/services/*.py` 文件已删除
- `/api/v1/admin/crawler/*` 管理端点已迁移到 `app/modules/crawler`；任务 CRUD
  和启停接口拆分到 `task_router.py`，爬取源列表、维护、健康检查和来源统计拆分到
  `source_router.py`，统计报表与 Scrapy 运行状态拆分到 `stats_router.py`，定时
  任务维护和运行历史拆分到 `schedule_router.py`，爬虫运行配置拆分到
  `config_router.py`，日志查询、导出、文件重试和实时日志拆分到 `log_router.py`；
  原含糊的 `crawler/router.py` 已移除。URL、鉴权和响应行为保持不变，并由路由
  归属契约测试防止重新回流到集中式路由
- 已下载文件列表、详情和预览接口已迁移到 `app/modules/crawler/file_router.py`；
  下载根目录统一由 `crawler/storage.py` 管理，文件预览改为真实父目录校验，
  避免相似路径前缀绕过访问边界
- 仍通过 `CrawlTask(source=pdf)` 和 Scrapy Bridge 执行的旧版 PDF 入库接口已迁移到
  `app/modules/crawler/pdf_ingest_router.py`；保留 `/api/v1/admin/knowledge/ingest*`
  兼容路径，并确保任务发布异常时 Bridge 连接仍会关闭
- 原 `app/api/admin.py` 中的后台接口已全部按业务域迁移，空的兼容路由及
  `main.py` 注册已删除；`app/api` 仅保留跨模块通用 HTTP Schema

每个阶段都必须满足：

- 保留兼容 API 或提供明确迁移路径
- 添加与风险匹配的测试
- 测试通过后单独提交
- 不混入无关重构

## 参考

- FastAPI Bigger Applications:
  https://fastapi.tiangolo.com/tutorial/bigger-applications/
- SQLAlchemy Session Basics:
  https://docs.sqlalchemy.org/en/20/orm/session_basics.html
- AWS Prescriptive Guidance - Decompose monoliths into microservices:
  https://docs.aws.amazon.com/prescriptive-guidance/latest/modernization-decomposing-monoliths/
