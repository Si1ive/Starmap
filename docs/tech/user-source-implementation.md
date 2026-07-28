# 用户私有资料入库、阅读与检索授权

## 适用范围

本卷说明用户端 PDF 如何进入真实语料库、如何绑定当前用户、如何阅读已入库原件，以及“暂停 Agent 使用”
和删除撤权如何同时约束普通检索与模拟考。平台资料的管理员入库仍由语料管理模块负责，不经过用户接口。

## 数据与迁移

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 所有权与可用性模型 | `backend/app/models/mysql_models.py` | `CorpusFile` | L677-L735 | 平台资料或认证用户上传文件 | `owner_user_id=NULL` 表示平台资料；个人资料保存真实用户 ID；`retrieval_enabled` 与 `deleted_at` 分开表达检索授权和删除撤权 | `corpus_files` 权威状态 | 列表、阅读、检索和练习过滤 |
| 前向迁移 | `backend/alembic/versions/20260728_user_source_controls.py` | `upgrade`、`downgrade` | L18-L42 | 已升级至 `20260728_practice_snapshot` 的数据库 | 新增默认启用的检索开关、逻辑删除时间和可用性组合索引；不 stamp、不改写历史迁移 | head=`20260728_user_source_controls` | ORM 与服务查询消费 |

## 上传到原始 PDF 阅读

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 上传与真实入库 | `backend/app/modules/library/router.py` | `upload_library_sources` | L99-L132 | 带登录会话、可信 Origin、CSRF 的 multipart PDF | 同时校验扩展名和 `%PDF-` 文件签名，把 `owner_user_id` 交给语料服务，再启动解析、实体抽取与索引 | `corpus_files`、解析任务和抽取任务；失败以可见状态返回 | `list_library_sources` 轮询状态 |
| 同用户去重 | `backend/app/modules/corpus/file_service.py` | `CorpusFileService.register_single_file` | L171-L235 | 本地暂存路径、展示名、用户 ID | SHA256 只在同一 owner 且未删除资料内去重；其他用户相同文件不会复用记录，已删除文件允许重新入库 | 新建或复用当前用户的 `CorpusFile` | 解析服务 |
| 列表投影 | `backend/app/modules/library/router.py` | `list_library_sources` | L38-L96 | 当前用户、来源筛选、搜索和分页 | 只返回平台资料与本人未删除资料，并公开真实处理状态、检索授权、页数和可读 URL | 用户资料 DTO；只读 | `SourcesPage.loadSources` |
| PDF 原件读取 | `backend/app/modules/library/router.py` | `read_original_pdf` | L185-L214 | Document ID 和当前会话 | 重新联表校验平台/本人所有权、未删除和 PDF 类型，再以内联响应读取入库记录保存的原始路径 | 原始 PDF 字节；无权 404、文件缺失 410 | 浏览器原生 PDF 阅读器 |

## 检索授权与删除撤权

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 个人资料作用域门 | `backend/app/modules/library/router.py` | `_owned_personal_source` | L135-L149 | source ID、当前用户 ID | 只匹配本人且未删除记录；平台资料、其他用户资料、已删除资料统一 404 | 已授权 `CorpusFile` | 两个写接口 |
| 暂停或恢复检索 | `backend/app/modules/library/router.py` | `update_source_retrieval` | L152-L165 | source ID、布尔 `enabled`、CSRF 会话 | 只修改 `retrieval_enabled`，不删除 PDF、不改变解析事实 | 同事务更新检索授权 | 列表刷新；后续检索水合 |
| 删除撤权 | `backend/app/modules/library/router.py` | `delete_library_source` | L168-L182 | source ID、CSRF 会话 | 同一事务先关闭检索，再写 `deleted_at` 和归档状态；保留最小元数据与历史外键用于已有练习/引用复盘 | 新检索与阅读立即不可见；不会破坏历史练习快照 | 后续保留策略清理二进制和向量副本 |
| 检索最终门禁 | `backend/app/modules/retrieval/search_engine.py` | `RetrievalSearchEngine.hydrate_results` | L286-L328 | Qdrant 或稀疏召回命中、当前 user ID | MySQL 水合时同时要求资料未删除、检索已启用，并只允许平台或当前用户 owner；旧向量命中也无法穿透 | 安全的 `RetrievalResult[]` | Agent RAG 消费 |
| 模拟考选卷门禁 | `backend/app/modules/practice/router.py` | `_visible_document` | L53-L58 | 当前 user ID | 对试卷资料复用 owner、未删除和检索启用三个条件 | 可用于新练习的真实文档范围 | 选卷与创建练习接口 |

## 用户端消费

| 执行阶段 | 文件 | 符号 | 代码范围 | 输入 | 处理 | 输出/副作用 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| API 客户端 | `frontend/src/api/library.ts` | `listLibrarySources`、`uploadLibrarySources`、`mutateLibrarySource`、`setLibrarySourceRetrieval`、`deleteLibrarySource` | L37-L115 | 当前浏览器会话、文件或 source ID | 读取列表；上传使用 multipart；写操作重新获取 CSRF 并只发送 JSON | 类型化资料状态或用户可见错误 | `SourcesPage` |
| 资料工作区 | `frontend/src/pages/SourcesPage.tsx` | `SourcesPage`、`toggleRetrieval`、`removeSource` | L53-L171、L173-L310 | 真实资料列表与用户动作 | 轮询活跃入库任务；个人资料提供阅读、暂停/恢复 Agent 使用和确认删除；操作后重新读取服务端事实 | 不维护 mock 资料；删除后关闭已打开阅读器 | 用户继续上传、阅读或检索 |

## 错误传播与边界

1. 用户写接口都经过 Session、Origin 和 CSRF 校验；仅知道 source ID 不能修改资料。
2. 暂停 Agent 使用不等于删除：PDF 仍可阅读，也可再次恢复检索。
3. 删除先完成访问与检索撤权。历史练习依赖冻结题面，删除资料不会改写已交卷成绩；最小元数据暂时保留以满足引用和外键完整性。
4. 当前上传面只开放 PDF，这是本次“原始 PDF 像电子书阅读”的明确范围；图片和文本格式仍是产品文档中的后续能力，不能在界面上虚报支持。
