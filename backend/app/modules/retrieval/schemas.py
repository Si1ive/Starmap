"""Request schemas for retrieval and segment administration."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="查询文本")
    subject_id: Optional[str] = Field(None, description="学科过滤")
    chapter_ids: Optional[List[str]] = Field(None, description="章节过滤")
    entity_type: Optional[str] = Field(None, description="实体类型过滤")
    mode: str = Field("hybrid", description="检索模式: dense/sparse/hybrid")
    limit: int = Field(10, ge=1, le=50, description="返回数量")
    filters: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "结构化过滤: exam_year/exam_scope/difficulty/"
            "question_type/answer_source/tags"
        ),
    )


class SearchWithOutlineRequest(SearchRequest):
    """Search request with outline-assisted query expansion."""


class DualPathRecallRequest(BaseModel):
    expanded_query: str = Field(..., min_length=1, description="已扩展的查询文本")
    chapter_ids: List[str] = Field(
        ...,
        min_length=1,
        description="Phase 2 展开后的考点范围",
    )
    subject_id: Optional[str] = Field(None, description="学科过滤")
    limit: int = Field(20, ge=1, le=50, description="归并后返回总数")
    per_chapter_cap: int = Field(
        10,
        ge=1,
        le=50,
        description="路 B 每考点展开上限",
    )


class ChapterExpansionRequest(BaseModel):
    chapter_ids: List[str] = Field(..., min_length=1, description="考点 ID 列表")
    max_results: int = Field(
        10,
        ge=1,
        le=50,
        description="每题点最多返回关联数",
    )
