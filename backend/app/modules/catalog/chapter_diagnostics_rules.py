"""章节归属诊断的纯规则与响应组装工具。"""

import re
from typing import Any, Dict, List, Optional, Tuple

DIAG_OPTION_BLOCK_RE = re.compile(r"^\s*[A-H]\s*[.．、:：]\s*\S+")
DIAG_QUESTION_NUMERIC_RE = re.compile(
    r"^\s*\d{1,3}(?:\s*[.、．。]\s*|\s+)(?=\S)"
)
DIAG_QUESTION_PAREN_RE = re.compile(r"^\s*[（(]\s*\d{1,3}\s*[）)]\s*\S+")
DIAG_QUESTION_TITLE_RE = re.compile(
    r"^\s*第\s*[一二三四五六七八九十百千\d]+\s*题"
)
DIAG_QUESTION_CUE_RE = re.compile(
    r"[?？]|下列|以下|关于|若|设|已知|正确|错误|不是|可以|能够|应|属于|采用|"
    r"给出|求|计算|证明|说明|分析|为什么|多少|哪个|哪些|如果|判断"
)

EXAM_DOC_TYPES = {"past_exam", "mock_exam"}

MappingTuple = Tuple[Any, Any, Any]


def float_or_none(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


def block_text(block: Any) -> str:
    return (block.content_text or block.content_md or "").strip()


def text_excerpt(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def looks_like_option_block(text: str) -> bool:
    return bool(DIAG_OPTION_BLOCK_RE.match(text or ""))


def looks_like_question_start(text: str, block_type: str) -> bool:
    if not text or block_type not in ("paragraph", "heading", "list"):
        return False
    if looks_like_option_block(text):
        return False
    if DIAG_QUESTION_TITLE_RE.match(text):
        return True
    if DIAG_QUESTION_PAREN_RE.match(text):
        return bool(DIAG_QUESTION_CUE_RE.search(text)) or len(text) > 20
    if DIAG_QUESTION_NUMERIC_RE.match(text):
        return bool(DIAG_QUESTION_CUE_RE.search(text)) or len(text) > 20
    return False


def build_section_range(
    section: Any,
    block_index: Dict[str, int],
    total_blocks: int,
) -> Dict[str, Any]:
    start_idx = (
        block_index.get(section.block_start_id)
        if section.block_start_id
        else None
    )
    end_idx = (
        block_index.get(section.block_end_id)
        if section.block_end_id
        else None
    )
    if start_idx is None:
        start_idx = 0
    if end_idx is None:
        end_idx = max(total_blocks - 1, start_idx)
    if end_idx < start_idx:
        end_idx = start_idx
    return {
        "section": section,
        "start_idx": start_idx,
        "end_idx": end_idx,
    }


def section_for_page(
    page_no: int,
    section_ranges: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    candidates = []
    for section_range in section_ranges:
        section = section_range["section"]
        if not section.page_start:
            continue
        page_end = section.page_end or section.page_start
        if section.page_start <= page_no <= page_end:
            candidates.append(section_range)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item["section"].level,
            item["section"].page_start or 0,
            item["start_idx"],
        ),
    )


def section_for_block(
    block: Any,
    block_index: Dict[str, int],
    section_ranges: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    block_idx = block_index.get(block.id)
    candidates = []
    for section_range in section_ranges:
        section = section_range["section"]
        page_end = section.page_end or section.page_start
        page_matches = (
            section.page_start is not None
            and page_end is not None
            and section.page_start <= block.page_no <= page_end
        )
        index_matches = (
            block_idx is not None
            and section_range["start_idx"]
            <= block_idx
            <= section_range["end_idx"]
        )
        if page_matches and index_matches:
            candidates.append(section_range)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item["section"].level,
            item["section"].page_start or 0,
            item["start_idx"],
        ),
    )


def select_mapping_for_section(
    section_id: str,
    mappings_by_section: Dict[str, List[MappingTuple]],
    accepted_only: bool = False,
) -> Optional[MappingTuple]:
    mappings = mappings_by_section.get(section_id, [])
    if accepted_only:
        mappings = [
            item
            for item in mappings
            if item[0].review_status in ("approved", "pending")
        ]
    if not mappings:
        return None
    return max(
        mappings,
        key=lambda item: (
            1 if item[0].review_status in ("approved", "pending") else 0,
            float_or_none(item[0].confidence) or 0,
        ),
    )


def resolve_page_mapping(
    page_no: Optional[int],
    page_mappings: Dict[int, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if page_no is None or not page_mappings:
        return None
    if page_no in page_mappings:
        return {
            **page_mappings[page_no],
            "source": "section_range",
            "fallback_distance": 0,
        }

    previous_pages = [page for page in page_mappings if page <= page_no]
    if previous_pages:
        previous_page = max(previous_pages)
        return {
            **page_mappings[previous_page],
            "source": "previous_page",
            "fallback_distance": page_no - previous_page,
        }

    next_pages = [page for page in page_mappings if page > page_no]
    if next_pages:
        next_page = min(next_pages)
        return {
            **page_mappings[next_page],
            "source": "next_page",
            "fallback_distance": next_page - page_no,
        }
    return None


def section_to_diag_dict(section: Any) -> Dict[str, Any]:
    return {
        "id": section.id,
        "title": section.title,
        "section_path": section.section_path,
        "level": section.level,
        "page_start": section.page_start,
        "page_end": section.page_end,
        "block_start_id": section.block_start_id,
        "block_end_id": section.block_end_id,
        "confidence": float_or_none(section.confidence),
    }


def mapping_to_dict(
    mapping: Any,
    chapter: Any,
    subject: Any,
    *,
    section: Any,
    source: str,
    fallback_distance: int,
) -> Dict[str, Any]:
    return {
        "mapping_id": mapping.id,
        "section_id": section.id,
        "section_title": section.title,
        "section_path": section.section_path,
        "canonical_chapter_id": chapter.id,
        "canonical_chapter_name": chapter.name,
        "canonical_chapter_code": chapter.code,
        "subject_id": subject.id,
        "subject_name": subject.name,
        "mapping_type": mapping.mapping_type,
        "confidence": float_or_none(mapping.confidence),
        "review_status": mapping.review_status,
        "source": source,
        "fallback_distance": fallback_distance,
    }


def section_with_mapping_to_diag_dict(
    section: Any,
    mappings_by_section: Dict[str, List[MappingTuple]],
) -> Dict[str, Any]:
    raw_mapping = select_mapping_for_section(
        section.id,
        mappings_by_section,
    )
    return {
        **section_to_diag_dict(section),
        "mapping": (
            mapping_to_dict(
                *raw_mapping,
                section=section,
                source="native_section",
                fallback_distance=0,
            )
            if raw_mapping
            else None
        ),
    }


def page_issues(
    active_section: Optional[Dict[str, Any]],
    section_mapping: Optional[Dict[str, Any]],
    extraction_mapping: Optional[Dict[str, Any]],
    is_exam_doc: bool = False,
) -> List[Dict[str, str]]:
    if is_exam_doc:
        if not extraction_mapping:
            return [{
                "code": "exam_no_chapter_mapping",
                "severity": "error",
                "message": "试卷类文档需要在抽取时显式指定学科或题目级章节归属",
            }]
        return []
    if not active_section:
        return [{
            "code": "no_native_section",
            "severity": "warning",
            "message": "该页没有原生标题树覆盖，抽取只能依赖相邻页章节归属或兜底学科",
        }]
    return ownership_issues(section_mapping, extraction_mapping)


def block_issues(
    active_section: Optional[Dict[str, Any]],
    section_mapping: Optional[Dict[str, Any]],
    extraction_mapping: Optional[Dict[str, Any]],
    is_exam_doc: bool = False,
) -> List[Dict[str, str]]:
    if is_exam_doc:
        if not extraction_mapping:
            return [{
                "code": "exam_no_chapter_mapping",
                "severity": "warning",
                "message": "试卷类文档需要在抽取时显式指定学科",
            }]
        return []
    if not active_section:
        return [{
            "code": "no_native_section",
            "severity": "warning",
            "message": "该块没有原生标题树覆盖",
        }]
    return ownership_issues(section_mapping, extraction_mapping)


def ownership_issues(
    section_mapping: Optional[Dict[str, Any]],
    extraction_mapping: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    issues = []
    if not section_mapping:
        if extraction_mapping:
            issues.append({
                "code": "section_unmapped_using_fallback",
                "severity": "warning",
                "message": "当前原生章节未映射，抽取将使用相邻页或范围内已有映射",
            })
        else:
            issues.append({
                "code": "section_unmapped",
                "severity": "error",
                "message": "当前原生章节没有可用标准章节映射",
            })
        return issues

    if section_mapping.get("review_status") == "rejected":
        if extraction_mapping:
            issues.append({
                "code": "section_mapping_rejected_using_fallback",
                "severity": "warning",
                "message": "当前章节映射已拒绝，抽取会跳过它并使用其他可用映射",
            })
        else:
            issues.append({
                "code": "section_mapping_rejected",
                "severity": "error",
                "message": "当前章节映射已拒绝，抽取没有可用章节归属",
            })
        return issues

    if not extraction_mapping:
        issues.append({
            "code": "no_extraction_mapping",
            "severity": "error",
            "message": "章节映射存在，但抽取链路没有解析到可用页级归属",
        })
        return issues

    if extraction_mapping.get("source") in ("previous_page", "next_page"):
        issues.append({
            "code": "extraction_mapping_from_neighbor_page",
            "severity": "warning",
            "message": "抽取归属来自相邻页回退，建议检查标题树页码范围",
        })

    if (
        section_mapping.get("canonical_chapter_id")
        != extraction_mapping.get("canonical_chapter_id")
    ):
        issues.append({
            "code": "native_section_mapping_differs_from_extraction",
            "severity": "warning",
            "message": "原生章节自身映射与抽取最终归属不一致",
        })

    return issues


def diagnostic_status(issues: List[Dict[str, str]]) -> str:
    if any(issue.get("severity") == "error" for issue in issues):
        return "error"
    if issues:
        return "warning"
    return "ok"
