"""LLM-assisted repair for question extraction issues."""

import json
import re
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.modules.corpus.question_validation import get_option_label

logger = get_logger(__name__)


class LLMFallbackFixer:
    """Repair unresolved question extraction issues with an LLM."""

    def __init__(self, llm_client: Any):
        self.llm_client = llm_client

    async def fix_remaining_issues(
        self,
        questions: List[Dict[str, Any]],
        validation_report: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        critical_issues = validation_report.get(
            "summary",
            {},
        ).get("critical_issues", [])

        unfixed_issues = []
        for issue in critical_issues:
            index = issue.get("question_index")
            if (
                not isinstance(index, int)
                or index < 0
                or index >= len(questions)
            ):
                logger.warning(
                    "LLM fallback skipped invalid issue index",
                    issue=issue,
                )
                continue
            if not questions[index].get("fixed_by_rule"):
                self._remember_original_issue(questions[index], issue)
                unfixed_issues.append(issue)

        if not unfixed_issues:
            return questions

        logger.info(
            f"LLM fallback for {len(unfixed_issues)} unfixed issues"
        )
        for issue in sorted(
            unfixed_issues,
            key=lambda item: item.get("question_index", 0),
            reverse=True,
        ):
            index = issue["question_index"]
            if index < 0 or index >= len(questions):
                logger.warning(
                    "LLM fallback skipped stale issue index",
                    issue=issue,
                )
                continue

            context_start = max(0, index - 1)
            context_end = min(len(questions), index + 2)
            prompt = self._build_fix_prompt(
                questions[context_start:context_end],
                target_idx=index - context_start,
                issue=issue,
            )

            try:
                llm_response = await self.llm_client.chat(
                    prompt,
                    purpose="题目结构修复",
                )
                fix_action = self._parse_llm_fix_result(llm_response)
                if fix_action and fix_action.get("action") != "none":
                    fix_action["issue"] = issue
                    questions = self._apply_llm_fix(
                        questions,
                        index,
                        context_start,
                        fix_action,
                    )
                    logger.info(f"LLM fixed question {index}")
            except Exception as exc:
                logger.error(
                    f"LLM fix failed for question {index}: {exc}"
                )
        return questions

    @staticmethod
    def _remember_original_issue(
        question: Dict[str, Any],
        issue: Dict[str, Any],
    ) -> None:
        """Keep the original diagnosis after the repaired question is saved."""
        meta = dict(question.get("extraction_meta") or {})
        original_issues = list(meta.get("original_issues") or [])
        issue_snapshot = {
            key: issue.get(key)
            for key in (
                "question_number",
                "page_no",
                "issue_type",
                "missing_options",
                "missing_number",
                "from_number",
                "to_number",
                "gap",
            )
            if key in issue
        }
        identity = (
            issue_snapshot.get("issue_type"),
            tuple(issue_snapshot.get("missing_options") or []),
            issue_snapshot.get("missing_number"),
        )
        existing_identities = {
            (
                item.get("issue_type"),
                tuple(item.get("missing_options") or []),
                item.get("missing_number"),
            )
            for item in original_issues
            if isinstance(item, dict)
        }
        if identity not in existing_identities:
            original_issues.append(issue_snapshot)
        meta["original_issues"] = original_issues
        question["extraction_meta"] = meta

    def _build_fix_prompt(
        self,
        context: List[Dict[str, Any]],
        target_idx: int,
        issue: Dict[str, Any],
    ) -> str:
        """Build the three-question repair prompt."""
        formatted = []
        for index, question in enumerate(context):
            marker = " ← 【目标】" if index == target_idx else ""
            stem = question.get("stem") or question.get("content", "")
            raw_text = (
                question.get("raw_text")
                or question.get("content")
                or stem
            )
            options_text = ", ".join(
                f"{get_option_label(option)}. "
                f"{option.get('text', '')[:80]}"
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
你是一个教材题目结构分析专家。以下是从PDF中提取的目标题及其相邻题，共最多三题。

{chr(10).join(formatted)}

【当前问题】
{issue_description}

【任务】分析标记为【目标】的题目，并选择一种动作：
1. repair_options：目标题独立，但选项缺失或选项粘在题干中。
   - 优先从“原始提取文本”和相邻题原文中逐字恢复缺失选项。
   - 原文确实不存在时，允许生成合理选项。
   - 每个补充选项必须标 source：原文恢复为 extracted，AI 生成则为 ai_generated。
   - 返回完整题干和 A-D 选项；不要改写已有选项。
2. merge：目标题被错误拆开，需要与前题或后题合并。
3. none：无需修改或无法可靠修复。

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

    def _parse_llm_fix_result(
        self,
        llm_response: str,
    ) -> Optional[Dict[str, Any]]:
        """Parse a repair action from the LLM response."""
        try:
            json_match = re.search(r"\{.*\}", llm_response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                action = str(result.get("action") or "").strip().lower()
                repaired_question = (
                    result.get("repaired_question")
                    or result.get("fixed_question")
                )
                if action not in {"repair_options", "merge", "none"}:
                    if result.get("should_merge"):
                        action = "merge"
                    elif isinstance(repaired_question, dict):
                        action = "repair_options"
                    else:
                        action = "none"
                return {
                    "action": action,
                    "should_merge": result.get("should_merge", False),
                    "merge_with": result.get("merge_with", "none"),
                    "merge_indices": result.get("merge_indices", []),
                    "merged_question": result.get("merged_question"),
                    "repaired_question": repaired_question,
                    "reason": result.get("reason"),
                }
        except Exception as exc:
            logger.warning(f"Failed to parse LLM response: {exc}")
        return {"action": "none", "should_merge": False}

    def _apply_llm_fix(
        self,
        questions: List[Dict[str, Any]],
        index: int,
        context_start: int,
        fix_action: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if fix_action.get("action") == "repair_options":
            return self._apply_option_repair(
                questions,
                index,
                fix_action,
            )
        if (
            fix_action.get("action") != "merge"
            and not fix_action.get("should_merge")
        ):
            return questions

        merged_question = fix_action.get("merged_question")
        if not merged_question:
            return questions

        global_indices: List[int] = []
        merge_indices = fix_action.get("merge_indices", [])
        if isinstance(merge_indices, list):
            for relative_index in merge_indices:
                if isinstance(relative_index, int):
                    global_index = context_start + relative_index
                    if 0 <= global_index < len(questions):
                        global_indices.append(global_index)

        if not global_indices:
            merge_with = fix_action.get("merge_with")
            if merge_with == "previous" and index > 0:
                global_indices = [index - 1, index]
            elif merge_with == "next" and index + 1 < len(questions):
                global_indices = [index, index + 1]
            else:
                global_indices = [index]
        if index not in global_indices:
            global_indices.append(index)

        global_indices = sorted(set(global_indices))
        keep_index = global_indices[0]
        merged_blocks = []
        merged_block_ids = []
        page_numbers = []
        for global_index in global_indices:
            question = questions[global_index]
            merged_blocks.extend(question.get("blocks") or [])
            merged_block_ids.extend(question.get("block_ids") or [])
            if question.get("page_no") is not None:
                page_numbers.append(question["page_no"])

        merged_meta = dict(
            questions[keep_index].get("extraction_meta") or {}
        )
        original_issues = list(merged_meta.get("original_issues") or [])
        for global_index in global_indices:
            source_meta = (
                questions[global_index].get("extraction_meta") or {}
            )
            for original_issue in source_meta.get("original_issues") or []:
                if original_issue not in original_issues:
                    original_issues.append(original_issue)

        questions[keep_index].update(merged_question)
        if "stem" in merged_question and "content" not in merged_question:
            questions[keep_index]["content"] = merged_question["stem"]
        if "content" in merged_question and "stem" not in merged_question:
            questions[keep_index]["stem"] = merged_question["content"]
        if merged_blocks:
            questions[keep_index]["blocks"] = merged_blocks
        if merged_block_ids:
            questions[keep_index]["block_ids"] = merged_block_ids
        if page_numbers:
            questions[keep_index]["page_no"] = min(page_numbers)
            questions[keep_index]["page_range"] = (
                f"{min(page_numbers)}-{max(page_numbers)}"
            )
        questions[keep_index]["fixed_by_llm"] = True
        merged_meta["original_issues"] = original_issues
        self._append_llm_fix_action(
            questions[keep_index],
            merged_meta,
            action={
                "action": "merge",
                "merged_question_indices": global_indices,
                "reason": fix_action.get("reason"),
            },
        )

        for remove_index in sorted(
            [
                candidate
                for candidate in global_indices
                if candidate != keep_index
            ],
            reverse=True,
        ):
            del questions[remove_index]
        return questions

    def _apply_option_repair(
        self,
        questions: List[Dict[str, Any]],
        index: int,
        fix_action: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Only add missing labels and verify each added option's source."""
        if index < 0 or index >= len(questions):
            return questions
        repaired = fix_action.get("repaired_question")
        if not isinstance(repaired, dict):
            return questions

        target = questions[index]
        existing_options = list(target.get("options") or [])
        existing_labels = {
            get_option_label(option)
            for option in existing_options
            if get_option_label(option)
        }
        issue = fix_action.get("issue") or {}
        missing_labels = {
            str(label).strip().upper()[:1]
            for label in issue.get("missing_options") or []
            if str(label).strip().upper()[:1] in {"A", "B", "C", "D"}
        }
        if not missing_labels:
            missing_labels = {"A", "B", "C", "D"} - existing_labels

        source_text = self._collect_source_text(questions, index)
        added_options: List[Dict[str, Any]] = []
        for option in repaired.get("options") or []:
            if not isinstance(option, dict):
                continue
            label = get_option_label(option)
            text = str(
                option.get("text") or option.get("content") or ""
            ).strip()
            if (
                label not in {"A", "B", "C", "D"}
                or label in existing_labels
                or label not in missing_labels
                or not text
            ):
                continue
            source = (
                "extracted"
                if self._text_exists_in_source(text, source_text)
                else "ai_generated"
            )
            added_options.append({
                "key": label,
                "label": label,
                "option_label": label,
                "text": text,
                "source": source,
            })
            existing_labels.add(label)

        if not added_options:
            return questions
        target["options"] = sorted(
            [*existing_options, *added_options],
            key=get_option_label,
        )

        current_stem = target.get("stem") or target.get("content") or ""
        repaired_stem = str(
            repaired.get("stem") or repaired.get("content") or ""
        ).strip()
        if self._is_safe_repaired_stem(current_stem, repaired_stem):
            target["stem"] = repaired_stem
            target["content"] = repaired_stem

        meta = dict(target.get("extraction_meta") or {})
        self._append_llm_fix_action(
            target,
            meta,
            action={
                "action": "repair_options",
                "issue_type": issue.get("issue_type"),
                "added_options": [
                    {
                        "key": option["key"],
                        "source": option["source"],
                    }
                    for option in added_options
                ],
                "reason": fix_action.get("reason"),
            },
        )
        return questions

    @staticmethod
    def _collect_source_text(
        questions: List[Dict[str, Any]],
        index: int,
    ) -> str:
        parts: List[str] = []
        for question in questions[
            max(0, index - 1):min(len(questions), index + 2)
        ]:
            for key in ("raw_text", "stem", "content"):
                value = question.get(key)
                if value:
                    parts.append(str(value))
            for option in question.get("options") or []:
                text = (
                    option.get("text")
                    if isinstance(option, dict)
                    else None
                )
                if text:
                    parts.append(str(text))
            for block in question.get("blocks") or []:
                if isinstance(block, dict):
                    text = (
                        block.get("content_text")
                        or block.get("content_md")
                        or ""
                    )
                else:
                    text = (
                        getattr(block, "content_text", None)
                        or getattr(block, "content_md", None)
                        or ""
                    )
                if text:
                    parts.append(str(text))
        return "\n".join(parts)

    @staticmethod
    def _normalize_source_text(text: str) -> str:
        return re.sub(r"[\s　]+", "", text or "")

    @classmethod
    def _text_exists_in_source(
        cls,
        text: str,
        source_text: str,
    ) -> bool:
        normalized = cls._normalize_source_text(text)
        return bool(
            normalized
            and normalized in cls._normalize_source_text(source_text)
        )

    @classmethod
    def _is_safe_repaired_stem(
        cls,
        current_stem: str,
        repaired_stem: str,
    ) -> bool:
        if not repaired_stem:
            return False
        current_normalized = cls._normalize_source_text(current_stem)
        repaired_normalized = cls._normalize_source_text(repaired_stem)
        return bool(
            repaired_normalized
            and current_normalized
            and repaired_normalized in current_normalized
        )

    @staticmethod
    def _append_llm_fix_action(
        question: Dict[str, Any],
        meta: Dict[str, Any],
        action: Dict[str, Any],
    ) -> None:
        actions = list(meta.get("llm_fix_actions") or [])
        actions.append(action)
        meta["llm_fix_actions"] = actions
        meta["fixed_by_llm"] = True
        question["fixed_by_llm"] = True
        question["llm_fix_actions"] = actions
        question["extraction_meta"] = meta


__all__ = ["LLMFallbackFixer"]
