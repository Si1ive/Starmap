"""Compatibility exports for the retrieval module."""

from app.modules.retrieval.service import (
    RetrievalResult,
    RetrievalService,
    get_retrieval_service,
)

__all__ = [
    "RetrievalResult",
    "RetrievalService",
    "get_retrieval_service",
]
