# StarMap 后端架构设计

## 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway                               │
│                    (FastAPI + Uvicorn)                           │
├─────────────┬─────────────┬─────────────┬───────────────────────┤
│   查询接口   │   对话接口   │   人物接口   │      推荐接口         │
│  /persons/   │   /chat     │  /persons/   │    /persons/similar  │
│   search     │             │   {id}       │                      │
├─────────────┴─────────────┴─────────────┴───────────────────────┤
│                      Service Layer                               │
│         PersonService        │        ChatService                │
├──────────────────────────────┼───────────────────────────────────┤
│         Cache Layer          │        Session Layer              │
│         (Redis)              │        (Redis)                    │
├──────────────────────────────┴───────────────────────────────────┤
│                      Data Access Layer                           │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│   │    Neo4j     │  │   ChromaDB   │  │       Redis          │ │
│   │  (图数据库)   │  │  (向量数据库) │  │      (缓存)           │ │
│   │  人物关系图谱 │  │  语义搜索    │  │   会话/搜索结果缓存   │ │
│   └──────────────┘  └──────────────┘  └──────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                      Agent Core                                  │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│   │IntentRecognizer│ │ ToolRegistry │  │ ResponseGenerator    │ │
│   │   意图识别     │  │   工具注册   │  │    回答生成          │ │
│   └──────────────┘  └──────────────┘  └──────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                      LLM Layer                                   │
│              OpenAI GPT-4 / GPT-3.5                             │
└─────────────────────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| Web框架 | FastAPI | 0.100+ | API服务 |
| 服务器 | Uvicorn | 0.23+ | ASGI服务器 |
| 数据验证 | Pydantic | 2.0+ | 模型验证 |
| 图数据库 | Neo4j | 5.11+ | 人物关系存储 |
| 向量数据库 | ChromaDB | 0.4.6+ | 语义搜索 |
| 缓存 | Redis | 7.0+ | 会话/结果缓存 |
| 日志 | structlog | 23.0+ | 结构化日志 |
| 测试 | pytest | 7.4+ | 单元测试 |

## 项目结构

```
backend/
├── app/
│   ├── main.py              # FastAPI入口，生命周期管理
│   ├── config.py            # 配置管理（环境变量）
│   ├── api/                 # API路由层
│   │   ├── query.py         # 查询接口 (/persons/search)
│   │   ├── chat.py          # 对话接口 (/chat)
│   │   ├── person.py        # 人物接口 (/persons/{id})
│   │   └── recommend.py     # 推荐接口 (/persons/{id}/similar)
│   ├── agent/               # Agent核心（Week 2实现）
│   │   ├── intent.py        # 意图识别
│   │   ├── tools.py         # 工具定义
│   │   ├── query_builder.py # 查询构建
│   │   ├── response.py      # 回答生成
│   │   └── conversation.py  # 对话管理
│   ├── core/                # 核心组件
│   │   ├── session.py       # Session管理
│   │   ├── cache.py         # 缓存封装
│   │   └── logging.py       # 日志配置
│   ├── db/                  # 数据库连接层
│   │   ├── neo4j.py         # Neo4j连接封装
│   │   ├── chroma.py        # ChromaDB连接封装
│   │   └── redis.py         # Redis连接封装
│   ├── models/              # 数据模型（Pydantic）
│   │   ├── person.py        # 人物模型
│   │   └── transaction.py   # 对话/事务模型
│   ├── services/            # 业务服务层
│   │   ├── person_service.py # 人物服务
│   │   └── chat_service.py  # 对话服务
│   └── middleware/          # 中间件
│       └── error_handler.py # 全局错误处理
├── tests/                   # 测试
│   ├── test_api.py          # API接口测试
│   ├── test_services.py     # 服务层测试
│   ├── test_neo4j.py        # Neo4j测试
│   └── test_redis.py        # Redis测试
├── requirements.txt         # 依赖
└── pytest.ini              # 测试配置
```

## 核心设计模式

### 1. 依赖注入

使用FastAPI的`Depends`实现服务层依赖注入：

```python
async def get_person_detail(
    person_id: str,
    service: PersonService = Depends(get_person_service)
):
    return await service.get_person_by_id(person_id)
```

### 2. 降级模式（Graceful Degradation）

当数据库不可用时，服务自动降级：

- **Neo4j不可用**：返回Mock数据，保证API可用
- **Redis不可用**：跳过缓存，直接查询数据库
- **所有数据库不可用**：返回基础Mock响应

### 3. 缓存策略

| 数据类型 | 缓存位置 | TTL | 说明 |
|---------|---------|-----|------|
| 人物详情 | Redis | 1小时 | 频繁访问的人物 |
| 搜索结果 | Redis | 5分钟 | 搜索关键词缓存 |
| 关系图谱 | Redis | 10分钟 | 人物关系网络 |
| 会话状态 | Redis | 1小时 | 对话上下文 |
| LLM响应 | Redis | 30分钟 | 相同问题缓存 |

### 4. 错误处理

统一错误响应格式：

```json
{
  "code": "ERROR_CODE",
  "message": "用户友好的错误信息",
  "request_id": "uuid"
}
```

异常类型：
- `NotFoundException`: 404资源不存在
- `ValidationException`: 422参数验证失败
- `DatabaseException`: 503数据库服务不可用
- `LLMException`: 503 AI服务不可用

## 数据库设计

### Neo4j 图模型

```cypher
// 人物节点
(:Person {
  id: string,
  name: string,
  category: string,
  description: string,
  nationality: string,
  birth_date: string,
  avatar_url: string,
  aliases: [string]
})

// 关系
(:Person)-[:SPOUSE]->(:Person)
(:Person)-[:COLLABORATOR]->(:Person)
(:Person)-[:FRIEND]->(:Person)
(:Person)-[:FAMILY]->(:Person)
```

### ChromaDB 集合

| 集合名称 | 用途 | 元数据 |
|---------|------|--------|
| persons | 人物向量嵌入 | person_id, name, category |
| relations | 关系描述 | relation_type, source, target |
| knowledge | 知识库 | source, type |

### Redis 键规范

```
starmap:person:{person_id}     # 人物详情
starmap:search:{query_hash}    # 搜索结果
starmap:relation:{person_id}:{depth}  # 关系图谱
starmap:session:{session_id}   # 会话状态
starmap:llm:{query_hash}       # LLM响应
```

## 性能指标

| 场景 | 目标 | 优化策略 |
|------|------|---------|
| 简单查询 | < 500ms | Redis缓存 |
| 复杂查询（多跳） | < 2s | Neo4j索引 + 缓存 |
| Agent对话 | < 3s | LLM缓存 + 异步 |
| 首次连接Neo4j | < 100ms | 连接池 |
| 缓存命中 | < 10ms | Redis内存存储 |

## 安全设计

1. **CORS配置**: 限制允许的源
2. **请求追踪**: 每个请求分配唯一ID
3. **参数验证**: Pydantic模型自动验证
4. **错误隐藏**: 生产环境不暴露内部错误详情
5. **敏感信息**: API密钥通过环境变量配置

## 部署架构

```
┌─────────────────────────────────────────┐
│              Docker Compose              │
│  ┌─────────┐ ┌─────────┐ ┌───────────┐ │
│  │ Backend │ │ Neo4j   │ │  Redis    │ │
│  │ :8000   │ │ :7474   │ │  :6379    │ │
│  │         │ │ :7687   │ │           │ │
│  └─────────┘ └─────────┘ └───────────┘ │
│  ┌─────────┐ ┌─────────┐               │
│  │ ChromaDB│ │ Frontend│               │
│  │ :8001   │ │ :5173   │               │
│  └─────────┘ └─────────┘               │
└─────────────────────────────────────────┘
```

## 扩展计划

### Week 2: Agent核心
- 集成OpenAI API
- 实现意图识别模块
- 实现Function Calling框架
- 完善对话流程

### Week 3: 增强功能
- Session管理完善
- 多轮对话支持
- 上下文传递
- 性能优化

### Week 4-5: 扩展
- 时间线API
- 限流与熔断
- 部署脚本
