"""Request schemas for content management."""

from typing import List, Optional

from pydantic import BaseModel


class UpdateKnowledgePointRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    difficulty: Optional[str] = None
    exam_frequency: Optional[str] = None
    tags: Optional[List[str]] = None
    key_points: Optional[List[str]] = None
    status: Optional[str] = None


class UpdateQuestionRequest(BaseModel):
    content: Optional[str] = None
    options: Optional[List[dict]] = None
    answer: Optional[str] = None
    explanation: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
