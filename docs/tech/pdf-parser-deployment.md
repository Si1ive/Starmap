# PDF 解析器部署方案

> 版本：v1  
> 日期：2026-06-13  
> 适用范围：当前仓库 `Docling` / `MinerU` 单活部署、Podman 运行、后端系统设置切换

## 1. 先说结论

当前项目最初的 PDF 解析器是由后端进程在本地直接导入 Python 依赖并执行：

- `Docling` 通过 `docling.document_converter.DocumentConverter`
- `MinerU` 通过 `mineru.cli.common.convert_single_pdf`

但从 `2026-06-13` 开始，系统设置已预留“本地 Podman 服务 / 远程解析服务”两种部署位置。因此现阶段建议拆分为：

1. 继续以 `Podman` 作为统一容器运行时。
2. 默认通过本地 Podman 中的独立解析服务镜像提供解析能力。
3. 在管理端“系统设置 -> PDF解析器”中选择 `local` 或 `remote`。
4. `remote` 模式先保存远程地址和切换记录，后续再接入真实转发。
5. 任一时刻只保留一个激活解析器和一个激活部署位置。

换句话说：

- **要用 Podman**：是，和现有项目基线一致。
- **要不要单独给解析器再开一个 Podman 容器**：建议，尤其当本机算力有限时。

当前仓库已提供独立解析服务脚手架：

- `backend/parser_service/main.py`
- `backend/parser_service/Dockerfile`
- `docker-compose.podman.yml` 中的 `pdf-parser-service`

## 2. 为什么当前不建议单独拆解析器容器

当前代码路径在 `backend/app/services/document_parsers.py`，解析器调用是进程内 import：

- `DoclingParser.parse()`
- `MinerUParser.parse()`

这意味着后端现在依赖的是“本机 Python 包可用”，而不是：

- HTTP 解析服务
- gRPC 解析服务
- 消息队列异步解析服务

如果现在硬拆成独立容器，会额外引入一整层新工作：

1. 定义解析服务 API 协议
2. 改写 `document_parsers.py` 为远程调用
3. 处理大 PDF 文件传输
4. 处理超时、重试、任务回调
5. 处理远端服务日志、监控、鉴权

这对你当前“先把 PDF 入库跑通，再保留低频切换能力”的目标来说，成本过高。

## 3. 推荐部署形态

推荐采用 **“单 backend 容器 + 单活解析器依赖”** 的部署模式。

### 3.1 运行单元

建议保持如下结构：

- `mysql`：Podman 容器
- `redis`：Podman 容器
- `qdrant`：Podman 容器
- `backend`：Podman 容器
- `frontend-admin`：本地开发进程或 Podman 容器

其中 PDF 解析能力放在 `backend` 容器内部，不单拆。

### 3.2 解析器部署原则

- 生产同一时刻只启用一个主解析器
- 默认主解析器使用 `MinerU`
- `Docling` 作为性能优先备选
- 切换解析器时必须伴随容器重建和后端重启
- 切换后必须跑一批基准 PDF 回归验证

### 3.3 为什么推荐 `MinerU` 作为默认

结合你当前判断和现有代码设计，推荐：

- `MinerU` 作为主流默认方案，适合大多数文档场景
- `Docling` 保留为吞吐和性能优先的备选方案

这也和当前系统设置默认值保持一致：

- `pdf_parser.active_parser = mineru`

## 4. 两种可落地方案

## 4.1 方案 A：单镜像按环境构建，推荐先落地

思路：

- 后端镜像按当前激活解析器安装对应依赖
- 例如部署 `MinerU` 版本 backend 镜像
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

## 4.2 方案 B：双镜像预构建，切换时替换 backend 镜像，推荐中期采用

思路：

- 提前准备两个 backend 镜像：
  - `backend:mineru`
  - `backend:docling`
- 平时只运行其中一个 backend 容器
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

### 5.2 单独部署远程解析器服务，但后端代码仍保持本地 import

问题：

- 架构与实现不一致
- 只会增加运维复杂度，不能解决当前错误

### 5.3 手工在宿主机 Python 环境装依赖，不进容器

问题：

- 环境不可复制
- 开发机、测试机、线上机容易漂移
- 排障成本高

## 6. 推荐的实际部署流程

以下流程最符合当前项目。

### 6.1 首次部署 `MinerU`

1. 基础设施继续使用 `Podman`
2. 构建包含 `MinerU` 依赖的 `backend` 镜像
3. 启动 `backend` 容器
4. 调用 `GET /api/v1/admin/settings` 检查：
   - `pdf_parser.active_parser`
   - `pdf_parser.active_runtime_status`
   - `available_parsers`
5. 在管理端确认 `MinerU` 显示为 `ready`
6. 将系统设置中的激活解析器切为 `mineru`
7. 用基准 PDF 执行解析回归

### 6.2 从 `MinerU` 切到 `Docling`

1. 停止当前 `backend` 容器
2. 启动包含 `Docling` 依赖的新 `backend` 容器
3. 先做健康检查，确认 `docling` 为 `ready`
4. 在“系统设置 -> PDF解析器”填写切换备注并切换到 `docling`
5. 重新跑基准 PDF
6. 确认通过后恢复批量入库

### 6.3 回滚流程

1. 停止当前 `backend` 容器
2. 启动上一个可用解析器镜像
3. 在系统设置中切回旧解析器
4. 记录失败原因和回滚时间

## 7. Podman 编排建议

当前项目已经以 `Podman + podman-compose` 作为部署基线，因此 PDF 解析器部署也应保持一致。

推荐做法不是增加独立 `mineru` / `docling` 服务，而是给 `backend` 增加镜像变体，例如：

- `starmap-backend:mineru`
- `starmap-backend:docling`

运维切换动作是：

1. 替换 backend 镜像标签
2. 重启 backend 容器
3. 再切系统设置中的 `active_parser`

这样能保证：

- 配置和运行时一致
- 不会出现“数据库说是 mineru，容器里实际没有 mineru”

## 8. 你现在应该怎么做

你当前报错说明：

1. 数据库里的激活解析器仍是 `docling`
2. 当前运行中的后端环境没有可用 `docling`

因此下一步不该继续重试解析，而应该先完成部署动作：

### 路线 1：先用 `MinerU` 跑通，推荐

1. 准备 `MinerU` 依赖版 backend 镜像
2. 重启 backend
3. 在系统设置中切换到 `mineru`
4. 做一轮 PDF 回归

### 路线 2：坚持先上 `Docling`

1. 准备 `Docling` 依赖版 backend 镜像
2. 重启 backend
3. 保持系统设置为 `docling`
4. 做一轮 PDF 回归

如果按你的产品判断，建议优先走路线 1。

## 9. 后续演进建议

当你后续满足以下条件时，再考虑把解析器真正拆成独立服务：

1. PDF 解析吞吐明显成为瓶颈
2. 单个解析任务耗时很长，需要异步队列化
3. 需要多台机器横向扩容解析能力
4. 需要 GPU / OCR / 版面分析能力独立伸缩

到那时再升级成：

- `backend` 负责任务编排
- `parser-service` 负责 PDF 解析
- `backend` 通过 HTTP / MQ 调用解析服务

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
