# StarMap Admin

StarMap 后台管理端 - 面向系统管理员和数据运营人员的管理平台。

## 技术栈

- React 18 + TypeScript 5
- Vite 4 (构建工具)
- Ant Design 5 (UI 组件库)
- React Query 4 (数据获取)
- Zustand 4 (状态管理)
- React Router 6 (路由)
- ECharts 5 (图表)

## 快速启动

### 前提条件

- Node.js >= 18
- npm >= 9

### 安装依赖

```bash
cd frontend-admin
npm install
```

### 开发模式

```bash
npm run dev
```

- 本地地址：http://localhost:5174
- 代理配置：Vite 开发服务器会自动代理 `/api` 请求到 `http://localhost:8000`

### 生产构建

```bash
npm run build
```

构建产物输出到 `dist/` 目录。

### 预览构建产物

```bash
npm run preview
```

- 本地地址：http://localhost:4173

## 项目结构

```
frontend-admin/
├── src/
│   ├── api/              # API 接口封装
│   │   ├── client.ts     # Axios 客户端（含拦截器）
│   │   ├── auth.ts       # 认证 API
│   │   ├── dashboard.ts  # 看板 API
│   │   ├── person.ts     # 艺人 API
│   │   ├── crawler.ts    # 爬虫 API
│   │   ├── conversation.ts # 对话 API
│   │   ├── monitor.ts    # 监控 API
│   │   └── settings.ts   # 配置 API
│   ├── components/       # 公共组件
│   │   ├── Layout/       # 布局框架
│   │   ├── Header/       # 顶部栏
│   │   ├── Sider/        # 侧边栏菜单
│   │   ├── StatCard/     # 统计卡片
│   │   └── Chart/        # 图表组件
│   ├── pages/            # 页面组件
│   │   ├── Login/        # 登录页
│   │   ├── Dashboard/    # 数据看板
│   │   ├── Person/       # 艺人管理（列表/详情/编辑）
│   │   ├── Work/         # 作品管理
│   │   ├── Crawler/      # 爬虫管理
│   │   ├── Conversation/ # 对话管理
│   │   ├── Monitor/      # 系统监控
│   │   └── Settings/     # 系统配置
│   ├── router/           # 路由配置
│   ├── store/            # Zustand 状态管理
│   ├── types/            # TypeScript 类型定义
│   ├── hooks/            # 自定义 Hooks
│   └── utils/            # 工具函数
├── package.json
├── tsconfig.json
├── vite.config.ts
└── Dockerfile.dev
```

## 功能模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 数据看板 | `/admin/dashboard` | 核心指标、趋势图表 |
| 艺人管理 | `/admin/persons` | 艺人 CRUD、搜索筛选 |
| 作品管理 | `/admin/works` | 作品列表管理 |
| 爬虫管理 | `/admin/crawler` | 任务控制、实时日志 |
| 对话管理 | `/admin/conversations` | 记录查看、质量分析 |
| 系统监控 | `/admin/monitor` | API 性能、数据库状态 |
| 系统配置 | `/admin/settings` | LLM 参数、搜索权重等 |

## API 配置

开发环境下，Vite 代理配置（`vite.config.ts`）：

```typescript
server: {
  port: 5174,
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
}
```

所有管理端 API 以 `/api/v1/admin` 为前缀。

## 开发规范

- 使用封装好的 API 方法，不直接调用 axios
- 所有组件使用 TypeScript 类型
- 错误状态必须处理（message.error）
- 列表页必须支持加载状态（Spin / Skeleton）
- 表单提交必须显示 loading 状态

## 脚本说明

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器 |
| `npm run build` | 生产构建 |
| `npm run preview` | 预览构建产物 |
| `npm run lint` | ESLint 检查 |
| `npm run format` | Prettier 格式化 |
