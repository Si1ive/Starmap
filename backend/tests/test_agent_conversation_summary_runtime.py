"""历史对话摘要的结构化模型运行时测试。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic_ai.models.test import TestModel

from app.modules.agent.model_runtime.conversation_summary import (
    ConversationSummaryDeps,
    ConversationSummaryMessage,
    ConversationSummaryRuntime,
)


def _deps() -> ConversationSummaryDeps:
    return ConversationSummaryDeps(
        thread_id="thread_summary_001",
        user_id="user_001",
        trigger_run_id="run_summary_001",
    )


def _messages() -> list[ConversationSummaryMessage]:
    return [
        ConversationSummaryMessage(
            id="msg_user_001",
            role="user",
            sequence=1,
            content="我正在复习二分查找。",
        ),
        ConversationSummaryMessage(
            id="msg_assistant_001",
            role="assistant",
            sequence=2,
            content="先明确循环不变量。",
        ),
    ]


@pytest.mark.asyncio
async def test_summary_runtime_returns_structured_internal_summary():
    runtime = ConversationSummaryRuntime(
        TestModel(custom_output_args={"summary": "用户在复习二分查找，需要明确循环不变量。"})
    )

    summary = await runtime.summarize(
        previous_summary=None,
        messages=_messages(),
        deps=_deps(),
    )

    assert summary == "用户在复习二分查找，需要明确循环不变量。"


@pytest.mark.asyncio
async def test_summary_runtime_uses_trigger_run_model_configuration(monkeypatch):
    opened_run_ids: list[str] = []
    model = TestModel(custom_output_args={"summary": "合并后的摘要"})

    @asynccontextmanager
    async def fake_open_agent_model(db, *, run_id=None):
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
        "app.modules.agent.model_runtime.conversation_summary.open_agent_model",
        fake_open_agent_model,
    )

    summary = await ConversationSummaryRuntime().summarize(
        previous_summary="旧摘要",
        messages=_messages(),
        deps=_deps(),
        db=object(),
    )

    assert summary == "合并后的摘要"
    assert opened_run_ids == ["run_summary_001"]
