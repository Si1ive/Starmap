# Agent 对话模块教学文档路由

本目录用于同步记录 Agent 对话模块的设计、实现细节和实际进展。目标不是只告诉维护者
“改了什么”，而是让维护者能够理解整个系统为什么这样设计、一次对话如何运行，以及出现
问题时应该从哪里开始排查。

## 当前状态

`architecture/`、`implementation/`、`tasks/` 和 `progress/` 已在 2026-07-25 完成首轮分卷迁移；
`progress/2026-07.md` 在 2026-07-26 因接近硬上限进一步拆为月份主题分卷。
`01-technical-panorama.md`、`02-detailed-implementation.md` 和 `progress-log.md` 现仅保留薄索引职责，
后续 Agent 教学正文只更新对应分卷与当月进展日志。

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
├── tasks/
│   ├── README.md                      # 跨阶段任务阅读路由
│   └── YYYY-MM-DD-主题.md             # 待做任务状态、依赖和验收入口
└── progress/
    ├── README.md                       # 进展日志总路由
    ├── YYYY-MM.md                      # 月度兼容薄索引
    └── YYYY-MM/README.md               # 当月主题分卷路由
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
| 跨多个提交的待做计划 | `tasks/` 中对应任务单页 | 实施某项任务时再进入对应 architecture/implementation 分卷 |

每个 Agent 提交最后更新当月路由指向的最小主题分卷；未拆分月份直接写 `progress/YYYY-MM.md`，已拆分月份不得再向兼容薄索引追加正文。

## 当前待做任务

- [Agent 对话任务路由](./tasks/README.md)：当前包含 RAG、Explain 与分层记忆整改总览，以及
  已完成基础、记忆生命周期和管理端可观测性主题分卷。

## 薄索引入口

### 技术实现全景图

[01-technical-panorama.md](./01-technical-panorama.md)

作为旧路径兼容索引，指向 `architecture/` 下的系统边界、主链和旁路分卷。

### 分模块细致讲解

[02-detailed-implementation.md](./02-detailed-implementation.md)

作为旧路径兼容索引，指向 `implementation/` 下的上下文、模型运行时、RAG、事件、管理端和前端分卷。

### 历史进展记录

[progress-log.md](./progress-log.md)

作为旧路径兼容索引，指向 `progress/` 月度日志。

## 按需阅读方法

1. 先根据上方更新路由确定一个主分卷。
2. 使用 `rg -n "关键词|符号名" docs/agent-conversation` 找到精确章节，再用 `sed -n` 读取必要行段。
3. 只有做全局架构审计或文档迁移时才读取全部全景；普通修复不得默认加载所有历史文档。
4. 排查回归时先从当月进展或独立 incident 定位提交，再进入对应实现分卷。
