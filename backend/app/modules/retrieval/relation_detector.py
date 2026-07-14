"""知识点之间的纯规则关系检测。"""

from typing import List, Optional, Protocol, Tuple


class RelationKnowledgePoint(Protocol):
    """规则检测所需的最小知识点字段集合。"""

    title: str
    content: str
    topic_terms: Optional[List[str]]
    primary_chapter_id: Optional[str]


RelationCandidate = Tuple[str, float, Optional[str], str]

CONTRAST_KEYWORDS = ("vs", "对比", "比较", "区别", "差异", "不同", "相反")
PREREQUISITE_KEYWORDS = (
    "前置",
    "先修",
    "基础",
    "预备",
    "需要先了解",
    "首先",
)


class KnowledgeRelationDetector:
    """根据知识点字段生成待审核的关系候选。"""

    def detect(
        self,
        knowledge_point: RelationKnowledgePoint,
        other: RelationKnowledgePoint,
    ) -> List[RelationCandidate]:
        terms = set(knowledge_point.topic_terms or []) | {knowledge_point.title}
        other_terms = set(other.topic_terms or []) | {other.title}
        common_terms = terms & other_terms

        if not common_terms:
            if (
                knowledge_point.primary_chapter_id
                and knowledge_point.primary_chapter_id
                == other.primary_chapter_id
            ):
                return [("similar_to", 0.5, "同一章节", "both")]
            return []

        relations: List[RelationCandidate] = []
        term_similarity = len(common_terms) / max(
            len(terms),
            len(other_terms),
            1,
        )
        title_similarity = self.string_similarity(
            knowledge_point.title,
            other.title,
        )
        evidence_terms = ", ".join(sorted(common_terms)[:3])

        if 0.6 < title_similarity < 0.95:
            relations.append(
                (
                    "common_confusion",
                    0.7,
                    f"标题相似度 {title_similarity:.2f}，共同术语: {evidence_terms}",
                    "both",
                )
            )

        content = (knowledge_point.content or "").lower()
        other_content = (other.content or "").lower()
        for keyword in CONTRAST_KEYWORDS:
            if keyword in content or keyword in other_content:
                relations.append(
                    (
                        "contrast_with",
                        0.6,
                        f"包含对比关键词: {keyword}",
                        "both",
                    )
                )
                break

        for keyword in PREREQUISITE_KEYWORDS:
            if keyword in content and other.title in content:
                relations.append(
                    (
                        "prerequisite",
                        0.7,
                        f"内容提到需要先了解: {other.title}",
                        "backward",
                    )
                )
                break
            if keyword in other_content and knowledge_point.title in other_content:
                relations.append(
                    (
                        "prerequisite",
                        0.7,
                        f"内容提到需要先了解: {knowledge_point.title}",
                        "forward",
                    )
                )
                break

        if not relations and term_similarity > 0.3:
            relations.append(
                (
                    "similar_to",
                    0.5 + term_similarity * 0.3,
                    f"共同术语: {evidence_terms}",
                    "both",
                )
            )

        return relations

    @staticmethod
    def string_similarity(first: str, second: str) -> float:
        """使用字符集合的 Jaccard 系数计算标题相似度。"""
        if not first or not second:
            return 0.0

        first = first.lower().strip()
        second = second.lower().strip()
        if first == second:
            return 1.0

        first_chars = set(first)
        second_chars = set(second)
        union_size = len(first_chars | second_chars)
        if union_size == 0:
            return 0.0
        return len(first_chars & second_chars) / union_size
