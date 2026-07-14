# PDF 解析器切换设计

> 版本：v1  
> 日期：2026-06-12  
> 适用范围：`Docling` / `MinerU` 单活切换、后端解析链路、管理端系统设置

## 1. 设计目标

本设计解决以下问题：

1. 平台同时保留 `Docling` 与 `MinerU` 两套 PDF 解析方案。
2. 运行时只允许一个解析器服务处于激活状态，避免双服务并存带来的资源占用。
3. 解析器切换属于系统级运维动作，而不是单文件操作。
4. 切换解析器后，上下游数据结构与接口契约保持稳定。

## 2. 非目标

本期不做以下内容：

1. 不做自动 fallback 路由。
2. 不做单次入库任务临时选择不同解析器的产品能力。
3. 不做双活解析器并发运行。
4. 不做解析器自动安装、自动卸载、自动服务注册。

## 3. 总体原则

### 3.1 单活原则

- 任一时刻只允许一个 PDF 解析器被视为“当前激活解析器”。
- 切换解析器前，运维或开发者需要先停用当前服务，再部署或注册新的服务。
- 系统设置只记录“当前应该使用哪个解析器”，不负责真正执行环境安装卸载。

### 3.2 契约稳定原则

- `Docling` 与 `MinerU` 的原始输出结构不同。
- 后端通过统一适配层将二者归一到 `ParsedDocumentResult`。
- 下游统一消费：
  - `documents`
  - `document_pages`
  - `document_blocks`
  - `document_assets`

因此，切换解析器不会要求章节抽取、实体抽取、segment 构建、检索接口修改字段契约。

### 3.3 切换入口集中原则

- 解析器切换入口只应存在于“系统设置”。
- `PDF 入库` 页面不应暴露解析器选择控件。
- 单文件入库只调用“当前系统激活解析器”。

### 3.4 部署位置显式化原则

- PDF 解析器除“解析器类型”外，还需要显式区分“部署位置”。
- 当前支持的部署位置：
  - `local`：本地 Podman 解析服务
  - `remote`：远程机器上的解析服务
- 系统设置应同时维护：
  - `active_parser`
  - `deployment_target`
  - `local_service_endpoint`
  - `remote_service_endpoint`

说明：

- `local` 模式是当前主实现路径。
- `remote` 模式通过同一套 HTTP 协议调用远程解析服务。
- 两种模式都要求服务实现 `/health`、`/parse` 与 `/progress/{task_id}`。
- 远程生产部署应使用 HTTPS，并通过私有网络或反向代理限制访问。

## 4. 当前实现

## 4.1 解析适配层

文件：`backend/app/modules/corpus/document_parsers.py`

核心对象：

- `ParsedPage`
- `ParsedBlock`
- `ParsedAsset`
- `ParsedDocumentResult`
- `DoclingParser`
- `MinerUParser`

职责：

1. 屏蔽 `Docling` / `MinerU` 原始输出差异。
2. 输出统一结构给 `DocumentParseService`。
3. 将切换影响限制在解析层内部。

## 4.2 解析主流程

文件：`backend/app/services/document_parse_service.py`

流程：

1. 读取 `CorpusFile`
2. 读取系统设置中的 `pdf_parser.active_parser`
3. 选择当前激活解析器
4. 执行解析并得到 `ParsedDocumentResult`
5. 写入 `parse_runs`
6. 写入 `documents / document_pages / document_blocks / document_assets`

## 4.3 系统设置持久化

文件：`backend/app/services/system_settings_service.py`

当前实现采用数据库表：

- `system_configs`

当前保存结构：

```json
{
  "pdf_parser": {
    "active_parser": "mineru",
    "service_mode": "single_active",
    "service_switch_notes": "",
    "deployment_target": "local",
    "local_service_endpoint": "http://localhost:8090",
    "remote_service_endpoint": "",
    "request_timeout_seconds": 120
  }
}
```

说明：

- 当前已升级为数据库持久化方案。
- 新环境默认以 `MinerU` 作为主解析器，`Docling` 作为性能优先的备选实现。
- 后续可再迁移到独立配置中心。

对应迁移脚本：

- `backend/scripts/20260612170000_add_system_configs.sql`

落地步骤：

1. 执行数据库迁移，创建 `system_configs` 表并写入 `pdf_parser` 默认记录。
2. 重启后端服务。
3. 进入“系统设置 -> PDF解析器”确认当前激活解析器。

## 4.4 管理端入口

文件：

- `frontend-admin/src/pages/Settings/index.tsx`
- `frontend-admin/src/api/settings.ts`

设计要求：

1. 在“系统设置”中增加 `PDF解析器` 页签。
2. 页签中展示当前激活解析器。
3. 页签中同时展示解析器运行状态探活结果。
4. 保存时更新系统级设置。
5. 提示用户这属于服务级切换动作。

## 5. 为什么不能放在 PDF 入库页

原因如下：

1. 切换解析器不是业务参数，而是系统运行形态变化。
2. 切换一次通常伴随依赖安装、旧服务下线、新服务注册。
3. 如果把切换入口放在单文件入库页，会导致同一批文件的解析结果来源不稳定。
4. 运维责任和业务操作应分离。

因此，`PDF 入库` 页面只能触发解析，不能决定系统当前使用哪个解析器。

## 6. 结构兼容性分析

## 6.1 是否真正“即插即用”

答案是：结构层面可以，语义层面不能保证完全一致。

### 可以稳定的部分

- 解析产物字段结构
- 落库表结构
- 后续章节抽取入口
- 实体抽取入口
- segment 构建入口
- 检索入口

### 仍然可能变化的部分

- 分页数量
- block 切分颗粒度
- 表格转 HTML 的完整度
- 图片/图表提取数量
- OCR 文本质量
- 阅读顺序还原质量

结论：

- 上下游代码接口不需要改。
- 但业务质量评估和抽取效果需要重新验证。

## 7. 推荐切换流程

建议的人工切换流程如下：

1. 停止当前激活解析器服务。
2. 卸载、下线或禁用旧解析器依赖。
3. 部署并验证新解析器服务可用。
4. 在“系统设置 -> PDF解析器”中切换 `active_parser`。
5. 记录 `service_switch_notes`：
   - 切换原因
   - 安装方式
   - 依赖版本
   - 回滚步骤
6. 选择一批基准 PDF 做回归验证。
7. 确认通过后再恢复批量入库。

## 8. 当前接口约束

### 系统设置读取

- `GET /api/v1/admin/settings`

返回：

```json
{
  "pdf_parser": {
    "active_parser": "mineru",
    "service_mode": "single_active",
    "service_switch_notes": "",
    "active_runtime_status": {
      "parser_name": "mineru",
      "parser_version": "3.x",
      "health_status": "ready",
      "is_available": true,
      "is_active": true,
      "checked_at": "2026-06-12T09:10:00",
      "error_detail": null
    },
    "available_parsers": [
      {
        "parser_name": "mineru",
        "parser_version": "3.x",
        "health_status": "ready",
        "is_available": true,
        "is_active": true,
        "checked_at": "2026-06-12T09:10:00",
        "error_detail": null
      },
      {
        "parser_name": "docling",
        "parser_version": "2.x",
        "health_status": "unavailable",
        "is_available": false,
        "is_active": false,
        "checked_at": "2026-06-12T09:10:00",
        "error_detail": "No module named 'docling'"
      }
    ]
  }
}
```

### 系统设置更新

- `PUT /api/v1/admin/settings`

请求体示例：

```json
{
  "pdf_parser": {
    "active_parser": "mineru",
    "service_switch_notes": "已停用 Docling 服务，切换至 MinerU OCR 方案"
  }
}
```

### 文件解析触发

- `POST /api/v1/admin/corpus/files/{file_id}/parse`

约束：

- 正式运行默认使用系统设置中的当前激活解析器。
- `parser_name` 字段仅保留给开发调试，不应作为常规产品入口。
- 系统设置接口会顺带返回解析器探活状态，用于区分“配置已切换”和“服务真实可用”。
- 当当前激活解析器不可用时，接口应返回明确错误并提示前往“系统设置 -> PDF解析器”完成低频切换，而不是自动 fallback。

## 9. 后续演进建议

按优先级建议如下：

1. 增加“当前解析器运行状态”探活信息，而不仅仅是配置值。
2. 为 `Docling` 与 `MinerU` 各建立一套基准 PDF 回归测试集。
3. 在 `parse_runs.metrics_json` 中增加质量指标，支持切换前后效果对比。
4. 增加一键回滚指引，但仍保持人工确认。

## 10. 相关文件

- `backend/app/modules/corpus/document_parsers.py`
- `backend/app/services/document_parse_service.py`
- `backend/app/services/system_settings_service.py`
- `backend/app/api/admin.py`
- `frontend-admin/src/pages/Settings/index.tsx`
- `frontend-admin/src/api/settings.ts`
- `frontend-admin/src/pages/Ingest/index.tsx`
