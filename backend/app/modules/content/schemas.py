"""Request schemas for content management."""

from typing import List, Literal, Optional

from pydantic import BaseModel


class UpdateKnowledgePointRequest(BaseModel):
    subject_id: Optional[str] = None
    chapter_id: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    exam_frequency: Optional[Literal["high", "medium", "low", "never"]] = None
    tags: Optional[List[str]] = None
    key_points: Optional[List[str]] = None
    status: Optional[Literal["active", "pending"]] = None


class UpdateQuestionRequest(BaseModel):
    subject_id: Optional[str] = None
    chapter_id: Optional[str] = None
    primary_chapter_id: Optional[str] = None
    type: Optional[
        Literal[
            "choice",
            "fill",
            "judge",
            "short_answer",
            "design",
            "analysis",
        ]
    ] = None
    content: Optional[str] = None
    options: Optional[List[dict]] = None
    answer: Optional[str] = None
    explanation: Optional[str] = None
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    source: Optional[str] = None
    exam_year: Optional[int] = None
    tags: Optional[List[str]] = None
    status: Optional[Literal["active", "pending"]] = None
