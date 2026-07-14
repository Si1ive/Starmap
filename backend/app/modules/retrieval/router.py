"""Admin routes for segment construction and retrieval debugging."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.modules.retrieval.schemas import (
    ChapterExpansionRequest,
    DualPathRecallRequest,
    SearchRequest,
    SearchWithOutlineRequest,
)
from app.modules.retrieval.outline_service import expand_related_chapters
from app.modules.retrieval.relation_service import RelationService
from app.modules.retrieval.service import RetrievalService
from app.modules.retrieval.segment_service import SegmentService

router = APIRouter(prefix="/admin", tags=["检索"])


@router.post("/segments/build", response_model=ApiResponse)
async def build_segments(
    subject_id: Optional[str] = None,
    document_id: Optional[str] = None,
    rebuild: bool = False,
    db: AsyncSession = Depends(get_db),
):
    result = await SegmentService(db).build_all_segments(
        subject_id=subject_id,
        document_id=document_id,
        rebuild=rebuild,
    )
    return ApiResponse(data=result)


@router.post("/segments/build/knowledge", response_model=ApiResponse)
async def build_knowledge_segments(
    subject_id: Optional[str] = None,
    document_id: Optional[str] = None,
    knowledge_point_ids: Optional[List[str]] = None,
    rebuild: bool = False,
    db: AsyncSession = Depends(get_db),
):
    result = await SegmentService(db).build_knowledge_segments(
        subject_id=subject_id,
        document_id=document_id,
        knowledge_point_ids=knowledge_point_ids,
        rebuild=rebuild,
    )
    return ApiResponse(data=result)


@router.post("/segments/build/questions", response_model=ApiResponse)
async def build_question_segments(
    subject_id: Optional[str] = None,
    document_id: Optional[str] = None,
    question_ids: Optional[List[str]] = None,
    rebuild: bool = False,
    db: AsyncSession = Depends(get_db),
):
    result = await SegmentService(db).build_question_segments(
        subject_id=subject_id,
        document_id=document_id,
        question_ids=question_ids,
        rebuild=rebuild,
    )
    return ApiResponse(data=result)


@router.post("/segments/build/chapters", response_model=ApiResponse)
async def build_chapter_segments(
    subject_id: Optional[str] = None,
    outline_id: Optional[str] = None,
    rebuild: bool = False,
    db: AsyncSession = Depends(get_db),
):
    result = await SegmentService(db).build_canonical_chapter_segments(
        subject_id=subject_id,
        outline_id=outline_id,
        rebuild=rebuild,
    )
    return ApiResponse(data=result)


@router.post("/relations/build", response_model=ApiResponse)
async def build_knowledge_relations(
    subject_id: Optional[str] = None,
    knowledge_point_ids: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db),
):
    """构建知识点规则关系和语义相似关系。"""
    try:
        result = await RelationService(db).build_relations(
            subject_id=subject_id,
            knowledge_point_ids=knowledge_point_ids,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"关系构建失败: {str(exc)[:200]}",
        ) from exc
    return ApiResponse(data=result)


@router.post("/search", response_model=ApiResponse)
async def search_knowledge(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    results = await RetrievalService(db).search(
        query=request.query,
        subject_id=request.subject_id,
        chapter_ids=request.chapter_ids,
        entity_type=request.entity_type,
        mode=request.mode,
        limit=request.limit,
        filters=request.filters,
    )
    return ApiResponse(
        data={
            "results": [result.to_dict() for result in results],
            "total": len(results),
            "mode": request.mode,
        }
    )


@router.post("/search/with-relations", response_model=ApiResponse)
async def search_with_relations(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await RetrievalService(db).search_with_relations(
        query=request.query,
        subject_id=request.subject_id,
        chapter_ids=request.chapter_ids,
        limit=request.limit,
    )
    return ApiResponse(data=result)


@router.post("/search/with-outline", response_model=ApiResponse)
async def search_with_outline(
    request: SearchWithOutlineRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await RetrievalService(db).search_with_outline_expansion(
        query=request.query,
        subject_id=request.subject_id,
        chapter_ids=request.chapter_ids,
        entity_type=request.entity_type,
        mode=request.mode,
        limit=request.limit,
        filters=request.filters,
    )
    return ApiResponse(data=result)


@router.post("/search/dual-path", response_model=ApiResponse)
async def dual_path_recall(
    request: DualPathRecallRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await RetrievalService(db).merge_dual_path_recall(
        expanded_query=request.expanded_query,
        chapter_ids=request.chapter_ids,
        subject_id=request.subject_id,
        limit=request.limit,
        per_chapter_cap=request.per_chapter_cap,
    )
    return ApiResponse(data=result)


@router.post("/search/chapter-expansion", response_model=ApiResponse)
async def expand_chapters(
    request: ChapterExpansionRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await expand_related_chapters(
        db,
        chapter_ids=request.chapter_ids,
        max_results=request.max_results,
    )
    return ApiResponse(data={"relations": result})
