"""Pydantic AI 讲解工作流模型运行时测试。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic_ai.models.test import TestModel

from app.modules.agent.model_runtime.explanation import (
    ExplanationDeps,
    ExplanationRuntime,
)


def _deps() -> ExplanationDeps:
    return ExplanationDeps(
        run_id="run_explain_001",
        user_id="user_001",
        conversation_summary="用户此前在复习红黑树。",
    )


@pytest.mark.asyncio
async def test_explanation_runtime_returns_structured_decision_and_content():
    runtime = ExplanationRuntime(
        decision_model=TestModel(
            custom_output_args={
                "action": "retrieve_knowledge",
                "parameters": {"query": "红黑树 五大性质", "limit": 5},
                "reasoning": "需要先查找相关资料",
                "confidence": 0.95,
            }
        ),
        generation_model=TestModel(
            custom_output_args={
                "outline": ["定义", "性质"],
                "body": "红黑树是一种近似平衡二叉搜索树。",
                "citations": ["红黑树"],
                "summary": "红黑树通过颜色约束维持近似平衡。",
            }
        ),
    )

    decision = await runtime.decide(
        "讲解一下红黑树",
        evidence_count=0,
        deps=_deps(),
    )
    output = await runtime.generate(
        "讲解一下红黑树",
        evidence_text="红黑树具有五条性质。",
        deps=_deps(),
    )

    assert decision.action.value == "retrieve_knowledge"
    assert decision.parameters["query"] == "红黑树 五大性质"
    assert output.body == "红黑树是一种近似平衡二叉搜索树。"
    assert output.citations == ["红黑树"]


@pytest.mark.asyncio
async def test_explanation_runtime_uses_run_bound_agent_model_config(monkeypatch):
    opened_run_ids: list[str] = []
    model = TestModel(
        custom_output_args={
            "action": "finish",
            "parameters": {},
            "reasoning": "已有资料足够",
            "confidence": 0.9,
        }
    )

    @asynccontextmanager
    async def fake_open_agent_model(db, *, run_id=None, purpose=None):
        opened_run_ids.append(run_id)
        yield SimpleNamespace(
            model=model,
            config=SimpleNamespace(
                model_name="glm-5.2",
                source="agent_model_configs",
                model_settings={"temperature": 0.2},
            ),
        )

    monkeypatch.setattr(
        "app.modules.agent.model_runtime.explanation.open_agent_model",
        fake_open_agent_model,
    )

    decision = await ExplanationRuntime().decide(
        "讲解一下红黑树",
        evidence_count=1,
        deps=_deps(),
        db=object(),
    )

    assert decision.action.value == "finish"
    assert opened_run_ids == ["run_explain_001"]


@pytest.mark.asyncio
async def test_explanation_context_selection_budget_does_not_limit_output():
    runtime = ExplanationRuntime(
        decision_model=TestModel(
            custom_output_args={
                "action": "finish",
                "parameters": {},
                "reasoning": "资料足够",
                "confidence": 0.9,
            }
        ),
        generation_model=TestModel(
            custom_output_args={
                "outline": ["定义"],
                "body": "红黑树通过颜色约束维持近似平衡。" * 20,
                "citations": [],
                "summary": "讲解红黑树",
            }
        ),
    )
    deps = ExplanationDeps(
        run_id="run_explain_001",
        user_id="user_001",
        token_budget=1,
    )

    decision = await runtime.decide("讲解红黑树", evidence_count=0, deps=deps)
    output = await runtime.generate(
        "讲解红黑树",
        evidence_text="没有检索到相关文档",
        deps=deps,
    )

    assert decision.action.value == "finish"
    assert output.body.startswith("红黑树通过颜色约束")
