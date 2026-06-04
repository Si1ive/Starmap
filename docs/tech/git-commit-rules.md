# Git 提交规范（强制）

## 核心原则

**每开发一个功能，或做一次完整修改，必须提交一次代码。**

**禁止：**
- ❌ 开发多个功能后才提交
- ❌ 修改多个文件后才提交
- ❌ 长时间工作不提交（超过2小时）
- ❌ 提交信息为空或随意填写

**必须：**
- ✅ 每个独立功能一个提交
- ✅ 每个完整修改一个提交
- ✅ 提交前检查变更内容
- ✅ 写有意义的提交信息

---

## 提交时机

### 什么时候必须提交？

| 场景 | 示例 | 提交信息 |
|------|------|---------|
| 完成一个API接口 | 实现搜索接口 | `feat(backend): 添加人物搜索API` |
| 完成一个组件 | 实现搜索框 | `feat(frontend): 添加搜索框组件` |
| 修复一个Bug | 修复连接超时 | `fix(backend): 修复Neo4j连接超时` |
| 重构代码 | 优化查询逻辑 | `refactor(db): 优化人物查询` |
| 更新文档 | 更新API文档 | `docs(api): 更新搜索接口文档` |
| 添加测试 | 添加单元测试 | `test(backend): 添加搜索接口测试` |

### 什么时候可以提交？

| 场景 | 说明 |
|------|------|
| 工作2小时后 | 即使没有完成功能，也要提交进度 |
| 切换任务前 | 提交当前进度，再切换分支 |
| 下班前 | 提交当天所有工作 |
| 测试通过后 | 功能开发完成并自测通过 |

---

## 提交流程

### 标准流程

```bash
# 1. 检查变更
$ git status

# 2. 查看具体变更
$ git diff

# 3. 添加变更文件（不要 git add .，要逐个检查）
$ git add backend/app/api/search.py
$ git add backend/app/services/search_service.py

# 4. 提交（写有意义的提交信息）
$ git commit -m "feat(backend): 添加人物搜索API

- 实现 GET /api/v1/persons/search
- 支持关键词搜索
- 支持分页
- 添加缓存"

# 5. 推送到远程
$ git push origin feature/backend-search
```

### 提交信息格式

```
<类型>(<范围>): <简短描述>

<详细描述（可选）>

<Footer（可选）>
```

**示例：**

```bash
# 简单提交
$ git commit -m "feat(backend): 添加人物搜索API"

# 详细提交
$ git commit -m "feat(backend): 添加人物搜索API

- 实现 GET /api/v1/persons/search
- 支持关键词搜索和分页
- 添加Redis缓存
- 添加单元测试

Closes #123"
```

---

## 提交类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(backend): 添加对话API` |
| `fix` | 修复Bug | `fix(frontend): 修复搜索框样式` |
| `docs` | 文档更新 | `docs(api): 更新接口文档` |
| `refactor` | 代码重构 | `refactor(db): 优化查询` |
| `test` | 测试相关 | `test(agent): 添加意图识别测试` |
| `chore` | 构建/工具 | `chore(deps): 升级FastAPI` |
| `perf` | 性能优化 | `perf(backend): 优化查询速度` |
| `style` | 代码格式 | `style(frontend): 格式化代码` |

---

## 提交范围

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

## 提交检查清单

提交前必须检查：

- [ ] 变更内容是否正确？
- [ ] 是否只包含相关变更？
- [ ] 提交信息是否清晰？
- [ ] 是否遵循提交规范？
- [ ] 测试是否通过？
- [ ] 是否有敏感信息？

---

## 多会话协作提交规范

### 每个会话的工作流程

```bash
# 1. 开始工作前
$ git checkout develop
$ git pull origin develop
$ git checkout -b feature/角色-功能

# 2. 开发过程中（每2小时或完成功能后）
$ git add <相关文件>
$ git commit -m "feat(范围): 描述"
$ git push origin feature/角色-功能

# 3. 功能完成后
$ git add .
$ git commit -m "feat(范围): 完成功能描述"
$ git push origin feature/角色-功能

# 4. 创建PR合并到develop（GitHub上操作）
```

### 提交频率要求

| 时间 | 要求 |
|------|------|
| 每2小时 | 至少提交一次进度 |
| 完成功能 | 立即提交 |
| 修复Bug | 修复后立即提交 |
| 下班前 | 提交当天所有工作 |

---

## 常见问题

### Q: 功能没做完，可以提交吗？

**A: 可以！** 提交进度，使用WIP标记：

```bash
$ git commit -m "WIP(backend): 对话API开发中

- 完成意图识别
- 待完成：Function Calling"
```

### Q: 修改了多个文件，可以一起提交吗？

**A: 如果相关可以，否则分开提交：**

```bash
# 相关文件一起提交
$ git add backend/app/api/search.py
$ git add backend/app/services/search_service.py
$ git commit -m "feat(backend): 添加搜索功能"

# 不相关文件分开提交
$ git add backend/app/api/search.py
$ git commit -m "feat(backend): 添加搜索API"

$ git add docs/api/README.md
$ git commit -m "docs(api): 更新搜索接口文档"
```

### Q: 提交后发现有问题，怎么办？

**A: 使用修正提交：**

```bash
# 修改文件
$ git add <文件>
$ git commit --amend -m "feat(backend): 添加搜索API"

# 或追加提交
$ git add <文件>
$ git commit -m "fix(backend): 修复搜索API参数验证"
```

---

## 违规处理

| 违规情况 | 处理方式 |
|---------|---------|
| 长时间不提交 | PM提醒，要求立即提交 |
| 提交信息不规范 | 要求修正并重新提交 |
| 提交包含敏感信息 | 立即撤销提交，清理历史 |
| 提交包含无关文件 | 要求拆分提交 |

---

## 示例

### 后端开发示例

```bash
# 开发搜索API
$ git checkout -b feature/backend-search

# 实现模型
$ git add backend/app/models/person.py
$ git commit -m "feat(backend): 添加人物数据模型"

# 实现服务
$ git add backend/app/services/search_service.py
$ git commit -m "feat(backend): 添加搜索服务"

# 实现API
$ git add backend/app/api/search.py
$ git commit -m "feat(backend): 添加搜索API接口"

# 添加测试
$ git add backend/tests/test_search.py
$ git commit -m "test(backend): 添加搜索接口测试"

# 推送
$ git push origin feature/backend-search
```

### 前端开发示例

```bash
# 开发搜索页面
$ git checkout -b feature/frontend-search

# 实现组件
$ git add frontend/src/components/SearchBox.tsx
$ git commit -m "feat(frontend): 添加搜索框组件"

# 实现页面
$ git add frontend/src/pages/Search/index.tsx
$ git commit -m "feat(frontend): 添加搜索页面"

# 对接API
$ git add frontend/src/api/person.ts
$ git commit -m "feat(frontend): 对接搜索API"

# 推送
$ git push origin feature/frontend-search
```
