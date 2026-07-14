"""基于知识点向量相似度生成语义关系候选。"""

import math
from dataclasses import dataclass
from typing import List, Optional, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.ai.embedding_service import (
    EmbeddingService,
    get_embedding_service_from_settings,
)


class SemanticKnowledgePoint(Protocol):
    """语义关系检测所需的最小知识点字段集合。"""

    id: str
    title: str
    summary: Optional[str]
    topic_terms: Optional[List[str]]


@dataclass(frozen=True)
class SemanticRelationCandidate:
    """一条尚未落库的无向语义相似关系。"""

    source: SemanticKnowledgePoint
    target: SemanticKnowledgePoint
    similarity: float


class KnowledgeSemanticRelationDetector:
    """批量计算知识点向量并筛选高相似关系候选。"""

    DEFAULT_THRESHOLD = 0.82
    DEFAULT_TOP_N = 3

    def __init__(
        self,
        db: AsyncSession,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        top_n: int = DEFAULT_TOP_N,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        self.db = db
        self.threshold = threshold
        self.top_n = top_n
        self.embedding_service = embedding_service

    async def detect(
        self,
        knowledge_points: List[SemanticKnowledgePoint],
    ) -> List[SemanticRelationCandidate]:
        if len(knowledge_points) < 2:
            return []

        embedding = self.embedding_service
        if embedding is None:
            embedding = await get_embedding_service_from_settings(self.db)

        texts = [self._build_embedding_text(point) for point in knowledge_points]
        vectors = await embedding.embed_batch(texts)
        if len(vectors) != len(knowledge_points):
            raise ValueError(
                "知识点向量数量不一致："
                f"expected={len(knowledge_points)}, actual={len(vectors)}"
            )

        candidates: List[SemanticRelationCandidate] = []
        point_count = len(knowledge_points)
        for source_index in range(point_count):
            similarities = []
            for target_index in range(point_count):
                if source_index == target_index:
                    continue
                similarity = self.cosine_similarity(
                    vectors[source_index],
                    vectors[target_index],
                )
                if similarity >= self.threshold:
                    similarities.append((target_index, similarity))

            similarities.sort(key=lambda item: item[1], reverse=True)
            for target_index, similarity in similarities[: self.top_n]:
                if source_index >= target_index:
                    continue
                candidates.append(
                    SemanticRelationCandidate(
                        source=knowledge_points[source_index],
                        target=knowledge_points[target_index],
                        similarity=similarity,
                    )
                )
        return candidates

    @staticmethod
    def _build_embedding_text(point: SemanticKnowledgePoint) -> str:
        base = (point.summary or point.title or "").strip()
        if point.topic_terms:
            base = f"{base} {' '.join(point.topic_terms)}"
        return base or point.title or ""

    @staticmethod
    def cosine_similarity(first: List[float], second: List[float]) -> float:
        """计算等维向量的余弦相似度，异常输入按不相似处理。"""
        if not first or len(first) != len(second):
            return 0.0

        dot_product = sum(x * y for x, y in zip(first, second))
        first_norm = math.sqrt(sum(value * value for value in first))
        second_norm = math.sqrt(sum(value * value for value in second))
        if first_norm == 0 or second_norm == 0:
            return 0.0
        return dot_product / (first_norm * second_norm)
