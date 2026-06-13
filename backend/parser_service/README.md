# PDF Parser Service

独立 PDF 解析服务，供主 `backend` 在 `local` 模式下通过 HTTP 调用。

## 目标

- 将 PDF 解析负载从主后端剥离
- 支持 `Docling` / `MinerU` 两类解析器
- 兼容本机 Podman 和后续远程部署

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
pip install "mineru[core]>=2.0.0"
uvicorn parser_service.main:app --host 0.0.0.0 --port 8090
```

## Podman 构建

默认构建 `MinerU` 镜像：

```bash
podman build -f backend/parser_service/Dockerfile -t starmap-pdf-parser:mineru --build-arg PARSER_FLAVOR=mineru backend
```

构建 `Docling` 镜像：

```bash
podman build -f backend/parser_service/Dockerfile -t starmap-pdf-parser:docling --build-arg PARSER_FLAVOR=docling backend
```
