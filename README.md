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
| 部署 | Docker + Docker Compose |

## 数据库架构

本项目采用 **MySQL + Neo4j + ChromaDB + Redis** 多数据库架构：

- **MySQL** (主存储): 人物属性、作品信息、爬虫任务/日志、管理员用户、审计日志
- **Neo4j** (图数据库): 人物关系网络、图遍历查询
- **ChromaDB** (向量数据库): 语义搜索、向量嵌入
- **Redis** (缓存): 会话状态、搜索结果缓存

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
├── docker-compose.yml       # Docker编排
└── README.md               # 项目说明
```

## 快速开始

### 1. 启动数据库服务

```bash
# 启动 MySQL + Neo4j + Redis + ChromaDB
docker-compose up -d mysql neo4j redis chromadb
```

### 2. 初始化 MySQL 数据库

```bash
# 自动创建表结构和默认管理员账号
cd backend
python scripts/init_database.py --all
```

### 3. 安装后端依赖

```bash
cd backend && pip install -r requirements.txt
```

### 4. 运行后端

```bash
uvicorn app.main:app --reload
```

### 5. 安装前端依赖

```bash
cd ../frontend && npm install
```

### 6. 运行前端

```bash
npm run dev
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
