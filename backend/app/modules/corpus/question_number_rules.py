"""Question number extraction and continuity rules."""

import re
from collections import Counter
from typing import Any, Dict, List, Optional

NUMBER_PATTERNS = [
    (r"^(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)", "arabic"),
    (r"^[（(](\d+)[）)]\s*", "paren"),
    (r"^\[(\d+)\]\s*", "bracket"),
    (r"^例(\d+)", "example"),
    (r"^第(\d+)题", "diti"),
]


def parse_question_number(text: str) -> Optional[int]:
    """Extract a leading question number from normalized question text."""
    for pattern, _ in NUMBER_PATTERNS:
        match = re.match(pattern, text)
        if match:
            return int(match.group(1))
    return None


def extract_question_number(question: Dict[str, Any]) -> Optional[int]:
    """Extract a leading question number using the validation patterns."""
    text = (question.get("stem") or question.get("content") or "").strip()
    return parse_question_number(text)


class QuestionNumberChecker:
    """Detect numbering gaps, duplicates, jumps, and unnumbered questions."""

    NUMBER_PATTERNS = NUMBER_PATTERNS

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
                current_segment["pattern"] and pattern != current_segment["pattern"]
            ) or (
                number == 1
                and current_segment["numbers"]
                and current_segment["numbers"][-1] != 0
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
            issues.append(
                {
                    "type": "missing",
                    "missing_number": missing_number,
                    "after_index": before_index,
                    "severity": "high",
                }
            )

        duplicates = [number for number, count in Counter(numbers).items() if count > 1]
        for duplicate in duplicates:
            issues.append(
                {
                    "type": "duplicate",
                    "number": duplicate,
                    "indices": [
                        info["index"] for info in infos if info["number"] == duplicate
                    ],
                    "severity": "medium",
                }
            )

        for offset in range(len(numbers) - 1):
            difference = numbers[offset + 1] - numbers[offset]
            if difference > 1:
                issues.append(
                    {
                        "type": "jump",
                        "from_number": numbers[offset],
                        "to_number": numbers[offset + 1],
                        "gap": difference - 1,
                        "at_index": infos[offset + 1]["index"],
                        "severity": "high",
                    }
                )
            elif difference < 0:
                issues.append(
                    {
                        "type": "reverse",
                        "from_number": numbers[offset],
                        "to_number": numbers[offset + 1],
                        "at_index": infos[offset + 1]["index"],
                        "severity": "high",
                    }
                )
        return issues

    @staticmethod
    def _compute_global_stats(
        number_infos: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        total = len(number_infos)
        numbered = sum(1 for info in number_infos if info["number"] is not None)
        return {
            "total_questions": total,
            "numbered_questions": numbered,
            "unnumbered_questions": total - numbered,
            "unnumbered_indices": [
                info["index"] for info in number_infos if info["number"] is None
            ],
        }


__all__ = [
    "NUMBER_PATTERNS",
    "QuestionNumberChecker",
    "extract_question_number",
    "parse_question_number",
]
