# 前端开发路线 - 爬虫管理增强

> 版本：v2.0  
> 日期：2026-06-05  
> 负责人：Frontend  
> 状态：规划中

---

## 1. 新增页面清单

### 1.1 页面路由

```typescript
// router/index.tsx 新增路由
const crawlerRoutes = [
  {
    path: '/crawler',
    element: <CrawlerLayout />,
    children: [
      { path: 'dashboard', element: <CrawlerDashboard /> },
      { path: 'sources', element: <CrawlerSourceList /> },
      { path: 'sources/:id', element: <CrawlerSourceDetail /> },
      { path: 'sources/:id/edit', element: <CrawlerSourceEdit /> },
      { path: 'tasks', element: <CrawlerTaskList /> },
      { path: 'tasks/:id', element: <CrawlerTaskDetail /> },
      { path: 'schedules', element: <CrawlerScheduleList /> },
      { path: 'schedules/new', element: <CrawlerScheduleForm /> },
      { path: 'schedules/:id/edit', element: <CrawlerScheduleForm /> },
      { path: 'logs', element: <CrawlerLogList /> },
    ]
  }
]
```

### 1.2 页面组件

| 页面 | 组件路径 | 说明 | 优先级 |
|------|----------|------|--------|
| 统计概览 | `pages/Crawler/Dashboard.tsx` | 核心指标、图表 | P0 |
| 源列表 | `pages/Crawler/SourceList.tsx` | 爬取源管理 | P0 |
| 源详情 | `pages/Crawler/SourceDetail.tsx` | 源配置、统计 | P0 |
| 源编辑 | `pages/Crawler/SourceEdit.tsx` | 添加/编辑源 | P0 |
| 任务列表 | `pages/Crawler/TaskList.tsx` | 任务管理（已有，需增强） | P0 |
| 任务详情 | `pages/Crawler/TaskDetail.tsx` | 实时进度、日志 | P0 |
| 定时任务列表 | `pages/Crawler/ScheduleList.tsx` | 定时任务管理 | P0 |
| 定时任务表单 | `pages/Crawler/ScheduleForm.tsx` | 新建/编辑定时任务 | P0 |
| 日志中心 | `pages/Crawler/LogList.tsx` | 日志查询、实时流 | P0 |

---

## 2. 组件开发计划

### 2.1 复用组件

```typescript
// components/Crawler/
├── StatCard.tsx           // 统计卡片（数值+趋势）
├── ProgressBar.tsx        // 进度条（带百分比）
├── StatusTag.tsx          // 状态标签（颜色+文字）
├── SourceSelector.tsx     // 爬取源选择器
├── CronPicker.tsx         // Cron表达式选择器
├── LogViewer.tsx          // 日志查看器（实时流）
├── ChartCard.tsx          // 图表卡片
└── EfficiencyTable.tsx    // 效率对比表
```

### 2.2 关键组件设计

#### CronPicker 组件

```typescript
interface CronPickerProps {
  value: string;
  onChange: (cron: string) => void;
}

// 支持两种模式：
// 1. 可视化模式：选择 每天/每周/每月/自定义
// 2. 表达式模式：直接输入 Cron 表达式
```

#### LogViewer 组件

```typescript
interface LogViewerProps {
  taskId?: string;
  sourceId?: string;
  realTime?: boolean;
  filter?: LogFilter;
}

// 功能：
// - 自动滚动到底部
// - 高亮 ERROR 级别
// - 支持暂停/继续
// - 支持筛选级别
```

---

## 3. API 对接

### 3.1 新增 API 文件

```typescript
// api/crawler.ts 扩展现有文件
export const getCrawlerSources = (params?: SourceParams) => {...}
export const createCrawlerSource = (data: SourceForm) => {...}
export const updateCrawlerSource = (id: string, data: SourceForm) => {...}
export const deleteCrawlerSource = (id: string) => {...}
export const getCrawlerSourceStats = (id: string, params?: DateRange) => {...}

export const getCrawlerStats = (params?: StatsParams) => {...}
export const getCrawlerTrend = (params?: TrendParams) => {...}
export const getCrawlerEfficiency = (params?: EfficiencyParams) => {...}

export const getCrawlerSchedules = (params?: ScheduleParams) => {...}
export const createCrawlerSchedule = (data: ScheduleForm) => {...}
export const updateCrawlerSchedule = (id: string, data: ScheduleForm) => {...}
export const toggleCrawlerSchedule = (id: string) => {...}
export const getCrawlerScheduleRuns = (id: string, params?: PaginationParams) => {...}

export const getCrawlerLogs = (params?: LogParams) => {...}
export const getCrawlerLogStream = (params?: StreamParams) => {...} // WebSocket
```

### 3.2 类型定义

```typescript
// types/crawler.ts
export interface CrawlerSource {
  id: string;
  name: string;
  code: string;
  type: 'encyclopedia' | 'social' | 'official' | 'news';
  baseUrl: string;
  config: SourceConfig;
  status: 'active' | 'inactive' | 'error' | 'deprecated';
  healthStatus: 'healthy' | 'degraded' | 'down';
  stats: SourceStats;
  createdAt: string;
  updatedAt: string;
}

export interface CrawlerSchedule {
  id: string;
  name: string;
  taskType: 'full' | 'incremental' | 'targeted' | 'health_check' | 'cleanup';
  sourceIds: string[];
  cronExpression: string;
  isEnabled: boolean;
  lastRunAt?: string;
  lastRunStatus?: string;
  nextRunAt?: string;
  totalRuns: number;
  successRuns: number;
  failedRuns: number;
}

export interface CrawlerLog {
  id: number;
  taskId: string;
  sourceId: string;
  level: 'debug' | 'info' | 'success' | 'warning' | 'error' | 'critical';
  stage: 'fetch' | 'parse' | 'validate' | 'store';
  url: string;
  resourceName: string;
  status: 'success' | 'failed' | 'retry' | 'pending';
  durationMs: number;
  message: string;
  details?: Record<string, unknown>;
  createdAt: string;
}
```

---

## 4. 开发顺序

### Week 1

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1 | 搭建页面框架、路由配置 | 可访问的空页面 |
| Day 2 | 爬取源列表页 + 源管理API | 源CRUD可用 |
| Day 3 | 统计概览页 + 图表组件 | 统计报表可用 |
| Day 4 | 任务管理页增强 + 实时日志 | 任务控制可用 |
| Day 5 | 日志中心页 | 日志查询可用 |

### Week 2

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1-2 | 定时任务列表 + 表单 | 定时任务CRUD |
| Day 3 | Cron选择器组件 | 可视化配置 |
| Day 4 | WebSocket实时日志 | 实时推送 |
| Day 5 | 联调 + Bug修复 | 功能完整 |
| Day 6-7 | 优化 + 测试 | 验收通过 |

---

## 5. 技术要点

### 5.1 WebSocket 实时日志

```typescript
// hooks/useLogStream.ts
export const useLogStream = (params: LogStreamParams) => {
  const [logs, setLogs] = useState<CrawlerLog[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/admin/crawler/logs/stream`);
    
    ws.onmessage = (event) => {
      const log = JSON.parse(event.data);
      setLogs(prev => [...prev, log]);
    };
    
    return () => ws.close();
  }, [params]);
  
  return { logs, isConnected };
};
```

### 5.2 图表库选择

```typescript
// 使用 ECharts
import ReactECharts from 'echarts-for-react';

// 趋势图
const trendOption = {
  xAxis: { type: 'category', data: dates },
  yAxis: { type: 'value' },
  series: [
    { name: '请求数', type: 'line', data: requests },
    { name: '成功数', type: 'line', data: successes }
  ]
};

// 效率散点图
const efficiencyOption = {
  xAxis: { name: '请求数', type: 'value' },
  yAxis: { name: '有效数据', type: 'value' },
  series: [{
    type: 'scatter',
    data: sources.map(s => [s.totalRequests, s.validRecords]),
    symbolSize: (data: number[]) => Math.sqrt(data[1]) / 2
  }]
};
```

---

## 6. 验收 checklist

- [ ] 爬取源可添加、编辑、禁用、删除
- [ ] 各源统计准确展示（请求数/成功数/成功率）
- [ ] 定时任务可配置 Cron 表达式
- [ ] 手动任务可启动、停止、查看实时进度
- [ ] 日志可实时查看（WebSocket）
- [ ] 所有数据来自真实 API，无 mock
- [ ] 页面加载 < 3s
- [ ] 图表渲染 < 2s

---

**文档状态**：✅ 已完成  
**下次更新**：Week 1 结束后
