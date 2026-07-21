"""
Loop action Schema（Pydantic model）
+
每轮 decision 必须结构化，包含 action 和 reasoning。
"""

from typing import Optional, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """P0 允许的 Action 类型"""
    RETRIEVE_KNOWLEDGE = "retrieve_knowledge"
    FINISH = "finish"
    NEED_SCOPE = "need_scope"


class LoopAction(BaseModel):
    """Loop 动作"""
    action: ActionType = Field(..., description="要执行的动作")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="动作参数")
    reasoning: str = Field(..., description="推理过程（为什么选这个动作）")


class LoopDecision(BaseModel):
    """Loop 决策输出"""
    action: ActionType = Field(..., description="选定的动作")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="动作参数")
    reasoning: str = Field(..., description="完整推理过程")
    confidence: float = Field(default=1.0, ge=0, le=1, description="置信度")

    class Config:
        json_schema_extra = {
            "example": {
                "action": "retrieve_knowledge",
                "parameters": {"query": "进程调度算法", "limit": 5},
                "reasoning": "用户询问进程调度，需要先检索相关知识",
                "confidence": 0.95,
            }
        }


class ExplanationOutput(BaseModel):
    """讲解产物输出"""
    outline: list = Field(default_factory=list, description="讲解提纲")
    body: str = Field(..., description="讲解正文（Markdown）")
    citations: list = Field(default_factory=list, description="引用列表")
    summary: str = Field(default="", description="一句话总结")


class ArtifactContent(BaseModel):
    """Artifact 内容"""
    type: str = Field(..., description="产物类型")
    title: str = Field(..., description="标题")
    content: str = Field(..., description="内容（Markdown）")
    citations: list = Field(default_factory=list, description="引用")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
