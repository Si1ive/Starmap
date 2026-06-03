# 部署指南

## 开发环境部署

### 1. 克隆项目

```bash
git clone <repo-url>
cd starmap
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的配置
```

### 3. 启动基础设施

```bash
docker-compose up -d neo4j redis chromadb
```

### 4. 安装后端依赖

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 5. 运行后端

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. 安装前端依赖

```bash
cd ../frontend
npm install
```

### 7. 运行前端

```bash
npm run dev
```

### 8. 验证部署

- 前端：http://localhost:5173
- 后端API：http://localhost:8000
- API文档：http://localhost:8000/docs
- Neo4j浏览器：http://localhost:7474

## 生产环境部署

### Docker Compose 生产配置

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "80:80"
    depends_on:
      - backend

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    environment:
      - NEO4J_URI=bolt://neo4j:7687
      - REDIS_URL=redis://redis:6379
      - CHROMA_HOST=chromadb
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - neo4j
      - redis
      - chromadb

  neo4j:
    image: neo4j:5-community
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc"]
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  chromadb:
    image: chromadb/chroma:latest
    volumes:
      - chroma_data:/chroma/chroma

volumes:
  neo4j_data:
  neo4j_logs:
  redis_data:
  chroma_data:
```

### 部署步骤

```bash
# 1. 服务器准备
# 安装 Docker 和 Docker Compose

# 2. 拉取代码
git clone <repo-url>
cd starmap

# 3. 配置环境变量
export OPENAI_API_KEY=sk-...
export NEO4J_PASSWORD=your-password

# 4. 启动服务
docker-compose -f docker-compose.prod.yml up -d

# 5. 验证
curl http://localhost/api/v1/health
```

## 监控与日志

### 日志收集

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
```

### 健康检查

```bash
# API健康检查
curl http://localhost:8000/health

# Neo4j健康检查
curl http://localhost:7474/db/manage/server/jmx/domain/org.neo4j/instance%3Dkernel%230%2Cname%3DDiagnostics
```

## 备份与恢复

### Neo4j备份

```bash
# 备份
docker exec starmap_neo4j_1 neo4j-admin backup --from=localhost --backup-dir=/backups

# 恢复
docker exec starmap_neo4j_1 neo4j-admin restore --from=/backups --database=neo4j --force
```

### Redis备份

```bash
# 手动备份
redis-cli SAVE

# 复制备份文件
cp /var/lib/redis/dump.rdb /backups/redis/dump.rdb
```
