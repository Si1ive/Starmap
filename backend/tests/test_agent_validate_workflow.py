"""validate 工作流的候选题资格门测试。"""

from unittest.mock import AsyncMock

import pytest

from app.modules.agent.workflows import validate
from app.modules.agent.workflows.contracts import ExecutionContext, NodeStatus


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
