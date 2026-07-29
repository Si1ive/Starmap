"""题库候选只读工具适配器。

它复用已有 ``retrieve_knowledge`` 的用户归属、检索和审计实现，只固定
``entity_type=question``，不创建练习、不写学习证据。
"""

from __future__ import annotations

from typing import Any

from .registry import ToolRegistry, ToolSpec
from .retrieve_knowledge import retrieve_knowledge


async def search_question_candidates(
    db,
    *,
    query: str,
    subject_id: str | None = None,
    chapter_ids: list[str] | None = None,
    knowledge_point_ids: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    exclude_entity_ids: list[str] | None = None,
    limit: int = 10,
    run_id: str | None = None,
) -> dict[str, Any]:
    result = await retrieve_knowledge(
        db=db,
        query=query,
        subject_id=subject_id,
        chapter_ids=chapter_ids,
        knowledge_point_ids=knowledge_point_ids,
        filters=filters,
        exclude_entity_ids=exclude_entity_ids,
        entity_type="question",
        limit=limit,
        run_id=run_id,
    )
    return {
        **result,
        "tool": "search_question_candidates",
    }


_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "subject_id": {"type": ["string", "null"]},
        "chapter_ids": {"type": "array", "items": {"type": "string"}},
        "knowledge_point_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "filters": {"type": "object"},
        "exclude_entity_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    "required": ["query"],
}


def register_search_question_candidates(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="search_question_candidates",
            description="按当前用户有权访问的知识点范围读取题目候选。",
            parameters=_TOOL_PARAMETERS,
            execute=search_question_candidates,
            read_only=True,
            allowed_workflows=("conversation", "validate"),
            injected_parameters=("run_id",),
        )
    )


__all__ = ["register_search_question_candidates", "search_question_candidates"]
