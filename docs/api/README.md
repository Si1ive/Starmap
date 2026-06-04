# StarMap API 接口文档

> ⚠️ **本文档由 FastAPI 自动生成，与代码实时同步**
> 
> 📖 在线文档地址：http://localhost:8000/docs
> 
> 🔄 最后更新时间：2026-06-05

---

## 目录

- [通用规范](#通用规范)
- [查询接口](#查询接口)
- [对话接口](#对话接口)
- [人物接口](#人物接口)
- [后台管理接口](#后台管理接口)
- [数据模型](#数据模型)
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
Authorization: Bearer <token>  # 后台管理接口需要
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
| q | string | 是 | 搜索关键词（1-100字符） |
| category | string | 否 | 分类过滤：actor/singer/director/all，默认all |
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
      "id": "person_001",
      "name": "周杰伦",
      "categories": ["singer", "actor", "director"],
      "avatar_url": null,
      "summary": "华语流行乐男歌手、音乐人...",
      "popularity_score": 95.5,
      "category": null,
      "description": null
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

**响应模型：** `PersonSearchResult`

---

## 对话接口

### 发送对话消息

与AI Agent进行对话，查询艺人信息。

```http
POST /api/v1/chat
```

**请求体：**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "周杰伦的妻子是谁？",
  "context": []
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 否 | 会话ID，不传则创建新会话 |
| message | string | 是 | 用户消息 |
| context | array | 否 | 历史消息上下文 |

**响应示例：**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "周杰伦的妻子是昆凌（Hannah Quinlivan），两人于2015年结婚...",
  "suggestions": ["昆凌的作品有哪些？", "周杰伦和昆凌怎么认识的？"],
  "related_persons": ["person_002"],
  "sources": ["person_001", "relation_001"]
}
```

**响应模型：** `ChatResponse`

---

### 获取对话历史

```http
GET /api/v1/chat/{session_id}/history
```

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话ID |

**响应模型：** `ChatHistory`

---

## 人物接口

### 获取人物详情

```http
GET /api/v1/persons/{person_id}
```

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| person_id | string | 是 | 人物ID，如 person_001 |

**响应示例：**

```json
{
  "name": "周杰伦",
  "name_en": "Jay Chou",
  "gender": "male",
  "categories": ["singer", "actor", "director"],
  "summary": "华语流行乐男歌手、音乐人、演员、导演、编剧...",
  "nationality": "中国",
  "birth_date": "1979-01-18",
  "birth_place": "台湾省新北市",
  "popularity_score": 95.5,
  "avatar_url": null,
  "aliases": null,
  "id": "person_001"
}
```

**响应模型：** `Person`

---

### 获取人物关系图谱

```http
GET /api/v1/persons/{person_id}/relations
```

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| person_id | string | 是 | 人物ID |

**查询参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| depth | int | 否 | 1 | 关系深度（1-3） |
| relation_type | string | 否 | null | 关系类型过滤 |

**响应模型：** `PersonRelationGraph`

---

### 获取相似人物推荐

```http
GET /api/v1/persons/{person_id}/similar
```

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| person_id | string | 是 | 人物ID |

**查询参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| limit | int | 否 | 5 | 返回数量 |

**响应模型：** `SimilarPersonResult`

---

## 后台管理接口

### 认证

#### 登录

```http
POST /api/v1/admin/auth/login
```

**请求体：**

```json
{
  "username": "admin",
  "password": "admin123"
}
```

**响应模型：** `LoginResponse`

---

#### 登出

```http
POST /api/v1/admin/auth/logout
```

---

#### 获取当前用户

```http
GET /api/v1/admin/auth/me
```

**响应模型：** `AdminUser`

---

### 仪表盘

#### 获取统计数据

```http
GET /api/v1/admin/dashboard/stats
```

**响应模型：** `DashboardStats`

---

#### 获取图表数据

```http
GET /api/v1/admin/dashboard/charts
```

**响应模型：** `DashboardCharts`

---

### 人物管理

#### 获取人物列表

```http
GET /api/v1/admin/persons
```

**查询参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量 |
| keyword | string | 否 | null | 搜索关键词 |
| category | string | 否 | null | 分类过滤 |
| status | string | 否 | null | 状态过滤 |

**响应模型：** `PersonListResponse`

---

#### 创建人物

```http
POST /api/v1/admin/persons
```

**请求体：** `PersonCreate`

**响应模型：** `Person`

---

#### 获取人物详情

```http
GET /api/v1/admin/persons/{person_id}
```

**响应模型：** `Person`

---

#### 更新人物

```http
PUT /api/v1/admin/persons/{person_id}
```

**请求体：** `PersonUpdate`

**响应模型：** `Person`

---

#### 删除人物

```http
DELETE /api/v1/admin/persons/{person_id}
```

**响应：** 204 No Content

---

### 爬虫任务

#### 获取任务列表

```http
GET /api/v1/admin/crawler/tasks
```

**响应模型：** `CrawlerTaskList`

---

#### 创建任务

```http
POST /api/v1/admin/crawler/tasks
```

**请求体：** `CrawlerTaskCreate`

**响应模型：** `CrawlerTask`

---

#### 停止任务

```http
POST /api/v1/admin/crawler/tasks/{task_id}/stop
```

**响应模型：** `CrawlerTask`

---

### 对话记录

#### 获取对话列表

```http
GET /api/v1/admin/conversations
```

**响应模型：** `ConversationList`

---

### 系统监控

#### API监控

```http
GET /api/v1/admin/monitor/api
```

**响应模型：** `ApiMonitorData`

---

#### 数据库监控

```http
GET /api/v1/admin/monitor/database
```

**响应模型：** `DatabaseMonitorData`

---

#### 错误日志

```http
GET /api/v1/admin/monitor/errors
```

**响应模型：** `ErrorLogList`

---

### 系统设置

#### 获取设置

```http
GET /api/v1/admin/settings
```

**响应模型：** `SystemSettings`

---

#### 更新设置

```http
PUT /api/v1/admin/settings
```

**请求体：** `SystemSettingsUpdate`

**响应模型：** `SystemSettings`

---

## 数据模型

### Person

人物完整模型（响应用）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 人物唯一标识 |
| name | string | 人物姓名 |
| name_en | string/null | 英文名 |
| gender | string/null | 性别 |
| categories | array | 人物分类列表 |
| summary | string/null | 人物简介 |
| nationality | string/null | 国籍 |
| birth_date | string/null | 出生日期（YYYY-MM-DD格式） |
| birth_place | string/null | 出生地 |
| popularity_score | number/null | 人气分数 |
| avatar_url | string/null | 头像URL |
| aliases | array/null | 别名列表 |

---

### PersonListItem

人物列表项（简化版）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 人物唯一标识 |
| name | string | 人物姓名 |
| categories | array | 人物分类列表 |
| avatar_url | string/null | 头像URL |
| summary | string/null | 人物简介（摘要） |
| popularity_score | number/null | 人气分数 |
| category | string/null | 人物分类（兼容旧版） |
| description | string/null | 人物简介（兼容旧版） |

---

### PersonSearchResult

人物搜索结果

| 字段 | 类型 | 说明 |
|------|------|------|
| items | array | 人物列表（PersonListItem） |
| total | integer | 总数 |
| page | integer | 当前页码 |
| page_size | integer | 每页数量 |
| total_pages | integer | 总页数 |

---

### ChatMessage

对话消息

| 字段 | 类型 | 说明 |
|------|------|------|
| role | string | 消息角色（user/assistant/system） |
| content | string | 消息内容 |
| timestamp | string/null | 消息时间（ISO 8601） |

---

### ChatResponse

对话响应

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID |
| message | string | AI回复内容 |
| suggestions | array | 推荐问题 |
| related_persons | array | 相关人物ID列表 |
| sources | array | 信息来源 |

---

### PersonRelationGraph

人物关系图谱

| 字段 | 类型 | 说明 |
|------|------|------|
| center | object | 中心人物（RelationNode） |
| nodes | array | 所有节点（RelationNode） |
| edges | array | 所有边（RelationEdge） |

---

### SimilarPersonResult

相似人物推荐结果

| 字段 | 类型 | 说明 |
|------|------|------|
| items | array | 相似人物列表（SimilarPerson） |

---

### AdminUser

管理员用户

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 用户ID |
| username | string | 用户名 |
| email | string | 邮箱 |
| role | string | 角色（super_admin/admin） |
| is_active | boolean | 是否激活 |
| created_at | string | 创建时间 |

---

### CrawlerTask

爬虫任务

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 任务ID |
| name | string | 任务名称 |
| status | string | 状态（pending/running/completed/failed） |
| source | string | 数据源 |
| created_at | string | 创建时间 |
| completed_at | string/null | 完成时间 |

---

## 错误码

### HTTP 状态码

| 状态码 | 说明 | 场景 |
|--------|------|------|
| 200 | 成功 | 正常响应 |
| 400 | 请求参数错误 | 参数校验失败 |
| 401 | 未授权 | 缺少认证信息 |
| 403 | 禁止访问 | 权限不足 |
| 404 | 资源不存在 | 人物/会话不存在 |
| 422 | 验证错误 | 请求体格式错误 |
| 500 | 服务器内部错误 | 数据库连接失败等 |

### 业务错误码

| 错误码 | 说明 | 场景 |
|--------|------|------|
| SUCCESS | 成功 | 操作成功 |
| PARAM_ERROR | 参数错误 | 必填参数缺失或格式错误 |
| NOT_FOUND | 资源不存在 | 查询的人物不存在 |
| AUTH_FAILED | 认证失败 | 用户名或密码错误 |
| FORBIDDEN | 权限不足 | 非管理员访问管理接口 |
| DB_ERROR | 数据库错误 | 数据库连接或查询失败 |
| RATE_LIMIT | 请求频繁 | 超过接口调用频率限制 |

---

## 变更日志

### v1.0.0 (2026-06-05)

- ✅ 初始化 API 文档
- ✅ 人物搜索接口 `/persons/search`
- ✅ 人物详情接口 `/persons/{person_id}`
- ✅ 人物关系接口 `/persons/{person_id}/relations`
- ✅ 相似推荐接口 `/persons/{person_id}/similar`
- ✅ 对话接口 `/chat`
- ✅ 后台管理接口 `/admin/*`

---

> 💡 **提示**：本文档与代码实时同步，访问 http://localhost:8000/docs 查看最新文档
