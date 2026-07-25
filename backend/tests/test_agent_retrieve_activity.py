from unittest.mock import AsyncMock

import pytest

from app.modules.agent.tools import retrieve_knowledge as retrieve_module


@pytest.mark.asyncio
async def test_retrieve_knowledge_emits_public_running_and_completed_activity(monkeypatch):
    search = AsyncMock(
        return_value={
            "mode": "hybrid",
            "outline_expansion": {"matched_chapters": [{"title": "循环队列"}]},
            "results": [
                {
                    "id": "kp_001",
                    "title": "循环队列",
                    "content": "循环队列通过取模复用数组空间。",
                    "source_type": "knowledge_point",
                    "score": 0.91,
                    "entity_type": "knowledge_point",
                }
            ],
        }
    )
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        search,
    )
    append = AsyncMock()
    monkeypatch.setattr(retrieve_module.event_store, "append", append)
    db = AsyncMock()

    result = await retrieve_module.retrieve_knowledge(
        db,
        query="循环队列",
        limit=5,
        run_id="run_001",
    )

    assert result["status"] == "success"
    assert result["total"] == 1
    assert [call.args[2] for call in append.await_args_list] == [
        "tool.called",
        "tool.result",
    ]
    completed = append.await_args_list[1].args[3]
    assert completed["detail"] == "混合检索完成，命中 1 份资料"
    assert completed["public_metadata"]["documents"][0]["title"] == "循环队列"
    assert db.commit.await_count == 2
