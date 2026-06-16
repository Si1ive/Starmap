# 题目抽取校验与修复方案

## 一、背景

PDF解析时存在两类问题：
1. **标点识别错误**：句号、逗号等被错误识别为 `<sub>．</sub>` 格式
2. **跨列/跨页分离**：双栏排版或换页时，题干和选项被拆分成多个独立题目

## 二、解决方案

### 总体架构

```
LLM初步提取 → 结构校验 → 规则修复 → LLM兜底 → 最终验证
               ↓
          1. 选项完整性
          2. 编号连续性
          3. 数量一致性
```

### 核心思路

- **规则优先**：使用确定性规则处理80%+的常见问题
- **LLM兜底**：只对规则无法处理的复杂情况调用LLM（降低成本）
- **特征驱动**：基于选择题必有ABCD选项、题号必须连续等客观特征进行校验

## 三、功能模块

### 3.1 标点清洗

**位置**：`backend/app/services/entity_extract.py`

**功能**：清理解析器误识别的标点符号

```python
def clean_punctuation_subscript(text: str) -> str:
    """将 <sub>．</sub> 等错误格式替换为原始标点"""
    patterns = [
        (r'<sub>\s*[．。]\s*</sub>', '。'),
        (r'<sub>\s*[，,]\s*</sub>', '，'),
        (r'<sub>\s*[；;]\s*</sub>', '；'),
        (r'<sub>\s*[：:]\s*</sub>', '：'),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text
```

### 3.2 选项完整性检查器

**类名**：`OptionIntegrityChecker`

**功能**：检测选择题是否有完整的ABCD选项

**检查维度**：
- 选项是否连续（不能有AB跳过C直接D）
- 选项数量是否足够（至少4个）
- 缺失类型判断（缺头部/缺尾部/缺中间）

**返回格式**：
```python
{
    'is_complete': bool,
    'missing_options': ['C', 'D'],
    'issue_type': 'missing_end' | 'missing_middle' | 'complete'
}
```

### 3.3 编号连续性检查器

**类名**：`QuestionNumberChecker`

**功能**：检测题目编号是否连续、是否有缺失或重复

**支持编号格式**：
- `1. 2. 3.` - 阿拉伯数字加句号
- `(1) (2) (3)` - 括号格式
- `[1] [2] [3]` - 方括号格式
- `例1 例2` - 例题格式
- `第1题 第2题` - 中文格式

**检查维度**：
- 编号连续性（1,2,3 不能跳到5）
- 编号重复（两道题都标记为3）
- 编号缺失（应该有编号但没识别到）
- 分段处理（遇到编号重置或格式变化，视为新段）

**返回格式**：
```python
{
    'segments': [  # 按编号模式分段
        {
            'start_index': 0,
            'end_index': 10,
            'number_range': (1, 11),
            'pattern': 'arabic',
            'issues': [
                {'type': 'missing', 'missing_number': 3, 'after_index': 5},
                {'type': 'duplicate', 'number': 5, 'indices': [7, 8]},
                {'type': 'jump', 'from_number': 10, 'to_number': 15}
            ]
        }
    ],
    'global_issues': {
        'total_questions': 50,
        'numbered_questions': 45,
        'unnumbered_questions': 5
    }
}
```

### 3.4 规则修复器

**类名**：`RuleBasedFixer`

**修复策略**：

#### 3.4.1 选项问题修复
- **缺尾部选项**（有AB缺CD）：向后查找最多3个题目，找到孤立的CD选项并合并
- **缺头部选项**（罕见）：向前查找
- **缺中间选项**：标记为LLM兜底处理

#### 3.4.2 编号问题修复
- **编号缺失**：查找无编号但结构完整的题目，推断并赋予缺失编号
- **编号重复**：判断两道题是否应合并（一道题被拆成两道）
  - 判断条件：页码相邻 + 第一道缺选项 + 第二道只有选项
  - 合并策略：拼接题干，合并选项列表

#### 3.4.3 合并判断
```python
def _should_merge_duplicates(q1: Dict, q2: Dict) -> bool:
    """判断重复编号的两道题是否应合并"""
    # 1. 页码相邻（同页或相邻页）
    # 2. q1缺选项
    # 3. q2只有选项（题干很短）
```

### 3.5 LLM兜底

**触发条件**：规则修复后仍有critical_issues

**处理方式**：
1. 提取规则未修复的问题
2. 为每个问题构造上下文（前2题+当前+后2题）
3. 调用LLM判断并给出修复建议
4. 应用LLM修复

**Prompt设计**：
```
以下是题目提取结果，存在问题：
- 问题类型：选项不完整 / 编号重复 / ...
- 上下文：[题目列表]

请分析：
1. 这是否是题目分离问题？
2. 应该如何合并/修复？
3. 给出修复后的完整题目结构

输出JSON格式：
{
  "should_merge": true/false,
  "merge_indices": [1, 2],
  "merged_question": {...}
}
```

### 3.6 完整流程

**函数**：`extract_questions_with_validation()`

```
Step 1: 标点清洗（clean_punctuation_in_blocks）
Step 2: LLM初步提取（llm_extract_questions）
Step 3: 综合校验（comprehensive_validation）
Step 4: 规则修复
  4.1 修复选项问题
  4.2 修复编号问题
Step 5: 重新校验
Step 6: LLM兜底（如果仍有critical issues）
Step 7: 最终验证
Step 8: 保存诊断报告
```

## 四、数据结构

### 题目结构（Question）

```python
{
    'id': str,
    'stem': str,                    # 题干
    'options': [                    # 选项列表
        {'label': 'A', 'text': '...'},
        {'label': 'B', 'text': '...'},
    ],
    'question_type': str,           # 'single_choice' | 'multiple_choice' | 'fill_blank'
    'page_no': int,                 # 页码
    'bbox': {...},                  # 边界框
    'raw_text': str,                # 原始文本
    
    # 修复相关字段
    'fixed_by_rule': str,           # 'option_append' | 'duplicate_merge' | 'number_infer'
    'fixed_by_llm': bool,
    'inferred_number': int,         # 推断的题号
}
```

### 诊断报告（DiagnosticReport）

```python
{
    'initial_report': {
        'option_issues': [...],
        'number_continuity': {...},
        'quantity_check': {...}
    },
    'after_rule_fix': {...},        # 规则修复后的校验报告
    'final_report': {...},          # 最终报告
    'fix_history': [                # 修复历史
        {
            'question_index': 5,
            'fix_type': 'rule' | 'llm',
            'fix_action': 'option_append',
            'details': {...}
        }
    ]
}
```

## 五、前端可视化

在页级对比工具中添加"题目诊断"Tab，展示：

1. **编号连续性图表**：可视化显示编号序列（1-2-3-?-5-6）
2. **选项完整性列表**：列出所有缺选项的题目
3. **修复历史**：显示哪些题目被规则/LLM修复
4. **问题统计**：总题数、修复数、剩余问题数

## 六、实现计划

1. ✅ 创建设计文档
2. ✅ 实现标点清洗功能 (commit: dc84694)
3. ✅ 实现选项完整性检查器 (commit: b8561d8)
4. ✅ 实现编号连续性检查器 (commit: c379ad5)
5. ✅ 实现综合校验功能 (commit: 464d6bc)
6. ✅ 实现规则修复器 (commit: 442f096)
7. ✅ 实现LLM兜底 (commit: 8a3a2a9)
8. ✅ 集成到完整流程 (commit: 464d6bc)
9. [ ] 前端可视化

## 七、测试验证

### 测试用例

1. **标点清洗**：包含 `<sub>．</sub>` 的文本
2. **选项缺失**：题干在page1底部，选项在page2顶部
3. **题干截断**：题干被拆成两部分
4. **编号缺失**：1,2,4,5（缺3）
5. **编号重复**：两道题都标记为"3"
6. **多种编号格式混合**：前10题用"1."，后面用"(1)"

### 验证方式

1. 单元测试：每个检查器和修复器独立测试
2. 集成测试：完整流程测试
3. 真实数据测试：使用生产环境的PDF文档
4. 前端可视化验证：在页级对比工具中查看修复效果
