"""Request schemas for administration operations."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


AdminRole = Literal["super_admin", "data_admin", "operator"]


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    email: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=100)
    role: AdminRole = "operator"
    permissions: List[str] = Field(default_factory=list)
    is_active: bool = True


class UpdateUserRequest(BaseModel):
    email: Optional[str] = Field(default=None, min_length=3, max_length=100)
    password: Optional[str] = Field(default=None, min_length=8, max_length=100)
    role: Optional[AdminRole] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None
