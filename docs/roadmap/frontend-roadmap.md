# 前端开发路线

## 概述

前端开发包含**两个独立项目**：

| 项目 | 路径 | 用户 | 端口 | 开发时间 |
|------|------|------|------|----------|
| **用户端** | `frontend/` | 普通用户 | 5173 | Week 1-3 |
| **管理端** | `frontend-admin/` | 管理员 | 5174 | Week 4-5 |

---

## 用户端开发路线 (frontend/)

### Week 1：基础设施搭建

#### Day 1（周一）
**目标**：项目初始化

- [ ] **上午**：创建React项目
  ```bash
  npm create vite@latest frontend -- --template react-ts
  cd frontend
  npm install
  ```

- [ ] **下午**：配置开发环境
  - 配置ESLint
  - 配置Prettier
  - 配置路径别名

**产出**：
- 可运行的React项目
- 开发环境配置完成

---

#### Day 2（周二）
**目标**：UI框架配置

- [ ] **上午**：安装Ant Design
  ```bash
  npm install antd @ant-design/icons
  ```

- [ ] **下午**：配置主题
  - 自定义主题色
  - 配置全局样式
  - 创建布局组件

**产出**：
- Ant Design配置完成
- 基础布局组件（Header/Footer）

---

#### Day 3（周三）
**目标**：路由与状态管理

- [ ] **上午**：配置路由
  - 安装 `react-router-dom`
  - 配置页面路由

- [ ] **下午**：配置Zustand
  - 创建Store
  - 实现状态管理

**产出**：
- 路由系统
- 状态管理Store

---

#### Day 4（周四）
**目标**：HTTP客户端

- [ ] **上午**：封装Axios
  - 创建API客户端
  - 配置拦截器
  - 错误处理

- [ ] **下午**：API方法封装
  - 创建 `api/person.ts`
  - 创建 `api/chat.ts`
  - 类型定义

**产出**：
- HTTP客户端封装
- API方法定义

---

#### Day 5（周五）
**目标**：搜索页面

- [ ] **上午**：搜索框组件
  - 实现SearchBox
  - 添加搜索建议
  - 防抖处理

- [ ] **下午**：搜索结果列表
  - 实现PersonCard
  - 实现结果列表
  - 分页组件

**产出**：
- 搜索页面（UI）
- 搜索相关组件

---

#### Day 6（周六）
**目标**：人物详情页

- [ ] **上午**：基本信息展示
  - 人物头像
  - 基本信息卡片
  - 标签展示

- [ ] **下午**：作品列表
  - 作品卡片
  - 分类筛选
  - 排序功能

**产出**：
- 人物详情页（UI）
- 作品列表组件

---

#### Day 7（周日）
**目标**：对话页面

- [ ] **上午**：消息组件
  - 消息气泡
  - 头像展示
  - 时间戳

- [ ] **下午**：输入组件
  - 文本输入框
  - 发送按钮
  - 加载状态

**产出**：
- 对话页面（UI）
- 消息组件

---

### Week 2：MVP核心功能

#### Day 8（周一）
**目标**：API对接 - 搜索

- [ ] 对接搜索API
- [ ] 实现搜索功能
- [ ] 处理加载状态
- [ ] 处理错误状态

#### Day 9（周二）
**目标**：API对接 - 人物详情

- [ ] 对接人物详情API
- [ ] 展示人物信息
- [ ] 实现标签页切换

#### Day 10（周三）
**目标**：API对接 - 对话

- [ ] 对应对话API
- [ ] 实现消息发送
- [ ] 实现消息接收
- [ ] 维护Session

#### Day 11（周四）
**目标**：关系图谱页

- [ ] 安装D3.js
- [ ] 实现基础力导向图
- [ ] 节点交互

#### Day 12（周五）
**目标**：领域浏览页

- [ ] 实现分类展示
- [ ] 实现分类筛选
- [ ] 实现人物列表

#### Day 13（周六）
**目标**：联调

- [ ] 前后端联调
- [ ] 修复接口问题
- [ ] 测试端到端流程

#### Day 14（周日）
**目标**：优化

- [ ] 性能优化
- [ ] 错误处理完善
- [ ] 加载状态优化

---

### Week 3：功能完善

#### Day 15-21
- [ ] 关系图谱优化（交互、动画）
- [ ] 对话功能优化（历史记录、快捷输入）
- [ ] 响应式适配
- [ ] 动画与过渡效果

---

## 管理端开发路线 (frontend-admin/)

### Week 4：核心功能开发

#### Day 1（周一）：基础框架搭建
**目标**：创建管理端项目结构

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 创建 `frontend-admin/` 目录 | 独立项目 | 目录结构清晰 |
| 配置 React + Vite + TypeScript | `package.json` | 与用户端技术栈一致 |
| 配置 Ant Design Pro | 主题配置 | 组件可用 |
| 配置 React Router | 路由定义 | 路由跳转正常 |
| 配置 React Query | QueryClient | 数据获取正常 |
| 实现登录页面 | `src/pages/Login/` | UI完成 |

**目录结构**：
```
frontend-admin/
├── public/
├── src/
│   ├── api/              # API接口
│   │   ├── client.ts     # Axios封装
│   │   ├── auth.ts       # 认证API
│   │   ├── dashboard.ts  # 看板API
│   │   ├── person.ts     # 艺人API
│   │   ├── work.ts       # 作品API
│   │   ├── crawler.ts    # 爬虫API
│   │   ├── conversation.ts # 对话API
│   │   ├── monitor.ts    # 监控API
│   │   └── settings.ts   # 配置API
│   ├── components/       # 公共组件
│   │   ├── Layout/       # 布局组件
│   │   ├── Header/       # 顶部栏
│   │   ├── Sider/        # 侧边栏
│   │   ├── StatCard/     # 统计卡片
│   │   └── Chart/        # 图表组件
│   ├── hooks/            # 自定义Hooks
│   ├── pages/            # 页面
│   │   ├── Login/        # 登录
│   │   ├── Dashboard/    # 数据看板
│   │   ├── Person/       # 艺人管理
│   │   ├── Work/         # 作品管理
│   │   ├── Crawler/      # 爬虫管理
│   │   ├── Conversation/ # 对话管理
│   │   ├── Monitor/      # 系统监控
│   │   └── Settings/     # 系统配置
│   ├── router/           # 路由配置
│   ├── store/            # 状态管理
│   ├── types/            # 类型定义
│   ├── utils/            # 工具函数
│   ├── App.tsx
│   └── main.tsx
├── package.json
├── tsconfig.json
└── vite.config.ts
```

---

#### Day 2（周二）：认证与布局
**目标**：实现登录认证和基础布局

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现登录表单 | `pages/Login/index.tsx` | Day 1 |
| 集成JWT认证 | `api/auth.ts` | Backend API |
| 实现路由守卫 | `router/guard.tsx` | 登录状态 |
| 实现侧边栏菜单 | `components/Sider/` | 路由配置 |
| 实现顶部Header | `components/Header/` | 用户信息 |
| 实现布局框架 | `components/Layout/` | Sider + Header |

**菜单配置**：
```typescript
const menuItems = [
  { key: '/admin/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/admin/persons', icon: <UserOutlined />, label: '艺人管理' },
  { key: '/admin/works', icon: <VideoCameraOutlined />, label: '作品管理' },
  { key: '/admin/crawler', icon: <BugOutlined />, label: '爬虫管理' },
  { key: '/admin/conversations', icon: <MessageOutlined />, label: '对话管理' },
  { key: '/admin/monitor', icon: <MonitorOutlined />, label: '系统监控' },
  { key: '/admin/settings', icon: <SettingOutlined />, label: '系统配置' },
]
```

---

#### Day 3（周三）：数据看板
**目标**：实现Dashboard页面

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现统计卡片组件 | `components/StatCard/` | - |
| 实现看板API对接 | `api/dashboard.ts` | Backend API |
| 实现核心指标展示 | `pages/Dashboard/` | 统计卡片 |
| 实现趋势图（ECharts） | `components/Chart/LineChart.tsx` | ECharts |
| 实现分布图（饼图） | `components/Chart/PieChart.tsx` | ECharts |
| 实现热门搜索词 | `pages/Dashboard/HotSearch.tsx` | Backend API |

**看板布局**：
```
┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐
│ 艺人总数 │ 作品总数 │ 关系总数 │ 今日对话 │ 数据完整率│ API响应 │  ← 统计卡片
└─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘
┌──────────────────────────┐  ┌──────────────────────────┐
│     近7日对话趋势图        │  │      艺人分类分布         │
│     (折线图)              │  │      (饼图)              │
└──────────────────────────┘  └──────────────────────────┘
┌──────────────────────────┐  ┌──────────────────────────┐
│     热门搜索词Top10       │  │      爬虫任务状态         │
│     (柱状图)              │  │      (进度条列表)         │
└──────────────────────────┘  └──────────────────────────┘
```

---

#### Day 4（周四）：艺人管理 - 列表页
**目标**：实现艺人列表页

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现艺人API对接 | `api/person.ts` | Backend API |
| 实现搜索组件 | `components/SearchBar/` | - |
| 实现筛选组件 | `components/FilterPanel/` | - |
| 实现艺人列表表格 | `pages/Person/List.tsx` | Ant Design Table |
| 实现分页功能 | 内置在Table | - |
| 实现批量操作栏 | `components/BatchAction/` | - |

---

#### Day 5（周五）：艺人管理 - 详情/编辑页
**目标**：实现艺人详情和编辑

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现艺人详情页 | `pages/Person/Detail.tsx` | Day 4 |
| 实现艺人编辑表单 | `pages/Person/Edit.tsx` | Ant Design Form |
| 实现图片上传组件 | `components/ImageUpload/` | Ant Design Upload |
| 实现富文本编辑器 | `components/RichEditor/` | react-quill |
| 实现关联作品选择 | `components/WorkSelector/` | Backend API |
| 实现编辑历史 | `pages/Person/History.tsx` | Backend API |

---

#### Day 6（周六）：作品管理 + 爬虫管理
**目标**：实现作品管理和爬虫管理

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现作品列表 | `pages/Work/List.tsx` | 类似艺人列表 |
| 实现作品编辑 | `pages/Work/Edit.tsx` | 动态表单 |
| 实现爬虫任务列表 | `pages/Crawler/List.tsx` | Backend API |
| 实现爬虫任务详情 | `pages/Crawler/Detail.tsx` | Backend API |
| 实现实时日志组件 | `components/LogViewer/` | WebSocket |
| 实现爬虫配置表单 | `pages/Crawler/Config.tsx` | Ant Design Form |

---

#### Day 7（周日）：对话管理 + 系统监控
**目标**：实现对话管理和监控页面

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现对话记录列表 | `pages/Conversation/List.tsx` | Backend API |
| 实现对话详情 | `pages/Conversation/Detail.tsx` | Backend API |
| 实现热门问题分析 | `pages/Conversation/Stats.tsx` | Backend API |
| 实现API性能监控 | `pages/Monitor/Api.tsx` | ECharts |
| 实现数据库监控 | `pages/Monitor/Database.tsx` | Backend API |
| 实现错误日志 | `pages/Monitor/Errors.tsx` | Backend API |

---

### Week 5：完善与优化

#### Day 8-9（周一-周二）：系统配置 + 优化

| 任务 | 产出 | 说明 |
|------|------|------|
| 实现系统配置页 | `pages/Settings/` | 分类配置表单 |
| 实现用户管理 | `pages/Settings/Users.tsx` | 超级管理员权限 |
| 响应式适配 | 全局 | 平板/手机端 |
| 性能优化 | 全局 | 懒加载、代码分割 |
| 错误边界 | `components/ErrorBoundary/` | 全局错误捕获 |
| 加载状态优化 | 全局 | Skeleton屏 |

#### Day 10-11（周三-周四）：测试与Bug修复

| 任务 | 产出 | 说明 |
|------|------|------|
| 单元测试 | `tests/` | Jest + React Testing Library |
| 集成测试 | - | 关键流程端到端测试 |
| Bug修复 | - | 测试中发现的问题 |
| 代码审查 | - | 团队内Review |

#### Day 12-13（周五-周六）：文档与部署

| 任务 | 产出 | 说明 |
|------|------|------|
| 编写使用文档 | `docs/admin/usage.md` | 管理员使用指南 |
| 编写部署文档 | `docs/admin/deployment.md` | 部署说明 |
| 构建生产包 | `dist/` | Vite build |
| Dockerfile | `Dockerfile` | 容器化 |

#### Day 14（周日）：验收

| 任务 | 产出 | 负责人 |
|------|------|--------|
| 功能验收 | 验收报告 | PM |
| 性能验收 | 性能测试报告 | Frontend |
| 安全验收 | 安全检查 | Backend |

---

## 组件开发清单

### 用户端组件

#### 基础组件
- [ ] Layout（布局）
- [ ] Header（头部）
- [ ] Footer（底部）
- [ ] Loading（加载）
- [ ] ErrorBoundary（错误边界）

#### 业务组件
- [ ] SearchBox（搜索框）
- [ ] PersonCard（人物卡片）
- [ ] WorkCard（作品卡片）
- [ ] Message（消息）
- [ ] ForceGraph（力导向图）
- [ ] Timeline（时间线）

#### 页面组件
- [ ] SearchPage（搜索页）
- [ ] PersonPage（人物详情）
- [ ] ChatPage（对话页）
- [ ] GraphPage（关系图谱）
- [ ] BrowsePage（领域浏览）

### 管理端组件

#### 基础组件
- [ ] Layout（布局 - 含侧边栏）
- [ ] Header（顶部栏 - 含用户信息）
- [ ] Sider（侧边栏 - 菜单）
- [ ] Footer（底部）
- [ ] Loading（加载）
- [ ] ErrorBoundary（错误边界）

#### 数据组件
- [ ] StatCard（统计卡片）
- [ ] LineChart（折线图）
- [ ] PieChart（饼图）
- [ ] BarChart（柱状图）

#### 业务组件
- [ ] SearchBar（搜索栏）
- [ ] FilterPanel（筛选面板）
- [ ] BatchAction（批量操作栏）
- [ ] ImageUpload（图片上传）
- [ ] RichEditor（富文本编辑器）
- [ ] WorkSelector（作品选择器）
- [ ] LogViewer（日志查看器 - WebSocket）

#### 页面组件
- [ ] LoginPage（登录页）
- [ ] DashboardPage（数据看板）
- [ ] PersonListPage（艺人列表）
- [ ] PersonDetailPage（艺人详情）
- [ ] PersonEditPage（艺人编辑）
- [ ] WorkListPage（作品列表）
- [ ] CrawlerListPage（爬虫任务列表）
- [ ] CrawlerDetailPage（爬虫任务详情）
- [ ] ConversationListPage（对话记录）
- [ ] MonitorPage（系统监控）
- [ ] SettingsPage（系统配置）

---

## 技术债务跟踪

| 债务 | 产生时间 | 影响 | 计划偿还时间 |
|------|---------|------|-------------|
| 缺少单元测试 | Week 1 | 质量风险 | Week 3 |
| 缺少响应式适配 | Week 2 | 用户体验 | Week 3 |
| 缺少错误上报 | Week 2 | 排查困难 | Week 4 |
| 缺少性能监控 | Week 3 | 性能风险 | Week 4 |

---

## 关键决策点

### Week 1
- **决策**：状态管理方案
  - 选项A：Zustand（简单，推荐）
  - 选项B：Redux（复杂，但功能强）
  - **建议**：用户端用Zustand，管理端用Zustand + React Query

### Week 2
- **决策**：可视化方案
  - 选项A：D3.js（灵活，但学习曲线陡）
  - 选项B：ECharts（简单，但定制性弱）
  - **建议**：用户端用D3.js（关系图谱），管理端用ECharts（数据报表）

### Week 3
- **决策**：是否添加PWA？
  - 评估：工作量、收益
  - **建议**：MVP不做，后续评估

### Week 4
- **决策**：管理端组件库
  - 选项A：Ant Design（轻量）
  - 选项B：Ant Design Pro（功能全）
  - **建议**：管理端用Ant Design Pro（含ProLayout、ProTable等）
