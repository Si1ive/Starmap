"""Admin routes for questions, knowledge points, and their review records."""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.db import get_db
from app.modules.content.schemas import (
    UpdateKnowledgePointRequest,
    UpdateQuestionRequest,
)
from app.modules.content.service import ContentService
from app.services.chapter_link_service import ChapterLinkService
from app.services.review_service import ReviewService

router = APIRouter(prefix="/admin", tags=["题目与知识点"])


@router.get("/knowledge/points", response_model=ApiResponse)
async def get_knowledge_points(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    subject_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    difficulty: Optional[str] = None,
    keyword: Optional[str] = None,
    review_status: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    result = await ContentService(db).list_knowledge_points(
        page=page,
        page_size=page_size,
        subject_id=subject_id,
        chapter_id=chapter_id,
        difficulty=difficulty,
        keyword=keyword,
        review_status=review_status,
        item_status=status,
    )
    return ApiResponse(data=result)


@router.get("/knowledge/points/{point_id}", response_model=ApiResponse)
async def get_knowledge_point_detail(
    point_id: str,
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ContentService(db).get_knowledge_point(point_id))


@router.put("/knowledge/points/{point_id}", response_model=ApiResponse)
async def update_knowledge_point(
    point_id: str,
    req: UpdateKnowledgePointRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await ContentService(db).update_knowledge_point(
        point_id,
        req.model_dump(exclude_unset=True),
    )
    return ApiResponse(message="更新成功", data={"id": point_id, "indexing": result})


@router.delete("/knowledge/points/{point_id}", response_model=ApiResponse)
async def delete_knowledge_point(
    point_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await ContentService(db).delete_knowledge_point(point_id)
    return ApiResponse(message="删除成功", data=result)


@router.post("/knowledge/points/batch-delete", response_model=ApiResponse)
async def batch_delete_knowledge_points(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await ContentService(db).batch_delete_knowledge_points(req.ids)
    return ApiResponse(message="删除成功", data=result)


@router.get("/questions", response_model=ApiResponse)
async def get_questions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    subject_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    type: Optional[str] = None,
    difficulty: Optional[str] = None,
    exam_scope: Optional[str] = None,
    exam_year: Optional[int] = None,
    keyword: Optional[str] = None,
    review_status: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    result = await ContentService(db).list_questions(
        page=page,
        page_size=page_size,
        subject_id=subject_id,
        chapter_id=chapter_id,
        question_type=type,
        difficulty=difficulty,
        exam_scope=exam_scope,
        exam_year=exam_year,
        keyword=keyword,
        review_status=review_status,
        item_status=status,
    )
    return ApiResponse(data=result)


@router.get("/questions/{question_id}", response_model=ApiResponse)
async def get_question_detail(
    question_id: str,
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ContentService(db).get_question(question_id))


@router.put("/questions/{question_id}", response_model=ApiResponse)
async def update_question(
    question_id: str,
    req: UpdateQuestionRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await ContentService(db).update_question(
        question_id,
        req.model_dump(exclude_unset=True),
    )
    return ApiResponse(message="更新成功", data={"id": question_id, "indexing": result})


@router.delete("/questions/{question_id}", response_model=ApiResponse)
async def delete_question(
    question_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await ContentService(db).delete_question(question_id)
    return ApiResponse(message="删除成功", data=result)


@router.post("/questions/batch-delete", response_model=ApiResponse)
async def batch_delete_questions(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await ContentService(db).batch_delete_questions(req.ids)
    return ApiResponse(message="删除成功", data=result)


# Compatibility routes. Review is audit metadata, not a publication gate.


@router.get("/review/knowledge", response_model=ApiResponse)
async def list_knowledge_points_for_review(
    subject_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    review_status: Optional[str] = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await ReviewService(db).get_knowledge_points_for_review(
        subject_id=subject_id,
        chapter_id=chapter_id,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result)


@router.post("/review/knowledge/{knowledge_id}", response_model=ApiResponse)
async def review_knowledge_point(
    knowledge_id: str,
    review_status: Literal["pending", "approved", "rejected"] = Query(...),
    review_notes: Optional[str] = None,
    primary_chapter_id: Optional[str] = None,
    topic_terms: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await ReviewService(db).review_knowledge_point(
            knowledge_point_id=knowledge_id,
            review_status=review_status,
            review_notes=review_notes,
            primary_chapter_id=primary_chapter_id,
            topic_terms=topic_terms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get("/review/questions", response_model=ApiResponse)
async def list_questions_for_review(
    subject_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    exam_scope: Optional[str] = None,
    exam_year: Optional[int] = None,
    question_type: Optional[str] = None,
    review_status: Optional[str] = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await ReviewService(db).get_questions_for_review(
        subject_id=subject_id,
        chapter_id=chapter_id,
        exam_scope=exam_scope,
        exam_year=exam_year,
        question_type=question_type,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result)


@router.post("/review/questions/backfill-chapters", response_model=ApiResponse)
async def backfill_question_review_chapters(
    review_status: str = Query("pending"),
    item_status: str = Query("active"),
    subject_id: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
    force: bool = Query(False),
    dry_run: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    result = await ChapterLinkService(db).backfill_question_chapters(
        review_status=review_status,
        status=item_status,
        subject_id=subject_id,
        limit=limit,
        force=force,
        dry_run=dry_run,
    )
    return ApiResponse(data=result)


@router.post("/review/questions/{question_id}", response_model=ApiResponse)
async def review_question(
    question_id: str,
    review_status: Literal["pending", "approved", "rejected"] = Query(...),
    review_notes: Optional[str] = None,
    primary_chapter_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await ReviewService(db).review_question(
            question_id=question_id,
            review_status=review_status,
            review_notes=review_notes,
            primary_chapter_id=primary_chapter_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=result)
