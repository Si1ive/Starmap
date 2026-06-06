# 开发日志 - 项目经理

## 日志规范
- 每次会议后记录
- 遇到阻塞立即记录
- 解决后记录方案
- 每天下班前完成每日总结

---

## 2026-06-06

### 22:20 - 23:05

**工作内容：**
- 补齐 FastAPI 与 Scrapy Service 的 Redis 任务闭环
- 将 Scrapy consumer 调整为常驻 `brpop` 模式，单任务子进程执行
- 增加 FastAPI 应用级 Scrapy 事件监听器，持久化进度和日志并广播 WebSocket
- 对齐 Scrapy MySQL 落库字段，避免写入 `works` 和 `person_relations` 不存在列
- 更新管理端任务字段、Docker Compose、API 契约、交付计划和变更日志

**遇到的问题：**
1. 原 Scrapy consumer 依赖 `spider_idle`，空队列时会关闭 spider
2. 单进程循环执行多个 Scrapy 任务会遇到 Twisted reactor 不能重启的问题
3. Scrapy pipeline 写入字段与当前 MySQL 表结构不一致
4. `execute_now` 复用请求会话，后台执行存在 session 生命周期风险

**解决方式：**
1. 使用 Redis `brpop` 常驻消费队列
2. 每个任务启动独立 Python 子进程执行 single 模式
3. 扩展字段写入 `raw_data/properties`，核心字段对齐当前表结构
4. 后台执行和事件监听均使用独立 MySQL session

**验证计划：**
- 后端测试：`PYTHONPATH=backend backend/venv/bin/python -m pytest backend/tests -q`
- 管理端构建：`npm run build`
- 用户端构建：`npm run build`
- Scrapy 服务 Python 编译检查

### 21:42 - 22:20

**工作内容：**
- 以 PM 角色执行 `./scripts/session-start.sh pm`
- 分析爬虫模块现状、现有规范、架构文档、接口文档和任务分配
- 新增爬虫优先交付计划，明确需求、架构、排期、角色分工和验收场景
- 补齐管理端爬虫 API 契约，统一字段和枚举
- 更新架构、决策记录、工程师任务分配和变更日志
- 推进 P0 字段对齐：`task_type`、`failed_count`、`total_requests`、`error_message`、`request_id`

**遇到的问题：**
1. `docs/api/README.md` 为空，但 CHANGELOG 中已有“更新 API 文档”的记录
2. 爬虫任务字段存在 `type/task_type`、`fail_count/failed_count` 不一致风险
3. 后端已有 Scrapy Service 方向代码，但架构文档未明确目标边界
4. 后端模型和初始化 SQL 对任务类型、请求统计、错误信息字段支持不完整

**解决方式：**
1. 将 `docs/api/README.md` 补为爬虫接口契约真相源
2. 在爬虫优先交付计划中列出 P0 对齐清单
3. 在架构文档和决策记录中明确 FastAPI + Redis + Scrapy Service 的目标链路
4. 同步更新后端模型、SQL、管理端类型和接口响应字段

**验证结果：**
- 后端编译检查通过
- 后端测试：`94 passed`
- 管理端构建通过
- 用户端构建通过

**经验教训：**
- 早期开发阶段可以快速试错，但一旦进入前后端联调，必须先冻结 API 和数据体契约
- 爬虫模块跨越多个角色，应先定义边界和验收场景，再进入并行开发

---

## 2024-01-15

### 10:00 - 12:00

**工作内容：**
- 

**遇到的问题：**
- 

**解决方式：**
- 

**经验教训：**
- 

---

## 每日总结 - 2024-01-15

### 今日完成
- [ ] 

### 遇到的问题
- 

### 明日计划
- [ ] 

### 项目状态
- 
