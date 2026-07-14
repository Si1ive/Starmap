# MinerU 解析运行时设计

> 更新日期：2026-07-14
> 适用范围：语料 PDF 解析、独立解析服务、系统设置与运行监控

## 1. 决策

平台的 PDF 解析实现固定为 `MinerU`，不再保留其他解析器实现，也不提供按文件或
系统级的解析器类型切换。

系统设置只负责 MinerU 的运行位置和参数：

- `local`：调用本地 Podman 中的 `pdf-parser-service`
- `remote`：调用远程部署的同协议 MinerU 服务
- `request_timeout_seconds`：主后端等待解析响应的超时
- `processing_window_size`：MinerU 页面处理窗口

解析失败时返回明确错误并记录 `ParseRun`，不自动切换到其他解析实现。

## 2. 模块边界

解析子系统位于 `backend/app/modules/corpus`：

| 模块 | 职责 |
|------|------|
| `parser_types.py` | `DocumentParser`、标准页面/块/资产/结果与运行配置契约 |
| `mineru_parser.py` | 嵌入式 MinerU 调用、原始输出归一化、图片资产内联 |
| `parser_service_client.py` | 本地/远程 HTTP 调用、进度查询和响应反序列化 |
| `parser_runtime.py` | 配置归一化、部署目标选择、解析器注册与健康检查 |
| `document_parse_service.py` | 解析任务编排、运行状态和标准结果持久化 |
| `document_store.py` | 文档、页面、块和资产落库 |

旧的 `app/services/document_parsers.py` 和过渡聚合文件
`app/modules/corpus/document_parsers.py` 已删除。

## 3. 稳定契约

下游只消费 `ParsedDocumentResult`：

- `pages`：页码、宽高
- `blocks`：块类型、阅读顺序、文本、Markdown、bbox、表格和公式
- `assets`：图片、表格、公式等资产及其 bbox
- `document_markdown`
- `metadata`
- `raw_output`

MinerU 的 `content_list` 字段、版本差异和临时输出目录只在适配层处理。章节识别、
题目抽取、知识点抽取和检索构建不直接依赖 MinerU 原始结构。

## 4. 调用流程

```text
CorpusFile
  -> DocumentParseService
  -> parser_runtime.choose_parser()
  -> LocalParserServiceClient / RemoteParserServiceClient
  -> MinerU parser service
  -> ParsedDocumentResult
  -> ParsedDocumentStore
```

独立 parser 进程直接通过 `parser_runtime.get_parser("mineru")` 获取嵌入式适配器。
主后端默认通过 HTTP 调用解析服务，避免安装和加载重型 MinerU 依赖。

## 5. 服务协议

MinerU 服务必须提供：

- `GET /health`
- `POST /parse`
- `GET /progress/{task_id}`

`POST /parse` 接收 PDF 文件、`parser_name=mineru`、可选 `task_id` 和
`processing_window_size`，返回标准化解析结果。主后端负责最终资产落盘和数据库
持久化。

## 6. 配置兼容

数据库或旧环境中残留的 `active_parser` 值会统一归一为 `mineru`，
`service_mode` 统一归一为 `mineru_only`。管理端不展示解析器类型选择，只展示：

- 当前 MinerU 健康状态
- 本地/远程部署位置
- 服务地址
- 请求超时
- 页面处理窗口
- 配置变更说明

`/api/v1/admin/settings/pdf-parser/history` 继续保留，用于审计 MinerU 部署目标和
运行参数变更。

## 7. 失败处理

- 服务地址缺失或格式错误：任务启动前返回配置错误
- 服务不可连接或超时：记录明确的服务端点和错误摘要
- 服务返回非 JSON 或非标准结构：转换为 `ParserUnavailableError`
- MinerU 解析失败：保留失败运行记录，允许人工调整参数后重试
- 进度端点不可用：不阻断主解析请求，仅暂停进度刷新

## 8. 测试要求

- MinerU 原始输出到标准块/资产的归一化测试
- HTTP 上传、运行参数和进度查询测试
- 本地/远程部署目标选择测试
- 健康检查与错误响应测试
- 设置中旧解析器值归一为 MinerU 的兼容测试
- 完整后端回归测试
