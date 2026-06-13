# 部署指南

## 当前部署基线

当前 408 平台文档以仓库内现有运行方式为准：

- 基础设施优先使用 `Podman + podman-compose`
- 向量数据库使用 `Qdrant`
- 管理端目录为 `frontend-admin`
- 后端目录为 `backend`

## 本地开发部署

### 1. 克隆项目

```bash
git clone <repo-url>
cd my-agent
```

### 2. 启动基础设施

```bash
podman-compose -f docker-compose.podman.yml up -d
```

### 2.1 启动本地 PDF 解析服务

默认按 `MinerU` 构建独立解析服务镜像：

```bash
export PDF_PARSER_FLAVOR=mineru
export PDF_PARSER_SERVICE_DEFAULT=mineru
export MINERU_PACKAGE_SPEC='mineru[all]>=3.3,<4'
podman-compose -f docker-compose.podman.yml up -d pdf-parser-service
```

如果要切换为 `Docling`：

```bash
export PDF_PARSER_FLAVOR=docling
export PDF_PARSER_SERVICE_DEFAULT=docling
podman-compose -f docker-compose.podman.yml up -d --build pdf-parser-service
```

注意：

- 若你当前是 `macOS + Podman`，这条链路更适合联调，不建议直接承载大规模 PDF 批量解析
- 若你要稳定跑 `MinerU`，更建议把 `pdf-parser-service` 部署到 `Linux` 机器

### 3. 初始化 MySQL

```bash
podman exec -i starmap-mysql mysql -ustarmap -pstarmap123 starmap < backend/scripts/init_408_tables.sql
```

### 4. 启动后端

如已通过 `podman-compose -f docker-compose.podman.yml up -d backend` 启动容器，可跳过本节。

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PDF_PARSER_LOCAL_ENDPOINT=http://localhost:8090
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 启动管理端

如已通过 `podman-compose -f docker-compose.podman.yml up -d frontend-admin` 启动容器，可跳过本节。

```bash
cd frontend-admin
npm install
npm run dev
```

## 本地验证

| 服务 | 地址 |
|------|------|
| 后端 API | `http://localhost:8000` |
| PDF 解析服务 | `http://localhost:8090` |
| Swagger | `http://localhost:8000/docs` |
| 管理端 | `http://localhost:5174` |
| Qdrant | `http://localhost:6333` |

## 关键环境变量

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=starmap
MYSQL_PASSWORD=starmap123
MYSQL_DATABASE=starmap
REDIS_URL=redis://localhost:6379
QDRANT_HOST=localhost
QDRANT_PORT=6333
PDF_PARSER_LOCAL_ENDPOINT=http://localhost:8090
MINERU_PACKAGE_SPEC=mineru[all]>=3.3,<4
```

## 运维说明

### 查看容器状态

```bash
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### 查看日志

```bash
podman logs starmap-backend
podman logs starmap-mysql
podman logs starmap-qdrant
podman logs starmap-pdf-parser-service
```

### Qdrant 健康检查

```bash
curl http://localhost:6333/collections
```

### PDF 解析服务健康检查

```bash
curl http://localhost:8090/health
```

### Redis 健康检查

```bash
redis-cli ping
```

## 说明

本文件描述当前仓库的本地开发部署基线。若后续新增其他部署方式，应单独补充并明确适用范围。
