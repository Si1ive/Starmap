"""偏好候选模型运行时的结构化输出与审计契约。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.agent.model_runtime.preference_extractor import (
    PreferenceCandidateProposal,
    PreferenceExtractionDeps,
    PreferenceExtractionOutput,
    PreferenceExtractionRuntime,
    preference_extraction_agent,
)


@pytest.mark.asyncio
async def test_preference_extractor_returns_structured_candidates_and_model_audit(
    monkeypatch,
):
    run = AsyncMock(
        return_value=SimpleNamespace(
            output=PreferenceExtractionOutput(
                candidates=[
                    PreferenceCandidateProposal(
                        preference_key="daily_study_minutes",
                        value=45,
                        scope="user",
                        confidence=0.93,
                    )
                ]
            )
        )
    )
    monkeypatch.setattr(preference_extraction_agent, "run", run)
    runtime = PreferenceExtractionRuntime(
        model="test-model",
        model_name="test-model-v3",
    )

    batch = await runtime.extract(
        "我每天希望学习 45 分钟",
        deps=PreferenceExtractionDeps(
            user_id="user_001",
            thread_id="thread_001",
            run_id="run_001",
        ),
    )

    assert batch.model_name == "test-model-v3"
    assert batch.model_config_id is None
    assert batch.candidates[0].preference_key == "daily_study_minutes"
    assert batch.candidates[0].value == 45
    prompt = run.await_args.args[0]
    assert "user_message" in prompt
    assert "我每天希望学习 45 分钟" in prompt
    assert run.await_args.kwargs["usage_limits"].request_limit == 2


@pytest.mark.asyncio
async def test_preference_extractor_rejects_duplicate_keys(monkeypatch):
    duplicate = PreferenceCandidateProposal(
        preference_key="response_detail",
        value="detailed",
        scope="user",
        confidence=0.8,
    )
    monkeypatch.setattr(
        preference_extraction_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(
                output=PreferenceExtractionOutput(
                    candidates=[duplicate, duplicate.model_copy()]
                )
            )
        ),
    )

    with pytest.raises(ValueError, match="重复 preference_key"):
        await PreferenceExtractionRuntime(model="test-model").extract(
            "我喜欢详细回答",
            deps=PreferenceExtractionDeps(
                user_id="user_001",
                thread_id="thread_001",
                run_id="run_001",
            ),
        )
