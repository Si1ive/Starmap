# StarMap - 艺人知识图谱与对话Agent

## 项目简介

StarMap是一个基于知识图谱的艺人信息探索系统，支持通过自然语言对话查询艺人信息、关系网络、作品等，并提供可视化关系图谱展示。

## 核心功能

- **知识图谱**：构建艺人、作品、公司等实体关系网络
- **智能对话**：通过自然语言与Agent交互，查询艺人信息
- **关系探索**：可视化展示人物关系、合作网络
- **领域浏览**：按演员、歌手、导演等分类浏览

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design + D3.js |
| 后端 | FastAPI (Python 3.11) |
| Agent | LangChain + OpenAI GPT-4 |
| 主数据库 | **MySQL 8.0** - 结构化数据存储 |
| 图数据库 | Neo4j 5.x - 人物关系网络 |
| 向量数据库 | ChromaDB - 语义搜索 |
| 缓存 | Redis - 会话与热点数据 |
| 部署 | **Podman** + Podman Compose |

## 数据库架构

本项目采用 **MySQL + Neo4j + ChromaDB + Redis** 多数据库架构：

- **MySQL** (主存储): 人物属性、作品信息、爬虫任务/日志、管理员用户、审计日志
- **Neo4j** (图数据库): 人物关系网络、图遍历查询
- **ChromaDB** (向量数据库): 语义搜索、向量嵌入
- **Redis** (缓存): 会话状态、搜索结果缓存

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- **Podman** + podman-compose

### 1. 克隆项目

```bash
git clone <repo-url>
cd starmap
```

### 2. 安装 Podman（macOS）

```bash
# 安装 Podman 和 podman-compose
brew install podman podman-compose

# 初始化 Podman 虚拟机（首次）
podman machine init

# 启动虚拟机
podman machine start
```

### 3. 启动数据库服务（Podman）

```bash
# 启动 MySQL + Neo4j + Redis + ChromaDB
podman-compose -f docker-compose.podman.yml up -d

# 查看服务状态
podman-compose -f docker-compose.podman.yml ps

# 查看服务日志
podman-compose -f docker-compose.podman.yml logs -f mysql
podman-compose -f docker-compose.podman.yml logs -f neo4j
podman-compose -f docker-compose.podman.yml logs -f redis
podman-compose -f docker-compose.podman.yml logs -f chromadb
```

服务启动后访问：
- Neo4j Browser: http://localhost:7474 (用户名: neo4j, 密码: starmap123)
- ChromaDB API: http://localhost:8001

### 4. 初始化 MySQL 数据库

```bash
cd backend

# 自动创建表结构和默认管理员账号
python scripts/init_database.py --all
```

### 5. 启动后端服务（本地开发模式）

```bash
cd backend

# 创建虚拟环境（首次）
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# 或: venv\Scripts\activate  # Windows

# 安装依赖（首次）
pip install -r requirements.txt

# 启动服务
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端服务：
- API 地址: http://localhost:8000
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 6. 启动前端服务

```bash
cd frontend

# 安装依赖（首次）
npm install

# 启动开发服务器
npm run dev
```

前端服务：
- 开发服务器: http://localhost:5173

### 7. 验证服务状态

```bash
# 检查所有服务健康状态
curl http://localhost:8000/health

# 预期响应
{
    "status": "healthy",
    "version": "1.0.0",
    "services": {
        "mysql": "up",
        "neo4j": "up",
        "redis": "up",
        "chromadb": "up"
    }
}
```

## MySQL 数据同步

将 MySQL 数据同步到 Neo4j：

```bash
# 全量同步
python scripts/sync_to_neo4j.py --full

# 增量同步
python scripts/sync_to_neo4j.py --incremental --since 2024-01-01T00:00:00
```

## 默认管理员账号

- 用户名: `admin`
- 密码: `admin123`
- 角色: 超级管理员

> 请在首次登录后修改默认密码。

## 项目结构

```
starmap/
├── docs/                    # 项目文档
│   ├── team/               # 团队角色与职责
│   ├── roadmap/            # 开发路线
│   ├── tech/               # 技术文档
│   └── api/                # 接口文档
├── backend/                 # 后端服务
│   ├── app/                # 应用代码
│   │   ├── db/             # 数据库连接
│   │   │   ├── mysql.py          # MySQL 连接封装
│   │   │   ├── neo4j.py          # Neo4j 连接封装
│   │   │   ├── chroma.py         # ChromaDB 连接封装
│   │   │   └── redis.py          # Redis 连接封装
│   │   ├── models/         # 数据模型
│   │   │   └── mysql_models.py   # SQLAlchemy ORM 模型
│   │   └── ...
│   ├── crawler/            # 数据采集
│   ├── scripts/            # 脚本工具
│   │   ├── init_mysql.sql        # MySQL 初始化脚本
│   │   ├── sync_to_neo4j.py      # MySQL → Neo4j 同步脚本
│   │   └── init_database.py      # 数据库初始化工具
│   └── tests/              # 测试
├── frontend/                # 前端应用
│   ├── src/                # 源代码
│   └── public/             # 静态资源
├── frontend-admin/          # 管理端 (React)
├── docker-compose.podman.yml  # Podman 编排配置
└── README.md               # 项目说明
```

## 常见问题排查

### Podman 服务启动失败

**问题**: `podman-compose up` 报错或容器无法启动

**解决方案**:
```bash
# 1. 检查 Podman 虚拟机是否运行
podman machine list

# 2. 如果未运行，启动虚拟机
podman machine start

# 3. 清理并重新启动
podman-compose -f docker-compose.podman.yml down
podman system prune -f  # 清理未使用的镜像和缓存
podman-compose -f docker-compose.podman.yml up -d

# 4. 查看具体错误日志
podman-compose -f docker-compose.podman.yml logs mysql
podman-compose -f docker-compose.podman.yml logs neo4j
```

### 后端启动报错：模块未找到

```bash
cd backend
source venv/bin/activate

# 重新安装依赖
pip install -r requirements.txt

# 如果 chroma-hnswlib 编译失败，安装编译工具
# macOS:
brew install cmake gcc

# 然后重新安装
pip install --no-cache-dir chromadb
```

### 端口被占用

```bash
# 查找占用端口的进程
lsof -i :8000  # 后端端口
lsof -i :5173  # 前端端口
lsof -i :3306  # MySQL 端口
lsof -i :7474  # Neo4j 端口
lsof -i :6379  # Redis 端口
lsof -i :8001  # ChromaDB 端口

# 终止进程
kill -9 <PID>
```

### 数据库连接失败

**检查服务是否运行**:
```bash
podman-compose -f docker-compose.podman.yml ps
# 应该看到 mysql、neo4j、redis、chromadb 都是 healthy 状态
```

**检查环境变量**:
```bash
# 后端默认连接本地数据库，确认以下配置
cat backend/.env
# 应该包含:
# MYSQL_HOST=localhost
# MYSQL_PORT=3306
# MYSQL_USER=starmap
# MYSQL_PASSWORD=starmap123
# MYSQL_DATABASE=starmap
# NEO4J_URI=bolt://localhost:7687
# NEO4J_USER=neo4j
# NEO4J_PASSWORD=starmap123
# REDIS_URL=redis://localhost:6379
# CHROMA_HOST=localhost
# CHROMA_PORT=8001
```

### 构建缓存过大

```bash
# 查看磁盘使用
podman system df

# 清理构建缓存（可释放数GB空间）
podman builder prune -f

# 清理所有未使用资源
podman system prune -a -f
```

## 数据库监控与访问

### 服务状态监控

```bash
# 查看所有容器资源占用
podman stats --no-stream

# 查看容器日志
podman-compose -f docker-compose.podman.yml logs -f mysql
podman-compose -f docker-compose.podman.yml logs -f neo4j
podman-compose -f docker-compose.podman.yml logs -f redis
podman-compose -f docker-compose.podman.yml logs -f chromadb

# 检查服务健康状态
curl http://localhost:8000/health
```

### MySQL 数据库

**命令行访问**:
```bash
# 进入 MySQL 容器
podman exec -it starmap-mysql mysql -u starmap -p starmap
# 密码: starmap123

# 常用查询
SHOW TABLES;
SELECT COUNT(*) FROM persons;
SELECT * FROM persons LIMIT 10;
```

### Neo4j 图数据库

**可视化界面**：
```bash
# 浏览器访问
open http://localhost:7474
```
- 用户名：`neo4j`
- 密码：`starmap123`

**命令行查询**：
```bash
# 进入 Neo4j 容器执行 Cypher 查询
podman exec -it starmap-neo4j cypher-shell -u neo4j -p starmap123

# 常用查询
MATCH (n) RETURN count(n) as nodes;                    # 统计节点数
MATCH ()-[r]->() RETURN count(r) as relations;         # 统计关系数
MATCH (n) RETURN n LIMIT 10;                           # 查看前10个节点
```

### Redis 缓存

**使用 RedisInsight（推荐）**：
```bash
# 安装可视化工具
brew install --cask redisinsight

# 启动后添加连接
# Host: localhost, Port: 6379, Name: starmap-redis
```

**命令行操作**：
```bash
# 进入 Redis 容器
podman exec -it starmap-redis redis-cli

# 常用命令
KEYS *                    # 查看所有键
INFO memory               # 查看内存使用
DBSIZE                    # 查看键数量
```

### ChromaDB 向量数据库

**HTTP API 查询**：
```bash
# 查看集合列表
curl http://localhost:8001/api/v2/tenants/default_tenant/databases/default_database/collections

# 查看集合中的数据
curl http://localhost:8001/api/v2/tenants/default_tenant/databases/default_database/collections/persons

# 向量相似度搜索
curl -X POST http://localhost:8001/api/v2/tenants/default_tenant/databases/default_database/collections/persons/query \
  -H "Content-Type: application/json" \
  -d '{
    "query_embeddings": [[0.1, 0.2, ...]],
    "n_results": 5
  }'
```

**Python 客户端**：
```python
import chromadb

client = chromadb.HttpClient(host="localhost", port=8001)

# 列出所有集合
print(client.list_collections())

# 获取集合并查询
collection = client.get_collection("persons")
results = collection.query(
    query_texts=["周杰伦风格的中国风歌手"],
    n_results=5
)
print(results)
```

**注意**：ChromaDB 没有官方可视化界面，建议使用 Python 客户端或 HTTP API 进行查询。

## 数据库初始化

**当前状态**：数据库服务已启动，但**数据为空**（未初始化）。

### 初始化步骤

```bash
# 1. 确保数据库服务运行
podman-compose -f docker-compose.podman.yml up -d

# 2. 启动后端服务（会自动创建 ChromaDB 集合）
cd backend
source venv/bin/activate
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 3. 导入测试数据（新终端）
cd backend
source venv/bin/activate
python scripts/init_database.py --all

# 或分别初始化
python scripts/init_database.py --mysql       # 仅 MySQL
python scripts/init_database.py --neo4j      # 仅 Neo4j
python scripts/init_database.py --chromadb   # 仅 ChromaDB
python scripts/init_database.py --all --clear # 清空后重新导入
```

### 验证初始化

```bash
# MySQL 表数量（应显示 8 张表 + 2 个视图）
podman exec starmap-mysql mysql -u starmap -p starmap -e "SHOW TABLES;"

# Neo4j 节点数（应显示 13 个节点）
podman exec starmap-neo4j cypher-shell -u neo4j -p starmap123 "MATCH (n) RETURN count(n) as nodes;"

# Redis 键数量（应为 0 或少量缓存）
podman exec starmap-redis redis-cli dbsize

# ChromaDB 集合（应显示 persons 集合有 8 条向量）
curl http://localhost:8001/api/v2/tenants/default_tenant/databases/default_database/collections
```

### 后台账号密码

| 服务 | 地址 | 账号 | 密码 | 说明 |
|------|------|------|------|------|
| **MySQL** | localhost:3306 | `starmap` | `starmap123` | 数据库连接 |
| **Neo4j** | http://localhost:7474 | `neo4j` | `starmap123` | 图数据库管理界面 |
| **Redis** | localhost:6379 | - | - | 本地开发无密码 |
| **ChromaDB** | http://localhost:8001 | - | - | 本地开发无认证 |
| **后端 API** | http://localhost:8000 | - | - | 开发环境无认证 |
| **前端（用户端）** | http://localhost:5173 | - | - | 无需登录 |
| **前端（管理端）** | http://localhost:5174 | `admin` | `admin123` | 演示账号 |

### 服务端口一览

| 服务 | 端口 | 用途 |
|------|------|------|
| MySQL | 3306 | 关系型数据库 |
| 后端 API | 8000 | FastAPI 服务 |
| Neo4j HTTP | 7474 | 图数据库浏览器 |
| Neo4j Bolt | 7687 | 图数据库驱动连接 |
| Redis | 6379 | 缓存服务 |
| ChromaDB | 8001 | 向量数据库 API |
| 前端（用户端） | 5173 | Vite 开发服务器 |
| 前端（管理端） | 5174 | Vite 开发服务器 |

## 开发团队

详见 [docs/team/README.md](docs/team/README.md)

## 开发路线

详见 [docs/roadmap/README.md](docs/roadmap/README.md)

## 技术文档

- [架构设计](docs/tech/architecture.md)
- [数据模型](docs/tech/data-model.md)
- [MySQL 实施总结](docs/mysql-integration-summary.md)

## 项目看板

详见 [docs/project-board.md](docs/project-board.md)

## 决策记录

详见 [docs/DECISIONS.md](docs/DECISIONS.md)
