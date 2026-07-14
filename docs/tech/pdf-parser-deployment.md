# PDF 解析器部署方案

> 版本：v1  
> 日期：2026-06-13  
> 更新：2026-07-14
> 适用范围：当前仓库 `Docling` / `MinerU` 单活部署、Podman 运行、后端系统设置切换

## 1. 先说结论

当前项目已将 PDF 解析能力从主 backend 拆分为独立 `pdf-parser-service`。主 backend 通过统一 HTTP 协议调用本地 Podman 服务或远程服务：

1. 继续以 `Podman` 作为统一容器运行时。
2. 默认通过本地 Podman 中的独立解析服务镜像提供解析能力。
3. 在管理端“系统设置 -> PDF解析器”中选择 `local` 或 `remote`。
4. `remote` 模式会真实执行健康检查、文件上传解析和任务进度轮询。
5. 任一时刻只保留一个激活解析器和一个激活部署位置。

换句话说：

- **要用 Podman**：是，和现有项目基线一致。
- **要不要单独给解析器再开一个 Podman 容器**：建议，尤其当本机算力有限时。

当前仓库已提供独立解析服务脚手架：

- `backend/parser_service/main.py`
- `backend/parser_service/Dockerfile`
- `docker-compose.podman.yml` 中的 `pdf-parser-service`

当前唯一有效的本地编排入口为：

- `docker-compose.podman.yml`

旧的 `docker-compose.yml` 已移除，避免与当前 Podman 基线和 Qdrant 方案冲突。

并且当前镜像构建策略已经细化为：

- `PARSER_FLAVOR=mineru`：安装 `MinerU`
- `PARSER_FLAVOR=docling`：安装 `Docling`
- `PARSER_FLAVOR=both`：两套依赖同时安装，仅建议开发调试

当前 `pdf-parser-service` 还额外做了两件事：

- 将 `MinerU` 模型缓存目录持久化到容器卷，避免每次重建后重复下载
- 将 `MINERU_PROCESSING_WINDOW_SIZE` 默认压到 `1`，把页面推理改成逐页窗口，降低峰值内存

对于 `MinerU`，当前默认先按较轻量依赖构建：

- `mineru[pipeline]>=3.3,<4`

若后续你明确需要官方完整依赖集合，再切换为：

- `mineru[all]>=3.3,<4`

## 2. 统一 HTTP 协议

本地和远程服务必须实现相同接口：

- `GET /health?parser_name=mineru`：解析器探活与版本信息
- `POST /parse`：multipart 文件上传，接收 `parser_name`、`processing_window_size`、`task_id`
- `GET /progress/{task_id}`：长任务页级进度查询

主 backend 负责运行配置、任务状态和结果入库，解析服务只负责把 PDF 转换为标准化 `ParsedDocumentResult`。远程生产部署应使用 HTTPS，并通过私有网络、防火墙或反向代理限制访问。

## 3. 推荐部署形态

推荐采用 **“backend + 单活 parser-service”** 的部署模式。

### 3.1 运行单元

建议保持如下结构：

- `mysql`：Podman 容器
- `redis`：Podman 容器
- `qdrant`：Podman 容器
- `backend`：Podman 容器
- `pdf-parser-service`：本地 Podman 容器，或等价的远程服务
- `frontend-admin`：本地开发进程或 Podman 容器

解析器依赖只安装在 `pdf-parser-service`，主 backend 不再承担 MinerU / Docling 的重型运行时。

### 3.2 解析器部署原则

- 生产同一时刻只启用一个主解析器
- 默认主解析器使用 `MinerU`
- `Docling` 作为性能优先备选
- 本地切换解析器时替换或重建 parser-service 镜像
- 远程切换时先部署并探活远程 parser-service，再更新系统设置
- 切换后必须跑一批基准 PDF 回归验证

### 3.3 为什么推荐 `MinerU` 作为默认

结合你当前判断和现有代码设计，推荐：

- `MinerU` 作为主流默认方案，适合大多数文档场景
- `Docling` 保留为吞吐和性能优先的备选方案

这也和当前系统设置默认值保持一致：

- `pdf_parser.active_parser = mineru`

## 4. 两种可落地方案

## 4.1 方案 A：单 parser-service 镜像按环境构建，推荐

思路：

- parser-service 镜像按当前激活解析器安装对应依赖
- 例如部署 `MinerU` 版本 parser-service 镜像
- 需要切换到 `Docling` 时，重新构建并发布 `Docling` 版本镜像

优点：

1. 和当前代码最匹配
2. 运维链路简单
3. 容器资源边界清晰
4. 更符合“低频切换”的产品设定

缺点：

1. 切换需要重建镜像
2. 切换时有短暂发布窗口

适用：

- 当前阶段
- 单机或轻量环境
- 优先保证可控性而不是秒级切换

## 4.2 方案 B：双镜像预构建，切换时替换 parser-service 镜像

思路：

- 提前准备两个 parser-service 镜像：
  - `parser-service:mineru`
  - `parser-service:docling`
- 平时只运行其中一个 parser-service 容器
- 切换时停旧容器、启新容器，并在系统设置中修改激活解析器

优点：

1. 切换速度更快
2. 不必在切换时临时安装依赖
3. 更符合“停旧启新”的单活切换模式

缺点：

1. 需要维护两套镜像
2. CI/CD 会稍复杂

适用：

- 你后续准备把 PDF 入库纳入稳定运维
- 已有固定回归样本集
- 能接受多维护一套镜像标签

## 5. 不推荐的方案

当前阶段不推荐以下方式：

### 5.1 在同一个 backend 容器里同时安装两套解析器并频繁切换

问题：

- 依赖冲突风险高
- 镜像膨胀
- 很容易出现“配置切了，但实际环境不干净”
- 和你“不能频繁切换”的约束相冲突

### 5.2 将无访问控制的远程解析服务暴露到公网

问题：

- 文件上传接口会成为高资源消耗入口
- 当前协议不内置应用层鉴权，应由私有网络或反向代理提供访问控制
- 必须启用 HTTPS，避免上传文档在传输中泄露

### 5.3 手工在宿主机 Python 环境装依赖，不进容器

问题：

- 环境不可复制
- 开发机、测试机、线上机容易漂移
- 排障成本高

## 6. 推荐的实际部署流程

以下流程最符合当前项目。

### 6.1 首次部署 `MinerU`

1. 基础设施继续使用 `Podman`
2. 构建 `PARSER_FLAVOR=mineru` 的 parser-service 镜像
3. 启动 `pdf-parser-service` 和 backend 容器
4. 调用 `GET /api/v1/admin/settings` 检查：
   - `pdf_parser.active_parser`
   - `pdf_parser.active_runtime_status`
   - `available_parsers`
5. 在管理端确认 `MinerU` 显示为 `ready`
6. 将系统设置中的激活解析器切为 `mineru`
7. 用基准 PDF 执行解析回归

### 6.2 从 `MinerU` 切到 `Docling`

1. 停止当前 `pdf-parser-service` 容器
2. 启动包含 `Docling` 依赖的新 parser-service 容器
3. 先做健康检查，确认 `docling` 为 `ready`
4. 在“系统设置 -> PDF解析器”填写切换备注并切换到 `docling`
5. 重新跑基准 PDF
6. 确认通过后恢复批量入库

### 6.3 回滚流程

1. 停止当前 parser-service
2. 启动上一个可用解析器镜像
3. 在系统设置中切回旧解析器
4. 记录失败原因和回滚时间

## 7. Podman 编排建议

当前项目已经以 `Podman + podman-compose` 作为部署基线，因此 PDF 解析器部署也应保持一致。

推荐维护 parser-service 镜像变体，例如：

- `starmap-parser-service:mineru`
- `starmap-parser-service:docling`

运维切换动作是：

1. 替换 parser-service 镜像标签
2. 重启 parser-service 容器
3. 再切系统设置中的 `active_parser`

这样能保证：

- 配置和运行时一致
- 不会出现“数据库说是 mineru，解析服务实际没有 mineru”

## 8. 远程部署检查清单

1. 在远程机器部署与仓库 `parser_service` 契约兼容的服务。
2. 使用 HTTPS 地址，并限制只有 backend 所在网络可以访问。
3. 先请求 `/health` 验证目标解析器为 `ready`。
4. 在系统设置填写 `remote_service_endpoint` 并切换到 `remote`。
5. 用小型基准 PDF 验证解析和 `/progress/{task_id}`。
6. 再执行批量任务，并观察超时、失败率和网络带宽。

## 9. 后续演进建议

当解析吞吐继续增长时，可在当前独立服务基础上演进：

1. PDF 解析吞吐明显成为瓶颈
2. 单个解析任务耗时很长，需要异步队列化
3. 需要多台机器横向扩容解析能力
4. 需要 GPU / OCR / 版面分析能力独立伸缩

- 在 parser-service 前增加任务队列和对象存储，避免大文件同步上传长连接
- 按解析器或 GPU 资源拆分 worker 池
- 增加服务级认证、限流和请求签名
- 保持 `ParsedDocumentResult` 契约不变，避免影响下游入库与抽取链路

但这属于下一阶段架构，不是当前最优先事项。

## 10. 当前推荐结论

最终建议如下：

1. **继续用 Podman**
2. **不要先拆独立解析器容器**
3. **把解析器依赖放进 backend 镜像**
4. **默认部署 MinerU 版 backend**
5. **Docling 保留为低频切换备选**
6. **每次切换都按“停旧 backend -> 启新 backend -> 再切系统设置”执行**

这套方案和你当前代码、管理端入口、单活切换约束是一致的，也是现阶段成本最低、最稳的落地方式。
