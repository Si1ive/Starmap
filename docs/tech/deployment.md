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

当前 `docker-compose.podman.yml` 已内置以下行为：

- `pdf-parser-service` 默认以 `PARSER_FLAVOR=both` 构建，同时提供 `docling` / `mineru`
- `pdf-parser-service` 挂载持久化 `mineru_cache` 卷，避免模型重复下载
- 全新 MySQL 数据卷会先初始化通用基础表和 408 基础表
- `backend` 启动前自动执行 `alembic upgrade head`，用于补齐 `document_pages` 等解析链路表
- FastAPI 进程只校验当前数据库是否位于 Alembic head，不在应用启动期执行迁移
- `MinerU` 默认窗口大小为 `1`，也可在后台“系统配置 -> PDF解析器”里调整 `processing_window_size`

### 2.1 启动本地 PDF 解析服务

默认按双依赖构建独立解析服务镜像，激活解析器仍由后台系统设置控制：

```bash
export PDF_PARSER_FLAVOR=both
export PDF_PARSER_SERVICE_DEFAULT=mineru
export MINERU_PACKAGE_SPEC='mineru[pipeline]>=3.3,<4'
podman-compose -f docker-compose.podman.yml up -d pdf-parser-service
```

若你是在 `Linux` 机器上做完整批量解析，且明确需要官方全量依赖，再切到：

```bash
export MINERU_PACKAGE_SPEC='mineru[all]>=3.3,<4'
```

如只想在镜像层单装某一种解析器，仍可显式改回 `mineru` 或 `docling`。

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
alembic -c alembic.ini upgrade head
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

生产环境应由发布任务或单独 migration job 执行
`alembic upgrade head`，完成后再滚动启动 API 实例。数据库可连接但版本落后时，
API 会拒绝启动并输出当前版本与期望版本，避免旧结构下继续写入数据。

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
MINERU_PACKAGE_SPEC=mineru[pipeline]>=3.3,<4
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
