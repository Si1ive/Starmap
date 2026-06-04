# StarMap 团队协作规范

> 版本：v1.0  
> 日期：2026-06-05  
> 适用范围：所有工程师

---

## 1. 核心原则

### 1.1 发现即停止

**当发现以下问题时，立即停止执行，抛出异常，等待人工确认：**

- 数据库表结构与代码预期不一致
- API 接口返回格式与文档描述不符
- 配置文件缺失或配置项不匹配
- 依赖服务版本不兼容
- 环境变量未设置或值异常

**禁止行为：**
- ❌ 猜测字段名并继续执行
- ❌ 假设数据存在而跳过验证
- ❌ 在错误信息不明确时反复重试
- ❌ 修改生产环境配置而不通知团队

---

## 2. 数据库变更规范

### 2.1 变更流程

```
需求提出 → Schema设计 → 迁移脚本 → Code Review → 执行迁移 → 通知全员
```

### 2.2 检查清单

**在修改数据库前，必须确认：**

- [ ] 是否已有其他工程师修改了相同表？
- [ ] 是否检查了最新的迁移脚本？
- [ ] 是否更新了对应的数据模型代码？
- [ ] 是否同步更新了接口文档？
- [ ] 是否通知了所有相关角色的工程师？

### 2.3 字段命名冲突处理

**当发现字段名不匹配时：**

1. **首先检查** `backend/app/models/` 下的模型定义
2. **然后检查** `docs/api/README.md` 接口文档
3. **然后检查** 数据库迁移脚本 `backend/scripts/migrate_*.sql`
4. **然后检查** 其他工程师的最近提交
5. **如果无法确认**，立即在飞书/钉钉群 @相关工程师

**示例：**
```python
# 错误做法：猜测字段名
cursor.execute("SELECT source_person_id FROM person_relations")
# 如果报错，就改成 source_id，再报错就改成 from_person_id...

# 正确做法：先检查
cursor.execute("SHOW COLUMNS FROM person_relations")
# 确认实际字段名后再写代码
```

---

## 3. 代码提交规范

### 3.1 提交信息格式

```
type(scope): subject

body

footer
```

**类型说明：**
- `feat`: 新功能
- `fix`: 修复
- `docs`: 文档
- `style`: 格式（不影响代码逻辑）
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建过程或辅助工具的变动
- `db`: 数据库相关变更（新增类型）

### 3.2 数据库变更提交示例

```bash
# 好的提交信息
db(person_relations): 修改关系表字段名

- source_person_id → source_id
- target_person_id → target_id
- 新增 properties JSON 字段存储扩展信息
- 更新对应的数据模型和接口文档

BREAKING CHANGE: 旧版初始化脚本不再兼容，需同步更新
```

---

## 4. 问题上报模板

### 4.1 数据库不匹配问题

```markdown
## 问题：数据库表结构不匹配

**发现时间**：2026-06-05 03:20
**发现人**：AI Agent / 工程师姓名
**涉及表**：person_relations

### 预期结构（来自代码/文档）
- source_person_id: varchar(32)
- target_person_id: varchar(32)
- relation_desc: text

### 实际结构（来自数据库）
- source_id: varchar(32)
- target_id: varchar(32)
- properties: json

### 影响范围
- [ ] 初始化脚本 scripts/init-demo-data.sh
- [ ] 后端模型 backend/app/models/mysql_models.py
- [ ] API 接口 backend/app/api/admin.py

### 建议处理方案
1. 确认是哪位工程师修改了表结构
2. 同步更新所有相关代码
3. 更新接口文档

### 阻塞状态
- [x] 已阻塞：初始化脚本无法执行
```

### 4.2 API 接口不一致问题

```markdown
## 问题：API 返回格式与文档不符

**发现时间**：2026-06-05 03:25
**API 端点**：/api/v1/persons/search
**文档位置**：docs/api/README.md

### 预期返回（来自文档）
```json
{
  "items": [...],
  "total": 10
}
```

### 实际返回（来自测试）
```json
{
  "data": [...],
  "count": 10
}
```

### 建议处理方案
1. 确认后端实现是否已更新
2. 同步更新前端代码或接口文档
```

---

## 5. 沟通渠道

### 5.1 紧急问题（阻塞开发）

**渠道**：飞书/钉钉群 @所有人  
**响应时间**：15分钟内  
**适用场景**：
- 数据库结构变更导致代码无法运行
- API 接口变更导致前后端联调失败
- 配置文件错误导致服务无法启动

### 5.2 一般问题

**渠道**：GitHub Issues  
**标签**：`bug`, `db-schema`, `api-change`  
**响应时间**：2小时内  
**适用场景**：
- 文档更新
- 代码优化建议
- 非阻塞性Bug

### 5.3 技术讨论

**渠道**：GitHub Issues（带 `discussion` 标签）  
**响应时间**：24小时内  
**适用场景**：
- 技术选型
- 架构设计
- 性能优化方案

---

## 6. 自动化检查

### 6.1 预提交检查

```bash
# 建议在 .git/hooks/pre-commit 中添加
#!/bin/bash

# 检查数据库模型是否与迁移脚本一致
python backend/scripts/check_schema_consistency.py

# 检查接口文档是否与代码一致
python backend/scripts/check_api_docs.py

# 如果有不一致，阻止提交
if [ $? -ne 0 ]; then
    echo "❌ 数据库模型或接口文档不一致，请先同步"
    exit 1
fi
```

### 6.2 CI/CD 检查

```yaml
# .github/workflows/ci.yml
jobs:
  schema-check:
    runs-on: ubuntu-latest
    steps:
      - name: Check Database Schema Consistency
        run: |
          python backend/scripts/check_schema_consistency.py
      - name: Check API Documentation
        run: |
          python backend/scripts/check_api_docs.py
```

---

## 7. 责任划分

### 7.1 数据库变更责任

| 动作 | 负责人 | 通知对象 |
|------|--------|----------|
| 修改表结构 | Backend 工程师 | 所有工程师 |
| 修改字段名 | Backend 工程师 | 所有工程师 |
| 新增表 | Backend 工程师 | 所有工程师 |
| 修改初始化脚本 | Data 工程师 | Backend 工程师 |

### 7.2 接口变更责任

| 动作 | 负责人 | 通知对象 |
|------|--------|----------|
| 修改 API 路径 | Backend 工程师 | Frontend 工程师 |
| 修改返回格式 | Backend 工程师 | Frontend 工程师 |
| 修改请求参数 | Backend 工程师 | Frontend 工程师 |
| 更新接口文档 | Backend 工程师 | 所有工程师 |

---

## 8. 常见问题 FAQ

### Q1: 我发现数据库字段名和代码不一致，怎么办？

**A:** 立即停止执行，按照以下顺序检查：
1. 查看 `backend/app/models/` 下的模型定义
2. 查看 `docs/api/README.md` 接口文档
3. 查看数据库迁移脚本 `backend/scripts/migrate_*.sql`
4. 查看 Git 提交历史 `git log --oneline --all --grep="db\|schema\|migrate"`
5. 如果还是无法确认，在飞书/钉钉群 @Backend 工程师

### Q2: 我可以直接修改数据库表结构吗？

**A:** 不可以。必须通过以下流程：
1. 在 GitHub Issues 创建变更申请
2. 编写迁移脚本
3. 提交 PR，至少1人 Review
4. 合并后通知所有工程师
5. 更新接口文档

### Q3: 其他工程师修改了表结构，但我没收到通知，怎么办？

**A:** 
1. 在飞书/钉钉群提醒该工程师补发通知
2. 更新你的本地代码和文档
3. 在团队周会上提出，完善通知机制

---

**文档状态**：✅ 已生效  
**下次评审**：每周站会  
**违反处理**：首次提醒，二次警告，三次影响绩效评估