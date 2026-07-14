# 后端模块化单体演进方案

## 结论

项目已经使用 FastAPI、SQLAlchemy 2.x、Pydantic、Alembic、Redis 和 Qdrant，
并不是缺少开发框架。当前主要问题是模块边界退化：

- `app/api/admin.py` 同时承载大量不相关业务域和接口模型
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
  modules/
    catalog/                   # 学科、章节目录
      router.py
      schemas.py               # 模块需要时再创建
      service.py
    content/                   # 题目、知识点及人工审核记录
    corpus/                    # 文件、解析、实体抽取任务
    retrieval/                 # Segment、召回、章节扩展
    crawler/                   # 爬取源、任务、调度、日志
    operations/                # 监控、配置、用户与审计
  services/                    # 尚未迁移的兼容服务
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
- 新接口不得继续添加到巨型 `admin.py`
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

状态：进行中。

- 阶段 3A 已完成：语料文件登记、上传、查询、删除及解析任务路由已迁移到
  `app/modules/corpus`
- 原 `/api/v1/admin/corpus/*` URL 保持不变，并增加模块归属与重复路由契约测试
- 解析任务在后台派发前先持久化 `ParseRun` 和语料 `parsing` 状态
- 上传改为安全文件名、分块写入、可配置大小限制，并清理重复或失败的临时副本
- 阶段 3B 已完成：文档块、标题树、页对比、章节映射、内容总览和实体抽取端点
  已迁移到 `app/modules/corpus`
- 文档原生标题树提取和查询已迁移到
  `app/modules/corpus/document_section_service.py`，标题识别与题目误判过滤规则位于
  `app/modules/corpus/section_heading.py`，旧 Service 路径仅保留兼容导出
- 实体抽取任务使用文档行锁避免并发重复创建，运行记录先落库再派发后台任务
- PDF 页渲染移入线程池，避免同步转换阻塞 FastAPI 事件循环
- 阶段 3C 进行中：题目选项完整性、题号连续性、综合诊断和确定性规则修复已迁移到
  `app/modules/corpus/question_validation.py`
- LLM 兜底修复、三题上下文提示、选项来源核验和修复审计已迁移到
  `app/modules/corpus/question_llm_repair.py`
- bbox 页面统计、单双栏阅读顺序、题目边界、选项恢复和跨页合并已迁移到
  `app/modules/corpus/question_layout.py`
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
- 标题驱动的知识点分组、章节映射和保存编排已迁移到
  `app/modules/corpus/knowledge_pipeline.py`
- 文档加载、block 分类、题目/知识点分流、答案回连和事务提交已迁移到
  `app/modules/corpus/entity_extraction_pipeline.py`
- 后台抽取运行状态、失败恢复和抽取后索引已由
  `app/modules/corpus/extraction_tasks.py` 的 `EntityExtractionRunExecutor`
  负责，corpus 模块不再反向依赖旧 Service
- `app.modules.corpus` 包初始化不再隐式加载 Router，避免领域规则反向触发接口层和
  抽取任务加载
- `app/services/entity_extraction_service.py` 现作为旧调用方兼容门面保留

### 阶段 4：检索与关系

- 迁移 Segment、向量召回、章节关联和关系构建
- 为检索过滤条件和索引一致性增加集成测试

状态：进行中。

- Segment 构建、普通检索、关系扩展、大纲扩展、双路召回和章节扩展接口已迁移到
  `app/modules/retrieval`
- 原 `/api/v1/admin/segments/*` 和 `/api/v1/admin/search*` URL 保持不变
- 检索编排实现已迁移到 `app/modules/retrieval/service.py`，
  `app/services/retrieval_service.py` 仅保留兼容导出
- Segment 构建、重建、删除和 MySQL/Qdrant 一致性事务已迁移到
  `app/modules/retrieval/segment_service.py`，
  `app/services/segment_service.py` 仅保留兼容导出
- 大纲 Query 扩展、章节范围召回、题目到章节展开和交叉引用校验已迁移到
  `app/modules/retrieval/outline_service.py`，
  `app/services/outline_retrieval_service.py` 仅保留兼容导出
- 知识点关系构建、语义相似边、关系查询和审核已迁移到
  `app/modules/retrieval/relation_service.py`，
  `app/services/relation_service.py` 仅保留兼容导出
- 语料实体的章节解析、关联写入和历史题目章节回填已迁移到
  `app/modules/catalog/chapter_link_service.py`，
  `app/services/chapter_link_service.py` 仅保留兼容导出；关键词打分和向量召回策略进一步拆分到
  `app/modules/catalog/chapter_matcher.py`
- 标准章节树维护、文档 section 映射、映射审核和章节归属诊断已迁移到
  `app/modules/catalog`；其中标准章节树维护位于 `canonical_chapter_service.py`，
  section 映射与审核位于 `chapter_mapping_service.py`，
  页级、块级和 section 级章节归属诊断位于 `chapter_diagnostics_service.py`，
  `app/services/chapter_mapping_service.py` 仅保留兼容导出
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
