"""explain 工作流的模型接线、检索空结果与失败语义测试。"""

from unittest.mock import AsyncMock

import pytest

from app.modules.agent.model_runtime.schema import (
    ActionType,
    ExplanationOutput,
    LoopDecision,
)
from app.modules.agent.workflows import explain
from app.modules.agent.workflows.contracts import ExecutionContext, NodeStatus
from app.modules.agent.memory_selector import ConversationBundle, ConversationTurn, TopicBundle


class ExplanationRuntimeStub:
    def __init__(self, *, decisions=(), output=None, error=None):
        self.decisions = list(decisions)
        self.output = output
        self.error = error
        self.decide_calls = []
        self.generate_calls = []

    async def decide(self, current_input, *, evidence_count, deps, message_history=(), db=None):
        self.decide_calls.append(
            {"current_input": current_input, "message_history": list(message_history), "deps": deps}
        )
        if self.error:
            raise self.error
        return self.decisions.pop(0)

    async def generate(self, current_input, *, evidence_text, deps, message_history=(), db=None):
        self.generate_calls.append(
            {
                "current_input": current_input,
                "evidence_text": evidence_text,
                "run_id": deps.run_id,
                "message_history": list(message_history),
            }
        )
        if self.error:
            raise self.error
        return self.output


def _context() -> ExecutionContext:
    context = ExecutionContext("run_explain_001", "user_001", object())
    context.set("input_message", "给我讲解一下红黑树")
    return context


@pytest.mark.asyncio
async def test_evidence_loop_reports_model_failure_instead_of_false_completion(
    monkeypatch,
):
    runtime = ExplanationRuntimeStub(error=RuntimeError("模型配置不可用"))
    monkeypatch.setattr(explain, "explanation_runtime", runtime)
    record = AsyncMock()
    monkeypatch.setattr(explain.loop_turn_store, "record", record)

    result = await explain._evidence_loop_node(_context(), AsyncMock())

    assert result.status == NodeStatus.FAILED
    assert result.error == "模型配置不可用"
    record.assert_awaited_once()


@pytest.mark.asyncio
async def test_evidence_loop_keeps_zero_hits_out_of_valid_evidence(monkeypatch):
    runtime = ExplanationRuntimeStub(
        decisions=[
            LoopDecision(
                action=ActionType.RETRIEVE_KNOWLEDGE,
                parameters={"query": "红黑树", "limit": 5},
                reasoning="先查询资料",
                confidence=0.95,
            ),
            LoopDecision(
                action=ActionType.FINISH,
                parameters={},
                reasoning="结束查询",
                confidence=0.9,
            ),
        ]
    )
    monkeypatch.setattr(explain, "explanation_runtime", runtime)
    monkeypatch.setattr(explain.loop_turn_store, "record", AsyncMock())
    retrieve = AsyncMock(
        return_value={
            "status": "success",
            "query": "红黑树",
            "results": [],
            "total": 0,
        }
    )
    monkeypatch.setattr(explain, "retrieve_knowledge", retrieve)
    context = _context()

    result = await explain._evidence_loop_node(context, AsyncMock())
    gate = await explain._evidence_gate_node(context, AsyncMock())

    assert result.status == NodeStatus.COMPLETED
    assert result.output == {"evidence_count": 0, "retrieval_attempted": True}
    assert context.get("evidence") == []
    assert context.get("retrieval_outcome") == "empty"
    assert gate.output == {
        "gate_passed": False,
        "reason": "没有检索到相关文档",
    }


@pytest.mark.asyncio
async def test_evidence_loop_always_retrieves_once_before_finishing(monkeypatch):
    finish = LoopDecision(
        action=ActionType.FINISH,
        parameters={},
        reasoning="直接结束",
        confidence=0.9,
    )
    monkeypatch.setattr(
        explain,
        "explanation_runtime",
        ExplanationRuntimeStub(decisions=[finish, finish]),
    )
    monkeypatch.setattr(explain.loop_turn_store, "record", AsyncMock())
    retrieve = AsyncMock(
        return_value={
            "status": "success",
            "query": "给我讲解一下红黑树",
            "results": [],
            "total": 0,
        }
    )
    monkeypatch.setattr(explain, "retrieve_knowledge", retrieve)

    result = await explain._evidence_loop_node(_context(), AsyncMock())

    assert result.status == NodeStatus.COMPLETED
    retrieve.assert_awaited_once()
    assert retrieve.await_args.kwargs["query"] == "给我讲解一下红黑树"


@pytest.mark.asyncio
async def test_explain_uses_conversation_bundle_history_and_frozen_topic_query(monkeypatch):
    bundle = ConversationBundle(
        snapshot_id="snapshot_explain_001",
        standalone_request="给用户继续讲解二分查找",
        topic=TopicBundle(
            title="二分查找",
            entity_type="knowledge_point",
            entity_id="kp_binary_search",
            aliases=["折半查找"],
            source="thread_memory",
        ),
        messages=[
            ConversationTurn(
                message_id="msg_user",
                role="user",
                content="什么是二分查找？",
                sequence=1,
            ),
            ConversationTurn(
                message_id="msg_assistant",
                role="assistant",
                content="它每轮排除一半区间。",
                sequence=2,
            ),
        ],
        conversation_summary="用户此前在复习二分查找，并希望继续理解边界条件。",
        conversation_summary_id="convsum_explain_001",
        conversation_summary_version=3,
        artifact_summaries=["二分查找基础讲解"],
        reference_sources=[{"type": "knowledge_point", "id": "kp_binary_search"}],
        retrieval_query="二分查找 折半查找",
    )
    monkeypatch.setattr(explain, "load_conversation_bundle", AsyncMock(return_value=bundle))
    finish = LoopDecision(
        action=ActionType.FINISH,
        parameters={},
        reasoning="直接结束",
        confidence=0.9,
    )
    runtime = ExplanationRuntimeStub(decisions=[finish, finish])
    monkeypatch.setattr(explain, "explanation_runtime", runtime)
    monkeypatch.setattr(explain.loop_turn_store, "record", AsyncMock())
    retrieve = AsyncMock(
        return_value={"status": "success", "results": [], "total": 0}
    )
    monkeypatch.setattr(explain, "retrieve_knowledge", retrieve)
    context = _context()

    await explain._load_scope_node(context, AsyncMock())
    result = await explain._evidence_loop_node(context, AsyncMock())

    assert result.status == NodeStatus.COMPLETED
    assert retrieve.await_args.kwargs["query"] == "二分查找 折半查找"
    assert runtime.decide_calls[0]["current_input"] == "给用户继续讲解二分查找"
    assert len(runtime.decide_calls[0]["message_history"]) == 2
    assert runtime.decide_calls[0]["deps"].artifact_summaries == ("二分查找基础讲解",)
    assert runtime.decide_calls[0]["deps"].conversation_summary == (
        "用户此前在复习二分查找，并希望继续理解边界条件。"
    )


@pytest.mark.asyncio
async def test_generate_explanation_uses_structured_runtime(monkeypatch):
    runtime = ExplanationRuntimeStub(
        output=ExplanationOutput(
            outline=["定义", "性质"],
            body="红黑树通过颜色约束维持近似平衡。",
            citations=["红黑树"],
            summary="说明红黑树的核心性质。",
        )
    )
    monkeypatch.setattr(explain, "explanation_runtime", runtime)
    context = _context()
    context.set(
        "evidence",
        [
            {
                "result": {
                    "results": [
                        {"title": "红黑树", "content": "红黑树具有五条性质。"}
                    ]
                }
            }
        ],
    )

    result = await explain._generate_explanation_node(context, AsyncMock())

    assert result.status == NodeStatus.COMPLETED
    assert result.output["body"] == "红黑树通过颜色约束维持近似平衡。"
    assert runtime.generate_calls[0]["run_id"] == "run_explain_001"
    assert "红黑树具有五条性质" in runtime.generate_calls[0]["evidence_text"]


@pytest.mark.asyncio
async def test_evidence_gate_distinguishes_retrieval_error_from_zero_hits(monkeypatch):
    runtime = ExplanationRuntimeStub(
        decisions=[
            LoopDecision(
                action=ActionType.RETRIEVE_KNOWLEDGE,
                parameters={"query": "红黑树", "limit": 5},
                reasoning="先查询资料",
                confidence=0.95,
            ),
            LoopDecision(
                action=ActionType.FINISH,
                parameters={},
                reasoning="结束查询",
                confidence=0.8,
            ),
        ]
    )
    monkeypatch.setattr(explain, "explanation_runtime", runtime)
    monkeypatch.setattr(explain.loop_turn_store, "record", AsyncMock())
    monkeypatch.setattr(
        explain,
        "retrieve_knowledge",
        AsyncMock(
            return_value={
                "status": "error",
                "query": "红黑树",
                "results": [],
                "total": 0,
                "error": "qdrant unavailable",
            }
        ),
    )
    context = _context()

    result = await explain._evidence_loop_node(context, AsyncMock())
    gate = await explain._evidence_gate_node(context, AsyncMock())

    assert result.status == NodeStatus.COMPLETED
    assert context.get("retrieval_outcome") == "error"
    assert gate.output == {
        "gate_passed": False,
        "reason": "暂时无法检索相关文档",
    }


@pytest.mark.asyncio
async def test_generate_explanation_clears_citations_when_no_evidence(monkeypatch):
    runtime = ExplanationRuntimeStub(
        output=ExplanationOutput(
            outline=["定义"],
            body="红黑树是一种自平衡二叉搜索树。",
            citations=["不存在的教材"],
            summary="给出概念性说明。",
        )
    )
    monkeypatch.setattr(explain, "explanation_runtime", runtime)
    context = _context()
    context.set("evidence", [])
    context.set("retrieval_outcome", "error")

    result = await explain._generate_explanation_node(context, AsyncMock())

    assert result.status == NodeStatus.COMPLETED
    assert result.output["citations"] == []
    assert "资料检索暂时不可用" in runtime.generate_calls[0]["evidence_text"]
