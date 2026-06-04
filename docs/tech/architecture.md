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
│         SyncService          │        CrawlerService             │
├──────────────────────────────┼───────────────────────────────────┤
│         Cache Layer          │        Session Layer              │
│         (Redis)              │        (Redis)                    │
├──────────────────────────────┴───────────────────────────────────┤
│                      Data Access Layer                           │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│   │  MySQL   │  │  Neo4j   │  │ ChromaDB │  │  Redis   │      │
│   │ 主存储    │  │ 关系图谱  │  │ 语义搜索  │  │  缓存    │      │
│   │ 人物/作品 │  │ 人物关系  │  │ 向量嵌入  │  │ 会话数据  │      │
│   │ 爬取日志  │  │ 网络分析  │  │ 相似度   │  │ 热点数据  │      │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| Web框架 | FastAPI | 0.100+ | API服务 |
| 服务器 | Uvicorn | 0.23+ | ASGI服务器 |
| 数据验证 | Pydantic | 2.0+ | 模型验证 |
| 主数据库 | MySQL | 8.0+ | 结构化数据存储 |
| 图数据库 | Neo4j | 5.11+ | 人物关系存储 |
| 向量数据库 | ChromaDB | 0.4.6+ | 语义搜索 |
| 缓存 | Redis | 7.0+ | 会话/结果缓存 |
| ORM | SQLAlchemy | 2.0+ | MySQL ORM |
| 日志 | structlog | 23.0+ | 结构化日志 |
| 测试 | pytest | 7.4+ | 单元测试 |

## 数据库职责划分

| 数据库 | 存储内容 | 查询场景 |
|--------|----------|----------|
| **MySQL** | 人物详情、作品信息、关系数据、爬虫任务/日志、管理员用户 | 列表查询、分页、筛选、CRUD |
| **Neo4j** | 人物节点、作品节点、关系边 | 关系网络、图遍历、最短路径 |
| **ChromaDB** | 人物描述向量、作品描述向量 | 语义搜索、相似度匹配 |
| **Redis** | 会话状态、搜索结果、热点数据 | 缓存读取、会话管理 |

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
│   │   ├── recommend.py     # 推荐接口 (/persons/{id}/similar)
│   │   └── admin/           # 后台管理API
│   │       ├── auth.py      # 认证
│   │       ├── dashboard.py # 看板
│   │       ├── person.py    # 艺人管理
│   │       ├── crawler.py   # 爬虫管理
│   │       └── ...
│   ├── agent/               # Agent核心（Week 2实现）
│   │   ├── intent.py        # 意图识别
│   │   ├── tools.py         # 工具定义
│   │   ├── query_builder.py # 查询构建
│   │   ├── response.py      # 回答生成
│   │   └── conversation.py  # 对话管理
│   ├── core/                # 核心组件
│   │   ├── session.py       # Session管理
│   │   ├── cache.py         # 缓存封装
│   │   ├── logging.py       # 日志配置
│   │   └── auth.py          # JWT认证
│   ├── db/                  # 数据库连接层
│   │   ├── mysql.py         # MySQL连接封装（SQLAlchemy）
│   │   ├── neo4j.py         # Neo4j连接封装
│   │   ├── chroma.py        # ChromaDB连接封装
│   │   └── redis.py         # Redis连接封装
│   ├── models/              # 数据模型（Pydantic + SQLAlchemy）
│   │   ├── person.py        # 人物模型
│   │   ├── work.py          # 作品模型
│   │   ├── relation.py      # 关系模型
│   │   ├── crawler.py       # 爬虫模型
│   │   └── transaction.py   # 对话/事务模型
│   ├── services/            # 业务服务层
│   │   ├── person_service.py # 人物服务
│   │   ├── chat_service.py  # 对话服务
│   │   ├── crawler_service.py # 爬虫服务
│   │   └── sync_service.py  # 数据同步服务
│   └── middleware/          # 中间件
│       ├── error_handler.py # 全局错误处理
│       ├── audit.py         # 审计日志
│       └── rate_limit.py    # 限流
├── scripts/                 # 脚本
│   ├── import_mysql.py      # 导入数据到MySQL
│   ├── sync_to_neo4j.py     # 同步MySQL到Neo4j
│   ├── init_database.py     # 初始化数据库
│   └── backup_data.py       # 数据备份
├── tests/                   # 测试
│   ├── test_api.py          # API接口测试
│   ├── test_services.py     # 服务层测试
│   ├── test_mysql.py        # MySQL测试
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

### 2. 数据访问模式

```python
# 查询人物列表 → MySQL
async def list_persons(filter: PersonFilter) -> List[Person]:
    return await mysql_service.query_persons(filter)

# 查询人物关系 → Neo4j
async def get_person_relations(person_id: str) -> RelationNetwork:
    return await neo4j_service.get_relations(person_id)

# 语义搜索 → ChromaDB
async def search_persons_semantic(query: str) -> List[Person]:
    return await chroma_service.similarity_search(query)
```

### 3. 降级模式（Graceful Degradation）

当数据库不可用时，服务自动降级：

- **MySQL不可用**：返回Redis缓存，缓存不存在返回错误
- **Neo4j不可用**：返回MySQL中的基础关系数据
- **ChromaDB不可用**：降级为MySQL全文搜索
- **Redis不可用**：跳过缓存，直接查询数据库
- **所有数据库不可用**：返回基础Mock响应

### 4. 缓存策略

| 数据类型 | 缓存位置 | TTL | 说明 |
|---------|---------|-----|------|
| 人物详情 | Redis | 1小时 | 频繁访问的人物 |
| 人物列表 | Redis | 5分钟 | 搜索列表缓存 |
| 搜索结果 | Redis | 5分钟 | 搜索关键词缓存 |
| 关系图谱 | Redis | 10分钟 | 人物关系网络 |
| 会话状态 | Redis | 1小时 | 对话上下文 |
| LLM响应 | Redis | 30分钟 | 相同问题缓存 |
| 爬取统计 | Redis | 1分钟 | 实时统计 |

### 5. MySQL ↔ Neo4j 同步

```python
# 关系创建时同步到Neo4j
async def create_relation(relation: RelationCreate):
    # 1. 写入MySQL（主存储）
    relation_id = await mysql.create_relation(relation)
    
    # 2. 同步到Neo4j（图数据库）
    try:
        await neo4j.merge_relation(
            source=relation.source_id,
            target=relation.target_id,
            type=relation.relation_type,
            properties=relation.properties
        )
    except Exception as e:
        # 同步失败，记录到队列稍后重试
        await sync_queue.add_failed_sync("relation", relation_id)
        logger.error(f"Neo4j sync failed: {e}")
    
    return relation_id
```

### 6. 错误处理

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

### MySQL 表结构

详见 [数据模型文档](./data-model.md)

### Neo4j 图模型

```cypher
// 人物节点（精简版，详细属性在MySQL）
(:Person {
  id: string,
  name: string,
  name_en: string,
  category: string,
  popularity_score: float
})

// 作品节点
(:Work {
  id: string,
  title: string,
  type: string
})

// 关系
(:Person)-[:SPOUSE]->(:Person)
(:Person)-[:COLLABORATOR]->(:Person)
(:Person)-[:FRIEND]->(:Person)
(:Person)-[:FAMILY]->(:Person)
(:Person)-[:ACTED_IN]->(:Work)
(:Person)-[:DIRECTED]->(:Work)
```

### ChromaDB 集合

| 集合名称 | 用途 | 元数据 |
|---------|------|--------|
| persons | 人物向量嵌入 | person_id, name, category |
| works | 作品向量嵌入 | work_id, title, type |
| knowledge | 知识库 | source, type |

### Redis 键规范

```
starmap:person:{person_id}           # 人物详情
starmap:person:list:{hash}           # 人物列表
starmap:work:{work_id}               # 作品详情
starmap:search:{query_hash}          # 搜索结果
starmap:relation:{person_id}:{depth} # 关系图谱
starmap:session:{session_id}         # 会话状态
starmap:llm:{query_hash}             # LLM响应
starmap:crawler:stats:{task_id}      # 爬取统计
```

## 性能指标

| 场景 | 目标 | 优化策略 |
|------|------|---------|
| 人物列表查询 | < 200ms | MySQL索引 + Redis缓存 |
| 人物详情查询 | < 100ms | Redis缓存 |
| 关系图谱查询 | < 500ms | Neo4j索引 + 缓存 |
| 语义搜索 | < 300ms | ChromaDB向量索引 |
| 复杂查询（多跳） | < 2s | Neo4j索引 + 缓存 |
| Agent对话 | < 3s | LLM缓存 + 异步 |
| 首次连接MySQL | < 50ms | 连接池 |
| 首次连接Neo4j | < 100ms | 连接池 |
| 缓存命中 | < 10ms | Redis内存存储 |

## 安全设计

1. **CORS配置**: 限制允许的源
2. **请求追踪**: 每个请求分配唯一ID
3. **参数验证**: Pydantic模型自动验证
4. **错误隐藏**: 生产环境不暴露内部错误详情
5. **敏感信息**: API密钥通过环境变量配置
6. **SQL注入防护**: 使用SQLAlchemy ORM，参数化查询
7. **审计日志**: 记录所有管理操作到MySQL

## 部署架构

```
┌─────────────────────────────────────────┐
│              Docker Compose              │
│  ┌─────────┐ ┌─────────┐ ┌───────────┐ │
│  │ Backend │ │ MySQL   │ │  Redis    │ │
│  │ :8000   │ │ :3306   │ │  :6379    │ │
│  │         │ │         │ │           │ │
│  └─────────┘ └─────────┘ └───────────┘ │
│  ┌─────────┐ ┌─────────┐ ┌───────────┐ │
│  │ Neo4j   │ │ ChromaDB│ │ Frontend  │ │
│  │ :7474   │ │ :8001   │ │ :5173     │ │
│  │ :7687   │ │         │ │           │ │
│  └─────────┘ └─────────┘ └───────────┘ │
│  ┌─────────┐                            │
│  │Frontend │                            │
│  │-Admin   │                            │
│  │ :5174   │                            │
│  └─────────┘                            │
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
