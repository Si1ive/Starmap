# 408考研智能学习平台

## 项目简介

408考研智能学习平台是一个基于 RAG（检索增强生成）的结构化学习系统，专为计算机考研 408 学科打造。系统将教材 PDF 解析入库，按大纲结构化组织知识点，提供智能问答、刷题练习等功能。

**核心差异化：** 不是简单的 PDF + ChatGPT，而是按 408 大纲结构化组织的知识库，带难度/考频标签、关联知识点、练习题。

## 覆盖学科

| 学科 | 408分值 | 内容 |
|------|---------|------|
| 数据结构 | ~45分 | 线性表、树与二叉树、图、查找、排序等 |
| 计算机组成原理 | ~45分 | 数据表示、存储器、指令系统、CPU、总线、I/O |
| 操作系统 | ~35分 | 进程管理、内存管理、文件管理、I/O管理 |
| 计算机网络 | ~25分 | 物理层、数据链路层、网络层、传输层、应用层 |

## 核心功能

- **结构化知识库**：按大纲章节组织，带难度、考频标签
- **RAG 智能问答**：基于向量检索的精准回答，附带来源引用
- **刷题系统**：真题 + 练习题，支持选择/填空/判断/简答/设计/分析题型
- **PDF 自动入库**：将王道/天勤教材 PDF 自动解析为结构化知识点
- **管理后台**：知识点/题目管理、数据质量校正

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design + ECharts |
| 后端 | FastAPI (Python 3.11) |
| RAG | LangChain + OpenAI GPT-4 + ChromaDB 向量检索 |
| 主数据库 | MySQL 8.0 - 学科/章节/知识点/题目 |
| 图数据库 | Neo4j 5.x - 知识点关联关系 |
| 向量数据库 | ChromaDB - 语义搜索 |
| 缓存 | Redis - 会话与热点数据 |
| 爬虫服务 | Scrapy 2.x - PDF 解析 + 网页爬取 |
| 部署 | Podman + Podman Compose |

## 数据库架构

本项目采用 **MySQL + Neo4j + ChromaDB + Redis** 多数据库架构：

- **MySQL** (主存储): 学科、章节、知识点、题目、做题记录、管理员用户
- **Neo4j** (图数据库): 知识点关联关系（前置依赖、相似、对比）
- **ChromaDB** (向量数据库): 知识点向量嵌入，支持语义搜索
- **Redis** (缓存): 会话状态、搜索结果缓存

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Podman + podman-compose

### 1. 克隆项目

```bash
git clone <repo-url>
cd my-agent
```

### 2. 安装 Podman（macOS）

```bash
brew install podman podman-compose
podman machine init
podman machine start
```

### 3. 启动基础设施（Podman）

```bash
# 启动 MySQL + Neo4j + Redis + ChromaDB + Scrapy Service
podman-compose -f docker-compose.podman.yml up -d

# 查看服务状态
podman-compose -f docker-compose.podman.yml ps
```

### 4. 初始化数据库

```bash
# 执行 408 平台建表 + 种子数据
podman exec -i starmap-mysql mysql -u starmap -p starmap < backend/scripts/init_408_tables.sql
# 密码: starmap123
```

### 5. 启动后端服务

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 配置 OpenAI API Key
echo "OPENAI_API_KEY=your-api-key" >> .env

# 启动服务
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端服务：
- API 地址: http://localhost:8000
- API 文档: http://localhost:8000/docs

### 6. 启动前端管理端

```bash
cd frontend-admin
npm install
npm run dev
```

管理端地址: http://localhost:5174

## PDF 数据入库

将王道/天勤教材 PDF 解析为结构化知识点：

```bash
# 通过管理后台触发 PDF 解析任务
# 或直接运行 Scrapy spider
cd backend/scrapy_service
scrapy crawl knowledge \
    -a pdf_path=/path/to/book.pdf \
    -a subject_id=subj_ds \
    -a chapter_id=ch_ds_01 \
    -a source="王道2025/数据结构"
```

## 项目结构

```
my-agent/
├── docs/                         # 项目文档
│   ├── tech/                    # 技术文档
│   ├── admin/                   # 管理端文档
│   ├── api/                     # 接口文档
│   └── roadmap/                 # 开发路线
├── backend/                      # 后端服务
│   ├── app/                     # FastAPI 应用
│   │   ├── api/admin.py         # 管理端 API
│   │   ├── api/chat.py          # 对话 API
│   │   ├── db/chroma.py         # ChromaDB 客户端
│   │   ├── models/mysql_models.py  # SQLAlchemy 模型
│   │   └── services/chat_service.py  # RAG 对话服务
│   ├── scrapy_service/          # Scrapy 爬虫服务
│   │   ├── starmap_scrapy/
│   │   │   ├── spiders/
│   │   │   │   └── knowledge_spider.py  # PDF 解析 spider
│   │   │   ├── items.py         # Scrapy Item 定义
│   │   │   └── pipelines/storage.py   # 数据存储 pipeline
│   │   └── requirements.txt
│   └── scripts/
│       └── init_408_tables.sql  # 408 平台建表脚本
├── frontend-admin/               # 管理端前端
│   └── src/
│       ├── pages/
│       │   ├── Dashboard/       # 看板
│       │   ├── Knowledge/       # 知识点管理
│       │   ├── Question/        # 题目管理
│       │   └── Conversation/    # 问答对话
│       └── api/
├── docker-compose.podman.yml     # Podman 编排配置
└── README.md
```

## 默认账号

| 服务 | 地址 | 账号 | 密码 |
|------|------|------|------|
| MySQL | localhost:3306 | `starmap` | `starmap123` |
| Neo4j | http://localhost:7474 | `neo4j` | `starmap123` |
| Redis | localhost:6379 | - | - |
| ChromaDB | http://localhost:8001 | - | - |
| 管理端 | http://localhost:5174 | `admin` | `admin123` |

## 服务端口

| 服务 | 端口 | 用途 |
|------|------|------|
| MySQL | 3306 | 关系型数据库 |
| Neo4j HTTP | 7474 | 图数据库浏览器 |
| Neo4j Bolt | 7687 | 图数据库驱动连接 |
| Redis | 6379 | 缓存服务 |
| ChromaDB | 8001 | 向量数据库 API |
| Scrapy Service | - | 爬虫消费进程（无对外端口） |
| 后端 API | 8000 | FastAPI 服务 |
| 管理端前端 | 5174 | Vite 开发服务器 |

## API 接口

### 知识点管理

```
GET    /api/v1/admin/knowledge/points       # 知识点列表
GET    /api/v1/admin/knowledge/points/{id}  # 知识点详情
PUT    /api/v1/admin/knowledge/points/{id}  # 编辑知识点
```

### 题目管理

```
GET    /api/v1/admin/questions              # 题目列表
GET    /api/v1/admin/questions/{id}         # 题目详情
PUT    /api/v1/admin/questions/{id}         # 编辑题目
```

### 学科/章节

```
GET    /api/v1/admin/subjects               # 学科列表
GET    /api/v1/admin/subjects/{id}/chapters # 章节列表
```

### 智能问答

```
POST   /api/v1/chat                         # RAG 问答
GET    /api/v1/chat/history/{session_id}    # 对话历史
DELETE /api/v1/chat/session/{session_id}    # 清除会话
```

### 看板统计

```
GET    /api/v1/admin/dashboard/stats        # 统计数据
GET    /api/v1/admin/dashboard/charts       # 图表数据
```

## 技术文档

- [架构设计](docs/tech/architecture.md)
- [数据模型](docs/tech/data-model.md)
- [部署指南](docs/tech/deployment.md)
- [API 接口文档](docs/api/README.md)

## 常见问题

### 爬虫任务无响应

```bash
# 检查 scrapy-service 是否运行
podman-compose -f docker-compose.podman.yml ps scrapy-service

# 查看日志
podman-compose -f docker-compose.podman.yml logs scrapy-service
```

### RAG 问答无回答

```bash
# 1. 检查 OPENAI_API_KEY 是否配置
cat backend/.env | grep OPENAI

# 2. 检查 ChromaDB 是否有数据
curl http://localhost:8001/api/v1/collections

# 3. 检查后端日志
podman-compose -f docker-compose.podman.yml logs backend
```

### 端口被占用

```bash
lsof -i :8000  # 后端
lsof -i :5174  # 管理端
kill -9 <PID>
```

## 决策记录

详见 [docs/DECISIONS.md](docs/DECISIONS.md)
