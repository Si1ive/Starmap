# 408 平台版本控制机制

## 状态：✅ 已配置

---

## 快速开始

### 1. 创建GitHub仓库

访问：https://github.com/new

填写信息：
- Repository name: `starmap`（当前远程仓库名）
- Description: `408考研智能学习平台`
- Visibility: Public（推荐，可展示）或 Private
- Initialize: ❌ 不要勾选（已有本地仓库）

### 2. 关联远程仓库

```bash
# 添加远程仓库
git remote add origin https://github.com/Si1ive/starmap.git

# 推送main分支
git push -u origin main

# 推送develop分支
git checkout develop
git push -u origin develop
```

### 3. 验证

```bash
# 查看远程仓库
git remote -v

# 查看分支
git branch -a
```

---

## 分支策略：Git Flow

```
main (生产分支，永远稳定)
  ↑
develop (开发分支，集成测试通过)
  ↑
feature/backend-api (后端功能分支)
feature/frontend-search (前端功能分支)
feature/data-crawler (数据功能分支)
  ↑
hotfix/neo4j-timeout (紧急修复分支)
release/v0.1.0 (发布准备分支)
```

### 分支说明

| 分支 | 用途 | 来源 | 合并到 |
|------|------|------|--------|
| `main` | 生产环境 | - | - |
| `develop` | 开发集成 | main | main |
| `feature/*` | 功能开发 | develop | develop |
| `hotfix/*` | 紧急修复 | main | main + develop |
| `release/*` | 发布准备 | develop | main + develop |

---

## 提交规范

### 格式
```
<类型>(<范围>): <描述>

[可选的详细描述]

[可选的Footer]
```

### 类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(backend): 添加对话API` |
| `fix` | 修复 | `fix(frontend): 修复搜索框样式` |
| `docs` | 文档 | `docs(api): 更新接口文档` |
| `refactor` | 重构 | `refactor(db): 优化Neo4j查询` |
| `test` | 测试 | `test(agent): 添加意图识别测试` |
| `chore` | 构建/工具 | `chore(deps): 升级FastAPI版本` |

### 范围

| 范围 | 说明 |
|------|------|
| `backend` | 后端代码 |
| `frontend` | 前端代码 |
| `data` | 数据相关 |
| `api` | 接口文档 |
| `db` | 数据库 |
| `agent` | Agent核心 |
| `crawler` | 爬虫 |
| `docs` | 项目文档 |
| `devops` | 运维配置 |

---

## 版本号规范（Semantic Versioning）

```
版本格式：MAJOR.MINOR.PATCH

MAJOR：不兼容的API变更
MINOR：向下兼容的功能添加
PATCH：向下兼容的问题修复
```

### 版本历史

| 版本 | 时间 | 说明 |
|------|------|------|
| v0.1.0 | Week 2 | MVP发布 |
| v0.2.0 | Week 3 | 功能完善 |
| v0.3.0 | Week 5 | 扩展优化 |
| v1.0.0 | Week 6 | 正式发布 |

---

## 常用操作

### 开始新功能

```bash
# 从develop创建功能分支
git checkout develop
git pull origin develop
git checkout -b feature/backend-api-chat

# 开发完成后
git add .
git commit -m "feat(backend): 添加对话API"
git push origin feature/backend-api-chat

# 创建PR合并到develop（GitHub上操作）
```

### 紧急修复

```bash
# 从main创建热修复分支
git checkout main
git pull origin main
git checkout -b hotfix/neo4j-timeout

# 修复完成后
git add .
git commit -m "fix(db): 修复Neo4j连接超时"
git push origin hotfix/neo4j-timeout

# 合并到main和develop（GitHub上操作）
```

### 发布新版本

```bash
# 使用发布脚本
./scripts/release.sh v0.1.0

# 或手动操作
./scripts/version-bump.sh minor
git push origin main
git push origin develop
git push origin v0.1.0
```

### 回滚版本

```bash
# 回滚到上一个版本
./scripts/rollback.sh HEAD~1

# 回滚到指定标签
./scripts/rollback.sh v0.1.0

# 或手动操作
git log --oneline  # 查看历史
git revert HEAD    # 撤销上一次提交
git reset --hard v0.1.0  # 强制回滚（危险！）
```

---

## 多会话协作工作流

### 场景：4个会话并行开发

```bash
# 会话1：后端开发
git checkout develop
git pull origin develop
git checkout -b feature/backend-api-chat
# ... 开发 ...
git add .
git commit -m "feat(backend): 添加对话API"
git push origin feature/backend-api-chat

# 会话2：前端开发
git checkout develop
git pull origin develop
git checkout -b feature/frontend-search-page
# ... 开发 ...
git add .
git commit -m "feat(frontend): 添加搜索页面"
git push origin feature/frontend-search-page

# 会话3：数据开发
git checkout develop
git pull origin develop
git checkout -b feature/data-crawler-v2
# ... 开发 ...
git add .
git commit -m "feat(data): 优化爬虫框架"
git push origin feature/data-crawler-v2

# 会话4：PM合并
git checkout develop
git merge feature/backend-api-chat
git merge feature/frontend-search-page
git merge feature/data-crawler-v2
git push origin develop
```

### 冲突解决

```bash
# 拉取最新代码
git fetch origin

# 合并时冲突
git merge feature/xxx

# 查看冲突文件
git status

# 手动解决冲突后
git add .
git commit -m "merge: 合并功能分支"
```

---

## CI/CD配置

### GitHub Actions

文件：`.github/workflows/ci.yml`

触发条件：
- push到main或develop分支
- 创建PR到main或develop分支

执行内容：
- 后端测试（pytest）
- 前端构建（npm run build）

---

## 脚本工具

| 脚本 | 用途 | 示例 |
|------|------|------|
| `scripts/git-setup.sh` | 初始化Git配置 | `./scripts/git-setup.sh` |
| `scripts/version-bump.sh` | 升级版本号 | `./scripts/version-bump.sh patch` |
| `scripts/release.sh` | 发布新版本 | `./scripts/release.sh v0.1.0` |
| `scripts/rollback.sh` | 回滚版本 | `./scripts/rollback.sh v0.1.0` |

---

## 注意事项

### 禁止操作

- ❌ 直接在main分支开发
- ❌ 强制推送（`git push -f`）
- ❌ 提交敏感信息（API Key、密码）
- ❌ 提交大文件（>100MB）

### 必须操作

- ✅ 每次开发前拉取最新代码
- ✅ 提交前检查变更内容
- ✅ 写有意义的提交信息
- ✅ 功能完成后及时合并

---

## 故障排查

### 问题：推送被拒绝

```bash
# 原因：远程有更新，本地未同步
# 解决：
git pull origin develop
git push origin feature/xxx
```

### 问题：合并冲突

```bash
# 查看冲突文件
git status

# 解决冲突后
git add .
git commit -m "merge: 解决冲突"
```

### 问题：误删分支

```bash
# 查看引用日志
git reflog

# 恢复分支
git checkout -b feature/xxx <commit-hash>
```

---

## 参考

- [Git Flow工作流](https://www.gitflow.com/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)
