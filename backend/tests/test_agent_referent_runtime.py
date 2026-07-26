"""结构化指代消解运行时的候选白名单测试。"""

import pytest
from pydantic_ai.models.test import TestModel

from app.modules.agent.model_runtime.referent import (
    ReferentCandidate,
    ReferentDeps,
    ReferentRuntime,
)


def _candidates() -> list[ReferentCandidate]:
    return [
        ReferentCandidate(
            candidate_key="question:question_001",
            entity_type="question",
            entity_id="question_001",
            source="artifact",
            artifact_id="artifact_practice",
            label="二分查找每轮把搜索区间缩小多少？",
        ),
        ReferentCandidate(
            candidate_key="question:question_002",
            entity_type="question",
            entity_id="question_002",
            source="artifact",
            artifact_id="artifact_practice",
            label="写出二分查找的循环不变量。",
        ),
    ]


@pytest.mark.asyncio
async def test_referent_runtime_returns_only_whitelisted_candidate():
    runtime = ReferentRuntime(
        TestModel(
            custom_output_args={
                "status": "resolved",
                "candidate_key": "question:question_002",
                "confidence": 0.94,
                "reason_code": "second_candidate_matches",
            }
        )
    )

    resolution = await runtime.resolve(
        "讲一下这个",
        candidates=_candidates(),
        deps=ReferentDeps(
            thread_id="thread_001",
            user_id="user_001",
            turn_id="run_001",
        ),
    )

    assert resolution.status == "resolved"
    assert resolution.candidate_key == "question:question_002"


@pytest.mark.asyncio
async def test_referent_runtime_rejects_invented_candidate_key():
    runtime = ReferentRuntime(
        TestModel(
            custom_output_args={
                "status": "resolved",
                "candidate_key": "question:invented",
                "confidence": 0.99,
                "reason_code": "invented_candidate",
            }
        )
    )

    with pytest.raises(ValueError, match="候选范围"):
        await runtime.resolve(
            "讲一下这个",
            candidates=_candidates(),
            deps=ReferentDeps(
                thread_id="thread_001",
                user_id="user_001",
                turn_id="run_001",
            ),
        )


@pytest.mark.asyncio
async def test_referent_runtime_downgrades_low_confidence_selection():
    runtime = ReferentRuntime(
        TestModel(
            custom_output_args={
                "status": "resolved",
                "candidate_key": "question:question_001",
                "confidence": 0.62,
                "reason_code": "weak_context_match",
            }
        )
    )

    resolution = await runtime.resolve(
        "讲一下这个",
        candidates=_candidates(),
        deps=ReferentDeps(
            thread_id="thread_001",
            user_id="user_001",
            turn_id="run_001",
        ),
    )

    assert resolution.status == "unresolved"
    assert resolution.candidate_key is None
    assert resolution.reason_code == "low_confidence"


@pytest.mark.asyncio
async def test_referent_runtime_rejects_candidate_without_semantic_label():
    candidate = _candidates()[0].model_copy(update={"label": None})
    runtime = ReferentRuntime(TestModel())

    with pytest.raises(ValueError, match="可判别标签"):
        await runtime.resolve(
            "讲一下这个",
            candidates=[candidate],
            deps=ReferentDeps(
                thread_id="thread_001",
                user_id="user_001",
                turn_id="run_001",
            ),
        )
