"""Shared API schemas."""

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.core.logging import get_request_id


class ApiResponse(BaseModel):
    """Common envelope returned by admin APIs."""

    code: int = 200
    message: str = "success"
    data: Optional[Any] = None
    request_id: str = Field(default_factory=get_request_id)


class BatchIdsRequest(BaseModel):
    """Request body for bounded bulk operations."""

    ids: List[str] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="待处理 ID 列表",
    )
