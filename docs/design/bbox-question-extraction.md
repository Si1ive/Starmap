# 题目提取策略重构设计文档

## 1. 背景

### 1.1 当前问题

MinerU 的 `content_list` 只输出布局级类型（`text`/`image`/`table`/`equation`），**不支持题目检测**。它的 12 种 type 值中没有 `question`、`option`、`exam` 等考试相关类型。

当前系统用**纯文本正则**识别题目边界，核心逻辑在 `_extract_questions_to_dict()` 和 `_question_start_kind()` 中，存在以下问题：

1. **尾部文字丢失**：`"处于死锁状态"` 被 MinerU 拆到独立 block，无题号无选项标记，文本策略无法判断归属
2. **figure caption 污染题干**：`"1"` `"II"` 等图片标注被当作题干文本拼接
3. **跨页/跨列题目拆分**：选项 D 被换行到下一个 block 后，可能被误判为新题目
4. **依赖文本质量**：MinerU 的 OCR 错误（如 `<sub>．</sub>` 误识别）直接影响边界判断

### 1.2 MinerU 能力边界

MinerU content_list 字段：

| 字段 | 说明 |
|------|------|
| `type` | `text`/`image`/`table`/`equation`/`code`/`list`/`chart`/`header`/`footer`/`page_number`/`aside_text`/`page_footnote` |
| `page_idx` | 0-based 页码 |
| `bbox` | `[x0, y0, x1, y1]`，归一化到 0-1000 |
| `text` | 文本内容（text 类型） |
| `text_level` | 0=正文, 1+=标题层级（text 类型） |
| `img_path` | 图片相对路径（image/table 类型） |
| `image_caption` | 图片说明 list（image 类型） |

**结论：MinerU 不做题目识别，我们必须自己构建。**

---

## 2. 新方案：基于 bbox 坐标的题目分组

### 2.1 核心思路

**题目边界 = 文本模式 + 空间位置 + 页面统计**，三者加权判断，不依赖单一阈值。

```
文本模式（强信号）: 题号正则、选项正则
空间位置（强信号）: 左边缘对齐、y 坐标连续性
页面统计（自适应）: 同页中位行距、左边缘基线
```

### 2.2 算法流程

```
Phase 1: 页面级统计
  输入: 单页所有 block
  输出: page_left_edge, median_line_gap, is_dense_layout

  1.1 计算页面左边缘基线
      page_left_edge = min(所有 text block 的 bbox.x0)
      用途: 判断一个 block 是否"顶格"（题号通常在最左边）

  1.2 计算中位行距
      收集所有相邻 text block 的 y 间距: gaps = [b[i+1].y0 - b[i].y1]
      median_gap = median(gaps)
      用途: 自适应判断"大间距"（新题目的信号）

  1.3 判断排版密度
      统计同 y 坐标的 block 数量 → 判断是否多栏排版
      is_dense = (同 y 带内 block 数 > 2 的占比 > 30%)

Phase 2: 逐 block 打标
  输入: 单页所有 block（按 MinerU 阅读顺序）
  输出: 每个 block 带标记

  对每个 block 计算:
    at_left_edge  = (bbox.x0 - page_left_edge) < 30   // 0-1000 坐标系
    has_q_number  = text 匹配 ^\d{1,3}[.、．。]
    has_option    = text 匹配 ^[A-H][.、．。]
    has_paren_q   = text 匹配 ^[（(]\d+[）)]
    is_media      = block_type in (image, figure, table, formula)
    is_noise      = block_type in (header, footer, page_number)
    gap_ratio     = (当前块 y0 - 前一块 y1) / median_gap

Phase 3: 题目边界判定
  输入: 带标记的 block 序列
  输出: 题目分组 [ [block, block, ...], [block, ...], ... ]

  新题目起点 = 满足以下任一条件:

    A. at_left_edge + has_q_number
       → 左边缘 + 题号，最高置信度，无论 gap 多大都算新题

    B. at_left_edge + has_paren_q + gap_ratio > 1.5
       → 左边缘 + 括号题号 + 间距不小于中位行距

    C. gap_ratio > 3.0 + 有实质文本（len > 10）+ 不是选项标记
       → 大间距 + 有内容 + 不是选项 → 可能是没识别出题号的题目
       （如只有 "1." 但被 MinerU 误识别为其他字符）

  排除（不是新题目）:
    - has_option → 是选项块，属于当前题
    - is_media   → 是图片/表格，属于当前题
    - is_noise   → 页眉页脚，跳过
    - gap_ratio < 1.5 且无题号 → 是上一题的延续内容

Phase 4: 组内处理
  输入: 一道题的所有 block
  输出: { stem, options, figures, question_no }

  4.1 定位题干
      第一个 has_q_number 的 text block → stem 起始
      后续无选项标记的 text block → stem 延续
      直到遇到 has_option 或 is_media

  4.2 定位选项
      所有 has_option 的 text block → 选项
      同一选项行内可能有多个选项（如 "A.xx B.xx C.xx D.xx"）
      选项可能跨多个 block（如 D 的尾部被换行到下一 block）

  4.3 选项跨 block 合并
      选项 block 之后的 text block，如果:
        - 无题号标记
        - 无选项标记
        - gap_ratio < 1.5
        - y 坐标在选项行下方且 x 坐标在选项区域范围内
      → 追加到最后一个选项的 text

  4.4 定位配图
      所有 is_media 的 block → 题目配图
      按 y 坐标排在 stem 和 options 之间

  4.5 提取题号
      从 stem 第一个 block 的文本中提取数字 → question_no

Phase 5: 跨页处理
  如果一道题在页尾没有选项结束（只有 stem 没有 options）:
    标记为"可能跨页"，与下一页的第一道题合并判断
  如果下一页开头是选项块（has_option）且没有题号:
    合并到上一页最后一道题
```

### 2.3 关键阈值说明

| 阈值 | 值 | 用途 | 为什么是这个值 |
|------|-----|------|---------------|
| `left_edge_margin` | 30 | 判断是否"顶格" | 0-1000 坐标系下，30 约等于 3% 页宽，足够覆盖题号缩进 |
| `gap_ratio_new_question` | 3.0 | 无题号时判断新题 | 3 倍中位行距 ≈ 空了一整行以上，中文试卷题目间通常有空行 |
| `gap_ratio_paren_q` | 1.5 | 括号题号判断 | 括号题号可能是子题，要求间距至少大于中位行距 |
| `gap_ratio_continuation` | 1.5 | 判断是否延续 | 小于 1.5 倍行距 = 正常行间距，是同一段落的延续 |

---

## 3. 与当前实现的对比

### 3.1 你的 case 在新方案下的表现

```
输入 block（page_idx=2）:
  b1: bbox=[70,347,418,366]  text="27。利用死锁定理..."  → at_left, has_q_number
  b2: bbox=[97,374,223,505]  type=image                  → is_media
  b3: bbox=[269,374,415,504] type=image                  → is_media
  b4: bbox=[86,531,466,552]  text="A 。Ⅰ B 。Ⅱ C。Ⅰ和Ⅱ D。都不" → has_option
  b5: bbox=[47,556,119,576]  text="处于死锁状态"          → 无标记

页面统计: page_left_edge=47, median_gap≈6

Phase 3 判断:
  b1: at_left + has_q_number → 新题目起点 ✓
  b2: is_media → 属于当前题
  b3: is_media → 属于当前题
  b4: has_option → 属于当前题
  b5: gap_ratio=(556-552)/6≈0.67 < 1.5 → 延续内容 ✓

Phase 4 组内处理:
  stem:  "27。利用死锁定理简化下列进程资源图，则处于死锁状态的是（ ）。"
  figures: [b2, b3]
  options:
    A: "Ⅰ"
    B: "Ⅱ"
    C: "Ⅰ和Ⅱ"
    D: "都不 处于死锁状态"  ← b5 合并到 D

结果: 1 道完整题目，5 个 block 全部归入，选项 D 完整 ✓
```

### 3.2 当前方案 vs 新方案

| 维度 | 当前方案 | 新方案 |
|------|---------|--------|
| 题目边界 | 纯文本正则状态机 | 文本模式 + bbox 坐标 + 页面统计 |
| 选项归属 | 正则匹配 A-H 标记 | 选项标记 + 组内聚合 + 跨 block 合并 |
| 图片归属 | block_type 判断 + 文本拼接 | 组内聚合，不拼入 stem |
| 尾部文字 | **丢失**（无标记无法判断） | gap_ratio 自适应判断 + 选项区域匹配 |
| 阈值 | 无（硬编码正则） | 自适应（每页独立统计 median_gap） |
| 跨页题目 | 不支持 | 支持（页尾未闭合题目与下页合并） |
| 多栏排版 | 不支持 | 支持（is_dense_layout 标记，x 坐标分栏） |
| 子题（(1)(2)(3)） | 特殊处理 paren 类型 | gap_ratio 区分大题小题 |

---

## 4. 废弃清单

### 4.1 完全废弃的方法

| 方法 | 位置 | 原因 |
|------|------|------|
| `_extract_questions_to_dict()` | entity_extraction_service.py:1502 | 纯文本状态机，替换为 bbox 分组 |
| `_question_start_kind()` | entity_extraction_service.py:1655 | 只依赖文本正则，替换为 Phase 3 |
| `_is_question_start_block()` | entity_extraction_service.py:1651 | 同上 |
| `_expand_blocks_with_embedded_question_starts()` | entity_extraction_service.py:1574 | bbox 分组不需要预拆分文本 |
| `_split_block_by_embedded_question_starts()` | entity_extraction_service.py:1581 | 同上 |
| `_is_embedded_question_start()` | entity_extraction_service.py:1628 | 同上 |
| `_blocks_to_question_dict()` | entity_extraction_service.py:1693 | 替换为 Phase 4 组内处理 |
| `_split_question_stem_options()` | entity_extraction_service.py:1814 | 替换为 Phase 4.2-4.3 |
| `_find_best_option_sequence()` | entity_extraction_service.py:1860 | 选项归属由 bbox 分组保证 |
| `_candidate_option_sequences()` | entity_extraction_service.py:1890 | 同上 |
| `_is_valid_option_marker_match()` | entity_extraction_service.py:1928 | 同上 |
| `_score_option_sequence()` | entity_extraction_service.py:1954 | 同上 |
| `_has_choice_stem_signal()` | entity_extraction_service.py:1988 | 同上 |
| `_has_choice_blank_near_option_start()` | entity_extraction_service.py:2000 | 同上 |
| `_is_plausible_option_text()` | entity_extraction_service.py:2007 | 同上 |
| `_strip_leading_option_marker()` | entity_extraction_service.py:2017 | 同上 |
| `_extract_options_from_content()` | entity_extraction_service.py:2032 | 同上 |

### 4.2 保留的方法

| 方法 | 原因 |
|------|------|
| `_extract_questions()` | 顶层入口，流程改为调用新方法 |
| `_save_question_from_dict()` | 落库逻辑不变 |
| `_normalize_options()` | 选项结构标准化，仍需要 |
| `_extract_topic_terms()` | 关键词提取，不变 |
| `_extract_and_link_answers()` | 答案回连，不变 |
| `_build_question_extraction_diagnostic()` | 诊断报告，不变 |
| `_question_numbering_summary()` | 编号摘要，不变 |
| `_question_text_excerpt()` | 文本摘要，不变 |
| `_resolve_mapping_for_page()` | 章节映射，不变 |
| `_get_section_mappings()` | 章节映射，不变 |
| `_cleanup_existing_entities()` | 清理逻辑，不变 |

### 4.3 保留但简化

| 方法 | 变化 |
|------|------|
| `comprehensive_validation()` | 选项完整性检查保留；编号连续性检查简化（bbox 分组后题号更可靠） |
| `OptionIntegrityChecker` | 保留，用于校验 |
| `QuestionNumberChecker` | 保留，但使用频率降低 |
| `RuleBasedFixer` | 保留 `fix_option_issues`，废弃 `fix_number_issues` |
| `LLMFallbackFixer` | 保留，但触发频率大幅降低 |

### 4.4 保留的正则常量

```python
OPTION_BLOCK_RE      # 选项块识别，Phase 2 打标用
OPTION_MARKER_RE     # 选项标记提取，Phase 4 选项拆分用
QUESTION_NUMERIC_RE  # 题号识别，Phase 2 打标用
QUESTION_PAREN_RE    # 括号题号，Phase 2 打标用
QUESTION_TITLE_RE    # "第X题"，Phase 2 打标用
QUESTION_EXAMPLE_RE  # "例X"，Phase 2 打标用
QUESTION_CUE_RE      # 题干关键词，辅助判断
```

---

## 5. 新增代码结构

```
entity_extraction_service.py

class QuestionLayoutGrouper:          # 新增类
    """基于 bbox 坐标的题目分组器"""

    def __init__(self, blocks: List[DocumentBlock]):
        self.blocks = blocks
        self.page_stats: Dict[int, PageStats] = {}

    # ---- Phase 1: 页面统计 ----
    def _compute_page_stats(self, page_no: int) -> PageStats:
        """计算单页的左边缘基线和中位行距"""

    # ---- Phase 2: 逐 block 打标 ----
    def _tag_block(self, block, stats: PageStats, prev_block) -> BlockTag:
        """为单个 block 计算所有标记"""

    # ---- Phase 3: 题目边界判定 ----
    def group_into_questions(self) -> List[QuestionGroup]:
        """主入口：将 blocks 分组为题目列表"""

    # ---- Phase 4: 组内处理 ----
    def _extract_stem(self, group: QuestionGroup) -> str:
        """从组内提取题干"""

    def _extract_options(self, group: QuestionGroup) -> List[Dict]:
        """从组内提取选项（含跨 block 合并）"""

    def _extract_figures(self, group: QuestionGroup) -> List[str]:
        """从组内提取配图 block_id"""

    def _extract_question_no(self, group: QuestionGroup) -> Optional[int]:
        """从组内提取题号"""


@dataclass
class PageStats:
    page_no: int
    left_edge: float
    median_gap: float
    is_dense: bool


@dataclass
class BlockTag:
    block: DocumentBlock
    at_left_edge: bool
    has_q_number: bool
    has_option: bool
    has_paren_q: bool
    is_media: bool
    is_noise: bool
    gap_ratio: float


@dataclass
class QuestionGroup:
    blocks: List[DocumentBlock]
    page_no: int
```

---

## 6. `_extract_questions()` 新流程

```
_extract_questions():
    Step 1: 标点清洗（不变）
    Step 2: QuestionLayoutGrouper.group_into_questions() → List[QuestionGroup]
    Step 3: 对每个 QuestionGroup 调用组内处理 → List[question_dict]
    Step 4: comprehensive_validation()（简化版）
    Step 5: RuleBasedFixer.fix_option_issues()（保留）
    Step 6: LLMFallbackFixer（保留，触发频率降低）
    Step 7: 保存题目和诊断报告（不变）
```

---

## 7. 风险与边界

### 7.1 已知风险

1. **无题号的题目**：gap_ratio > 3.0 的判断可能漏掉紧排的题目。需在诊断报告中标记，供人工审核
2. **多栏排版**：Phase 1 检测到 is_dense 后，需按 x 坐标分栏处理。第一版先标记 + 日志告警，后续迭代
3. **MinerU bbox 精度**：0-1000 归一化坐标系下，小尺寸文本的 bbox 可能有偏差
4. **页首第一题**：没有 prev_block，gap_ratio 无法计算 → 默认是题目起点

### 7.2 灰度策略

- 新方法作为 `_extract_questions_v2()` 实现
- `_extract_questions()` 中通过 feature flag 切换新旧
- 诊断报告中对比新旧结果，验证一致性
- 稳定后删除旧代码
