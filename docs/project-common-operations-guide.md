# 项目常见操作指南

本文档集中记录项目开发、部署和故障处理过程中经常需要手动执行的操作。新增操作时，
应同时写明适用场景、执行命令、验证方式和禁止事项。

## 数据库版本、迁移与结构故障修复

### 为什么数据库也有“版本”

这里的数据库版本不是 MySQL 软件版本，而是当前数据库已经执行到哪一份
**Alembic 结构迁移脚本**。

代码更新时可能新增表、字段、索引或外键。例如，代码开始读取
`agent_runs.parent_run_id` 前，数据库必须先执行创建该字段的迁移。项目通过
MySQL 中的 `alembic_version` 表记录已经执行到的迁移 revision：

```text
应用代码 ──依赖──> 数据库表结构
                         │
                         └── alembic_version 记录迁移位置
```

因此，一次完整发布包含两个同步动作：

1. 更新应用代码。
2. 对应用正在连接的 MySQL 执行 `alembic upgrade head`。

如果只更新代码，新代码就可能访问旧数据库中不存在的字段，进而出现：

```text
Unknown column 'agent_runs_x.parent_run_id' in 'where clause'
```

### 为什么问题可能反复出现

常见原因如下：

- 拉取了新代码，但直接启动 `uvicorn`，没有先执行 Alembic 迁移。
- MySQL 使用持久化数据卷；重建后端容器不会重建已有数据库。
- 在宿主机数据库执行了迁移，但后端实际连接的是容器中的另一个数据库，或反过来。
- 开发、测试和生产使用不同的 `MYSQL_HOST` / `MYSQL_DATABASE`，迁移执行到了错误的库。
- 使用过 `alembic stamp head`。`stamp` 只修改版本记录，不会真正创建表或字段。
- 迁移执行中途失败、数据库从旧备份恢复，或者有人手工修改过表结构。
- 使用热更新替换了代码，但旧 Worker 仍在运行，没有经过完整的启动检查。

注意：`alembic current` 显示最新，只能证明版本记录是最新。如果数据库曾被
`stamp` 或手工修改，真实表结构仍可能不完整。本项目启动时还会检查 Agent Worker
必需的关键字段，以便尽早发现这类 schema drift。

### 快速修复

纯本地后端运行方式：

```bash
cd backend
source venv/bin/activate
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current
```

Podman 后端容器正在运行时：

```bash
podman exec starmap-backend alembic -c alembic.ini upgrade head
podman exec starmap-backend alembic -c alembic.ini current
podman-compose -f docker-compose.podman.yml restart backend
```

如果后端因为数据库版本问题无法启动，使用一次性容器执行迁移：

```bash
podman-compose -f docker-compose.podman.yml run --rm backend \
  alembic -c alembic.ini upgrade head
podman-compose -f docker-compose.podman.yml up -d backend
```

### 标准诊断流程

#### 1. 查看代码要求的最新迁移版本

```bash
cd backend
source venv/bin/activate
alembic -c alembic.ini heads
```

#### 2. 查看当前数据库记录的迁移版本

```bash
alembic -c alembic.ini current
```

如果 `current` 与 `heads` 不一致，说明数据库迁移落后，执行：

```bash
alembic -c alembic.ini upgrade head
```

#### 3. 确认迁移命令与后端连接的是同一个数据库

本地运行时：

```bash
env | grep '^MYSQL_'
```

容器运行时：

```bash
podman exec starmap-backend env | grep '^MYSQL_'
```

重点检查：

- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_DATABASE`

#### 4. 版本一致时检查真实表结构

如果 `current` 与 `heads` 一致但仍出现 `Unknown column`，说明
`alembic_version` 与真实表结构不一致。

进入项目 MySQL 容器：

```bash
# 命令会提示输入密码；开发环境默认密码为 starmap123
podman exec -it starmap-mysql mysql -u starmap -p starmap
```

进入 MySQL 后执行：

```sql
USE starmap;
SELECT version_num FROM alembic_version;
SHOW COLUMNS FROM agent_runs LIKE 'parent_run_id';
SHOW COLUMNS FROM agent_runs LIKE 'root_run_id';
```

#### 5. 重启后端并检查日志

```bash
podman-compose -f docker-compose.podman.yml restart backend
podman-compose -f docker-compose.podman.yml logs --tail=200 backend
```

修复后不应再出现 `Unknown column`，启动日志中应出现“数据库结构版本校验通过”。

### `parent_run_id` 缺失专项修复

适用错误：

```text
Unknown column 'agent_runs_3.parent_run_id' in 'where clause'
```

仓库迁移 `20260723_repair_agent_parent` 会幂等地检查并补齐：

- `agent_runs.parent_run_id` 字段；
- `idx_agent_run_parent` 索引；
- `fk_agent_run_parent` 自引用外键。

不需要修改 Worker 查询，也不要删除线程串行执行逻辑，直接执行：

```bash
cd backend
source venv/bin/activate
alembic -c alembic.ini upgrade head
```

执行成功后，当前 migration head 至少应包含 `20260723_repair_agent_parent`。以后仓库
新增迁移时，head 名称会继续变化，应始终以 `alembic heads` 的实际输出为准。

### 禁止使用 `stamp head` 代替修复

以下命令不会执行任何建表或加字段操作：

```bash
alembic -c alembic.ini stamp head
```

它只会告诉 Alembic“假装数据库已经是最新版本”，很容易造成版本记录正常但真实字段
缺失。除非正在进行经过确认的迁移基线接管，否则不要使用 `stamp head`。

如果 `alembic upgrade head` 执行失败，请保留完整错误日志，先解决失败原因再重试；
不要为了绕过报错直接 stamp，也不要删除 `alembic_version` 表。

## Redis 连接状态诊断

### 管理员页面显示“Redis 断开”时先判断真假

管理员端“数据库与资源监控”通过后端 Redis 客户端执行 `INFO`，并根据命令是否成功显示
连接状态。不要只根据页面状态直接重建 Redis，先分别验证 Redis 服务、后端连接配置和监控
接口。

Podman 环境依次执行：

```bash
podman exec starmap-redis redis-cli ping
podman exec starmap-backend env | grep '^REDIS_URL='
podman-compose -f docker-compose.podman.yml logs --tail=100 redis backend
```

正常时第一条命令返回 `PONG`，后端容器中的地址通常应为：

```text
REDIS_URL=redis://redis:6379
```

注意，容器内不能使用 `redis://localhost:6379` 连接另一个容器；容器中的 `localhost`
表示后端容器自身。只有后端直接运行在宿主机时，才通常使用 `redis://localhost:6379`。

再请求管理员监控接口：

```bash
curl -H "Authorization: Bearer <管理员令牌>" \
  http://localhost:8000/api/v1/admin/monitor/database
```

响应中的 Redis 项应包含 `status: connected`、版本、连接数和内存使用量。若 Redis 能返回
`PONG` 但接口仍显示断开，查看后端日志中的“Redis 监控探活失败”；这通常说明监控调用方式
或后端 `REDIS_URL` 有误，而不是 Redis 服务本身停止。

### 本次修复的代码原因

旧监控代码调用了不存在的 `redis_client.client.info()`。`RedisClient` 实际只保存私有
`_client`，因此会触发 `AttributeError`，随后被监控层捕获并错误显示为“断开”。现在统一
通过公开的 `redis_client.info()` 获取指标，监控层不再依赖客户端内部字段。
