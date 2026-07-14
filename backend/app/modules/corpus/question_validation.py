"""Deterministic validation and repair rules for extracted questions."""

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


def get_option_label(option: Dict[str, Any]) -> str:
    """Read an option label from the supported extraction field names."""
    value = option.get("key") or option.get("label") or option.get("option_label") or ""
    return str(value).strip().upper()[:1]


class OptionIntegrityChecker:
    """Validate that choice questions contain a complete option set."""

    EXPECTED_OPTIONS = {
        "single_choice": ["A", "B", "C", "D"],
        "multiple_choice": ["A", "B", "C", "D"],
    }

    def check(self, question: Dict[str, Any]) -> Dict[str, Any]:
        question_type = question.get("question_type") or question.get("type")
        if question_type not in ["single_choice", "multiple_choice", "choice"]:
            return {
                "is_complete": True,
                "issue_type": "not_choice",
                "missing_options": [],
            }

        options = question.get("options", [])
        if not options:
            return {
                "is_complete": False,
                "missing_options": ["A", "B", "C", "D"],
                "issue_type": "missing_all",
            }

        option_labels = sorted(
            label for label in (get_option_label(option) for option in options) if label
        )
        if not option_labels:
            return {
                "is_complete": False,
                "missing_options": ["A", "B", "C", "D"],
                "issue_type": "missing_all",
            }

        first_label = option_labels[0]
        last_label = option_labels[-1]
        expected_labels = [
            chr(ord(first_label) + offset)
            for offset in range(ord(last_label) - ord(first_label) + 1)
        ]
        missing = set(expected_labels) - set(option_labels)

        if not missing:
            if len(option_labels) < 4:
                missing_count = 4 - len(option_labels)
                return {
                    "is_complete": False,
                    "missing_options": [
                        chr(ord(last_label) + offset + 1)
                        for offset in range(missing_count)
                    ],
                    "issue_type": "too_few",
                }
            return {
                "is_complete": True,
                "issue_type": "complete",
                "missing_options": [],
            }

        missing_list = sorted(missing)
        expected_end = expected_labels[-len(missing_list):]
        expected_start = expected_labels[:len(missing_list)]
        if set(missing_list) == set(expected_end):
            issue_type = "missing_end"
        elif set(missing_list) == set(expected_start):
            issue_type = "missing_start"
        else:
            issue_type = "missing_middle"

        return {
            "is_complete": False,
            "missing_options": missing_list,
            "issue_type": issue_type,
        }


class QuestionNumberChecker:
    """Detect numbering gaps, duplicates, jumps, and unnumbered questions."""

    NUMBER_PATTERNS = [
        (r"^(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)", "arabic"),
        (r"^[（(](\d+)[）)]\s*", "paren"),
        (r"^\[(\d+)\]\s*", "bracket"),
        (r"^例(\d+)", "example"),
        (r"^第(\d+)题", "diti"),
    ]

    def extract_question_numbers(
        self,
        questions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        results = []
        for index, question in enumerate(questions):
            text = (
                question.get("stem")
                or question.get("content")
                or question.get("raw_text", "")
            ).strip()
            number_info = None
            for pattern, pattern_type in self.NUMBER_PATTERNS:
                match = re.match(pattern, text)
                if match:
                    number_info = {
                        "index": index,
                        "number": int(match.group(1)),
                        "pattern": pattern_type,
                        "text": match.group(0),
                        "question": question,
                    }
                    break
            results.append(
                number_info
                or {
                    "index": index,
                    "number": None,
                    "pattern": "none",
                    "text": "",
                    "question": question,
                }
            )
        return results

    def detect_continuity_issues(
        self,
        number_infos: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        segments = self._segment_by_pattern(number_infos)
        for segment in segments:
            segment["issues"] = self._check_segment_continuity(segment)
        return {
            "segments": segments,
            "global_issues": self._compute_global_stats(number_infos),
        }

    def _segment_by_pattern(
        self,
        number_infos: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        segments = []
        current_segment = {
            "start_index": 0,
            "numbers": [],
            "pattern": None,
            "infos": [],
        }

        for index, info in enumerate(number_infos):
            number = info["number"]
            pattern = info["pattern"]
            if pattern == "none":
                continue

            should_start_new_segment = (
                (
                    current_segment["pattern"]
                    and pattern != current_segment["pattern"]
                )
                or (
                    number == 1
                    and current_segment["numbers"]
                    and current_segment["numbers"][-1] != 0
                )
            )
            if should_start_new_segment:
                current_segment["end_index"] = index - 1
                if current_segment["numbers"]:
                    current_segment["number_range"] = (
                        min(current_segment["numbers"]),
                        max(current_segment["numbers"]),
                    )
                    segments.append(current_segment)
                current_segment = {
                    "start_index": index,
                    "numbers": [number],
                    "pattern": pattern,
                    "infos": [info],
                }
                continue

            current_segment["numbers"].append(number)
            current_segment["infos"].append(info)
            current_segment["pattern"] = pattern

        if current_segment["numbers"]:
            current_segment["end_index"] = len(number_infos) - 1
            current_segment["number_range"] = (
                min(current_segment["numbers"]),
                max(current_segment["numbers"]),
            )
            segments.append(current_segment)
        return segments

    def _check_segment_continuity(
        self,
        segment: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        issues = []
        numbers = segment["numbers"]
        infos = segment["infos"]
        if not numbers:
            return issues

        expected_numbers = range(numbers[0], numbers[0] + len(numbers))
        missing = set(expected_numbers) - set(numbers)
        for missing_number in sorted(missing):
            before_index = None
            for offset, number in enumerate(numbers):
                if number < missing_number:
                    before_index = infos[offset]["index"]
            issues.append({
                "type": "missing",
                "missing_number": missing_number,
                "after_index": before_index,
                "severity": "high",
            })

        duplicates = [
            number
            for number, count in Counter(numbers).items()
            if count > 1
        ]
        for duplicate in duplicates:
            issues.append({
                "type": "duplicate",
                "number": duplicate,
                "indices": [
                    info["index"]
                    for info in infos
                    if info["number"] == duplicate
                ],
                "severity": "medium",
            })

        for offset in range(len(numbers) - 1):
            difference = numbers[offset + 1] - numbers[offset]
            if difference > 1:
                issues.append({
                    "type": "jump",
                    "from_number": numbers[offset],
                    "to_number": numbers[offset + 1],
                    "gap": difference - 1,
                    "at_index": infos[offset + 1]["index"],
                    "severity": "high",
                })
            elif difference < 0:
                issues.append({
                    "type": "reverse",
                    "from_number": numbers[offset],
                    "to_number": numbers[offset + 1],
                    "at_index": infos[offset + 1]["index"],
                    "severity": "high",
                })
        return issues

    @staticmethod
    def _compute_global_stats(
        number_infos: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        total = len(number_infos)
        numbered = sum(
            1 for info in number_infos if info["number"] is not None
        )
        return {
            "total_questions": total,
            "numbered_questions": numbered,
            "unnumbered_questions": total - numbered,
            "unnumbered_indices": [
                info["index"]
                for info in number_infos
                if info["number"] is None
            ],
        }


class RuleBasedFixer:
    """Repair deterministic option and numbering issues."""

    def __init__(self):
        self.option_checker = OptionIntegrityChecker()

    def fix_option_issues(
        self,
        questions: List[Dict[str, Any]],
        option_issues: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        fixed_questions = questions.copy()
        for issue in option_issues:
            index = issue["question_index"]
            missing = issue["missing_options"]
            if issue["issue_type"] != "missing_end":
                continue
            found_options = self._search_options_forward(
                questions,
                index,
                missing,
                max_distance=3,
            )
            if not found_options:
                continue
            fixed_questions[index].setdefault("options", []).extend(
                found_options["options"]
            )
            fixed_questions[index]["fixed_by_rule"] = "option_append"
            fixed_questions[index]["fixed_source_index"] = found_options[
                "source_index"
            ]
            logger.info(
                f"Fixed question {index}: appended options {missing}"
            )
        return fixed_questions

    def fix_number_issues(
        self,
        questions: List[Dict[str, Any]],
        continuity_report: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        fixed_questions = questions.copy()
        for segment in continuity_report["segments"]:
            for issue in segment["issues"]:
                if issue["type"] == "missing":
                    fixed = self._fix_missing_number(
                        fixed_questions,
                        issue["missing_number"],
                        issue["after_index"],
                    )
                elif issue["type"] == "duplicate":
                    fixed = self._fix_duplicate_number(
                        fixed_questions,
                        issue["number"],
                        issue["indices"],
                    )
                else:
                    fixed = None
                if fixed:
                    fixed_questions = fixed
        return fixed_questions

    def _search_options_forward(
        self,
        questions: List[Dict[str, Any]],
        start_index: int,
        missing_labels: List[str],
        max_distance: int,
    ) -> Optional[Dict[str, Any]]:
        current_page = questions[start_index].get("page_no", 0)
        for offset in range(1, max_distance + 1):
            candidate_index = start_index + offset
            if candidate_index >= len(questions):
                break
            candidate = questions[candidate_index]
            if abs(candidate.get("page_no", 0) - current_page) > 1:
                break
            options = candidate.get("options", [])
            labels = [get_option_label(option) for option in options]
            if set(labels) == set(missing_labels):
                return {
                    "source_index": candidate_index,
                    "options": options,
                }
            found_labels = set(labels) & set(missing_labels)
            if found_labels:
                return {
                    "source_index": candidate_index,
                    "options": [
                        option
                        for option in options
                        if get_option_label(option) in found_labels
                    ],
                    "partial": True,
                }
        return None

    def _fix_missing_number(
        self,
        questions: List[Dict[str, Any]],
        missing_number: int,
        after_index: Optional[int],
    ) -> Optional[List[Dict[str, Any]]]:
        if after_index is None:
            return None
        for offset in range(1, 4):
            candidate_index = after_index + offset
            if candidate_index >= len(questions):
                break
            candidate = questions[candidate_index]
            if (
                self._extract_number(candidate) is None
                and self._looks_like_complete_question(candidate)
            ):
                candidate["inferred_number"] = missing_number
                candidate["fixed_by_rule"] = "number_infer"
                logger.info(
                    "Inferred missing number "
                    f"{missing_number} for question at index {candidate_index}"
                )
                return questions
        return None

    def _fix_duplicate_number(
        self,
        questions: List[Dict[str, Any]],
        duplicate_number: int,
        duplicate_indices: List[int],
    ) -> Optional[List[Dict[str, Any]]]:
        if len(duplicate_indices) != 2:
            return None
        first_index, second_index = duplicate_indices
        first = questions[first_index]
        second = questions[second_index]
        if not self._should_merge_duplicates(first, second):
            return None
        merged = self._merge_questions(first, second)
        merged["fixed_by_rule"] = "duplicate_merge"
        logger.info(
            "Merged duplicate number "
            f"{duplicate_number} at indices {first_index}, {second_index}"
        )
        return (
            questions[:first_index]
            + [merged]
            + questions[first_index + 1:second_index]
            + questions[second_index + 1:]
        )

    @staticmethod
    def _extract_number(question: Dict[str, Any]) -> Optional[int]:
        text = (
            question.get("stem")
            or question.get("content")
            or question.get("raw_text", "")
        ).strip()
        for pattern, _ in QuestionNumberChecker.NUMBER_PATTERNS:
            match = re.match(pattern, text)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _looks_like_complete_question(question: Dict[str, Any]) -> bool:
        stem_length = len(
            question.get("stem", "") or question.get("content", "")
        )
        return stem_length > 20 and bool(question.get("options", []))

    def _should_merge_duplicates(
        self,
        first: Dict[str, Any],
        second: Dict[str, Any],
    ) -> bool:
        if abs(second.get("page_no", 0) - first.get("page_no", 0)) > 1:
            return False
        result = self.option_checker.check(first)
        return (
            not result["is_complete"]
            and result["issue_type"] == "missing_end"
            and len(second.get("stem", "") or second.get("content", "")) < 20
            and bool(second.get("options", []))
        )

    @staticmethod
    def _merge_questions(
        first: Dict[str, Any],
        second: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = first.copy()
        first_stem = first.get("stem", "") or first.get("content", "")
        second_stem = second.get("stem", "") or second.get("content", "")
        merged["stem"] = (first_stem + " " + second_stem).strip()
        if "content" in merged:
            merged["content"] = merged["stem"]
        merged["options"] = (
            first.get("options", []) + second.get("options", [])
        )
        merged["page_range"] = (
            f"{first.get('page_no')}-{second.get('page_no')}"
        )
        return merged


def extract_question_number(question: Dict[str, Any]) -> Optional[int]:
    """Extract a leading question number using the validation patterns."""
    text = (question.get("stem") or question.get("content") or "").strip()
    for pattern, _ in QuestionNumberChecker.NUMBER_PATTERNS:
        match = re.match(pattern, text)
        if match:
            return int(match.group(1))
    return None


def comprehensive_validation(
    questions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the combined option, numbering, and quantity report."""
    option_checker = OptionIntegrityChecker()
    number_checker = QuestionNumberChecker()

    option_issues = []
    for index, question in enumerate(questions):
        result = option_checker.check(question)
        if not result["is_complete"]:
            option_issues.append({
                "question_index": index,
                "question_number": extract_question_number(question),
                "page_no": question.get("page_no"),
                **result,
            })

    number_infos = number_checker.extract_question_numbers(questions)
    continuity_report = number_checker.detect_continuity_issues(number_infos)
    max_number = max(
        [info["number"] for info in number_infos if info["number"]],
        default=0,
    )
    quantity_check = {
        "total_extracted": len(questions),
        "max_number_found": max_number,
        "is_consistent": (
            len(questions)
            == continuity_report["global_issues"]["numbered_questions"]
        ),
    }

    critical_issues = list(option_issues)
    for segment in continuity_report["segments"]:
        for issue in segment["issues"]:
            if issue["severity"] == "high":
                critical_issues.append({
                    "question_index": issue.get(
                        "after_index",
                        issue.get("at_index", 0),
                    ),
                    "issue_type": issue["type"],
                    **issue,
                })

    return {
        "option_issues": option_issues,
        "number_continuity": continuity_report,
        "quantity_check": quantity_check,
        "summary": {
            "total_issues": (
                len(option_issues)
                + sum(
                    len(segment["issues"])
                    for segment in continuity_report["segments"]
                )
            ),
            "critical_issues": critical_issues,
        },
    }


__all__ = [
    "OptionIntegrityChecker",
    "QuestionNumberChecker",
    "RuleBasedFixer",
    "comprehensive_validation",
    "extract_question_number",
    "get_option_label",
]
