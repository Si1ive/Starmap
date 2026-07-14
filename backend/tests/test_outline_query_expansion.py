from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.retrieval import outline_query_expansion


@pytest.mark.asyncio
async def test_empty_query_skips_embedding_and_vector_search(monkeypatch):
    get_embedding = AsyncMock()
    search = Mock()
    monkeypatch.setattr(
        outline_query_expansion,
        "get_embedding_service_from_settings",
        get_embedding,
    )
    monkeypatch.setattr(
        outline_query_expansion.qdrant_manager,
        "search",
        search,
    )

    result = await outline_query_expansion.expand_query_with_outline(
        SimpleNamespace(),
        "   ",
    )

    assert result.expanded_query == "   "
    assert result.matched_chapters == []
    get_embedding.assert_not_awaited()
    search.assert_not_called()


@pytest.mark.asyncio
async def test_outline_expansion_merges_title_and_content_hits(monkeypatch):
    embedding = SimpleNamespace(
        embed_text=AsyncMock(return_value=[0.1, 0.2]),
    )
    monkeypatch.setattr(
        outline_query_expansion,
        "get_embedding_service_from_settings",
        AsyncMock(return_value=embedding),
    )
    search = Mock(
        side_effect=[
            [
                _hit("chapter-1", "title", 0.65),
                _hit("chapter-2", "title", 0.8),
                {"score": 0.99, "payload": {}},
            ],
            [
                _hit("chapter-1", "content", 0.9),
                _hit("chapter-3", "content", 0.69),
            ],
        ]
    )
    monkeypatch.setattr(
        outline_query_expansion.qdrant_manager,
        "search",
        search,
    )

    chapters = [
        _chapter(
            id="chapter-1",
            subject_id="subject-1",
            name="进程调度",
            outline_code="2.1",
            keywords=["时间片", "周转时间"],
            enhanced_description="比较不同调度算法。",
        ),
        _chapter(
            id="chapter-2",
            subject_id="subject-2",
            name="循环队列",
            outline_code="1.2",
            keywords=["队首", "队尾"],
            enhanced_description="掌握循环队列下标计算。",
        ),
    ]
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_scalars_result(chapters)),
    )

    result = await outline_query_expansion.expand_query_with_outline(
        db,
        "队列 调度",
        top_k=2,
    )

    embedding.embed_text.assert_awaited_once_with("队列 调度")
    assert search.call_count == 2
    assert [call.kwargs["limit"] for call in search.call_args_list] == [4, 4]
    assert result.chapter_ids == ["chapter-2", "chapter-1"]
    assert result.subject_ids == ["subject-2", "subject-1"]
    assert result.expanded_query == (
        "队列 调度 队首 队尾 掌握循环队列下标计算。 "
        "时间片 周转时间 比较不同调度算法。"
    )
    assert result.matched_chapters == [
        {
            "chapter_id": "chapter-2",
            "name": "循环队列",
            "outline_code": "1.2",
            "score": 0.96,
            "keywords": ["队首", "队尾"],
        },
        {
            "chapter_id": "chapter-1",
            "name": "进程调度",
            "outline_code": "2.1",
            "score": 0.9,
            "keywords": ["时间片", "周转时间"],
        },
    ]


@pytest.mark.asyncio
async def test_low_score_hits_leave_query_unchanged(monkeypatch):
    embedding = SimpleNamespace(
        embed_text=AsyncMock(return_value=[0.1, 0.2]),
    )
    monkeypatch.setattr(
        outline_query_expansion,
        "get_embedding_service_from_settings",
        AsyncMock(return_value=embedding),
    )
    monkeypatch.setattr(
        outline_query_expansion.qdrant_manager,
        "search",
        Mock(
            side_effect=[
                [_hit("chapter-1", "title", 0.5)],
                [_hit("chapter-2", "content", 0.69)],
            ]
        ),
    )
    db = SimpleNamespace(execute=AsyncMock())

    result = await outline_query_expansion.expand_query_with_outline(
        db,
        "原始查询",
    )

    assert result.expanded_query == "原始查询"
    assert result.chapter_ids == []
    assert result.subject_ids == []
    db.execute.assert_not_awaited()


def _hit(
    chapter_id: str,
    segment_type: str,
    score: float,
):
    return {
        "score": score,
        "payload": {
            "entity_id": chapter_id,
            "segment_type": segment_type,
        },
    }


def _chapter(**overrides):
    values = {
        "id": "chapter-1",
        "subject_id": "subject-1",
        "name": "章节",
        "outline_code": "1",
        "keywords": [],
        "enhanced_description": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _scalars_result(items):
    return SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=items),
            )
        )
    )
