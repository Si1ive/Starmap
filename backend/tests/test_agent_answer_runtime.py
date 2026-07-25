"""Pydantic AI 普通问答运行时测试。"""

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel

from app.modules.agent.model_runtime.answer import (
    DirectAnswerDeps,
    DirectAnswerRuntime,
)


@pytest.mark.asyncio
async def test_direct_answer_returns_structured_output_without_network():
    runtime = DirectAnswerRuntime(
        TestModel(
            custom_output_args={
                "content": "循环队列通过取模运算复用数组空间。",
                "public_summary": "说明循环队列的核心机制",
            }
        )
    )
    history = [ModelRequest(parts=[UserPromptPart(content="先讲一下队列")])]

    output = await runtime.answer(
        "循环队列呢？",
        deps=DirectAnswerDeps(
            thread_id="thread_001",
            user_id="user_001",
            turn_id="run_001",
        ),
        message_history=history,
    )

    assert output.content == "循环队列通过取模运算复用数组空间。"
    assert output.public_summary == "说明循环队列的核心机制"


@pytest.mark.asyncio
async def test_direct_answer_streams_structured_content_as_prefix_deltas():
    runtime = DirectAnswerRuntime(
        TestModel(
            custom_output_args={
                "content": "循环队列通过取模运算复用数组空间。",
                "public_summary": "说明循环队列的核心机制",
            }
        )
    )
    deltas: list[str] = []

    async def collect(delta: str) -> None:
        deltas.append(delta)

    output = await runtime.answer(
        "循环队列呢？",
        deps=DirectAnswerDeps(
            thread_id="thread_001",
            user_id="user_001",
            turn_id="run_001",
        ),
        on_delta=collect,
    )

    assert output.content == "循环队列通过取模运算复用数组空间。"
    assert "".join(deltas) == output.content
