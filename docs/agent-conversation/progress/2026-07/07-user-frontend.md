# 2026-07 用户端 Agent 外围体验进展

## 2026-07-28：移除任务中心固定样例

- 目标：全局任务中心不再向登录用户展示固定的 Agent、资料入库和练习任务，所有进行中状态必须来自当前用户的真实时间线。
- 实现：`frontend/src/components/AppShell.tsx::AppShell`（L33-L105、L168-L239）从当前 Thread 的 `timeline.workflowsByRootRunId` 筛选 queued、running、waiting_input 和 waiting_approval；展示真实标题、当前步骤、完成数与等待状态。没有真实运行时显示范围明确的空状态，任务红点同时消失。
- 视觉：`frontend/src/index.css`（L853-L940）让工作流图标和空状态沿用项目纸张、墨色和玉色，不保留 fixture 中资料/练习任务的多余视觉语义。
- 副作用与错误：只读前端已归并的 Thread 时间线，不新增请求或数据库写入；当前未打开 Thread 时不会声称掌握其他会话的运行状态，其他历史仍从左侧进入。
- 验证：`cd frontend && npm run build` 与 `npx eslint src/components/AppShell.tsx` 通过；`git diff --check` 通过。
- 提交信息：`移除用户任务中心固定样例`
