# StarMap 项目变更日志

## 格式说明

每条记录包含：
- **日期**：变更时间
- **会话**：哪个会话（角色）做的变更
- **类型**：feat/fix/docs/refactor/test
- **影响**：影响范围
- **详细描述**：具体变更内容

---

## 2026-06-05

### [会话-PM] 新增团队协作规范
- **类型**：docs
- **影响**：docs/team/
- **描述**：
  - 创建 `docs/team/collaboration-rules.md`
  - 定义"发现即停止"原则
  - 规范数据库变更流程
  - 添加检查清单
- **注意**：@All 请阅读并遵守协作规范

### [会话-Data] 爬虫管理增强模块
- **类型**：feat
- **影响**：backend/ (数据库 + API)
- **描述**：
  - 新增4个表：crawl_sources, crawl_source_stats, crawl_schedules, crawl_schedule_runs
  - 修改现有表结构
  - 创建SQL迁移脚本
  - 实现4个服务层：CrawlerSourceService, CrawlerStatsService, CrawlerScheduleService, CrawlerLogService
  - 扩展18个管理API端点
  - 集成BaseCrawler自动日志写入
  - 添加WebSocket实时日志流功能
- **注意**：@Backend 请确认API端点与前端对接需求

### [会话-Backend] 修复演示数据导入脚本
- **类型**：fix
- **影响**：scripts/
- **描述**：
  - 适配Podman容器运行时
  - 修复MySQL数据导入时字段名不匹配问题
  - 验证搜索API返回真实数据
- **注意**：@All 现在使用Podman替代Docker

### [会话-PM] 工程师任务分配与开发路线
- **类型**：docs
- **影响**：docs/roadmap/
- **描述**：
  - 制定Sprint 3开发计划（2周）
  - 分配Backend/Frontend/Data角色任务
  - 更新项目看板

### [会话-PM] 爬虫管理模块增强计划
- **类型**：docs
- **影响**：docs/
- **描述**：
  - 编写爬虫管理增强需求文档
  - 定义前后端开发路线

### [会话-Backend] 更新API接口文档
- **类型**：docs
- **影响**：docs/api/
- **描述**：
  - 同步后端代码更新API文档
  - 补充爬虫管理相关接口
- **注意**：@Frontend 请按最新文档对接

### [会话-Backend] 迁移到Podman容器运行时
- **类型**：feat
- **影响**：docker-compose.yml, scripts/
- **描述**：
  - 将Docker Compose配置迁移到Podman
  - 更新启动脚本适配Podman
- **注意**：@All 需要安装Podman并了解基本命令

---

## 2026-06-04

### [会话-Backend] 引入MySQL作为主存储
- **类型**：feat
- **影响**：backend/, docker-compose.yml
- **描述**：
  - 添加MySQL数据库支持
  - 创建MySQL连接模块
  - 添加MySQL数据模型
  - 创建数据库初始化脚本
  - 创建同步到Neo4j脚本
  - 创建MySQL连接测试
  - 更新requirements.txt添加mysql-connector-python
- **注意**：@Backend 需要配置MySQL环境变量

### [会话-Frontend] 实现核心页面功能和组件
- **类型**：feat
- **影响**：frontend/
- **描述**：
  - 实现搜索页面（真实搜索功能，对接API）
  - 实现人物详情页（完整信息展示）
  - 实现对话页面（消息发送接收）
  - 实现关系图谱页（D3.js力导向图）
  - 实现领域浏览页（分类展示）
  - 添加错误边界组件
  - 添加加载组件
  - 添加人物卡片组件
  - 更新API客户端封装
  - 更新状态管理（Zustand）
- **注意**：@Backend 前端已对接API，请确保后端服务正常运行

### [会话-Backend] 完善人物数据模型和服务层
- **类型**：feat
- **影响**：backend/
- **描述**：
  - 扩展Person模型字段（name_en, gender, categories等）
  - 更新人物服务层支持新字段
  - 更新Neo4j连接封装
- **注意**：@Data 爬虫采集时需要填充新字段

### [会话-Backend] 添加后台管理端项目
- **类型**：feat
- **影响**：frontend-admin/
- **描述**：
  - 创建独立的后台管理前端项目
  - 配置React + Ant Design Pro框架
  - 添加用户管理、人物管理、数据管理页面
  - 添加启动文档
- **注意**：@Frontend 管理端使用独立项目，技术栈有差异

### [会话-Backend] 更新项目文档和架构设计
- **类型**：docs
- **影响**：docs/
- **描述**：
  - 大幅更新README，添加项目介绍和快速开始
  - 添加MySQL数据模型设计（表结构、索引、关系）
  - 更新系统架构文档，反映MySQL集成
  - 更新决策记录，添加技术选型决策
  - 更新项目看板，反映当前进度
  - 更新PRD和开发路线图
  - 添加MySQL集成总结文档

### [会话-Backend] 更新Docker Compose配置
- **类型**：chore
- **影响**：docker-compose.yml
- **描述**：
  - 添加MySQL服务配置
  - 更新后端服务依赖
  - 添加健康检查

---

## 2026-06-03

### [会话-PM] 初始化StarMap项目
- **类型**：feat
- **影响**：项目整体
- **描述**：
  - 创建项目目录结构
  - 初始化Git仓库
  - 创建基础文档体系

### [会话-Backend] 添加版本控制机制
- **类型**：feat
- **影响**：docs/tech/, scripts/
- **描述**：
  - 创建Git Flow分支策略文档
  - 创建版本号规范
  - 创建发布流程文档
  - 添加版本升级脚本
  - 添加发布脚本
  - 添加回滚脚本

### [会话-Backend] 添加Git提交规范
- **类型**：docs
- **影响**：docs/tech/
- **描述**：
  - 创建Git提交规范文档
  - 定义提交信息格式
  - 规范提交时机

### [会话-Backend] 添加开发日志规范
- **类型**：docs
- **影响**：docs/tech/, docs/logs/
- **描述**：
  - 创建开发日志规范文档
  - 创建各角色日志模板
  - 创建问题追踪表
  - 创建技术知识库

### [会话-Backend] 添加命令执行规范
- **类型**：docs
- **影响**：docs/tech/
- **描述**：
  - 创建命令执行透明度规范
  - 定义执行前/后模板
  - 规范命令分类说明

---

## 2024-01-15

### [会话-PM] 项目初始化
- **类型**：docs
- **影响**：项目文档
- **描述**：
  - 创建项目目录结构
  - 创建团队角色文档（PM/Backend/Frontend/Data）
  - 创建开发路线图
  - 创建技术文档

### [会话-Backend] 后端框架搭建
- **类型**：feat
- **影响**：backend/
- **描述**：
  - 初始化FastAPI项目
  - 配置Docker Compose
  - 添加基础API路由

### [会话-Frontend] 前端框架搭建
- **类型**：feat
- **影响**：frontend/
- **描述**：
  - 初始化React + Vite项目
  - 配置Ant Design
  - 添加基础路由

### [会话-Data] 数据模型设计
- **类型**：docs
- **影响**：docs/tech/data-model.md
- **描述**：
  - 设计Neo4j图模型
  - 定义实体关系

---

## 模板

```markdown
### [会话-角色] 变更标题
- **类型**：feat/fix/docs/refactor/test
- **影响**：影响范围
- **描述**：
  - 具体变更1
  - 具体变更2
- **注意**：需要其他会话注意的事项
```

---

## 使用说明

1. **每次变更后**，在顶部添加新记录
2. **切换会话前**，阅读最新变更记录
3. **遇到问题时**，查看相关变更记录
