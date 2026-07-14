"""Knowledge semantic relation detector tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.retrieval.semantic_relation_detector import (
    KnowledgeSemanticRelationDetector,
)


def make_knowledge_point(
    point_id: str,
    title: str,
    *,
    summary: str | None = None,
    topic_terms: list[str] | None = None,
):
    return SimpleNamespace(
        id=point_id,
        title=title,
        summary=summary,
        topic_terms=topic_terms,
    )


@pytest.mark.asyncio
async def test_semantic_detector_builds_text_and_returns_threshold_candidates():
    embedding = SimpleNamespace(
        embed_batch=AsyncMock(
            return_value=[
                [1.0, 0.0],
                [1.0, 0.0],
                [0.0, 1.0],
            ]
        )
    )
    detector = KnowledgeSemanticRelationDetector(
        None,
        embedding_service=embedding,
    )
    points = [
        make_knowledge_point(
            "point-1",
            "进程调度",
            summary="调度器选择下一个进程",
            topic_terms=["时间片"],
        ),
        make_knowledge_point("point-2", "调度算法"),
        make_knowledge_point("point-3", "文件系统"),
    ]

    candidates = await detector.detect(points)

    embedding.embed_batch.assert_awaited_once_with(
        [
            "调度器选择下一个进程 时间片",
            "调度算法",
            "文件系统",
        ]
    )
    assert len(candidates) == 1
    assert candidates[0].source.id == "point-1"
    assert candidates[0].target.id == "point-2"
    assert candidates[0].similarity == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_semantic_detector_skips_embedding_for_insufficient_points():
    embedding = SimpleNamespace(embed_batch=AsyncMock())
    detector = KnowledgeSemanticRelationDetector(
        None,
        embedding_service=embedding,
    )

    assert await detector.detect([]) == []
    assert await detector.detect([make_knowledge_point("point-1", "进程")]) == []
    embedding.embed_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_semantic_detector_rejects_embedding_count_mismatch():
    embedding = SimpleNamespace(embed_batch=AsyncMock(return_value=[[1.0, 0.0]]))
    detector = KnowledgeSemanticRelationDetector(
        None,
        embedding_service=embedding,
    )
    points = [
        make_knowledge_point("point-1", "进程"),
        make_knowledge_point("point-2", "线程"),
    ]

    with pytest.raises(ValueError, match="知识点向量数量不一致"):
        await detector.detect(points)


def test_semantic_detector_cosine_similarity_handles_invalid_vectors():
    cosine_similarity = KnowledgeSemanticRelationDetector.cosine_similarity

    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
