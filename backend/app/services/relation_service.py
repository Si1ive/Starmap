"""Compatibility exports for knowledge relation workflows."""

from app.modules.retrieval.relation_service import (
    RELATION_PRIORITY,
    RelationService,
    generate_id,
)

__all__ = [
    "RELATION_PRIORITY",
    "RelationService",
    "generate_id",
]
