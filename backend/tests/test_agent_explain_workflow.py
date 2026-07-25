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


class ExplanationRuntimeStub:
    def __init__(self, *, decisions=(), output=None, error=None):
        self.decisions = list(decisions)
        self.output = output
        self.error = error
        self.generate_calls = []

    async def decide(self, current_input, *, evidence_count, deps, db=None):
        if self.error:
            raise self.error
        return self.decisions.pop(0)

    async def generate(self, current_input, *, evidence_text, deps, db=None):
        self.generate_calls.append(
            {
                "current_input": current_input,
                "evidence_text": evidence_text,
                "run_id": deps.run_id,
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
