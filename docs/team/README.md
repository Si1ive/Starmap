# StarMap 开发团队

## 团队总览

本项目采用精简团队模式，共4个核心角色：

| 角色 | 人数 | 核心职责 | 专属文档 |
|------|------|---------|---------|
| **项目经理 (PM)** | 1 | 需求管理、进度把控、风险协调 | [pm-role.md](./pm-role.md) |
| **后端工程师 (Backend)** | 1 | API开发、Agent核心、数据层 | [backend-role.md](./backend-role.md) |
| **前端工程师 (Frontend)** | 1 | UI实现、可视化、交互体验 | [frontend-role.md](./frontend-role.md) |
| **数据工程师 (Data)** | 1 | 数据采集、清洗、知识图谱构建 | [data-role.md](./data-role.md) |

## 快速导航

### 如果你是PM，请阅读：
- [PM角色定义](./pm-role.md) - 你的职责、目标、任务
- [PM开发路线](../roadmap/pm-roadmap.md) - 你的具体任务安排

### 如果你是后端工程师，请阅读：
- [后端角色定义](./backend-role.md) - 你的职责、技术栈、任务
- [后端开发路线](../roadmap/backend-roadmap.md) - 你的具体任务安排
- [后端技术文档](../tech/backend-tech.md) - 技术细节

### 如果你是前端工程师，请阅读：
- [前端角色定义](./frontend-role.md) - 你的职责、技术栈、任务
- [前端开发路线](../roadmap/frontend-roadmap.md) - 你的具体任务安排
- [前端技术文档](../tech/frontend-tech.md) - 技术细节

### 如果你是数据工程师，请阅读：
- [数据角色定义](./data-role.md) - 你的职责、技术栈、任务
- [数据开发路线](../roadmap/data-roadmap.md) - 你的具体任务安排
- [数据技术文档](../tech/data-tech.md) - 技术细节

## 公共文档

所有角色都需要了解：
- [接口文档](../api/README.md) - API规范
- [技术总览](../tech/README.md) - 技术选型概览
- [部署指南](../tech/deployment.md) - 环境搭建

## 协作规范

### 沟通渠道
- **日常沟通**：飞书/钉钉群
- **技术讨论**：GitHub Issues（带 `discussion` 标签）
- **Bug反馈**：GitHub Issues（带 `bug` 标签）
- **文档更新**：GitHub Wiki

### 代码协作
- **分支策略**：Git Flow
  - `main`：生产分支
  - `develop`：开发分支
  - `feature/*`：功能分支
  - `hotfix/*`：紧急修复
- **提交规范**：遵循 Conventional Commits
  - `feat:` 新功能
  - `fix:` 修复
  - `docs:` 文档
  - `refactor:` 重构
  - `test:` 测试
- **Code Review**：所有PR需至少1人Review

### 会议节奏
- **每日站会**：10分钟，同步进度与阻塞
- **周会**：1小时，回顾本周，规划下周
- **里程碑评审**：每阶段结束，全员参与

## 冲突解决

| 场景 | 处理方式 |
|------|---------|
| 前后端接口不一致 | 以接口文档为准，文档由后端维护，变更需双方确认 |
| 需求变更 | PM发起变更申请，评估影响后全员确认 |
| 技术选型争议 | 架构师（Backend兼任）决策，记录决策理由 |
| 进度延迟 | PM协调资源，必要时调整范围或延期 |
| 数据质量问题 | Data负责修复，PM评估是否影响里程碑 |

## 多会话并行开发

本项目支持多会话并行开发，每个会话对应一个角色：

```
会话1: PM - 加载 pm-role.md + pm-roadmap.md
会话2: 后端 - 加载 backend-role.md + backend-roadmap.md + backend-tech.md
会话3: 前端 - 加载 frontend-role.md + frontend-roadmap.md + frontend-tech.md
会话4: 数据 - 加载 data-role.md + data-roadmap.md + data-tech.md
```

**优势：**
- 每个会话只加载相关文档，上下文聚焦
- 多个会话并行执行，互不干扰
- 角色职责清晰，避免混淆

**同步机制：**
- 代码层面：Git分支管理
- 文档层面：接口文档由后端维护，变更通知全员
- 进度层面：每日站会同步
