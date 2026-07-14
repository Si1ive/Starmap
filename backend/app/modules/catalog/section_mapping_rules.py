"""文档 section 到标准章节的纯匹配规则。"""

from typing import Any, Dict, Iterable, Optional, Tuple

ChapterIndex = Dict[str, Dict[str, Any]]
SectionMatch = Tuple[str, float, str]


def build_chapter_index(chapters: Iterable[Any]) -> ChapterIndex:
    """按名称、别名和编码构建章节匹配索引。"""
    index: ChapterIndex = {}

    for chapter in chapters:
        name_lower = chapter.name.lower().strip()
        index[name_lower] = {
            "id": chapter.id,
            "level": chapter.level,
            "match_type": "exact",
        }

        for alias in chapter.aliases or []:
            alias_lower = alias.lower().strip()
            if alias_lower not in index:
                index[alias_lower] = {
                    "id": chapter.id,
                    "level": chapter.level,
                    "match_type": "alias",
                }

        if chapter.code:
            code_lower = chapter.code.lower().strip()
            if code_lower not in index:
                index[code_lower] = {
                    "id": chapter.id,
                    "level": chapter.level,
                    "match_type": "code",
                }

    return index


def match_section_multi(
    section: Any,
    chapter_indices: Dict[str, ChapterIndex],
) -> Optional[SectionMatch]:
    """跨学科匹配 section，并返回置信度最高的结果。"""
    best: Optional[SectionMatch] = None
    for chapter_index in chapter_indices.values():
        result = match_section(section, chapter_index)
        if result and (best is None or result[1] > best[1]):
            best = result
    return best


def match_section(
    section: Any,
    chapter_index: ChapterIndex,
) -> Optional[SectionMatch]:
    """按标题、路径、包含关系和公共词依次匹配标准章节。"""
    title = section.title.lower().strip()
    section_path = (
        section.section_path.lower().strip()
        if section.section_path
        else ""
    )

    if title in chapter_index:
        info = chapter_index[title]
        return info["id"], 1.0, "exact"

    if section_path:
        for key, info in chapter_index.items():
            if key in section_path or section_path in key:
                return info["id"], 0.85, "partial"

    best_match: Optional[SectionMatch] = None
    best_score = 0.0

    for key, info in chapter_index.items():
        if key in title:
            score = len(key) / max(len(title), 1)
            if score > best_score:
                best_score = score
                best_match = (
                    info["id"],
                    0.7 + score * 0.2,
                    "partial",
                )

        if title in key and len(title) > 3:
            score = len(title) / max(len(key), 1)
            if score > best_score:
                best_score = score
                best_match = (
                    info["id"],
                    0.6 + score * 0.2,
                    "partial",
                )

    if best_match and best_match[1] >= 0.5:
        return best_match

    title_words = set(title.replace(">", " ").replace("  ", " ").split())
    for key, info in chapter_index.items():
        key_words = set(key.replace(">", " ").replace("  ", " ").split())
        common_words = title_words & key_words
        if len(common_words) >= 2:
            score = len(common_words) / max(
                len(title_words),
                len(key_words),
                1,
            )
            if score > 0.3:
                return info["id"], 0.5 + score * 0.3, "related"

    return None
