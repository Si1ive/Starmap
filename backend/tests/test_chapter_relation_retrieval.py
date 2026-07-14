from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.retrieval import chapter_relation_retrieval


@pytest.mark.asyncio
async def test_similarity_fallback_skips_missing_chapter(monkeypatch):
    db = SimpleNamespace(get=AsyncMock(return_value=None))
    get_embedding = AsyncMock()
    search = Mock()
    monkeypatch.setattr(
        chapter_relation_retrieval,
        "get_embedding_service_from_settings",
        get_embedding,
    )
    monkeypatch.setattr(
        chapter_relation_retrieval.qdrant_manager,
        "search",
        search,
    )

    result = await chapter_relation_retrieval.fallback_chapter_similarity(
        db,
        "chapter-missing",
    )

    assert result == []
    get_embedding.assert_not_awaited()
    search.assert_not_called()


@pytest.mark.asyncio
async def test_similarity_fallback_filters_self_low_scores_and_invalid_payload(
    monkeypatch,
):
    chapter = SimpleNamespace(
        id="chapter-1",
        name="进程调度",
        enhanced_description="比较不同调度算法",
    )
    db = SimpleNamespace(get=AsyncMock(return_value=chapter))
    embedding = SimpleNamespace(
        embed_text=AsyncMock(return_value=[0.1, 0.2]),
    )
    monkeypatch.setattr(
        chapter_relation_retrieval,
        "get_embedding_service_from_settings",
        AsyncMock(return_value=embedding),
    )
    search = Mock(
        return_value=[
            _hit("chapter-1", 0.99),
            _hit("chapter-low", 0.74),
            {"score": 0.95, "payload": {}},
            _hit("chapter-2", 0.9),
            _hit("chapter-3", 0.8),
            _hit("chapter-4", 0.79),
        ]
    )
    monkeypatch.setattr(
        chapter_relation_retrieval.qdrant_manager,
        "search",
        search,
    )

    result = await chapter_relation_retrieval.fallback_chapter_similarity(
        db,
        "chapter-1",
        top_k=2,
    )

    embedding.embed_text.assert_awaited_once_with(
        "进程调度 比较不同调度算法"
    )
    assert search.call_args.kwargs["limit"] == 3
    assert result == [
        ("chapter-2", 0.9),
        ("chapter-3", 0.8),
    ]


@pytest.mark.asyncio
async def test_related_chapters_deduplicates_inputs_and_reads_approved_rows(
    monkeypatch,
):
    expand_scope = AsyncMock(
        side_effect=[
            ["chapter-1", "parent-1", "sibling-1"],
            ["chapter-2", "parent-2"],
        ]
    )
    monkeypatch.setattr(
        chapter_relation_retrieval,
        "expand_chapter_scope",
        expand_scope,
    )
    relation_1 = SimpleNamespace(
        target_chapter_id="related-1",
        source_type="manual",
        relation_type="similar_to",
        confidence=0.91,
        evidence_text="人工确认",
    )
    relation_2 = SimpleNamespace(
        target_chapter_id="related-2",
        source_type="llm",
        relation_type="used_with",
        confidence=None,
        evidence_text=None,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _scalars_result([relation_1]),
                _scalars_result([relation_2]),
            ]
        )
    )

    result = await chapter_relation_retrieval.expand_related_chapters(
        db,
        ["chapter-1", "chapter-1", "chapter-2"],
        max_results=4,
    )

    assert expand_scope.await_count == 2
    assert db.execute.await_count == 2
    first_query = db.execute.await_args_list[0].args[0]
    compiled_query = str(
        first_query.compile(compile_kwargs={"literal_binds": True})
    )
    assert "chapter_relations.review_status = 'approved'" in compiled_query
    assert result["chapter-1"] == {
        "scope_expansion": [
            {
                "chapter_id": "parent-1",
                "relation": "sibling_or_ancestor",
            },
            {
                "chapter_id": "sibling-1",
                "relation": "sibling_or_ancestor",
            },
        ],
        "semantic_relations": [
            {
                "chapter_id": "related-1",
                "source_type": "manual",
                "relation_type": "similar_to",
                "confidence": 0.91,
                "evidence_text": "人工确认",
            }
        ],
    }
    assert result["chapter-2"]["semantic_relations"][0]["confidence"] == 0.0


@pytest.mark.asyncio
async def test_cross_reference_validation_filters_unknown_and_malformed_refs(
    monkeypatch,
):
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_scalars_result(["chapter-1"])),
    )
    warning = Mock()
    monkeypatch.setattr(
        chapter_relation_retrieval.logger,
        "warning",
        warning,
    )
    valid_ref = {
        "target_chapter_id": "chapter-1",
        "relation_type": "similar_to",
    }

    result = await chapter_relation_retrieval.validate_cross_references(
        db,
        [
            valid_ref,
            {"target_chapter_id": "chapter-missing"},
            {"relation_type": "similar_to"},
        ],
    )

    assert result == [valid_ref]
    warning.assert_called_once_with(
        "cross_references 包含无效 chapter_id，已过滤",
        total=3,
        valid=1,
        invalid_ids=["chapter-missing", None],
    )


@pytest.mark.asyncio
async def test_empty_cross_references_skip_database_query():
    db = SimpleNamespace(execute=AsyncMock())

    result = await chapter_relation_retrieval.validate_cross_references(
        db,
        [],
    )

    assert result == []
    db.execute.assert_not_awaited()


def _hit(chapter_id: str, score: float):
    return {
        "score": score,
        "payload": {"entity_id": chapter_id},
    }


def _scalars_result(items):
    return SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=items),
            )
        )
    )
