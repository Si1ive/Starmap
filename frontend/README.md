# 408 Agent 用户端

这是根据 `docs/product/` 设计稿重建的用户端高保真界面。当前阶段使用本地 fixture，专注于 UI、响应式布局和核心交互，不连接后端，也不会修改正式题库数据。

## 启动

```bash
npm install
npm run dev
```

默认地址为 `http://127.0.0.1:5173/`。Vite 仍保留原项目配置：

- 开发端口：`5173`
- `/api` 代理：`http://localhost:8000`
- 路由模式：`BrowserRouter`

生产构建：

```bash
npm run build
```

## 主要入口

| 页面 | 地址 |
| --- | --- |
| 登录与产品介绍 | `/login` |
| 今日工作台 | `/today` |
| Agent 新线程 | `/agent` |
| 学习地图 | `/map` |
| 选择题练习 | `/practice/queue-check?question=1` |
| 长主观题练习 | `/practice/processor?question=1` |
| 错题与复习 | `/mistakes` |
| 资料库 | `/sources` |
| 组件状态检查 | `/states` |

旧入口继续兼容：

- `/` 跳转 `/today`
- `/chat` 跳转 `/agent`
- `/knowledge` 跳转 `/map`
- `/knowledge/:id` 跳转 `/map?point=queue`
- `/practice` 跳转 `/practice/queue-check?question=1`

## 状态地址

页面状态使用路径和查询参数表达，刷新或复制地址后仍能恢复对应演示画面。

| 状态 | 地址 |
| --- | --- |
| 今日空状态 | `/today?empty=1` |
| Agent 运行中 | `/agent/queue?state=running&hold=1` |
| Agent 已完成 | `/agent/queue?state=complete` |
| Agent 失败恢复 | `/agent/recovery?state=failed` |
| 内容优先级待确认 | `/agent/plan?state=approval` |
| 回答证据 | `/agent/queue?state=complete&evidence=1` |
| 考点详情 | `/map?point=queue` |
| 客观题反馈 | `/practice/queue-check/feedback?question=1` |
| 主观题评分点反馈 | `/practice/processor/feedback?question=1` |

## 演示路径

1. **提问到验证**
   `/agent` 提问，等待运行完成，打开引用，进入两道验证题，提交 B，确认错因并进入错题页。
2. **运行恢复与局部重试**
   从 `/agent/queue?state=running&hold=1` 打开任务中心；再进入 `/agent/recovery?state=failed`，查看已保留草稿并只重试失败步骤。
3. **长主观题与图片反馈**
   在 `/practice/processor?question=1` 打开真实处理机题图、缩放、填写第一小问并提交，随后查看评分点反馈。
4. **内容优先级调整**
   在 `/agent/plan?state=approval` 查看 Agent 根据对话和练习记录提出的内容优先级建议，并决定是否采用。
5. **移动端核心闭环**
   使用 `390 x 844` 视口走一遍 Agent 步骤抽屉、证据抽屉、验证题和客观题反馈。

## 设计实现

- 响应式 Web-first，桌面使用左侧导航、中心任务区和右侧证据/步骤区，移动端使用底部导航和全屏抽屉。
- 来源区分官方大纲、原题、平台知识、个人资料、AI 补充和模型推断。
- Agent 包含新建、运行、完成、失败恢复和长期修改审批状态。
- 练习包含选择题错因闭环和长主观题评分点辅助反馈。
- 原型真实题图位于 `public/assets/`，不依赖后端上传目录。

## 当前限制

- 数据、自动保存时间、任务进度和 Agent 结果均为本地演示数据。
- 输入内容只保存在当前 React 会话中；可恢复的演示状态由 URL 表达。
- 当前未实现登录、网络请求、SSE、正式持久化和后端错误处理。
