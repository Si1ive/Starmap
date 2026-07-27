"""
Agent Pydantic Schemas

P0 请求/响应模型。
"""

from datetime import datetime
from typing import Annotated, Optional, Dict, Any, List, Literal

from pydantic import BaseModel, Field, PlainSerializer

from .time_utils import utc_isoformat


UTCDateTime = Annotated[
    datetime,
    PlainSerializer(utc_isoformat, return_type=str, when_used="json"),
]


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
    created_at: UTCDateTime
    updated_at: UTCDateTime


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
    created_at: UTCDateTime
    updated_at: UTCDateTime


class EventResponse(BaseModel):
    """事件响应"""
    id: int
    run_id: str
    sequence: int
    event_type: str
    payload: Optional[Dict[str, Any]]
    created_at: UTCDateTime


class ArtifactResponse(BaseModel):
    """产物响应"""
    id: str
    run_id: str
    artifact_type: str
    content: Dict[str, Any]
    created_at: UTCDateTime


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


class PreferenceCandidateDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: Optional[str] = Field(default=None, max_length=255)


class TurnCreateRequest(BaseModel):
    """用户端创建一轮对话请求。"""

    content: str = Field(..., min_length=1, max_length=5000)
    model_config_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=32,
    )
    attachments: List[Dict[str, Any]] = Field(default_factory=list, max_length=20)
    context_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=50)
    client_message_id: str = Field(..., min_length=1, max_length=128)


class MessageView(BaseModel):
    """时间线中的公开消息投影。"""

    id: str
    role: Literal["user", "assistant", "system"]
    status: Literal["pending", "streaming", "completed", "failed"]
    content: Optional[str]
    content_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    completed_at: Optional[UTCDateTime] = None


class WorkflowRunView(BaseModel):
    """创建 turn 后返回的根运行摘要。"""

    id: str
    status: str
    presentation: str
    public_title: Optional[str]


class TurnCreateResponse(BaseModel):
    """创建一轮对话响应。"""

    user_message: MessageView
    root_run: WorkflowRunView
    timeline_cursor: int


class TimelineThreadView(BaseModel):
    """时间线所属 thread 摘要。"""

    id: str
    title: Optional[str]
    updated_at: UTCDateTime


class WorkflowProgressView(BaseModel):
    completed: int
    total: int


class WorkflowStepView(BaseModel):
    id: str
    label: str
    status: str
    started_at: Optional[UTCDateTime]
    completed_at: Optional[UTCDateTime]


class WorkflowActivityView(BaseModel):
    id: str
    activity_type: str
    title: str
    detail: Optional[str]
    status: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    started_at: UTCDateTime
    completed_at: Optional[UTCDateTime]


class WorkflowView(BaseModel):
    """供聊天界面直接渲染的 workflow 投影。"""

    root_run_id: str
    status: str
    title: str
    summary: Optional[str]
    current_step: Optional[str]
    progress: WorkflowProgressView
    steps: List[WorkflowStepView] = Field(default_factory=list)
    activities: List[WorkflowActivityView] = Field(default_factory=list)
    pending_input: Optional[Dict[str, Any]] = None
    pending_approval: Optional[Dict[str, Any]] = None
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: UTCDateTime
    updated_at: UTCDateTime


class TimelineItemView(BaseModel):
    """统一排序的 thread 时间线项。"""

    id: str
    sequence: int
    type: Literal["message", "workflow", "notice"]
    message: Optional[MessageView] = None
    workflow: Optional[WorkflowView] = None
    notice: Optional[Dict[str, Any]] = None
    created_at: UTCDateTime


class TimelineResponse(BaseModel):
    """thread 时间线分页响应。"""

    thread: TimelineThreadView
    items: List[TimelineItemView]
    previous_cursor: Optional[int]
    latest_cursor: int
    has_more: bool


class ThreadEventView(BaseModel):
    """thread 级可重放事件。"""

    id: int
    sequence: int
    event_type: str
    payload: Dict[str, Any]
    created_at: UTCDateTime


class ThreadEventsResponse(BaseModel):
    thread_id: str
    events: List[ThreadEventView]
    latest_cursor: int
