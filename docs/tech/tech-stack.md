# 技术选型详细说明

## 前端技术栈

### React 18

**选型理由：**
- 生态最成熟，组件库丰富
- Concurrent Features提升性能
- 团队熟悉度高

**版本：** 18.2.0

**关键特性使用：**
- Functional Components + Hooks
- Suspense for Data Fetching
- React.memo优化渲染

### TypeScript 5

**选型理由：**
- 类型安全，减少运行时错误
- IDE支持好，开发体验佳
- 便于团队协作和重构

**配置要点：**
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  }
}
```

### Vite 4

**选型理由：**
- 启动速度极快（比Webpack快10-100倍）
- 原生ESM，开发体验好
- 内置TypeScript支持

**配置：**
```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: true
  }
});
```

### Ant Design 5

**选型理由：**
- 企业级UI组件库，功能完整
- 支持主题定制
- 中文文档完善

**主题配置：**
```typescript
// src/theme.ts
import { theme } from 'antd';

export const customTheme = {
  token: {
    colorPrimary: '#1890ff',
    borderRadius: 6,
    fontSize: 14
  }
};
```

### Zustand 4

**选型理由：**
- 轻量（1KB）
- API简单，学习成本低
- 支持TypeScript

**使用示例：**
```typescript
// src/store/index.ts
import { create } from 'zustand';

interface AppState {
  currentPerson: Person | null;
  setCurrentPerson: (person: Person | null) => void;
  searchHistory: string[];
  addSearchHistory: (query: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentPerson: null,
  setCurrentPerson: (person) => set({ currentPerson: person }),
  searchHistory: [],
  addSearchHistory: (query) =>
    set((state) => ({
      searchHistory: [...state.searchHistory, query]
    }))
}));
```

### D3.js 7

**选型理由：**
- 可视化领域标准
- 力导向图支持好
- 灵活性高

**使用场景：**
- 人物关系图谱
- 时间线可视化
- 统计图表

---

## 后端技术栈

### FastAPI 0.100

**选型理由：**
- 高性能（基于Starlette）
- 自动API文档（Swagger/ReDoc）
- 原生异步支持
- 类型提示驱动

**核心配置：**
```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="StarMap API",
    description="408考研智能学习平台",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 路由注册
from app.api import query, chat, person, recommend
app.include_router(query.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(person.router, prefix="/api/v1")
app.include_router(recommend.router, prefix="/api/v1")
```

### LangChain 0.0.300

**选型理由：**
- LLM应用开发框架
- 支持多种LLM（OpenAI、文心等）
- 内置Chain和Agent模式
- 社区活跃

**核心使用：**
```python
from langchain import OpenAI, LLMChain, PromptTemplate
from langchain.agents import Tool, AgentExecutor, initialize_agent

# 定义工具
tools = [
    Tool(
        name="KnowledgeGraph",
        func=query_neo4j,
        description="查询知识图谱获取人物信息"
    )
]

# 初始化Agent
agent = initialize_agent(
    tools,
    OpenAI(temperature=0),
    agent="zero-shot-react-description",
    verbose=True
)
```

### Neo4j 5

**选型理由：**
- 原生图数据库，关系查询高效
- Cypher查询语言直观
- 支持向量索引（用于相似度）
- 社区版免费

**图模型设计：**
```cypher
// 节点类型
(:Person {id, name, name_en, birth_date, ...})
(:Work {id, title, type, year, ...})
(:Company {id, name, ...})
(:Award {id, name, year, ...})

// 关系类型
(:Person)-[:ACTED_IN]->(:Work)
(:Person)-[:DIRECTED]->(:Work)
(:Person)-[:SINGS]->(:Work)
(:Person)-[:MARRIED_TO]->(:Person)
(:Person)-[:COLLABORATED_WITH]->(:Person)
(:Person)-[:WORKS_FOR]->(:Company)
(:Person)-[:WON]->(:Award)
```

### ChromaDB 0.4

**选型理由：**
- 轻量级向量数据库
- 支持嵌入模型
- 本地运行，无需服务器
- 与LangChain集成好

**使用场景：**
- 人物描述语义检索
- 相似人物推荐
- 对话上下文检索

### Redis 7

**选型理由：**
- 高性能缓存
- 支持多种数据结构
- 持久化选项
- 会话存储

**使用场景：**
- API响应缓存
- 会话状态存储
- 限流计数器
- 热点数据缓存

---

## LLM选型

### 主模型：OpenAI GPT-4

**选型理由：**
- 能力强，理解准确
- Function Calling支持好
- 中文表现优秀

**配置：**
```python
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 对话模型
chat_model = "gpt-4"

# 意图识别（可用更便宜的模型）
intent_model = "gpt-3.5-turbo"
```

**成本估算：**
- GPT-4：$0.03/1K tokens (input), $0.06/1K tokens (output)
- 平均每次对话：~500 tokens
- 预估月成本（1000次对话）：~$45

### 备用模型：文心一言

**选型理由：**
- 国内访问稳定
- 成本可能更低
- 合规性更好

**切换方式：**
```python
# 通过环境变量切换
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai / baidu

if LLM_PROVIDER == "openai":
    from langchain.llms import OpenAI
    llm = OpenAI()
elif LLM_PROVIDER == "baidu":
    from langchain.llms import Wenxin
    llm = Wenxin()
```

---

## 部署技术栈

### Docker

**选型理由：**
- 环境一致性
- 便于部署和扩展
- 开发体验好

### Docker Compose

**编排服务：**
- backend (FastAPI)
- frontend (Nginx)
- neo4j
- redis
- chromadb

---

## 开发工具

### 代码质量

| 工具 | 用途 | 配置 |
|------|------|------|
| Black | Python格式化 | 行长度100 |
| isort | Python导入排序 | black兼容 |
| flake8 | Python代码检查 | 配合black |
| ESLint | TypeScript检查 | recommended |
| Prettier | 前端格式化 | 2空格缩进 |

### 测试

| 工具 | 用途 |
|------|------|
| pytest | Python单元测试 |
| pytest-asyncio | 异步测试 |
| Vitest | 前端单元测试 |
| React Testing Library | React组件测试 |

### 文档

| 工具 | 用途 |
|------|------|
| Swagger UI | API文档自动生成 |
| ReDoc | 替代API文档 |
| Markdown | 项目文档 |
