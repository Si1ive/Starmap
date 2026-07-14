"""LLM-assisted repair for question extraction issues."""

import json
import re
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.modules.corpus.question_repair_prompts import (
    build_choice_fix_prompt,
    build_fix_prompt,
    build_subjective_fix_prompt,
)
from app.modules.corpus.question_repair_rules import (
    collect_context_source_text,
    collect_target_source_text,
    is_safe_option_replacement,
    is_safe_repaired_stem,
    normalize_source_text,
    text_exists_in_source,
)
from app.modules.corpus.question_type import (
    looks_like_subjective_question,
    normalize_subjective_question,
)
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
            if (
                issue.get("issue_type")
                in {
                    "missing_all",
                    "missing_start",
                    "missing_middle",
                    "missing_end",
                    "too_few",
                }
                and looks_like_subjective_question(questions[index])
            ):
                self._remember_original_issue(questions[index], issue)
                if normalize_subjective_question(questions[index]):
                    logger.info(
                        "Restored false choice as subjective question",
                        question_index=index,
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
        return build_fix_prompt(context, target_idx, issue)

    def _build_choice_fix_prompt(
        self,
        context: List[Dict[str, Any]],
        target_idx: int,
        issue: Dict[str, Any],
    ) -> str:
        """Build a repair prompt for an objective choice question."""
        return build_choice_fix_prompt(context, target_idx, issue)

    def _build_subjective_fix_prompt(
        self,
        context: List[Dict[str, Any]],
        target_idx: int,
        issue: Dict[str, Any],
    ) -> str:
        """Build a repair prompt for a subjective multi-part question."""
        return build_subjective_fix_prompt(context, target_idx, issue)

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
                if action not in {
                    "repair_options",
                    "repair_subjective",
                    "merge",
                    "none",
                }:
                    if result.get("should_merge"):
                        action = "merge"
                    elif (
                        isinstance(repaired_question, dict)
                        and (
                            repaired_question.get("question_type")
                            == "short_answer"
                            or repaired_question.get("options") == []
                        )
                    ):
                        action = "repair_subjective"
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
        if fix_action.get("action") == "repair_subjective":
            return self._apply_subjective_repair(
                questions,
                index,
                fix_action,
            )
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
        """Add missing options and restore source-verified truncations."""
        if index < 0 or index >= len(questions):
            return questions
        repaired = fix_action.get("repaired_question")
        if not isinstance(repaired, dict):
            return questions

        target = questions[index]
        if looks_like_subjective_question(target):
            logger.warning(
                "Rejected option repair for subjective question",
                question_index=index,
            )
            return questions
        existing_options = [
            dict(option)
            for option in target.get("options") or []
            if isinstance(option, dict)
        ]
        existing_by_label = {
            get_option_label(option): option
            for option in existing_options
            if get_option_label(option)
        }
        existing_labels = {
            label for label in existing_by_label if label
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
        target_source_text = self._collect_target_source_text(target)
        added_options: List[Dict[str, Any]] = []
        replaced_options: List[Dict[str, Any]] = []
        for option in repaired.get("options") or []:
            if not isinstance(option, dict):
                continue
            label = get_option_label(option)
            text = str(
                option.get("text") or option.get("content") or ""
            ).strip()
            if label not in {"A", "B", "C", "D"} or not text:
                continue
            existing_option = existing_by_label.get(label)
            if existing_option:
                previous_text = str(
                    existing_option.get("text")
                    or existing_option.get("content")
                    or ""
                ).strip()
                if not self._is_safe_option_replacement(
                    previous_text,
                    text,
                    target_source_text,
                ):
                    continue
                existing_option["text"] = text
                existing_option.pop("content", None)
                existing_option["source"] = "extracted"
                replaced_options.append({
                    "key": label,
                    "previous_text": previous_text,
                    "text": text,
                    "source": "extracted",
                })
                continue
            if label not in missing_labels:
                continue
            source = (
                "extracted"
                if self._text_exists_in_source(text, source_text)
                else "ai_generated"
            )
            added_option = {
                "key": label,
                "label": label,
                "option_label": label,
                "text": text,
                "source": source,
            }
            added_options.append(added_option)
            existing_by_label[label] = added_option
            existing_labels.add(label)

        if not added_options and not replaced_options:
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
                "replaced_options": replaced_options,
                "reason": fix_action.get("reason"),
            },
        )
        return questions

    def _apply_subjective_repair(
        self,
        questions: List[Dict[str, Any]],
        index: int,
        fix_action: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if index < 0 or index >= len(questions):
            return questions
        repaired = fix_action.get("repaired_question")
        if not isinstance(repaired, dict):
            return questions

        target = questions[index]
        repaired_stem = str(
            repaired.get("stem") or repaired.get("content") or ""
        ).strip()
        source_text = self._collect_target_source_text(target)
        if not self._text_exists_in_source(repaired_stem, source_text):
            logger.warning(
                "Rejected subjective repair not found in target source",
                question_index=index,
            )
            return questions

        target["stem"] = repaired_stem
        target["content"] = repaired_stem
        target["question_type"] = "short_answer"
        target["type"] = "short_answer"
        target["options"] = []

        meta = dict(target.get("extraction_meta") or {})
        meta.update({
            "option_count": 0,
            "few_options": False,
            "suspected_truncated_options": False,
        })
        self._append_llm_fix_action(
            target,
            meta,
            action={
                "action": "repair_subjective",
                "issue_type": (
                    fix_action.get("issue") or {}
                ).get("issue_type"),
                "reason": fix_action.get("reason"),
            },
        )
        return questions

    @staticmethod
    def _collect_target_source_text(question: Dict[str, Any]) -> str:
        return collect_target_source_text(question)

    @staticmethod
    def _collect_source_text(
        questions: List[Dict[str, Any]],
        index: int,
    ) -> str:
        return collect_context_source_text(questions, index)

    @staticmethod
    def _normalize_source_text(text: str) -> str:
        return normalize_source_text(text)

    @classmethod
    def _text_exists_in_source(
        cls,
        text: str,
        source_text: str,
    ) -> bool:
        return text_exists_in_source(text, source_text)

    @classmethod
    def _is_safe_repaired_stem(
        cls,
        current_stem: str,
        repaired_stem: str,
    ) -> bool:
        return is_safe_repaired_stem(current_stem, repaired_stem)

    @classmethod
    def _is_safe_option_replacement(
        cls,
        current_text: str,
        repaired_text: str,
        source_text: str,
    ) -> bool:
        """Accept only a longer source-backed completion of existing text."""
        return is_safe_option_replacement(
            current_text,
            repaired_text,
            source_text,
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
