"""Deterministic question-type classification helpers."""

import re
from typing import Any, Dict, List


SUBQUESTION_RE = re.compile(
    r"[（(]\s*([1-9]\d*)\s*[）)]"
)
SCORE_RE = re.compile(r"[（(]\s*\d+\s*分\s*[）)]")
SUBJECTIVE_CUE_RE = re.compile(
    r"请(?:回答|说明|计算|证明|分析|画出|写出|指出)|"
    r"回答下列问题|"
    r"给出(?:算法|步骤|过程|理由|证明)|"
    r"说明(?:理由|原因|过程|复杂度)|"
    r"写明(?:步骤|过程|信号)"
)
CHOICE_BLANK_RE = re.compile(
    r"[（(]\s*(?:[）)]|_|　|\.{2,}|…{1,2})"
)
CHOICE_CUE_RE = re.compile(
    r"(?:下列|以下).{0,40}"
    r"(?:正确|错误|不正确|不属于|符合|可行|恰当|最佳)|"
    r"(?:正确|错误|不正确)的(?:是|有)|"
    r"(?:选择|选出).{0,20}(?:正确|错误|最佳|恰当)"
)


def is_subjective_question_text(text: str) -> bool:
    """Identify multi-part subjective questions before parsing A-D tokens."""
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if CHOICE_BLANK_RE.search(normalized) or CHOICE_CUE_RE.search(normalized):
        return False

    subquestion_numbers = {
        match.group(1)
        for match in SUBQUESTION_RE.finditer(normalized)
    }
    if len(subquestion_numbers) < 2:
        return False
    return bool(
        SUBJECTIVE_CUE_RE.search(normalized)
        or SCORE_RE.search(normalized)
    )


def infer_question_type(
    text: str,
    options: List[Dict[str, Any]],
) -> str:
    """Infer the persisted question type without trusting option tokens alone."""
    normalized = str(text or "").strip()
    if is_subjective_question_text(normalized):
        return "short_answer"
    if options:
        return "choice"
    if "判断" in normalized[:50]:
        return "judge"
    if "填空" in normalized[:50]:
        return "fill"
    return "short_answer"


def looks_like_subjective_question(question: Dict[str, Any]) -> bool:
    """Use the untruncated source text when checking a question candidate."""
    source_text = (
        question.get("raw_text")
        or question.get("content")
        or question.get("stem")
        or ""
    )
    return is_subjective_question_text(str(source_text))


def normalize_subjective_question(
    question: Dict[str, Any],
) -> bool:
    """Restore a false choice candidate to a source-faithful subjective form."""
    if not looks_like_subjective_question(question):
        return False

    raw_text = str(
        question.get("raw_text")
        or question.get("content")
        or question.get("stem")
        or ""
    ).strip()
    previous_type = question.get("question_type") or question.get("type")
    previous_options = list(question.get("options") or [])
    changed = bool(
        previous_type != "short_answer"
        or previous_options
        or question.get("stem") != raw_text
        or question.get("content") != raw_text
    )
    if not changed:
        return False

    question["question_type"] = "short_answer"
    question["type"] = "short_answer"
    question["stem"] = raw_text
    question["content"] = raw_text
    question["options"] = []

    meta = dict(question.get("extraction_meta") or {})
    corrections = list(meta.get("structure_corrections") or [])
    correction = {
        "action": "restore_subjective_question",
        "previous_type": previous_type,
        "discarded_option_labels": [
            str(
                option.get("key")
                or option.get("label")
                or option.get("option_label")
                or ""
            ).strip().upper()[:1]
            for option in previous_options
            if isinstance(option, dict)
        ],
    }
    if correction not in corrections:
        corrections.append(correction)
    meta.update({
        "structure_corrections": corrections,
        "option_count": 0,
        "few_options": False,
        "suspected_truncated_options": False,
    })
    question["extraction_meta"] = meta
    return True


__all__ = [
    "infer_question_type",
    "is_subjective_question_text",
    "looks_like_subjective_question",
    "normalize_subjective_question",
]
