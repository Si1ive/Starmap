"""考试大纲拆分、增强和复习指导 Prompt 构建。"""

import json
from typing import Any, Dict, List


_SKELETON_TEMPLATE = """下面是一门课《{subject_name}》的考试大纲文本。请把它拆成结构化的章节树（骨架）。

要求：
1. 先识别这门课开头的「考察目标」（概括性的整门课要求，通常三四句话），放进 exam_objective。
2. 再把后续内容拆成多层级章节树 chapters。层级用嵌套 children 表达（如 一 / (一) / 1. / (1) 这样的层级关系）。
3. 每个章节节点只包含：
   - name：章节标题（去掉前面的编号），必填
   - outline_code：原始编号（如 "1.1.1" / "一" / "(一)"），没有就 null
   - description：该节点对应的考点正文原文（大纲里列的具体考点），没有就 null
   - children：子章节数组，没有就空数组
4. 重要：不要生成 enhanced_description、keywords 或任何其他字段。
5. 只输出 JSON，不要任何解释文字。

输出格式：
{{
  "exam_objective": "……",
  "chapters": [
    {{
      "name": "哈希表",
      "outline_code": "1.5",
      "description": "大纲原文...",
      "children": [...]
    }}
  ]
}}

大纲文本：
---
{content}
---"""


_ENHANCEMENT_TEMPLATE = """你是408考研大纲解析专家。下面是一些《{subject_name}》的章节节点（每个节点含考点原文 description）。请为每个节点生成 enhanced_description、keywords 和 cross_references。

每个节点的 enhanced_description 要求（2-3句话，包含）：
- 核心内容概括
- 常见考法
- 易混淆概念

keywords 要求（5-10个）：
- 包含中英文名称
- 包含同义词/别名
- 包含该节点下的核心术语

cross_references 要求（可选，标注跨科目/跨章节的强关联考点）：
- relation_type: similar_to（相似考点）/ prerequisite（前置知识）/ contrast_with（对比考点）/ common_confusion（常见混淆）
- target_chapter_id 必须从下方考点目录中选择，不得编造
- reason 必须具体说明关联原因
- 宁缺毋滥，只标注确实存在强关联的考点

示例：
节点 "哈希表" 考点 "哈希函数、冲突解决、链地址法、开放寻址法"
→ enhanced_description: "哈希表是基于哈希函数的键值对存储结构。常考冲突解决方法（链地址法、开放寻址法）、哈希函数设计、装填因子分析。易混淆：线性探测 vs 二次探测。"
→ keywords: ["散列表", "Hash Table", "冲突解决", "链地址法", "开放寻址", "线性探测", "二次探测", "装填因子"]
→ cross_references: [{{"target_chapter_id": "chap_xxx", "relation_type": "similar_to", "reason": "缓存中的哈希映射与哈希表原理一致"}}]

全科目考点目录（选择 target_chapter_id 时参考）：
{chapter_catalog}

只输出 JSON 对象，格式：
{{
  "items": [
    {{"index": 0, "enhanced_description": "...", "keywords": ["...", ...], "cross_references": [{{"target_chapter_id": "...", "relation_type": "similar_to", "reason": "..."}}]}},
    ...
  ]
}}

节点列表：
{items_json}"""


def build_outline_skeleton_prompt(subject_name: str, content: str) -> str:
    """构建章节骨架拆分 Prompt。"""
    return _SKELETON_TEMPLATE.format(
        subject_name=subject_name,
        content=content,
    )


def build_outline_enhancement_prompt(
    subject_name: str,
    chapter_catalog: str,
    items: List[Dict[str, Any]],
) -> str:
    """构建叶节点批量增强 Prompt。"""
    return _ENHANCEMENT_TEMPLATE.format(
        subject_name=subject_name,
        chapter_catalog=chapter_catalog,
        items_json=json.dumps(items, ensure_ascii=False, indent=2),
    )


def build_outline_objective_prompt(subject_name: str, content: str) -> str:
    """构建考察目标提取 Prompt。"""
    return (
        f'请从以下《{subject_name}》大纲片段中提取"考察目标"部分。\n\n'
        f"内容：\n{content}\n\n"
        '只输出 JSON：{"exam_objective": "考察目标文本"}\n'
        '如果找不到，返回 {"exam_objective": null}'
    )


def build_outline_guidance_prompt(
    objective: str,
    items: List[Dict[str, Any]],
) -> str:
    """构建章节复习指导 Prompt。"""
    chapters_json = json.dumps(items, ensure_ascii=False, indent=2)
    return (
        "你是408考研复习规划专家。下面是一门课的考察目标，以及若干章节（含原文考点）。\n"
        "请结合考察目标，为每个章节生成简洁的『复习指导』（重点内容 + 复习方向，2-4 句），"
        "帮助考生抓住该章重点。\n\n"
        f"考察目标：\n{objective or '（未提供，按通用408要求）'}\n\n"
        f"章节列表（JSON，id 是章节标识）：\n{chapters_json}\n\n"
        '只输出 JSON，格式：{"guidance": {"<章节id>": "复习指导文本", ...}}，不要任何解释。'
    )
