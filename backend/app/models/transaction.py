"""
对话与事务数据模型

定义对话请求/响应和Agent事务相关的Pydantic模型。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """对话消息"""
    
    role: str = Field(
        ...,
        description="消息角色",
        examples=["user", "assistant", "system"]
    )
    content: str = Field(..., min_length=1, max_length=10000, description="消息内容")
    timestamp: Optional[datetime] = Field(
        default=None,
        description="消息时间"
    )


class ChatRequest(BaseModel):
    """对话请求"""
    
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户消息"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="会话ID（首次对话可不传）"
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="额外上下文信息"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "周杰伦的妻子是谁？",
                "session_id": "sess_abc123",
                "context": {"source": "web"}
            }
        }
    }


class SourceItem(BaseModel):
    """回答来源"""
    
    type: str = Field(..., description="来源类型", examples=["neo4j", "vector_db", "llm"])
    title: Optional[str] = Field(default=None, description="来源标题")
    content: Optional[str] = Field(default=None, description="来源内容摘要")
    url: Optional[str] = Field(default=None, description="来源链接")


class ChatResponse(BaseModel):
    """对话响应"""
    
    session_id: str = Field(..., description="会话ID")
    message: str = Field(..., description="AI回复消息")
    type: str = Field(
        default="answer",
        description="回复类型",
        examples=["answer", "clarification", "error"]
    )
    sources: List[SourceItem] = Field(
        default=[],
        description="信息来源"
    )
    suggestions: List[str] = Field(
        default=[],
        description="建议的后续问题"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "session_id": "sess_abc123",
                "message": "周杰伦的妻子是昆凌（Hannah Quinlivan）。",
                "type": "answer",
                "sources": [
                    {
                        "type": "neo4j",
                        "title": "周杰伦",
                        "content": "配偶：昆凌"
                    }
                ],
                "suggestions": [
                    "昆凌是哪里人？",
                    "周杰伦和昆凌什么时候结婚的？"
                ]
            }
        }
    }


class ChatHistory(BaseModel):
    """会话历史"""
    
    session_id: str = Field(..., description="会话ID")
    messages: List[ChatMessage] = Field(default=[], description="消息列表")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    updated_at: Optional[datetime] = Field(default=None, description="更新时间")


class IntentResult(BaseModel):
    """意图识别结果"""
    
    intent_type: str = Field(
        ...,
        description="意图类型",
        examples=["query_person", "query_relation", "recommend", "general"]
    )
    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="置信度"
    )
    entities: Dict[str, Any] = Field(
        default={},
        description="提取的实体"
    )
    parameters: Dict[str, Any] = Field(
        default={},
        description="附加参数"
    )


class AgentAction(BaseModel):
    """Agent执行动作"""
    
    action_type: str = Field(..., description="动作类型")
    tool_name: Optional[str] = Field(default=None, description="使用的工具")
    parameters: Dict[str, Any] = Field(default={}, description="动作参数")
    result: Optional[Any] = Field(default=None, description="执行结果")
