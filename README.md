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
| 前端 | React 18 + TypeScript + Vite |
| 后端 | FastAPI (Python 3.11) |
| Agent | LangChain + OpenAI GPT-4 |
| 知识图谱 | Neo4j |
| 向量数据库 | ChromaDB |
| 缓存 | Redis |
| 部署 | Docker + Docker Compose |

## 快速开始

```bash
# 1. 克隆项目
git clone <repo-url>
cd starmap

# 2. 启动基础设施
docker-compose up -d

# 3. 安装后端依赖
cd backend && pip install -r requirements.txt

# 4. 运行后端
uvicorn app.main:app --reload

# 5. 安装前端依赖
cd ../frontend && npm install

# 6. 运行前端
npm run dev
```

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
│   ├── crawler/            # 数据采集
│   └── tests/              # 测试
├── frontend/                # 前端应用
│   ├── src/                # 源代码
│   └── public/             # 静态资源
├── docker-compose.yml       # Docker编排
└── README.md               # 项目说明
```

## 开发团队

详见 [docs/team/README.md](docs/team/README.md)

## 开发路线

详见 [docs/roadmap/README.md](docs/roadmap/README.md)

## 技术文档

详见 [docs/tech/README.md](docs/tech/README.md)

## 接口文档

详见 [docs/api/README.md](docs/api/README.md)
