"""Agent 多模型管理请求模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class AgentModelConfigCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    provider: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=2000)
    model_name: str = Field(min_length=1, max_length=200)
    online: bool = False
    selectable: bool = True
    is_default: bool = False
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=2000, ge=1, le=200000)
    timeout_seconds: int = Field(default=60, ge=5, le=600)


class AgentModelConfigUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: Literal["openai_compatible"] | None = None
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=2000)
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    online: bool | None = None
    selectable: bool | None = None
    is_default: bool | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=200000)
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)


class AgentModelAvailabilityUpdate(BaseModel):
    online: bool
    selectable: bool
