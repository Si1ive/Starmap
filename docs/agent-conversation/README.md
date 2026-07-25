# Agent 对话模块教学文档路由

本目录用于同步记录 Agent 对话模块的设计、实现细节和实际进展。目标不是只告诉维护者
“改了什么”，而是让维护者能够理解整个系统为什么这样设计、一次对话如何运行，以及出现
问题时应该从哪里开始排查。

## 当前状态

现有 `01-technical-panorama.md`、`02-detailed-implementation.md` 和 `progress-log.md` 是早期连续追加形成的
迁移源，总计约 141 KB。它们仍保留现有内容和链接，但不再作为未来持续追加的目标。下一次 Agent 实现
需要新增教学正文前，应先用独立提交完成下述分卷迁移，并把三个旧路径收敛为薄索引。

## 目标文档结构

```text
docs/agent-conversation/
├── README.md                         # 唯一阅读路由，不放大段正文
├── architecture/
│   ├── system-map.md                 # 边界、组件、数据所有权
│   ├── conversation-mainline.md      # 用户消息到 SSE/前端的主链
│   ├── workflow-branches.md          # explain/validate/grade/plan 分支
│   └── admin-and-model-config.md     # 管理端、模型配置和旁路
├── implementation/
│   ├── routing-context-memory.md      # Router、上下文与分层记忆
│   ├── model-runtime-streaming.md     # 模型运行时、Token 与流式输出
│   ├── rag-and-tools.md               # RAG、实体类型、工具和重试
│   ├── events-timeline-errors.md      # Run/Thread 事件、投影和错误
│   ├── admin-observability.md         # Agent Runs 与模型调用审计
│   ├── frontend-experience.md         # 用户端交互与视觉
│   └── database-migrations.md         # 表结构、迁移和结构守卫
├── incidents/
│   └── YYYY-MM-DD-主题.md             # 单次复杂故障证据与复盘
└── progress/
    └── YYYY-MM.md                     # 当月提交进展
```

## 更新路由

| 改动类型 | 必读与更新目标 | 仅在何时扩展阅读 |
| --- | --- | --- |
| Router、指代消解、上下文、记忆 | `implementation/routing-context-memory.md` | 主链改变时再读 `architecture/conversation-mainline.md` |
| 模型配置、Token、结构化/流式输出 | `implementation/model-runtime-streaming.md` | 管理配置入口改变时再读 `architecture/admin-and-model-config.md` |
| RAG、题目/知识点检索、工具重试 | `implementation/rag-and-tools.md` | workflow 节点顺序改变时再读 `architecture/workflow-branches.md` |
| Run/消息/事件/SSE/错误投影 | `implementation/events-timeline-errors.md` | 端到端异步边界改变时再读主链全景 |
| Agent Runs 和模型调用监控 | `implementation/admin-observability.md` | 管理 API 边界改变时再读管理端全景 |
| 用户端交互和样式 | `implementation/frontend-experience.md` | API/SSE 契约改变时再读事件分卷 |
| ORM、Alembic、结构守卫 | `implementation/database-migrations.md` | 数据所有权改变时再读 `architecture/system-map.md` |
| 复杂线上故障 | 对应实现分卷 + 新建 `incidents/` 单页 | 只读取相关月份进展，不加载全部历史 |

每个 Agent 提交最后只追加当月 `progress/YYYY-MM.md`，不在进展日志中复制详细正文。

## 迁移源

### 技术实现全景图

[01-technical-panorama.md](./01-technical-panorama.md)

从系统边界出发说明用户端、API、时间线、Worker、工作流、模型运行时、数据库、Redis 和
管理员监控之间的关系，并持续维护请求链路与数据所有权。

### 分模块细致讲解

[02-detailed-implementation.md](./02-detailed-implementation.md)

按照全景图中的模块逐一讲解关键文件、状态变化、数据库结构、异常处理、前后端协议和测试
方法。每次实现或修复 Agent 功能时同步更新对应章节。

### 历史进展记录

[progress-log.md](./progress-log.md)

按功能提交记录目标、实现内容、验证结果和 Git 提交，便于将文档状态与代码状态对应起来。

## 按需阅读方法

1. 先根据上方更新路由确定一个主分卷。
2. 使用 `rg -n "关键词|符号名" docs/agent-conversation` 找到精确章节，再用 `sed -n` 读取必要行段。
3. 只有做全局架构审计或文档迁移时才读取全部全景；普通修复不得默认加载所有历史文档。
4. 排查回归时先从当月进展或独立 incident 定位提交，再进入对应实现分卷。
