"""validate 工作流的候选题检索与资格门测试。"""

from unittest.mock import AsyncMock

import pytest

from app.modules.agent.memory_selector import PracticeBundle, TopicBundle
from app.modules.agent.tools import retrieve_knowledge as retrieve_module
from app.modules.agent.workflows import validate
from app.modules.agent.workflows.contracts import ExecutionContext, NodeStatus
from app.modules.retrieval.search_engine import RetrievalResult


def _context() -> ExecutionContext:
    return ExecutionContext("run_validate_001", "user_001", object())


@pytest.mark.asyncio
async def test_question_gate_accepts_rich_question_metadata_without_source_type():
    context = _context()
    context.set(
        "candidates",
        [
            {
                "entity_id": "question_001",
                "entity_type": "question",
                "entity_title": "[12] 二分查找",
                "subject_id": "subject_ds",
                "question_meta": {
                    "question_type": "choice",
                    "difficulty": "medium",
                    "source": "2024 年 408 真题",
                    "paper_name": "数据结构试卷",
                    "answer_source": "extracted",
                    "review_status": "approved",
                    "status": "active",
                },
            }
        ],
    )

    result = await validate._question_gate_node(context, AsyncMock())

    assert result.status == NodeStatus.COMPLETED
    assert context.get("valid_questions")[0]["entity_id"] == "question_001"


@pytest.mark.asyncio
async def test_question_gate_filters_deleted_or_source_less_questions():
    context = _context()
    context.set(
        "candidates",
        [
            {
                "entity_id": "question_deleted",
                "entity_type": "question",
                "question_meta": {
                    "question_type": "choice",
                    "difficulty": "medium",
                    "source": "真题",
                    "paper_name": None,
                    "answer_source": "extracted",
                    "review_status": "approved",
                    "status": "deleted",
                },
            },
            {
                "entity_id": "question_without_source",
                "entity_type": "question",
                "question_meta": {
                    "question_type": "choice",
                    "difficulty": "medium",
                    "source": None,
                    "paper_name": None,
                    "answer_source": "none",
                    "review_status": "approved",
                    "status": "active",
                },
            },
        ],
    )

    result = await validate._question_gate_node(context, AsyncMock())

    assert result.status == NodeStatus.FAILED
    assert result.error == "未找到有效候选题"


@pytest.mark.asyncio
async def test_validate_binary_search_question_survives_retrieval_dto_and_gate(
    monkeypatch,
):
    context = _context()
    context.set("weak_areas", ["二分查找"])
    db = AsyncMock()
    search = AsyncMock(
        return_value={
            "mode": "hybrid",
            "outline_expansion": {
                "matched_chapters": [{"title": "查找"}],
            },
            "results": [
                RetrievalResult(
                    segment_id="segment_q_binary_search",
                    entity_type="question",
                    entity_id="question_binary_search",
                    segment_type="content",
                    content_text="请分析二分查找的时间复杂度，并说明前提条件。",
                    context_text="请分析二分查找的时间复杂度，并说明前提条件。",
                    score=0.97,
                    subject_id="subject_ds",
                    chapter_ids=["chapter_search"],
                    source_document_id="document_001",
                    source_filename="2024 年 408 真题",
                    page_no=3,
                    title="[12] 二分查找",
                    review_status="approved",
                    status="active",
                    entity_metadata={
                        "question_type": "analysis",
                        "difficulty": "medium",
                        "source": "2024 年 408 真题",
                        "paper_name": "数据结构试卷",
                        "answer_source": "extracted",
                        "review_status": "approved",
                        "status": "active",
                    },
                ).to_dict()
            ],
        }
    )
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        search,
    )
    monkeypatch.setattr(retrieve_module.event_store, "append", AsyncMock())
    monkeypatch.setattr(
        retrieve_module,
        "_next_attempt_number",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        validate,
        "load_practice_bundle",
        AsyncMock(return_value=PracticeBundle()),
    )

    loaded = await validate._load_learning_evidence_node(context, db)
    discovered = await validate._question_discovery_node(context, db)
    gated = await validate._question_gate_node(context, db)
    composed = await validate._composition_gate_node(context, db)

    assert loaded.status == NodeStatus.COMPLETED
    assert discovered.status == NodeStatus.COMPLETED
    assert gated.status == NodeStatus.COMPLETED
    assert composed.status == NodeStatus.COMPLETED
    search.assert_awaited_once()
    assert search.await_args.kwargs["query"] == "二分查找"
    assert search.await_args.kwargs["entity_type"] == "question"
    assert search.await_args.kwargs["mode"] == "hybrid"
    candidate = context.get("candidates")[0]
    assert candidate["entity_id"] == "question_binary_search"
    assert candidate["entity_title"] == "[12] 二分查找"
    assert candidate["source"]["filename"] == "2024 年 408 真题"
    assert candidate["question_meta"]["paper_name"] == "数据结构试卷"
    assert context.get("valid_questions")[0]["entity_id"] == "question_binary_search"
    assert context.get("composition") == {
        "total": 1,
        "types": {"analysis": 1},
        "difficulties": {"medium": 1},
        "subjects": {"subject_ds": 1},
    }


@pytest.mark.asyncio
async def test_validate_uses_practice_bundle_topic_for_query(monkeypatch):
    context = _context()
    db = AsyncMock()
    monkeypatch.setattr(
        validate,
        "load_practice_bundle",
        AsyncMock(
            return_value=PracticeBundle(
                snapshot_id="memsnap_001",
                standalone_request="给用户出一道关于二分查找的练习题",
                topic=TopicBundle(
                    title="二分查找",
                    entity_type="knowledge_point",
                    entity_id="kp_binary_search",
                    aliases=["折半查找"],
                    source="thread_memory",
                ),
                difficulty="medium",
                knowledge_point_ids=["kp_binary_search"],
                chapter_ids=["cchap_search"],
                excluded_question_ids=["question_old_001"],
            )
        ),
    )
    retrieve = AsyncMock(
        return_value={
            "status": "success",
            "results": [],
            "total": 0,
        }
    )
    monkeypatch.setattr(retrieve_module, "retrieve_knowledge", retrieve)

    loaded = await validate._load_learning_evidence_node(context, db)
    discovered = await validate._question_discovery_node(context, db)

    assert loaded.status == NodeStatus.COMPLETED
    assert discovered.status == NodeStatus.COMPLETED
    assert context.get("learning_evidence")["weak_areas"] == ["二分查找"]
    assert context.get("learning_evidence")["recent_topics"] == ["二分查找"]
    assert context.get("practice_bundle")["snapshot_id"] == "memsnap_001"
    assert retrieve.await_args.kwargs["query"] == "二分查找 折半查找"
    assert retrieve.await_args.kwargs["knowledge_point_ids"] == ["kp_binary_search"]
    assert retrieve.await_args.kwargs["chapter_ids"] == ["cchap_search"]
    assert retrieve.await_args.kwargs["filters"] == {"difficulty": "medium"}
    assert retrieve.await_args.kwargs["exclude_entity_ids"] == ["question_old_001"]
    assert retrieve.await_args.kwargs["entity_type"] == "question"


@pytest.mark.asyncio
async def test_validate_stops_when_no_topic_or_fallback_terms(monkeypatch):
    context = _context()
    db = AsyncMock()
    monkeypatch.setattr(
        validate,
        "load_practice_bundle",
        AsyncMock(return_value=PracticeBundle()),
    )
    class _AgentServiceStub:
        def __init__(self, session):
            self.session = session

        async def get_input(self, run_id, input_key):
            return None

        async def create_input(self, run_id, input_key, prompt_ref, input_schema_version="v1", expires_at=None):
            return None

    monkeypatch.setattr(validate, "AgentService", _AgentServiceStub)
    retrieve = AsyncMock()
    monkeypatch.setattr(retrieve_module, "retrieve_knowledge", retrieve)

    loaded = await validate._load_learning_evidence_node(context, db)
    discovered = await validate._question_discovery_node(context, db)

    assert loaded.status == NodeStatus.COMPLETED
    assert context.get("learning_evidence")["weak_areas"] == []
    assert discovered.status == NodeStatus.WAITING
    assert discovered.output["waiting_for_user"] is True
    assert discovered.output["clarification_input_key"] == "practice_topic"
    retrieve.assert_not_awaited()
