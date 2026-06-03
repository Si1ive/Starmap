# StarMap API 接口文档

## 目录

- [通用规范](#通用规范)
- [查询接口](#查询接口)
- [对话接口](#对话接口)
- [人物接口](#人物接口)
- [推荐接口](#推荐接口)
- [错误码](#错误码)

---

## 通用规范

### 基础信息

| 项目 | 值 |
|------|-----|
| 基础URL | `http://localhost:8000/api/v1` |
| 协议 | HTTP/1.1 (开发) / HTTPS (生产) |
| 数据格式 | JSON |
| 字符编码 | UTF-8 |
| 时间格式 | ISO 8601 (`2024-01-01T12:00:00Z`) |

### 请求头

```http
Content-Type: application/json
Accept: application/json
X-Request-ID: <uuid>          # 可选，用于追踪
Authorization: Bearer <token>  # 未来扩展
```

### 响应格式

```json
{
  "code": "SUCCESS",
  "message": "success",
  "data": {},
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 分页参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大100 |

### 分页响应

```json
{
  "items": [],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "total_pages": 5
}
```

---

## 查询接口

### 搜索人物

搜索艺人信息，支持模糊匹配。

```http
GET /api/v1/persons/search
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| q | string | 是 | 搜索关键词 |
| category | string | 否 | 分类过滤：actor/singer/director/all |
| page | int | 否 | 页码，默认1 |
| page_size | int | 否 | 每页数量，默认20，最大100 |

**请求示例：**

```http
GET /api/v1/persons/search?q=周杰伦&category=singer&page=1&page_size=10
```

**响应示例：**

```json
{
  "items": [
    {
      "id": "jay-chou",
      "name": "周杰伦",
      "category": "singer",
      "avatar_url": "https://example.com/jay.jpg",
      "description": "华语流行乐男歌手、音乐人..."
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10,
  "total_pages": 1
}
```

**错误响应：**

```json
{
  "code": "VALIDATION_ERROR",
  "message": "请求参数验证失败",
  "detail": ["body -> message: Field required"],
  "request_id": "550e8400-e29b-41d4-a716-446655440001"
}
```

---

## 对话接口

### 发送消息

与Agent进行对话，支持上下文。

```http
POST /api/v1/chat
```

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 用户消息（1-2000字符） |
| session_id | string | 否 | 会话ID，首次为空 |
| context | object | 否 | 上下文信息 |

**请求示例：**

```json
{
  "message": "周杰伦的妻子是谁？",
  "session_id": "sess_abc123",
  "context": {
    "current_person": "周杰伦"
  }
}
```

**响应示例：**

```json
{
  "session_id": "sess_abc123",
  "message": "周杰伦的妻子是昆凌。两人于2014年公开恋情，2015年在英国举行婚礼。",
  "type": "answer",
  "sources": [
    {
      "type": "neo4j",
      "title": "周杰伦",
      "content": "配偶：昆凌"
    }
  ],
  "suggestions": [
    "他们有几个孩子？",
    "昆凌是做什么的？",
    "周杰伦还有其他恋情吗？"
  ]
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID，用于保持上下文 |
| message | string | Agent回复内容 |
| type | string | 回复类型：answer/clarification/error |
| sources | array | 信息来源 |
| suggestions | array | 建议的后续问题 |

**错误响应：**

```json
{
  "code": "LLM_ERROR",
  "message": "AI服务暂时不可用",
  "request_id": "550e8400-e29b-41d4-a716-446655440003"
}
```

---

### 获取会话历史

获取指定会话的历史消息。

```http
GET /api/v1/chat/{session_id}/history
```

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**响应示例：**

```json
{
  "session_id": "sess_abc123",
  "messages": [
    {
      "role": "user",
      "content": "周杰伦的妻子是谁？",
      "timestamp": "2024-01-01T12:00:00Z"
    },
    {
      "role": "assistant",
      "content": "周杰伦的妻子是昆凌...",
      "timestamp": "2024-01-01T12:00:05Z"
    }
  ],
  "created_at": "2024-01-01T11:59:00Z",
  "updated_at": "2024-01-01T12:00:05Z"
}
```

---

## 人物接口

### 获取人物详情

获取指定人物的详细信息。

```http
GET /api/v1/persons/{person_id}
```

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| person_id | string | 是 | 人物ID |

**响应示例：**

```json
{
  "id": "jay-chou",
  "name": "周杰伦",
  "category": "singer",
  "description": "华语流行乐男歌手、音乐人、演员、导演、编剧...",
  "nationality": "中国台湾",
  "birth_date": "1979-01-18",
  "avatar_url": "https://example.com/jay.jpg",
  "aliases": ["Jay Chou", "周董"]
}
```

---

### 获取人物关系

获取指定人物的关系网络。

```http
GET /api/v1/persons/{person_id}/relations
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| depth | int | 否 | 关系深度，默认1，最大3 |
| relation_type | string | 否 | 关系类型过滤 |

**响应示例：**

```json
{
  "center": {
    "id": "jay-chou",
    "name": "周杰伦"
  },
  "nodes": [
    {
      "id": "jay-chou",
      "name": "周杰伦",
      "category": "singer",
      "avatar_url": "https://example.com/jay.jpg"
    },
    {
      "id": "hannah",
      "name": "昆凌",
      "category": "model",
      "avatar_url": "https://example.com/hannah.jpg"
    },
    {
      "id": "fangwenshan",
      "name": "方文山",
      "category": "lyricist",
      "avatar_url": "https://example.com/fang.jpg"
    }
  ],
  "edges": [
    {
      "source": "jay-chou",
      "target": "hannah",
      "type": "spouse",
      "properties": {}
    },
    {
      "source": "jay-chou",
      "target": "fangwenshan",
      "type": "collaborator",
      "properties": {}
    }
  ]
}
```

---

## 推荐接口

### 相似人物推荐

推荐与指定人物相似的人物。

```http
GET /api/v1/persons/{person_id}/similar
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| limit | int | 否 | 返回数量，默认5，最大20 |

**响应示例：**

```json
{
  "items": [
    {
      "id": "jj-lin",
      "name": "林俊杰",
      "category": "singer",
      "avatar_url": "https://example.com/jj.jpg",
      "similarity_score": 5,
      "common_connections": ["华语流行", "创作歌手"]
    },
    {
      "id": "leehom-wang",
      "name": "王力宏",
      "category": "singer",
      "avatar_url": "https://example.com/leehom.jpg",
      "similarity_score": 4,
      "common_connections": ["创作才子", "华语乐坛"]
    }
  ]
}
```

---

## 错误码

| 错误码 | HTTP状态码 | 说明 | 处理方式 |
|--------|-----------|------|---------|
| SUCCESS | 200 | 成功 | - |
| VALIDATION_ERROR | 422 | 请求参数错误 | 检查请求参数 |
| NOT_FOUND | 404 | 资源不存在 | 检查ID是否正确 |
| INTERNAL_ERROR | 500 | 服务器内部错误 | 稍后重试或联系管理员 |
| DATABASE_ERROR | 503 | 数据库服务暂时不可用 | 检查数据库服务状态 |
| LLM_ERROR | 503 | AI服务暂时不可用 | 稍后重试 |

### 错误响应格式

```json
{
  "code": "INTERNAL_ERROR",
  "message": "服务器内部错误",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**开发环境额外字段：**

```json
{
  "code": "INTERNAL_ERROR",
  "message": "服务器内部错误",
  "detail": "具体错误详情",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## 接口变更日志

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0.0 | 2024-06-03 | 初始版本，包含基础查询和对话接口 |

---

## 数据库连接降级说明

当数据库服务（Neo4j/Redis/ChromaDB）不可用时，API会自动降级运行：

- **Neo4j不可用时**：返回Mock人物数据，关系查询返回空图谱
- **Redis不可用时**：跳过缓存，直接查询数据库
- **ChromaDB不可用时**：向量搜索功能不可用

服务状态可通过 `/health` 接口实时查看。
