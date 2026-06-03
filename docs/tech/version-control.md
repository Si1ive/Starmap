# StarMap 版本控制机制

## 现状分析

**当前状态：**
- ✅ 项目已初始化
- ❌ 缺少版本控制规范
- ❌ 缺少Git工作流
- ❌ 缺少发布管理
- ❌ 缺少回滚机制

**风险：**
- 多会话并行开发可能互相覆盖代码
- 无法追踪哪个版本引入了问题
- 无法快速回滚到稳定版本
- 无法区分开发/测试/生产环境

---

## 需要用户提供的信息

### 1. Git仓库配置

| 信息 | 用途 | 是否必须 |
|------|------|---------|
| **GitHub/GitLab账号** | 创建远程仓库 | 是 |
| **仓库名称** | 例如 `starmap` | 是 |
| **仓库可见性** | 公开/私有 | 是 |
| **是否已创建仓库** | 已创建/未创建 | 是 |

### 2. 协作模式

| 信息 | 选项 | 推荐 |
|------|------|------|
| **分支策略** | Git Flow / GitHub Flow / Trunk Based | Git Flow（适合多角色） |
| **合并方式** | Merge / Squash / Rebase | Squash（保持历史整洁） |
| **代码审查** | 必需/建议/不需要 | 建议（至少自审） |

### 3. 环境配置

| 环境 | 用途 | 配置 |
|------|------|------|
| **开发环境** | 本地开发 | docker-compose.dev.yml |
| **测试环境** | 集成测试 | docker-compose.test.yml |
| **生产环境** | 线上服务 | docker-compose.prod.yml |

---

## 推荐的版本控制方案

### 分支策略：Git Flow

```
main (生产分支，永远稳定)
  ↑
develop (开发分支，集成测试通过)
  ↑
feature/backend-api (后端功能分支)
feature/frontend-search (前端功能分支)
feature/data-crawler (数据功能分支)
  ↑
hotfix/neo4j-connection (紧急修复分支)
```

### 分支命名规范

| 分支类型 | 命名格式 | 示例 |
|---------|---------|------|
| 功能分支 | `feature/<角色>-<功能>` | `feature/backend-api-chat` |
| 修复分支 | `fix/<角色>-<问题>` | `fix/frontend-cors-error` |
| 热修复 | `hotfix/<问题>` | `hotfix/neo4j-timeout` |
| 发布分支 | `release/v<版本>` | `release/v0.1.0` |

### 提交规范

```bash
# 格式：<类型>(<范围>): <描述>

feat(backend): 添加对话API
fix(frontend): 修复搜索框样式
docs(api): 更新接口文档
refactor(db): 优化Neo4j查询
test(agent): 添加意图识别测试
chore(deps): 升级FastAPI版本
```

### 版本号规范（Semantic Versioning）

```
版本格式：MAJOR.MINOR.PATCH

MAJOR：不兼容的API变更（如v1→v2）
MINOR：向下兼容的功能添加（如v0.1→v0.2）
PATCH：向下兼容的问题修复（如v0.1.0→v0.1.1）

示例：
v0.1.0 - MVP发布
v0.2.0 - 添加后台管理
v1.0.0 - 正式发布
```

---

## 需要我创建的文件

### 1. Git配置

```bash
# .gitignore（已创建，需完善）
# .gitattributes
# .github/workflows/ci.yml（GitHub Actions）
```

### 2. 版本管理脚本

```bash
# scripts/version-bump.sh - 版本升级脚本
# scripts/release.sh - 发布脚本
# scripts/rollback.sh - 回滚脚本
```

### 3. 环境配置

```bash
# docker-compose.dev.yml - 开发环境
# docker-compose.test.yml - 测试环境
# docker-compose.prod.yml - 生产环境
```

### 4. 文档

```bash
# docs/tech/version-control.md - 版本控制规范（本文件）
# docs/tech/deployment.md - 部署指南
```

---

## 回滚机制

### 代码回滚

```bash
# 回滚到上一个版本
git revert HEAD

# 回滚到指定版本
git revert <commit-hash>

# 强制回滚（危险！）
git reset --hard <commit-hash>
```

### 数据库回滚

```bash
# Neo4j数据备份/恢复
# 每次发布前备份数据
# 回滚时恢复备份
```

### Docker回滚

```bash
# 使用Docker镜像标签回滚
docker-compose pull
docker-compose up -d

# 回滚到上一个镜像版本
docker-compose down
docker image tag starmap:previous starmap:latest
docker-compose up -d
```

---

## 多会话协作的Git工作流

### 场景：4个会话并行开发

```
会话1（Backend）:
  git checkout -b feature/backend-api-chat
  # 开发API
  git add .
  git commit -m "feat(backend): 添加对话API"
  git push origin feature/backend-api-chat

会话2（Frontend）:
  git checkout -b feature/frontend-search-page
  # 开发搜索页
  git add .
  git commit -m "feat(frontend): 添加搜索页面"
  git push origin feature/frontend-search-page

会话3（Data）:
  git checkout -b feature/data-crawler-v2
  # 开发爬虫
  git add .
  git commit -m "feat(data): 优化爬虫框架"
  git push origin feature/data-crawler-v2

PM（合并）:
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
# 解决冲突文件
git add .
git commit -m "merge: 合并功能分支"
```

---

## 发布管理

### 发布流程

```bash
# 1. 创建发布分支
git checkout -b release/v0.1.0 develop

# 2. 版本升级
# 修改版本号（package.json, pyproject.toml等）

# 3. 最终测试
# 运行测试套件
pytest
npm test

# 4. 合并到main
git checkout main
git merge release/v0.1.0

# 5. 打标签
git tag -a v0.1.0 -m "Release v0.1.0 - MVP"

# 6. 合并回develop
git checkout develop
git merge release/v0.1.0

# 7. 删除发布分支
git branch -d release/v0.1.0
```

### 发布检查清单

- [ ] 所有测试通过
- [ ] 接口文档更新
- [ ] 版本号升级
- [ ] CHANGELOG.md更新
- [ ] Docker镜像构建成功
- [ ] 生产环境配置正确

---

## 请确认以下信息

### 必须提供

1. **GitHub/GitLab账号**：是否已有？是否需要我帮你创建？
2. **仓库名称**：`starmap` 还是其他？
3. **仓库可见性**：公开（展示项目）还是私有？

### 可选配置

4. **CI/CD**：是否需要GitHub Actions自动测试？
5. **代码审查**：是否需要PR Review机制？
6. **环境隔离**：是否需要独立的测试/生产环境？

---

## 下一步

**请提供上述信息，我将：**

1. 初始化Git仓库（如未创建）
2. 配置Git Flow分支策略
3. 创建版本管理脚本
4. 配置GitHub Actions（可选）
5. 创建环境隔离配置

**或者你可以直接告诉我：**
- "使用GitHub，仓库名starmap，私有仓库"
- "帮我配置Git Flow"
- "需要GitHub Actions自动测试"

**我将立即执行配置。**