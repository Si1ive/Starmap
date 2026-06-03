# 技术文档

## 目录

- [技术选型](./tech-stack.md) - 完整技术栈说明
- [数据模型](./data-model.md) - 知识图谱数据模型
- [架构设计](./architecture.md) - 系统架构详细设计
- [部署指南](./deployment.md) - 部署与运维

---

## 快速参考

### 技术栈总览

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 前端框架 | React | 18.2 | UI构建 |
| 前端语言 | TypeScript | 5.0 | 类型安全 |
| 构建工具 | Vite | 4.0 | 快速构建 |
| UI组件库 | Ant Design | 5.0 | 组件复用 |
| 状态管理 | Zustand | 4.3 | 状态管理 |
| 可视化 | D3.js | 7.8 | 关系图谱 |
| 后端框架 | FastAPI | 0.100 | API服务 |
| 后端语言 | Python | 3.11 | 业务逻辑 |
| Agent框架 | LangChain | 0.0.300 | LLM应用 |
| LLM | OpenAI GPT-4 | - | 自然语言处理 |
| 图数据库 | Neo4j | 5.x | 知识图谱存储 |
| 向量数据库 | ChromaDB | 0.4 | 语义检索 |
| 缓存 | Redis | 7.0 | 数据缓存 |
| 部署 | Docker | 24.0 | 容器化 |
| 编排 | Docker Compose | 2.20 | 多容器管理 |

### 开发环境要求

```bash
# 必需
Docker >= 24.0
Docker Compose >= 2.20
Node.js >= 18.0
Python >= 3.11

# 推荐
VSCode + 以下插件
- ESLint
- Prettier
- Python
- Docker
- GitLens
```

### 环境变量

```bash
# 后端 (.env)
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=starmap123
REDIS_URL=redis://localhost:6379
CHROMA_HOST=localhost
CHROMA_PORT=8000

# 前端 (.env)
VITE_API_BASE_URL=http://localhost:8000
```

### 端口分配

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端开发服务器 | 5173 | Vite默认 |
| 后端API | 8000 | FastAPI默认 |
| Neo4j HTTP | 7474 | 浏览器访问 |
| Neo4j Bolt | 7687 | 驱动连接 |
| Redis | 6379 | 默认端口 |
| ChromaDB | 8001 | 避免与FastAPI冲突 |

### 关键依赖版本

```txt
# 后端 (requirements.txt)
fastapi==0.100.0
uvicorn[standard]==0.23.0
langchain==0.0.300
openai==0.27.8
neo4j==5.11.0
chromadb==0.4.6
redis==4.6.0
pydantic==2.0.0
python-dotenv==1.0.0
requests==2.31.0
beautifulsoup4==4.12.0
pytest==7.4.0
pytest-asyncio==0.21.0
httpx==0.24.0

# 前端 (package.json)
"react": "^18.2.0"
"react-dom": "^18.2.0"
"typescript": "^5.0.0"
"vite": "^4.0.0"
"antd": "^5.0.0"
"zustand": "^4.3.0"
"d3": "^7.8.0"
"react-router-dom": "^6.0.0"
"axios": "^1.4.0"
"@types/d3": "^7.4.0"
```

---

## 项目结构

```
starmap/
├── docs/                          # 文档
│   ├── team/                      # 团队角色
│   ├── roadmap/                   # 开发路线
│   ├── tech/                      # 技术文档
│   └── api/                       # 接口文档
│
├── backend/                       # 后端服务
│   ├── app/                       # 应用代码
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI入口
│   │   ├── config.py             # 配置管理
│   │   ├── api/                  # API路由
│   │   │   ├── __init__.py
│   │   │   ├── query.py          # 查询接口
│   │   │   ├── chat.py           # 对话接口
│   │   │   ├── person.py         # 人物接口
│   │   │   └── recommend.py      # 推荐接口
│   │   ├── agent/                # Agent核心
│   │   │   ├── __init__.py
│   │   │   ├── intent.py         # 意图识别
│   │   │   ├── tools.py          # 工具定义
│   │   │   ├── query_builder.py  # 查询构建
│   │   │   ├── response.py       # 回答生成
│   │   │   └── conversation.py   # 对话管理
│   │   ├── core/                 # 核心组件
│   │   │   ├── __init__.py
│   │   │   ├── session.py        # Session管理
│   │   │   ├── cache.py          # 缓存封装
│   │   │   └── logging.py        # 日志配置
│   │   ├── db/                   # 数据库层
│   │   │   ├── __init__.py
│   │   │   ├── neo4j.py          # Neo4j连接
│   │   │   ├── chroma.py         # ChromaDB连接
│   │   │   └── redis.py          # Redis连接
│   │   ├── models/               # 数据模型
│   │   │   ├── __init__.py
│   │   │   ├── person.py         # 人物模型
│   │   │   ├── work.py           # 作品模型
│   │   │   └── transaction.py    # 交易记录
│   │   └── services/             # 业务服务
│   │       ├── __init__.py
│   │       ├── person_service.py
│   │       └── chat_service.py
│   ├── crawler/                   # 数据采集
│   │   ├── __init__.py
│   │   ├── base.py               # 爬虫基类
│   │   ├── wikipedia.py          # 维基百科爬虫
│   │   ├── parser.py             # HTML解析
│   │   ├── cleaner.py            # 数据清洗
│   │   ├── ner.py                # 实体识别
│   │   ├── relation.py           # 关系抽取
│   │   └── entity_linking.py     # 实体链接
│   ├── scripts/                   # 脚本
│   │   ├── import_neo4j.py       # 导入Neo4j
│   │   └── init_data.py          # 初始化数据
│   ├── tests/                     # 测试
│   │   ├── __init__.py
│   │   ├── test_api.py
│   │   ├── test_agent.py
│   │   └── test_crawler.py
│   ├── requirements.txt           # Python依赖
│   ├── Dockerfile                 # 后端镜像
│   └── pytest.ini                # 测试配置
│
├── frontend/                      # 前端应用
│   ├── public/                    # 静态资源
│   ├── src/                       # 源代码
│   │   ├── main.tsx              # 入口
│   │   ├── App.tsx               # 根组件
│   │   ├── router/               # 路由
│   │   │   └── index.tsx
│   │   ├── pages/                # 页面
│   │   │   ├── Search/           # 搜索页
│   │   │   ├── Person/           # 人物详情
│   │   │   ├── Chat/             # 对话页
│   │   │   ├── Graph/            # 关系图谱
│   │   │   └── Browse/           # 领域浏览
│   │   ├── components/           # 组件
│   │   │   ├── Layout/           # 布局
│   │   │   ├── SearchBox/        # 搜索框
│   │   │   ├── PersonCard/       # 人物卡片
│   │   │   ├── Message/          # 消息组件
│   │   │   ├── ForceGraph/       # 力导向图
│   │   │   └── Timeline/         # 时间线
│   │   ├── api/                  # API封装
│   │   │   └── client.ts
│   │   ├── store/                # 状态管理
│   │   │   └── index.ts
│   │   ├── types/                # TypeScript类型
│   │   │   └── index.ts
│   │   └── utils/                # 工具函数
│   │       └── index.ts
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── Dockerfile               # 前端镜像
│
├── docker-compose.yml            # Docker编排
├── .env.example                  # 环境变量示例
├── .gitignore
└── README.md                     # 项目说明
```

---

## 开发规范

### 代码风格

**Python:**
- 遵循 PEP 8
- 使用 Black 格式化
- 最大行长度 100
- 使用类型注解

**TypeScript:**
- 遵循 ESLint + Prettier
- 使用严格模式
- 接口命名 `I` 前缀（如 `IPerson`）
- 组件命名大驼峰

### Git规范

```bash
# 分支命名
feature/search-api      # 新功能
fix/neo4j-connection    # Bug修复
docs/api-document       # 文档更新
refactor/agent-core     # 重构

# 提交信息
feat: 添加人物搜索API
fix: 修复Neo4j连接超时
docs: 更新接口文档
refactor: 优化查询性能
test: 添加Agent单元测试
```

### 文档规范

- 所有API必须有文档注释
- 复杂逻辑必须有代码注释
- 公共函数必须有 docstring
- 配置变更必须更新文档

---

## 性能指标

| 指标 | 目标 | 测试方法 |
|------|------|---------|
| API响应时间 (P95) | < 2s | k6/Artillery |
| 首屏加载时间 | < 3s | Lighthouse |
| 并发用户数 | ≥ 100 | 压力测试 |
| 数据库查询时间 | < 500ms | 慢查询日志 |
| 缓存命中率 | ≥ 80% | Redis监控 |

---

## 监控与日志

### 日志级别

```python
# DEBUG: 开发调试信息
# INFO: 正常操作信息
# WARNING: 警告信息（如API降级）
# ERROR: 错误信息（如数据库连接失败）
# CRITICAL: 严重错误（如服务不可用）
```

### 关键日志点

- API请求/响应
- 数据库查询
- LLM调用（输入/输出/耗时/Token数）
- 爬虫状态
- 错误堆栈

### 监控指标

- QPS (Queries Per Second)
- 平均响应时间
- 错误率
- LLM Token消耗
- 数据库连接数
- 缓存命中率
