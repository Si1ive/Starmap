# 408 学习 Agent 原型样例库

> 版本：v0.1
> 日期：2026-07-15
> 用途：高保真原型、交互评审、前端 Story 和 Agent 回归用例

## 1. 使用规则

- 优先使用本地数据库和现有解析回归中的真实结构，不使用通用占位文案。
- 真实题目可以做排版清理，但不得改变题意；做过改编必须标记。
- 题库当前为空的答案、解析和用户行为属于“原型补充数据”，不能反向写回正式题库。
- 内部 ID 仅用于设计与研发对照，用户界面显示试卷、题号和来源。
- 图片资产来自本地 `uploads`，设计交付时应复制到专用原型资产目录，避免依赖运行数据库。

## 2. 原型用户

```yaml
user:
  id: fixture-user-001
  display_name: 张同学
  stage: 强化阶段
  target_score: 115
  daily_minutes: 120
  current_focus:
    - 数据结构/栈和队列
    - 计算机组成原理/指令系统
  explanation_preference: 先给结论，再解释推导
  current_week_goal: 完成队列、存储系统和中断三组专项
```

说明：目标日期和倒计时在原型中使用固定演示值，不将演示日期表述为官方考试日期。

## 3. 大纲与考点样例

### 3.1 循环队列

```yaml
subject: 数据结构
outline_path:
  - 栈、队列和数组
  - 栈和队列的顺序存储结构
canonical_chapter_id: bbf34e59ba3449429ea7f65c6f63da69
keywords:
  - 顺序队列
  - 循环队列
  - Circular Queue
  - 队满判断
  - 队空判断
prototype_summary: 利用模运算复用顺序存储空间，重点掌握队首、队尾、长度和判空判满公式。
```

掌握证据：

- 最近 7 天作答 4 题，正确 2 题。
- “已知 rear 与 length 求 front”连续错误 2 次。
- 使用过一次一级提示。
- 状态：待巩固，不显示无依据的百分比。

### 3.2 最小生成树

```yaml
subject: 数据结构
outline_path:
  - 图
  - 最小（代价）生成树
canonical_chapter_id: ae0ffffe176340868461a3d010a72ea0
keywords:
  - 最小生成树
  - Prim
  - Kruskal
  - MST
prototype_summary: 理解最小生成树唯一性的条件，并能比较 Prim 与 Kruskal 的选择过程。
```

## 4. 题目样例

### FQ-01：选项经 LLM 从原文恢复

来源：本地 `试卷4.pdf`，题号 1。

```yaml
question_id: 20a26803ef114966a40e6744fb98e660
type: choice
stem: >
  若循环队列以数组 Q[0...m-1] 作为其存储结构，变量 rear 表示循环队列中
  队尾元素的实际位置，其移动按 rear=(rear+1) MOD m 进行，变量 length
  表示当前循环队列中的元素个数，则循环队列队首元素的实际位置是（ ）。
options:
  A: rear-length
  B: (rear-length+m) MOD m
  C: (1+rear+m-length) MOD m
  D: (rear+length-1) MOD m
prototype_answer: C
source_label: 原题
repair_badge: 原文恢复
repair_detail:
  original_issue: C 缺失，B 和 D 被截断
  added:
    - C: extracted
  replaced:
    - B: extracted
    - D: extracted
```

用途：

- 选择题作答与反馈。
- 来源详情中的“原文恢复”记录。
- Agent 讲解后生成验证题。
- 验证前端不能把修复记录当成面向用户的错误警告。

### FQ-02：主观题中包含 A/B/C/D 寄存器

来源：本地 `试卷4.pdf`，题号 43。

```yaml
question_id: f7b02ffe877c4f0dad0915589a6caa42
type: short_answer
stem: >
  假设有两个整数 x=-68、y=-80，采用 8 位补码表示，分别存放在寄存器 A
  和 B 中，另有 8 位寄存器 C 和 D。回答 A、B 中的内容，x+y 存入 C 后
  C、OF、SF、CF 的值，以及 x-y 存入 D 后 D、OF、SF、CF 的值。
source_label: 原题
options: []
```

用途：

- 验证主观题不能因正文中的 A/B/C/D 被渲染为选择题。
- 主观题评分点反馈。
- 公式、十六进制与多小问排版。
- Agent 解题时默认先提供思路，不直接泄露完整答案。

### FQ-03：长题干、公式和两张图片

来源：本地 `试卷4.pdf`，题号 44。

```yaml
question_id: 20d95cce8c22414a95a9bacb6459bbef
type: short_answer
source_label: 原题
summary: >
  根据双总线、指令存储器和数据存储器结构，确定各寄存器位数，并画出 ADD
  指令从取指到执行结束的操作序列与微操作控制信号。
assets:
  - type: table
    local_path: backend/uploads/assets/b5287e11cffb460b8b46a0c0bb980ad5/185997c8f16540d9bb0d47a4ed527d5d.jpg
    role: instruction_format
  - type: figure
    local_path: backend/uploads/assets/b5287e11cffb460b8b46a0c0bb980ad5/f5efea5535b747ce9b7a119e7b105e27.jpg
    role: processor_diagram
```

用途：

- 两张图的缩放、全屏查看和题图定位。
- 600 字以上题干压力测试。
- 主观题草稿和分步答案。
- 引用原始页时展示图文证据。

### FQ-04：AI 补充选项

来源：本地 `试卷4.pdf`，题号 14。

```yaml
question_id: d3a374399b2f416d8ff10f8d33295455
type: choice
stem: 设浮点数的基数为 4，尾数用原码表示，则以下（ ）是规格化的数。
option_d:
  text: 0.011011
  source: ai_generated
source_label: 原题
repair_badge: 含 AI 补充
```

用途：

- 验证 AI 补充选项必须可追溯。
- 练习页不应用强警告打断作答，但来源详情必须明确。
- 正式统计可选择排除含 AI 补充选项的原题。

### FQ-05：跨题污染的失败样例

来源：本地 `试卷4.pdf`，题号 12。

当前数据的 C 选项混入第 13 题题干，虽已生成 D 选项，但结构仍不可靠。

用途：

- Agent 选题工具应过滤质量不达标题目。
- 无可靠验证题时显示降级，不为凑数使用坏题。
- 管理端问题不直接暴露给普通用户，但用户端需要“内容暂不可用”的恢复状态。

### FQ-06：LLM 修复后仍不完整

来源：本地 `试卷4.pdf`，题号 18。

当前只有 A/B/C 三个选项，元信息仍标记 `few_options=true`。

用途：

- 题目检索与组题必须读取质量状态，不能只看 `fixed_by_llm=true`。
- 验证“修复过”与“已经可靠”是两个不同概念。

### FQ-07：简答题带图论证明与作图

来源：本地 `试卷4.pdf`，题号 41。

```yaml
question_id: 124001abe6e541e08a987ed39910fa28
type: short_answer
tasks:
  - 证明边权互不相同时最小生成树唯一
  - 判断 Prim 与 Kruskal 生成的最小生成树是否一定相同
  - 画出给定图的所有最小生成树
```

用途：

- 多小问进度。
- 数学证明类评分点。
- 用户上传手写图片作为答案的后续能力占位。

## 5. Agent 线程样例

### FT-01：循环队列提问到验证

用户消息：

> 我总是记不住循环队列里已知 rear 和 length 时 front 怎么算，能不能不要让我死记公式？

Run 步骤：

```yaml
run_id: fixture-run-queue-001
status: completed
steps:
  - name: 识别学习意图
    status: completed
  - name: 检索大纲考点
    status: completed
    result: 栈和队列的顺序存储结构
  - name: 检索已审核知识与相关题
    status: completed
    result: 2 个知识片段，4 道候选题
  - name: 读取个人掌握证据
    status: completed
    result: 同类题最近 2 次错误
  - name: 生成分层讲解
    status: completed
  - name: 创建验证题草稿
    status: completed
    result: 2 道题，尚未开始
```

回答摘要：

> 不先背公式，先把 rear 看成“最后一个元素的位置”。队列里有 length 个元素，
> 从 rear 向前退 length-1 步就是队首，因此
> `front=(rear-length+1+m) MOD m`。加上 m 是为了避免出现负下标。

引用：

- 大纲考点：数据结构 / 栈和队列的顺序存储结构。
- 原题：`试卷4.pdf` 第 1 题。
- 平台知识：循环队列。

下一动作：

- 主按钮：用 2 道题验证。
- 次动作：换一种图示讲解。

### FT-02：运行失败后恢复

```yaml
run_id: fixture-run-recovery-001
status: failed
completed_steps:
  - 检索大纲
  - 检索题目
  - 创建练习草稿
failed_step:
  name: 生成逐题提示
  reason: 模型响应超时
recovery:
  preserved_artifact: 练习草稿，3 道题
  primary_action: 仅重试失败步骤
  secondary_action: 直接开始无提示练习
```

页面不能把已经创建的练习草稿清空，也不能重新创建一份重复练习。

### FT-03：调整周计划审批

```yaml
approval_id: fixture-approval-plan-001
action: 更新本周学习计划
reason: 操作系统死锁连续错误 3 次
changes:
  - remove: 周四 数据结构排序练习 20 分钟
  - add: 周四 死锁条件讲解 10 分钟
  - add: 周四 死锁专项 3 题 10 分钟
reversible: true
```

## 6. 练习会话样例

```yaml
session_id: fixture-practice-queue-001
title: 循环队列专项验证
source: agent_validation
question_count: 2
current_position: 1
questions:
  - id: FQ-01
    state: answered_incorrect
    user_answer: B
    correct_answer: C
    time_spent_seconds: 86
    hint_level: 0
  - id: fixture-generated-queue-002
    state: unanswered
    source_label: AI 生成
```

错因候选：

- 把队尾后一个位置误当成队首。
- 少考虑“包含队尾本身”，回退步数应为 `length-1`。
- 模运算处理负下标不熟。

用户确认后的主错因：

> 少考虑“包含队尾本身”，机械使用了 rear-length。

复习计划：

- 1 天后：一题无提示验证。
- 4 天后：一道改变 front/rear 定义的变式题。
- 两次均通过后进入“已掌握候选”，仍保留证据历史。

## 7. 今日样例

```yaml
available_minutes: 90
primary_task:
  type: review
  title: 循环队列下标计算
  duration_minutes: 12
  reason: 昨日同类题答错，今天到达首次复习间隔
queue:
  - title: 循环队列复习与 2 题验证
    duration_minutes: 12
    state: ready
  - title: Cache 平均访问时间专项
    duration_minutes: 25
    state: ready
  - title: 中断与异常易混点讲解
    duration_minutes: 18
    state: ready
  - title: 昨日错题快速复盘
    duration_minutes: 15
    state: ready
```

## 8. 来源标签样例

| 展示文案 | 内部类型 | 示例 |
|----------|----------|------|
| 官方大纲 | `official_outline` | 栈和队列的顺序存储结构 |
| 原题 | `original_question` | 试卷4.pdf 第 1 题 |
| 平台知识 | `reviewed_knowledge` | 循环队列 |
| 个人资料 | `user_source` | 我的数据结构笔记.pdf 第 12 页 |
| 平台改编 | `adapted_question` | 基于循环队列考点改编 |
| AI 生成 | `ai_generated` | 验证题 2 |
| 模型推断 | `model_inference` | 无直接资料支持的解释 |

## 9. 原型禁用样例

以下内容不得进入最终高保真稿：

- “欢迎来到 408 智能学习平台”式营销首屏。
- “AI 正在思考……”作为唯一运行信息。
- 无来源的“你的掌握度是 82%”。
- 用 Lorem ipsum 或“一段很长的题干”代替真实长题。
- 把主观题正文中的 A/B/C/D 自动展示成选项。
- 把 `fixed_by_llm=true` 直接展示成“题目已可靠”。
- 在普通用户页面展示 MinerU、数据库字段或内部质量门禁术语。
