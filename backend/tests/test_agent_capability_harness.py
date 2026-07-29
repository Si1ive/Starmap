"""受控 Capability/Tool Harness 的策略边界测试。"""

from unittest.mock import AsyncMock

import pytest

from app.modules.agent.capabilities import capability_registry
from app.modules.agent.tools import tool_registry


def test_capability_manifest_separates_model_and_audit_views():
    model_manifest = capability_registry.model_manifest(("validate",))
    audit_manifest = capability_registry.audit_manifest(("validate",))

    assert model_manifest == (
        {
            "key": "practice.prepare",
            "action": "validate",
            "description": "检索或生成题目，并幂等创建可进入练习页的草稿。",
        },
    )
    assert "side_effect" not in model_manifest[0]
    assert audit_manifest[0]["side_effect"] == "domain_write"
    assert audit_manifest[0]["tools"] == ["retrieve_knowledge"]


def test_read_only_tutor_manifest_is_closed_and_has_no_write_descriptor():
    model_manifest = capability_registry.read_only_model_manifest()
    audit_manifest = capability_registry.read_only_audit_manifest()

    assert [item["name"] for item in model_manifest] == [
        "get_learning_snapshot",
        "retrieve_knowledge",
        "search_question_candidates",
    ]
    assert all("read_only" not in item for item in model_manifest)
    assert all(item["read_only"] is True for item in audit_manifest)
    assert all("execute" not in item for item in audit_manifest)


@pytest.mark.asyncio
async def test_registered_tool_executes_only_for_allowed_workflow():
    implementation = AsyncMock(return_value={"status": "success"})

    result = await tool_registry.execute(
        "retrieve_knowledge",
        workflow="validate",
        db=object(),
        arguments={"query": "二分查找", "run_id": "run_001"},
        implementation=implementation,
    )

    assert result == {"status": "success"}
    implementation.assert_awaited_once()
    assert implementation.await_args.kwargs["query"] == "二分查找"
    assert implementation.await_args.kwargs["run_id"] == "run_001"


@pytest.mark.asyncio
async def test_registered_tool_rejects_wrong_workflow_and_unknown_arguments():
    implementation = AsyncMock()

    with pytest.raises(PermissionError, match="无权调用"):
        await tool_registry.execute(
            "retrieve_knowledge",
            workflow="grade",
            db=object(),
            arguments={"query": "二分查找"},
            implementation=implementation,
        )
    with pytest.raises(ValueError, match="未知参数"):
        await tool_registry.execute(
            "retrieve_knowledge",
            workflow="explain",
            db=object(),
            arguments={"query": "二分查找", "user_id": "伪造用户"},
            implementation=implementation,
        )

    implementation.assert_not_awaited()
