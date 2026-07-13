from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.segment_service import SegmentService


@pytest.mark.asyncio
async def test_build_document_segments_initializes_collections_and_scopes_work(
    monkeypatch,
):
    service = SegmentService(None)
    service.qdrant = SimpleNamespace(init_default_collections=Mock())
    service.embedding = SimpleNamespace(dimension=1024)
    calls = []

    async def fake_build_knowledge_segments(**kwargs):
        calls.append(("knowledge", kwargs))
        return {"segments_count": 4}

    async def fake_build_question_segments(**kwargs):
        calls.append(("question", kwargs))
        return {"segments_count": 6}

    monkeypatch.setattr(
        service,
        "build_knowledge_segments",
        fake_build_knowledge_segments,
    )
    monkeypatch.setattr(
        service,
        "build_question_segments",
        fake_build_question_segments,
    )

    result = await service.build_document_segments(
        document_id="doc-1",
        include_knowledge=True,
        include_questions=False,
    )

    service.qdrant.init_default_collections.assert_called_once_with(vector_size=1024)
    assert calls == [
        ("knowledge", {"document_id": "doc-1", "rebuild": True}),
    ]
    assert result == {
        "knowledge_segments": {"segments_count": 4},
        "question_segments": {"segments_count": 0, "skipped": True},
    }
