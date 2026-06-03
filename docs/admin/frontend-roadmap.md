# 后台管理端 - 前端开发路线

> 负责人：Frontend  
> 时间：Week 4-5  
> 依赖：主站前端框架已完成

---

## Week 4：核心功能开发

### Day 1（周一）：基础框架搭建

**目标**：创建后台管理端项目结构

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 创建 `frontend-admin/` 目录 | 独立项目 | 目录结构清晰 |
| 配置 React + Vite + TypeScript | `package.json` | 与主站技术栈一致 |
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

### Day 2（周二）：认证与布局

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

### Day 3（周三）：数据看板

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

### Day 4（周四）：艺人管理 - 列表页

**目标**：实现艺人列表页

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现艺人API对接 | `api/person.ts` | Backend API |
| 实现搜索组件 | `components/SearchBar/` | - |
| 实现筛选组件 | `components/FilterPanel/` | - |
| 实现艺人列表表格 | `pages/Person/List.tsx` | Ant Design Table |
| 实现分页功能 | 内置在Table | - |
| 实现批量操作栏 | `components/BatchAction/` | - |

**表格字段**：
```typescript
const columns = [
  { title: 'ID', dataIndex: 'id', sorter: true },
  { title: '头像', dataIndex: 'avatar', render: (url) => <Avatar src={url} /> },
  { title: '姓名', dataIndex: 'name', sorter: true },
  { title: '英文名', dataIndex: 'name_en', sorter: true },
  { title: '分类', dataIndex: 'categories', render: (tags) => tags.map(t => <Tag>{t}</Tag>) },
  { title: '国籍', dataIndex: 'nationality', sorter: true },
  { title: '数据状态', dataIndex: 'status', render: (s) => <StatusBadge status={s} /> },
  { title: '创建时间', dataIndex: 'created_at', sorter: true },
  { title: '操作', render: (_, record) => <ActionButtons record={record} /> },
]
```

---

### Day 5（周五）：艺人管理 - 详情/编辑页

**目标**：实现艺人详情和编辑

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现艺人详情页 | `pages/Person/Detail.tsx` | Day 4 |
| 实现艺人编辑表单 | `pages/Person/Edit.tsx` | Ant Design Form |
| 实现图片上传组件 | `components/ImageUpload/` | Ant Design Upload |
| 实现富文本编辑器 | `components/RichEditor/` | react-quill |
| 实现关联作品选择 | `components/WorkSelector/` | Backend API |
| 实现编辑历史 | `pages/Person/History.tsx` | Backend API |

**表单布局**：
```
┌─────────────────────────────────────────────┐
│  基本信息                                    │
│  ├── 姓名* [________] 英文名 [________]      │
│  ├── 头像 [上传区域]                         │
│  ├── 性别 (○)男 (○)女 (○)未知               │
│  ├── 出生日期 [日期选择器]                   │
│  ├── 国籍 [下拉选择]                         │
│  └── 分类 [多选标签]                         │
├─────────────────────────────────────────────┤
│  详细信息                                    │
│  ├── 摘要 [多行文本]                         │
│  └── 传记 [富文本编辑器]                     │
├─────────────────────────────────────────────┤
│  扩展信息                                    │
│  ├── 代表作品 [多选下拉]                     │
│  └── 社交媒体 [动态表格]                     │
├─────────────────────────────────────────────┤
│  [取消]  [保存]                              │
└─────────────────────────────────────────────┘
```

---

### Day 6（周六）：作品管理 + 爬虫管理

**目标**：实现作品管理和爬虫管理

| 任务 | 产出 | 依赖 |
|------|------|------|
| 实现作品列表 | `pages/Work/List.tsx` | 类似艺人列表 |
| 实现作品编辑 | `pages/Work/Edit.tsx` | 动态表单 |
| 实现爬虫任务列表 | `pages/Crawler/List.tsx` | Backend API |
| 实现爬虫任务详情 | `pages/Crawler/Detail.tsx` | Backend API |
| 实现实时日志组件 | `components/LogViewer/` | WebSocket |
| 实现爬虫配置表单 | `pages/Crawler/Config.tsx` | Ant Design Form |

**爬虫任务状态流转**：
```
待启动 → 运行中 → 已完成
   ↓       ↓        ↓
        已停止    失败 → 重新运行
```

---

### Day 7（周日）：对话管理 + 系统监控

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

## Week 5：完善与优化

### Day 8-9（周一-周二）：系统配置 + 优化

| 任务 | 产出 | 说明 |
|------|------|------|
| 实现系统配置页 | `pages/Settings/` | 分类配置表单 |
| 实现用户管理 | `pages/Settings/Users.tsx` | 超级管理员权限 |
| 响应式适配 | 全局 | 平板/手机端 |
| 性能优化 | 全局 | 懒加载、代码分割 |
| 错误边界 | `components/ErrorBoundary/` | 全局错误捕获 |
| 加载状态优化 | 全局 | Skeleton屏 |

### Day 10-11（周三-周四）：测试与Bug修复

| 任务 | 产出 | 说明 |
|------|------|------|
| 单元测试 | `tests/` | Jest + React Testing Library |
| 集成测试 | - | 关键流程端到端测试 |
| Bug修复 | - | 测试中发现的问题 |
| 代码审查 | - | 团队内Review |

### Day 12-13（周五-周六）：文档与部署

| 任务 | 产出 | 说明 |
|------|------|------|
| 编写使用文档 | `docs/admin/usage.md` | 管理员使用指南 |
| 编写部署文档 | `docs/admin/deployment.md` | 部署说明 |
| 构建生产包 | `dist/` | Vite build |
| Dockerfile | `Dockerfile` | 容器化 |

### Day 14（周日）：验收

| 任务 | 产出 | 负责人 |
|------|------|--------|
| 功能验收 | 验收报告 | PM |
| 性能验收 | 性能测试报告 | Frontend |
| 安全验收 | 安全检查 | Backend |

---

## 技术要点

### 状态管理

```typescript
// store/admin.ts
interface AdminState {
  // 用户信息
  user: AdminUser | null
  token: string | null
  
  // 权限
  permissions: string[]
  
  // 全局状态
  collapsed: boolean  // 侧边栏折叠
  theme: 'light' | 'dark'
  
  // 通知
  notifications: Notification[]
}
```

### 路由配置

```typescript
// router/index.tsx
const routes = [
  { path: '/admin/login', component: Login, noAuth: true },
  { path: '/admin/dashboard', component: Dashboard, auth: true },
  { path: '/admin/persons', component: PersonList, auth: true },
  { path: '/admin/persons/:id', component: PersonDetail, auth: true },
  { path: '/admin/persons/:id/edit', component: PersonEdit, auth: true, permission: 'person:edit' },
  // ...
]
```

### API封装

```typescript
// api/client.ts
const adminClient = axios.create({
  baseURL: '/api/v1/admin',
  timeout: 10000,
})

// 请求拦截器 - 添加Token
adminClient.interceptors.request.use((config) => {
  const token = useAdminStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器 - 处理401
adminClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = '/admin/login'
    }
    return Promise.reject(error)
  }
)
```

---

## 验收标准

| 检查项 | 标准 | 优先级 |
|--------|------|--------|
| 登录功能 | 正常登录，Token管理 | P0 |
| 权限控制 | 不同角色显示不同菜单 | P0 |
| 艺人列表 | 搜索、筛选、分页正常 | P0 |
| 艺人编辑 | 表单验证，保存成功 | P0 |
| 爬虫控制 | 启动/停止，日志实时 | P0 |
| 看板图表 | 数据正确，图表渲染 | P0 |
| 响应式 | 平板端可用 | P1 |
| 单元测试 | 覆盖率 ≥ 60% | P1 |
| 构建成功 | 无错误，无警告 | P0 |

---

**进度跟踪**：见项目看板 `docs/project-board.md`
