from unittest.mock import AsyncMock

import pytest

from app.modules.agent.tools import retrieve_knowledge as retrieve_module


@pytest.mark.asyncio
async def test_retrieve_knowledge_forwards_strict_chapter_scope(monkeypatch):
    search = AsyncMock(
        return_value={
            "mode": "hybrid",
            "outline_expansion": {"matched_chapters": []},
            "results": [],
        }
    )
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        search,
    )

    await retrieve_module.retrieve_knowledge(
        AsyncMock(),
        query="二分查找",
        chapter_ids=["cchap_ds_03"],
        strict_chapter_scope=True,
    )

    assert search.await_args.kwargs["chapter_ids"] == ["cchap_ds_03"]
    assert search.await_args.kwargs["strict_chapter_scope"] is True


@pytest.mark.asyncio
async def test_retrieve_knowledge_emits_public_running_and_completed_activity(monkeypatch):
    search = AsyncMock(
        return_value={
            "mode": "hybrid",
            "outline_expansion": {"matched_chapters": [{"title": "循环队列"}]},
            "results": [
                {
                    "segment_id": "segment_001",
                    "entity_id": "kp_001",
                    "title": "循环队列",
                    "content_text": "循环队列通过取模复用数组空间。",
                    "context_text": "循环队列通过取模复用数组空间。",
                    "score": 0.91,
                    "entity_type": "knowledge_point",
                    "subject_id": "subject_ds",
                    "chapter_ids": ["chapter_queue"],
                    "entity": {
                        "id": "kp_001",
                        "type": "knowledge_point",
                        "title": "循环队列",
                        "review_status": "approved",
                        "status": "active",
                    },
                    "source": {
                        "document_id": "document_001",
                        "filename": "王道教材",
                        "page_no": 12,
                    },
                    "question_meta": None,
                    "knowledge_point_meta": {
                        "difficulty": "medium",
                        "source": "王道教材",
                    },
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
    monkeypatch.setattr(
        retrieve_module,
        "_next_attempt_number",
        AsyncMock(return_value=1),
    )
    db = AsyncMock()

    result = await retrieve_module.retrieve_knowledge(
        db,
        query="循环队列",
        limit=5,
        run_id="run_001",
    )

    assert result["status"] == "success"
    assert result["total"] == 1
    assert result["results"][0]["entity_id"] == "kp_001"
    assert result["results"][0]["entity_title"] == "循环队列"
    assert result["results"][0]["content_text"] == "循环队列通过取模复用数组空间。"
    assert result["results"][0]["source"]["filename"] == "王道教材"
    assert [call.args[2] for call in append.await_args_list] == [
        "tool.called",
        "tool.result",
    ]
    completed = append.await_args_list[1].args[3]
    assert completed["detail"] == "混合检索完成，命中 1 份资料"
    assert completed["attempt_no"] == 1
    assert completed["public_metadata"]["documents"][0]["title"] == "循环队列"
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_retrieve_knowledge_explains_empty_result_without_internal_jargon(
    monkeypatch,
):
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        AsyncMock(
            return_value={
                "mode": "hybrid",
                "outline_expansion": {"matched_chapters": []},
                "results": [],
            }
        ),
    )
    append = AsyncMock()
    monkeypatch.setattr(retrieve_module.event_store, "append", append)
    monkeypatch.setattr(
        retrieve_module,
        "_next_attempt_number",
        AsyncMock(return_value=1),
    )
    db = AsyncMock()

    result = await retrieve_module.retrieve_knowledge(
        db,
        query="冷门知识点",
        limit=5,
        run_id="run_empty_001",
    )

    completed = append.await_args_list[1].args[3]
    assert result["total"] == 0
    assert completed["detail"] == "没有检索到相关文档"
    assert completed["public_metadata"]["total"] == 0
    assert "降级" not in completed["detail"]


@pytest.mark.asyncio
async def test_retrieve_knowledge_failure_hides_internal_degradation_wording(monkeypatch):
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        AsyncMock(side_effect=RuntimeError("qdrant unavailable")),
    )
    append = AsyncMock()
    monkeypatch.setattr(retrieve_module.event_store, "append", append)
    monkeypatch.setattr(
        retrieve_module,
        "_next_attempt_number",
        AsyncMock(return_value=1),
    )
    db = AsyncMock()

    result = await retrieve_module.retrieve_knowledge(
        db,
        query="红黑树",
        run_id="run_failed_001",
    )

    failed = append.await_args_list[1].args[3]
    assert result["status"] == "error"
    assert failed["detail"] == "暂时无法检索相关文档"
    assert "降级" not in failed["detail"]


@pytest.mark.asyncio
async def test_retrieve_knowledge_prefers_knowledge_points_for_mixed_explain_results(
    monkeypatch,
):
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        AsyncMock(
            return_value={
                "mode": "hybrid",
                "outline_expansion": {"matched_chapters": []},
                "results": [
                    {
                        "segment_id": "segment_q_001",
                        "entity_id": "q_001",
                        "title": "[3] 二分查找题",
                        "content_text": "请分析二分查找的时间复杂度。",
                        "context_text": "请分析二分查找的时间复杂度。",
                        "score": 0.97,
                        "entity_type": "question",
                        "subject_id": "subject_ds",
                        "chapter_ids": ["chapter_search"],
                        "entity": {
                            "id": "q_001",
                            "type": "question",
                            "title": "[3] 二分查找题",
                            "review_status": "approved",
                            "status": "active",
                        },
                        "source": {"filename": "数据结构真题"},
                        "question_meta": {
                            "question_type": "analysis",
                            "difficulty": "medium",
                            "source": "2024 年 408 真题",
                        },
                        "knowledge_point_meta": None,
                    },
                    {
                        "segment_id": "segment_kp_001",
                        "entity_id": "kp_001",
                        "title": "二分查找",
                        "content_text": "二分查找要求目标序列有序。",
                        "context_text": "二分查找要求目标序列有序。",
                        "score": 0.82,
                        "entity_type": "knowledge_point",
                        "subject_id": "subject_ds",
                        "chapter_ids": ["chapter_search"],
                        "entity": {
                            "id": "kp_001",
                            "type": "knowledge_point",
                            "title": "二分查找",
                            "review_status": "approved",
                            "status": "active",
                        },
                        "source": {"filename": "算法教材"},
                        "question_meta": None,
                        "knowledge_point_meta": {
                            "difficulty": "medium",
                            "source": "算法教材",
                        },
                    },
                ],
            }
        ),
    )

    result = await retrieve_module.retrieve_knowledge(
        AsyncMock(),
        query="二分查找",
        limit=5,
    )

    assert [item["entity_type"] for item in result["results"][:2]] == [
        "knowledge_point",
        "question",
    ]


@pytest.mark.asyncio
async def test_retrieve_knowledge_reuses_logical_activity_id_across_retries(
    monkeypatch,
):
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        AsyncMock(
            side_effect=[
                RuntimeError("qdrant unavailable"),
                {
                    "mode": "hybrid",
                    "outline_expansion": {"matched_chapters": []},
                    "results": [],
                },
            ]
        ),
    )
    append = AsyncMock()
    monkeypatch.setattr(retrieve_module.event_store, "append", append)
    monkeypatch.setattr(
        retrieve_module,
        "_next_attempt_number",
        AsyncMock(side_effect=[1, 2]),
    )
    db = AsyncMock()

    await retrieve_module.retrieve_knowledge(
        db,
        query="红黑树",
        run_id="run_retry_001",
    )
    await retrieve_module.retrieve_knowledge(
        db,
        query="红黑树",
        run_id="run_retry_001",
    )

    first_called = append.await_args_list[0].args[3]
    first_result = append.await_args_list[1].args[3]
    second_called = append.await_args_list[2].args[3]
    second_result = append.await_args_list[3].args[3]

    assert first_called["activity_id"] == second_called["activity_id"]
    assert first_result["activity_id"] == second_result["activity_id"]
    assert first_called["attempt_id"] != second_called["attempt_id"]
    assert first_called["attempt_no"] == 1
    assert second_called["attempt_no"] == 2
    assert second_called["detail"] == "正在第 2 次尝试检索“红黑树”"
