# 用户端产品设计

> 最后更新：2026-07-21

本目录是 408 学习 Agent 用户端的产品基线。当前已确定产品结构、核心闭环、技术边界、页面状态和真实原型样例；视觉语言与高保真交互稿将在设计 Skill 接入后继续完成。

## 文档索引

- [408 学习 Agent 主体 PRD](./408-agent-main-prd.md)
  - 用户端、管理端、学习进度、资料、评测、安全和分阶段交付的产品主契约
- [408 学习 Agent 对话运行时技术设计](../tech/408-agent-conversation-runtime-design.md)
  - Agent 线程与运行、数据模型、API/SSE、Worker、工具、恢复、评测和发布门禁的技术基线
- [408 学习 Agent 工作流编排技术设计](../tech/408-agent-workflow-orchestration-design.md)
  - Agent 路由、工作流图、节点契约、质量闸门、教学路径与轨迹评测
- [用户认证与账户系统 PRD](./authentication-and-user-account-prd.md)
  - 注册、登录、GitHub OAuth、邮箱验证、会话、用户信息、数据归属和安全验收
- [408 学习 Agent 文字原型](./408-agent-product-prototype.md)
  - 产品定位、信息架构、页面结构、核心工作流、Agent 模式与可信交互
- [408 学习 Agent 交互规格](./408-agent-interaction-spec.md)
  - P01-P20 页面清单、组件状态矩阵、响应式规则和高保真评审门禁
- [408 学习 Agent 原型样例库](./408-agent-prototype-fixtures.md)
  - 基于试卷4真实结构的题目、考点、Agent run、练习和来源样例
- [用户旅程与评测脚本](./408-agent-journeys-and-evaluation.md)
  - 核心旅程、可用性测试、Agent 离线评测集和设计开发交接条件
- [高保真设计执行简报](./408-agent-visual-design-brief.md)
  - 视觉方向、组件语言、D1-D5 可点击路径、真实样例映射和高保真交付门禁
- [用户端 Agent 技术架构](../tech/user-agent-client-architecture.md)
  - Web/桌面选型、客户端能力适配和安全边界
- [用户认证技术方案与数据模型](../tech/authentication-architecture-options.md)
  - 主流身份方案对比、推荐架构、关系表设计、API 契约和迁移路线
- [用户端实施路线](../roadmap/user-agent-delivery-plan.md)
  - 纵向切片、阶段范围、验收标准、桌面能力启用条件

## 当前结论

1. 第一版采用响应式 Web，不做桌面端优先。
2. 用户端第一屏是可操作的学习工作台，不是营销首页，也不是单纯聊天页。
3. Agent 的规划、工具调用、记忆、审批和任务恢复运行在服务端。
4. 本地文件、系统通知、浏览器上下文等能力通过客户端能力适配层逐步接入。
5. 只有在真实工作流证明需要持续目录访问、文件监听或系统级快捷键后，才使用 Tauri 复用现有 React 用户端。
6. 首批按单人自用和邀请制内测设计，但数据从第一天归属真实 `user_id`。
7. 首发以“提问到验证”为第一主线，主观题只提供评分点辅助反馈。
8. 推荐视觉方向为“专注型学术工作台”；具体视觉 token 和最终品牌名由设计 Skill 在既定交互与可信边界内完成。
