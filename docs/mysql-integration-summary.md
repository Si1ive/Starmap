# MySQL 引入实施总结

## 实施时间

2026-06-04

## 实施内容

### 1. Docker 环境配置

- **文件**: `docker-compose.yml`
- **变更**: 新增 MySQL 8.0 服务
- **配置**:
  - 端口: 3306
  - 数据库: starmap
  - 用户: starmap / starmap123
  - 字符集: utf8mb4
  - 内存限制: 512MB
  - 健康检查: 每10秒检查一次

### 2. 数据库初始化

- **文件**: `backend/scripts/init_mysql.sql`
- **内容**: 完整的建表脚本，包含:
  - persons（人物表）
  - works（作品表）
  - person_works（人物-作品关联表）
  - person_relations（人物关系表）
  - crawl_tasks（爬虫任务表）
  - crawl_logs（爬虫日志表）
  - admin_users（管理员用户表）
  - audit_logs（审计日志表）
  - 默认管理员账号（admin / admin123）
  - 统计视图（v_crawl_summary, v_person_summary）

### 3. MySQL 连接封装

- **文件**: `backend/app/db/mysql.py`
- **功能**:
  - 异步连接池管理（10连接，最大20）
  - 会话上下文管理器（自动事务）
  - 健康检查
  - CRUD 封装（get_by_id, create, update, delete, count）
  - 原始 SQL 执行
  - 全局客户端实例（依赖注入）

### 4. ORM 模型

- **文件**: `backend/app/models/mysql_models.py`
- **技术**: SQLAlchemy 2.0 声明式模型
- **模型**:
  - Person（人物）
  - Work（作品）
  - PersonWork（人物-作品关联）
  - PersonRelation（人物关系）
  - CrawlTask（爬虫任务）
  - CrawlLog（爬虫日志）
  - AdminUser（管理员用户）
  - AuditLog（审计日志）

### 5. 配置更新

- **文件**: `backend/app/core/config.py`
- **新增环境变量**:
  - MYSQL_HOST
  - MYSQL_PORT
  - MYSQL_USER
  - MYSQL_PASSWORD
  - MYSQL_DATABASE

### 6. 依赖更新

- **文件**: `backend/requirements.txt`
- **新增依赖**:
  - sqlalchemy[asyncio]==2.0.0
  - asyncmy==0.2.8
  - aiomysql==0.2.0

### 7. 同步脚本

- **文件**: `backend/scripts/sync_to_neo4j.py`
- **功能**:
  - 全量同步（所有数据）
  - 增量同步（按时间）
  - 单表同步（仅人物/仅关系）
  - 人物-作品关系同步
  - 同步报告生成

### 8. 初始化脚本

- **文件**: `backend/scripts/init_database.py`
- **功能**:
  - 初始化所有数据库（MySQL + Neo4j + ChromaDB）
  - 单独初始化指定数据库
  - 连接状态检查

### 9. 文档更新

- **架构文档**: `docs/tech/architecture.md`
  - 更新系统架构图（添加 MySQL）
  - 更新数据库职责划分
  - 更新部署架构
  - 添加 MySQL ↔ Neo4j 同步机制

- **数据模型文档**: `docs/tech/data-model.md`
  - 重写为 MySQL + Neo4j 双存储架构
  - 添加完整的 MySQL 表结构（含索引、注释）
  - 更新 Neo4j 图模型（精简版）
  - 添加数据流图
  - 添加同步策略说明

- **决策记录**: `docs/DECISIONS.md`
  - 添加 MySQL 引入决策记录

- **项目看板**: `docs/project-board.md`
  - 添加 MySQL 相关任务（10个）
  - 更新阻塞问题列表
  - 更新里程碑检查项
  - 更新变更记录

## 架构变化

### 引入前

```
Neo4j（唯一主存储）
  ├── 人物属性
  ├── 作品信息
  ├── 关系网络
  └── 爬虫日志
```

### 引入后

```
MySQL（主存储）          Neo4j（图数据库）
  ├── 人物属性              ├── 人物节点
  ├── 作品信息              ├── 作品节点
  ├── 关系数据              └── 关系边
  ├── 爬虫任务/日志
  ├── 管理员用户
  └── 审计日志
```

## 数据同步策略

| 数据操作 | 同步方式 | 说明 |
|---------|---------|------|
| 人物创建 | 异步 | 写入MySQL后，后台任务同步到Neo4j |
| 人物更新 | 异步 | 更新MySQL后，延迟同步到Neo4j |
| 关系创建 | **同步** | 必须保证图数据库一致性 |
| 关系删除 | **同步** | 必须保证图数据库一致性 |
| 批量导入 | 异步 | 使用队列批量同步 |

## 下一步工作

1. **安装 Docker**: 本地开发环境需要安装 Docker 才能启动 MySQL 服务
2. **安装 Python 依赖**: 执行 `pip install -r requirements.txt`
3. **启动服务**: `docker-compose up -d mysql`
4. **初始化数据库**: `python scripts/init_database.py --all`
5. **测试同步**: `python scripts/sync_to_neo4j.py --full`
6. **更新爬虫导入脚本**: 修改 `scripts/import_neo4j.py` 为 `scripts/import_mysql.py`
7. **后端 API 改造**: 查询接口从 Neo4j 改为 MySQL
8. **测试验证**: 确保所有 CRUD 操作正常

## 影响评估

| 方面 | 影响 | 应对措施 |
|------|------|---------|
| 运维复杂度 | 增加一个数据库 | Docker Compose 统一管理 |
| 开发工作量 | 需要改造查询接口 | 逐步迁移，先写后读 |
| 数据一致性 | 需要同步机制 | 同步脚本 + 队列重试 |
| 性能 | 列表查询提升 | MySQL 索引优化 |
| 存储成本 | 数据冗余 | Neo4j 仅存核心属性 |

## 负责人

- **Backend**: MySQL 连接模块、ORM 模型、同步脚本
- **Data**: 数据迁移、同步验证
- **PM**: 文档更新、任务跟踪
