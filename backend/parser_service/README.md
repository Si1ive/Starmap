# PDF Parser Service

独立 PDF 解析服务，供主 `backend` 在 `local` 模式下通过 HTTP 调用。

## 目标

- 将 PDF 解析负载从主后端剥离
- 支持 `Docling` / `MinerU` 两类解析器
- 兼容本机 Podman 和后续远程部署

## 平台约束

- `MinerU` 官方 README 当前标注 Python 支持范围为 `3.10-3.13`
- `MinerU` 官方 README 当前标注 Docker 部署主要面向 `Linux` 与 `Windows + WSL2`
- `MinerU` 官方 README 当前标注纯 CPU 可通过 `pipeline` backend 运行，但仍建议至少 `16GB` 内存
- 对于 `macOS + Podman`，建议视为“尽力支持”环境，不应默认承诺和 Linux 同等稳定性

因此：

- 生产环境优先建议把 `pdf-parser-service` 部署到 `Linux` 机器
- 本机 `macOS` 更适合作为联调和轻量验证环境

## 接口

### `GET /health`

请求参数：

- `parser_name`: `docling` / `mineru`，可选

返回：

- 当前解析器探活状态
- 当前服务默认解析器
- 当前服务运行模式

### `POST /parse`

表单参数：

- `file`: PDF 文件
- `parser_name`: `docling` / `mineru`，可选

返回：

- 统一后的 `pages / blocks / assets / document_markdown`

## 本地启动

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r parser_service/requirements.txt
pip install "mineru[all]>=3.3,<4"
uvicorn parser_service.main:app --host 0.0.0.0 --port 8090
```

## Podman 构建

默认构建 `MinerU` 镜像：

```bash
podman build \
  -f backend/parser_service/Dockerfile \
  -t starmap-pdf-parser:mineru \
  --build-arg PARSER_FLAVOR=mineru \
  --build-arg MINERU_PACKAGE_SPEC='mineru[all]>=3.3,<4' \
  backend
```

构建 `Docling` 镜像：

```bash
podman build \
  -f backend/parser_service/Dockerfile \
  -t starmap-pdf-parser:docling \
  --build-arg PARSER_FLAVOR=docling \
  backend
```

同时安装两套依赖，仅用于开发调试：

```bash
podman build \
  -f backend/parser_service/Dockerfile \
  -t starmap-pdf-parser:both \
  --build-arg PARSER_FLAVOR=both \
  backend
```

## 运行建议

- 本地联调默认：
  - `PARSER_FLAVOR=mineru`
  - `PDF_PARSER_SERVICE_DEFAULT=mineru`
- 若你的开发机是 `macOS`，优先只把它作为联调机，不要把大量解析任务压在本机上
- 如果准备正式跑批量 PDF，优先把这个服务部署到单独的 Linux 机器
