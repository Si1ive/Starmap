"""
Agent Pydantic Schemas
+
P0 请求/响应模型。
"""

from datetime import datetime
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field


class ThreadCreateRequest(BaseModel):
    """创建线程请求"""
    title: Optional[str] = Field(default=None, max_length=255)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class ThreadResponse(BaseModel):
    """线程响应"""
    id: str
    user_id: str
    title: Optional[str]
    status: str
    metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class RunCreateRequest(BaseModel):
    """创建运行请求"""
    thread_id: str = Field(..., min_length=1, max_length=32)
    workflow_name: str = Field(..., min_length=1, max_length=50)
    input_message: str = Field(..., min_length=1, max_length=5000)
    client_idempotency_key: Optional[str] = Field(default=None, max_length=64)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class RunStatusResponse(BaseModel):
    """运行状态响应"""
    id: str
    thread_id: str
    workflow_name: str
    status: str
    input_message: str
    result_artifact_id: Optional[str]
    error_message: Optional[str]
    model_call_count: int
    created_at: datetime
    updated_at: datetime


class EventResponse(BaseModel):
    """事件响应"""
    id: int
    run_id: str
    sequence: int
    event_type: str
    payload: Optional[Dict[str, Any]]
    created_at: datetime


class ArtifactResponse(BaseModel):
    """产物响应"""
    id: str
    run_id: str
    artifact_type: str
    content: Dict[str, Any]
    created_at: datetime


class SSEvent(BaseModel):
    """SSE 事件（序列化用）"""
    id: str
    event: str
    data: str


class SubmitInputRequest(BaseModel):
    """提交用户输入请求"""
    run_id: str = Field(..., min_length=1, max_length=32)
    input_text: str = Field(..., min_length=1, max_length=5000)


class SubmitInputResponse(BaseModel):
    """提交用户输入响应"""
    run_id: str
    status: str
    message: str
