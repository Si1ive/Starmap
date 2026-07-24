# 408考研大纲管理系统设计方案

## 📊 现状分析

### 已有的数据模型
经过检查，数据库中已经存在大纲相关的核心模型：

1. **`canonical_chapters`** (标准章节表) - 这就是考试大纲的章节结构
   - 支持层级结构（parent_id, level）
   - 支持编码和别名（code, aliases）
   - 与学科关联（subject_id）
   - 已有排序和状态管理

2. **关联模型**：
   - `knowledge_point_chapter_links` - 知识点与大纲章节的多对多关联
   - `question_chapter_links` - 题目与大纲章节的多对多关联
   - `document_section_mappings` - 文档章节到大纲章节的映射

3. **旧的简单模型**：
   - `subjects` - 学科（计组、数据结构、操作系统、计网）
   - `chapters` - 简单章节（即将废弃，被 canonical_chapters 替代）

### 问题诊断

✅ **数据模型已完整** - 支持考试大纲的层级结构和多对多关联  
❌ **缺少大纲维度的管理** - 需要添加考试年份、版本等元信息  
❌ **前后端未实现** - API 和前端页面都还没开发  
❌ **数据迁移未完成** - 还在使用旧的 chapters，需要迁移到 canonical_chapters

---

## 🎯 设计方案

### 方案概述

**核心思路**：基于已有的 `canonical_chapters` 表，扩展为完整的考试大纲管理系统。

### 1. 数据库设计

#### 1.1 新增：考试大纲元信息表

```sql
CREATE TABLE exam_outlines (
    id VARCHAR(32) PRIMARY KEY COMMENT '大纲ID',
    name VARCHAR(100) NOT NULL COMMENT '大纲名称，如：2025年408考研大纲',
    year INT NOT NULL COMMENT '考试年份',
    version VARCHAR(20) COMMENT '版本号，如：v1.0',
    description TEXT COMMENT '大纲说明',
    release_date DATE COMMENT '发布日期',
    effective_date DATE COMMENT '生效日期',
    status ENUM('draft', 'active', 'archived') DEFAULT 'draft' COMMENT '状态',
    is_default BOOLEAN DEFAULT false COMMENT '是否默认大纲',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_outline_year (year),
    INDEX idx_outline_status (status),
    INDEX idx_outline_default (is_default),
    UNIQUE KEY uk_outline_year_version (year, version)
) COMMENT '考试大纲元信息表';
```

#### 1.2 扩展：CanonicalChapter 添加大纲关联

```sql
ALTER TABLE canonical_chapters 
ADD COLUMN outline_id VARCHAR(32) COMMENT '所属大纲ID',
ADD COLUMN outline_code VARCHAR(50) COMMENT '大纲中的编号，如：1.1.1',
ADD FOREIGN KEY (outline_id) REFERENCES exam_outlines(id) ON DELETE CASCADE,
ADD INDEX idx_canonical_outline (outline_id);
```

#### 1.3 数据关系图

```
exam_outlines (考试大纲)
    ↓ 1:N
canonical_chapters (大纲章节/知识点分类)
    ↓ M:N                    ↓ M:N
knowledge_points         questions
(知识点)                  (题目)
```

### 2. 数据模型定义（Python）

```python
class ExamOutline(Base):
    """考试大纲元信息表"""
    __tablename__ = "exam_outlines"
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="大纲名称")
    year: Mapped[int] = mapped_column(nullable=False, comment="考试年份")
    version: Mapped[str] = mapped_column(String(20), default="v1.0", comment="版本号")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="大纲说明")
    release_date: Mapped[Optional[datetime]] = mapped_column(Date, comment="发布日期")
    effective_date: Mapped[Optional[datetime]] = mapped_column(Date, comment="生效日期")
    status: Mapped[str] = mapped_column(
        Enum("draft", "active", "archived"),
        default="draft",
        comment="状态"
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否默认大纲")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    # relationships
    chapters: Mapped[List["CanonicalChapter"]] = relationship(back_populates="outline")
    
    __table_args__ = (
        Index("idx_outline_year", "year"),
        Index("idx_outline_status", "status"),
        Index("idx_outline_default", "is_default"),
        UniqueConstraint("year", "version", name="uk_outline_year_version"),
        {"comment": "考试大纲元信息表"}
    )


# 扩展 CanonicalChapter
class CanonicalChapter(Base):
    # ... 原有字段 ...
    
    outline_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("exam_outlines.id", ondelete="CASCADE"),
        comment="所属大纲ID"
    )
    outline_code: Mapped[Optional[str]] = mapped_column(
        String(50), comment="大纲中的编号，如：1.1.1"
    )
    
    # relationships
    outline: Mapped[Optional["ExamOutline"]] = relationship(back_populates="chapters")
```

---

## 📋 实现步骤

### Phase 1: 数据库层（优先）

**任务清单：**
- [ ] 创建 `ExamOutline` 模型
- [ ] 扩展 `CanonicalChapter` 添加 outline_id 字段
- [ ] 创建数据库迁移脚本
- [ ] 初始化 2025 年 408 考试大纲数据

**迁移脚本示例：**
```python
# alembic/versions/xxx_add_exam_outline.py
def upgrade():
    # 1. 创建 exam_outlines 表
    op.create_table(...)
    
    # 2. 扩展 canonical_chapters 表
    op.add_column('canonical_chapters', sa.Column('outline_id', ...))
    op.add_column('canonical_chapters', sa.Column('outline_code', ...))
    
    # 3. 创建默认大纲（2025年408）
    op.execute("""
        INSERT INTO exam_outlines (id, name, year, version, status, is_default)
        VALUES ('outline_2025', '2025年408考研大纲', 2025, 'v1.0', 'active', true)
    """)
```

### Phase 2: 后端 API（核心）

**新增 API 端点：**

```python
# 1. 大纲管理
GET    /admin/outlines              # 大纲列表
POST   /admin/outlines              # 创建大纲
GET    /admin/outlines/{id}         # 大纲详情
PUT    /admin/outlines/{id}         # 更新大纲
DELETE /admin/outlines/{id}         # 删除大纲
POST   /admin/outlines/{id}/set-default  # 设为默认

# 2. 大纲章节管理（基于 canonical_chapters）
GET    /admin/outlines/{id}/chapters           # 某大纲的章节树
POST   /admin/outlines/{id}/chapters           # 添加章节
PUT    /admin/outlines/{id}/chapters/{ch_id}   # 更新章节
DELETE /admin/outlines/{id}/chapters/{ch_id}   # 删除章节

# 3. 大纲维度的内容查询
GET    /admin/outlines/{id}/knowledge-points   # 某大纲下的所有知识点
GET    /admin/outlines/{id}/questions          # 某大纲下的所有题目
GET    /admin/outlines/{id}/chapters/{ch_id}/knowledge-points  # 某章节的知识点
GET    /admin/outlines/{id}/chapters/{ch_id}/questions         # 某章节的题目

# 4. 统计
GET    /admin/outlines/{id}/stats              # 大纲统计（章节数、知识点数、题目数）
```

### Phase 3: 前端页面（交互）

**新增页面：**

```
frontend-admin/src/pages/
├── Outline/
│   ├── List.tsx           # 大纲列表（年份、版本、状态）
│   ├── Create.tsx         # 创建大纲
│   ├── Detail.tsx         # 大纲详情（展示章节树）
│   ├── Edit.tsx           # 编辑大纲基本信息
│   └── ChapterManage.tsx  # 章节管理（树形结构，可拖拽排序）
```

**修改现有页面：**

1. **Dashboard** - 添加大纲切换器
   ```tsx
   <Select 
     value={currentOutlineId}
     onChange={setOutline}
     options={outlines}
     placeholder="选择考试大纲"
   />
   ```

2. **Knowledge/List** - 按大纲筛选
   ```tsx
   <Space>
     <Select placeholder="大纲" />  {/* 新增 */}
     <Select placeholder="学科" />
     <Select placeholder="章节（大纲章节）" />
   </Space>
   ```

3. **Question/List** - 按大纲筛选
   ```tsx
   // 同上
   ```

### Phase 4: 数据导入（便利）

**工具脚本：**

```python
# scripts/import_outline_2025.py
"""
从 Excel/JSON 导入 2025 年 408 考试大纲
"""

# 大纲数据示例（JSON 格式）
outline_data = {
    "name": "2025年408考研大纲",
    "year": 2025,
    "subjects": {
        "数据结构": {
            "chapters": [
                {
                    "code": "1",
                    "name": "线性表",
                    "children": [
                        {"code": "1.1", "name": "线性表的定义和基本操作"},
                        {"code": "1.2", "name": "线性表的实现"},
                    ]
                },
                # ...
            ]
        },
        # ...
    }
}
```

---

## 🔄 迁移策略

### 旧数据迁移

**目标**：将现有的 `chapters` 数据迁移到 `canonical_chapters`

```python
# scripts/migrate_to_canonical_chapters.py
async def migrate():
    # 1. 创建默认大纲
    outline = ExamOutline(
        id="outline_2025",
        name="2025年408考研大纲",
        year=2025,
        status="active",
        is_default=True
    )
    db.add(outline)
    
    # 2. 迁移旧章节到 canonical_chapters
    old_chapters = await db.execute(select(Chapter))
    for old_ch in old_chapters.scalars():
        canonical_ch = CanonicalChapter(
            id=old_ch.id,  # 保持ID不变，避免关联断裂
            outline_id="outline_2025",
            subject_id=old_ch.subject_id,
            name=old_ch.name,
            level=1,  # 旧的都是一级章节
            status=old_ch.status
        )
        db.add(canonical_ch)
    
    # 3. 更新知识点和题目的关联
    # （它们已经有 chapter_id 字段，指向的就是这些ID）
    
    await db.commit()
```

### 平滑过渡

1. **保留旧字段**：`knowledge_points.chapter_id` 和 `questions.chapter_id` 暂时保留
2. **双写策略**：新增时同时写入 `chapter_id` 和 `primary_chapter_id`
3. **API 兼容**：旧 API 继续工作，新 API 使用大纲维度

---

## 🎨 前端交互设计

### 1. 大纲列表页

```
┌─────────────────────────────────────────────────┐
│ 考试大纲管理                      [+ 创建大纲]  │
├─────────────────────────────────────────────────┤
│ 🔍 搜索: [________]  年份: [2025▼]  状态: [全部▼] │
├─────────────────────────────────────────────────┤
│ 大纲名称             │ 年份 │ 版本 │ 状态   │ 操作    │
│ 2025年408考研大纲    │ 2025 │ v1.0 │ [启用] │ 查看 编辑 │
│ 2024年408考研大纲    │ 2024 │ v1.0 │ [归档] │ 查看      │
└─────────────────────────────────────────────────┘
```

### 2. 大纲详情页（章节树）

```
┌─────────────────────────────────────────────────┐
│ 2025年408考研大纲              [编辑] [导出]   │
├─────────────────────────────────────────────────┤
│ 📚 数据结构                              [+添加章节] │
│   ├─ 1. 线性表                     知识点(12) 题目(45)  │
│   │   ├─ 1.1 线性表的定义           知识点(5)  题目(20)  │
│   │   └─ 1.2 线性表的实现           知识点(7)  题目(25)  │
│   ├─ 2. 栈、队列和数组              知识点(8)  题目(30)  │
│   └─ 3. 树与二叉树                  知识点(15) 题目(50)  │
│                                                        │
│ 📚 计算机组成原理                                      │
│   ├─ 1. 计算机系统概述               ...                │
│   └─ 2. 数据的表示和运算             ...                │
└─────────────────────────────────────────────────┘
```

### 3. 知识点管理页（新增大纲筛选）

```
┌─────────────────────────────────────────────────┐
│ 知识点管理                                       │
├─────────────────────────────────────────────────┤
│ 大纲: [2025年408▼]  学科: [数据结构▼]  章节: [1.线性表▼] │
│ 搜索: [________]  难度: [全部▼]                   │
├─────────────────────────────────────────────────┤
│ 标题               │ 大纲章节        │ 难度 │ 考频 │ 操作 │
│ 线性表的定义        │ 1. 线性表      │ 简单 │ 高频 │ 查看  │
│ 顺序存储结构        │ 1.2 实现      │ 中等 │ 高频 │ 查看  │
└─────────────────────────────────────────────────┘
```

---

## ✅ 优势总结

1. **符合考试实际**：完全按照考试大纲组织知识点和题目
2. **支持多年份**：可以管理历年考试大纲，方便对比变化
3. **灵活的关联**：多对多关系，一个知识点可以属于多个章节
4. **版本管理**：支持大纲的版本迭代（如大纲微调）
5. **平滑迁移**：保留旧数据结构，逐步迁移
6. **数据完整性**：统计每个章节下的知识点和题目数量

---

## 📅 实施计划

### Week 1: 数据库 + 基础 API
- Day 1-2: 创建数据模型和迁移脚本
- Day 3-4: 实现大纲 CRUD API
- Day 5: 导入 2025 年真实大纲数据

### Week 2: 前端页面
- Day 1-2: 大纲管理页面（列表、创建、编辑）
- Day 3-4: 章节树管理页面
- Day 5: 修改知识点和题目页面，添加大纲筛选

### Week 3: 数据迁移 + 测试
- Day 1-2: 迁移现有数据到大纲体系
- Day 3-4: 集成测试和 Bug 修复
- Day 5: 文档完善和部署

---

## 🤔 待讨论的问题

1. **大纲录入方式**：
   - 手动录入（前端表单）
   - Excel 导入
   - JSON 文件导入
   - 推荐：支持 Excel 导入，格式化后转为 JSON

2. **章节编号规则**：
   - 自动编号还是手动指定？
   - 推荐：手动指定，保持与官方大纲一致

3. **旧数据处理**：
   - 是否删除 `chapters` 表？
   - 推荐：暂时保留，标记为 deprecated

4. **默认大纲**：
   - 用户未选择时使用哪个大纲？
   - 推荐：使用 `is_default=true` 的大纲

---

这个方案如何？需要我开始实施吗？
