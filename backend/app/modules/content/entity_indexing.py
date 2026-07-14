"""Shared search-index maintenance for managed content entities."""

from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.retrieval.segment_service import SegmentService

logger = get_logger(__name__)


async def rebuild_entity_index(
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
) -> Dict[str, Any]:
    """Rebuild one entity index without rolling back the saved content edit."""
    try:
        result = await SegmentService(db).rebuild_entity_segments(
            entity_type,
            entity_id,
        )
    except Exception as exc:
        await db.rollback()
        logger.exception(
            "内容实体索引重建失败",
            entity_type=entity_type,
            entity_id=entity_id,
            error=str(exc),
        )
        return {
            "status": "failed",
            "error": str(exc)[:500],
        }

    status = "warning" if result.get("cleanup_warning") else "success"
    return {"status": status, **result}
