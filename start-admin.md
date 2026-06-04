# StarMap 后台管理端 - 快速启动指南

## 一键启动

```bash
cd frontend-admin && npm run dev
```

访问 http://localhost:5174

---

## 完整启动流程

### 1. 进入项目目录

```bash
cd frontend-admin
```

### 2. 安装依赖（首次）

```bash
npm install
```

### 3. 启动开发服务器

```bash
npm run dev
```

- 地址：http://localhost:5174
- 代理：自动转发 `/api` 到 http://localhost:8000

---

## 其他常用命令

| 命令 | 作用 |
|------|------|
| `npm run build` | 生产构建 |
| `npm run preview` | 预览构建产物（端口 4173） |
| `npm run lint` | 代码检查 |
| `npm run format` | 代码格式化 |

---

## 项目信息

- **技术栈**：React 18 + TypeScript + Vite + Ant Design
- **状态管理**：Zustand
- **数据获取**：React Query
- **构建产物**：`frontend-admin/dist/`
