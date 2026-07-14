"""选择题与主观题结构修复 Prompt。"""

from __future__ import annotations

from typing import Any, Dict, List

from app.modules.corpus.question_type import looks_like_subjective_question
from app.modules.corpus.question_validation import get_option_label


def build_fix_prompt(
    context: List[Dict[str, Any]],
    target_idx: int,
    issue: Dict[str, Any],
) -> str:
    """按目标题型选择三题上下文修复模板。"""
    if 0 <= target_idx < len(context) and looks_like_subjective_question(
        context[target_idx]
    ):
        return build_subjective_fix_prompt(context, target_idx, issue)
    return build_choice_fix_prompt(context, target_idx, issue)


def build_choice_fix_prompt(
    context: List[Dict[str, Any]],
    target_idx: int,
    issue: Dict[str, Any],
) -> str:
    """构建选择题结构修复 Prompt。"""
    formatted = []
    for index, question in enumerate(context):
        marker = " ← 【目标】" if index == target_idx else ""
        stem = question.get("stem") or question.get("content", "")
        raw_text = question.get("raw_text") or question.get("content") or stem
        options_text = ", ".join(
            f"{get_option_label(option)}. " f"{option.get('text', '')[:80]}"
            for option in question.get("options", [])
        )
        formatted.append(f"""
题目{index + 1}{marker}:
页码: {question.get('page_no', '?')}
题干: {stem[:500]}
原始提取文本: {raw_text[:1200]}
选项: {options_text}
---
""")

    issue_description = f"""
问题类型: {issue.get('issue_type', 'unknown')}
缺失选项: {issue.get('missing_options', [])}
"""
    return f"""
你是一个教材选择题结构分析专家。以下是从PDF中提取的目标题及其相邻题，共最多三题。

{chr(10).join(formatted)}

【当前问题】
{issue_description}

【任务】分析标记为【目标】的题目，并选择一种动作：
1. repair_options：目标题独立，但选项缺失或选项粘在题干中。
   - 优先从“原始提取文本”和相邻题原文中逐字恢复缺失选项。
   - 原文确实不存在时，允许生成合理选项。
   - 每个补充选项必须标 source：原文恢复为 extracted，AI 生成则为 ai_generated。
   - 返回完整题干和 A-D 选项。
   - 不要改写内容完整的已有选项；若已有选项明显被截断，且完整文本能在目标题
     原始提取文本中逐字找到，应返回恢复后的完整文本。
2. merge：目标题被错误拆开，需要与前题或后题合并。
3. none：无需修改或无法可靠修复。

只有确认目标题是选择题时才允许 repair_options。若 A/B/C/D 只是题干中的变量、
寄存器、图节点或其他正文符号，不得生成或补充选择题选项。

merge_indices 使用上方上下文题目列表的 0 基索引，例如第一道题是 0，第二道题是 1。

【输出格式】JSON:
{{
  "action": "repair_options" / "merge" / "none",
  "is_complete": true/false,
  "should_merge": true/false,
  "merge_with": "previous" / "next" / "none",
  "merge_indices": [0, 1],
  "repaired_question": {{
    "stem": "修复后的题干",
    "options": [
      {{"key": "A", "text": "...", "source": "extracted"}},
      {{"key": "B", "text": "...", "source": "ai_generated"}}
    ]
  }},
  "merged_question": {{
    "stem": "合并后的题干",
    "options": [{{"label": "A", "text": "..."}}, ...]
  }},
  "reason": "简短说明"
}}
"""


def build_subjective_fix_prompt(
    context: List[Dict[str, Any]],
    target_idx: int,
    issue: Dict[str, Any],
) -> str:
    """构建主观题结构修复 Prompt。"""
    formatted = []
    for index, question in enumerate(context):
        marker = " ← 【目标】" if index == target_idx else ""
        stem = question.get("stem") or question.get("content", "")
        raw_text = question.get("raw_text") or question.get("content") or stem
        options_text = ", ".join(
            f"{get_option_label(option)}. " f"{option.get('text', '')[:80]}"
            for option in question.get("options", [])
        )
        formatted.append(f"""
题目{index + 1}{marker}:
页码: {question.get('page_no', '?')}
当前题干: {stem[:500]}
原始提取文本: {raw_text[:1600]}
当前疑似选项: {options_text}
---
""")

    return f"""
你是一个教材主观题结构分析专家。以下是从PDF中提取的目标题及其相邻题，共最多三题。

{chr(10).join(formatted)}

【当前问题】
问题类型: {issue.get('issue_type', 'unknown')}

【任务】分析标记为【目标】的主观题，并选择一种动作：
1. repair_subjective：A/B/C/D 等正文符号被误拆成选项，或题干因此被截断。
   - 只能根据目标题的“原始提取文本”逐字恢复完整题干。
   - options 必须返回空数组，question_type 必须返回 short_answer。
   - 不得生成选择题选项，不得改写题意。
2. merge：目标题被错误拆开，需要与前题或后题合并。
3. none：题目结构完整或无法可靠修复。

merge_indices 使用上方上下文题目列表的 0 基索引。

【输出格式】JSON:
{{
  "action": "repair_subjective" / "merge" / "none",
  "should_merge": true/false,
  "merge_with": "previous" / "next" / "none",
  "merge_indices": [0, 1],
  "repaired_question": {{
    "stem": "从原始提取文本恢复的完整题干",
    "question_type": "short_answer",
    "options": []
  }},
  "merged_question": {{
    "stem": "合并后的完整题干",
    "question_type": "short_answer",
    "options": []
  }},
  "reason": "简短说明"
}}
"""


__all__ = [
    "build_choice_fix_prompt",
    "build_fix_prompt",
    "build_subjective_fix_prompt",
]
