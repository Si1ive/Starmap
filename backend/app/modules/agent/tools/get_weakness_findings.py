"""只读读取当前 LearningSnapshot 的薄弱点派生结果。"""

from __future__ import annotations

from typing import Any

from .get_learning_snapshot import get_learning_snapshot
from .registry import ToolRegistry, ToolSpec


async def get_weakness_findings(
    db,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """复用同一快照读取，禁止以工具参数指定用户或写入 finding。"""

    snapshot = await get_learning_snapshot(db, run_id=run_id)
    return {
        "status": "success",
        "snapshot_id": snapshot.get("snapshot_id"),
        "run_id": snapshot.get("run_id"),
        "findings": list(snapshot.get("weakness_findings") or []),
        "diagnostic_hypotheses": list(snapshot.get("diagnostic_hypotheses") or []),
    }


_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {},
    "required": [],
}


def register_get_weakness_findings(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="get_weakness_findings",
            description="读取当前快照中的确认薄弱点、错误标签和诊断建议。",
            parameters=_TOOL_PARAMETERS,
            execute=get_weakness_findings,
            read_only=True,
            allowed_workflows=("conversation", "explain", "validate", "grade", "plan"),
            injected_parameters=("run_id",),
        )
    )


__all__ = ["get_weakness_findings", "register_get_weakness_findings"]
