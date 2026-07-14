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
- 实体抽取任务使用文档行锁避免并发重复创建，运行记录先落库再派发后台任务
- PDF 页渲染移入线程池，避免同步转换阻塞 FastAPI 事件循环
- 后续阶段 3C：继续拆分实体抽取中的解析规则、LLM 修复和实体持久化职责

### 阶段 4：检索与关系

- 迁移 Segment、向量召回、章节关联和关系构建
- 为检索过滤条件和索引一致性增加集成测试

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
