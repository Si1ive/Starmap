"""知识点关系审核路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.db import get_db
from app.models.mysql_models import KnowledgeRelation
from app.modules.content.review_service import ReviewService

router = APIRouter(prefix="/admin", tags=["题目与知识点"])


@router.get("/review/relations", response_model=ApiResponse)
async def list_relations_for_review(
    relation_type: Optional[str] = None,
    review_status: Optional[str] = "pending",
    subject_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核的知识点关系列表。"""
    result = await ReviewService(db).get_relations_for_review(
        relation_type=relation_type,
        review_status=review_status,
        subject_id=subject_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result)


@router.get("/review/stats", response_model=ApiResponse)
async def get_review_stats(
    subject_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取内容审核统计。"""
    return ApiResponse(data=await ReviewService(db).get_review_stats(subject_id))


@router.post("/review/relations/batch-delete", response_model=ApiResponse)
async def batch_delete_review_relations(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除知识点关系。"""
    unique_ids = list(dict.fromkeys(req.ids))
    existing_ids = [
        row[0]
        for row in (
            await db.execute(
                select(KnowledgeRelation.id).where(
                    KnowledgeRelation.id.in_(unique_ids)
                )
            )
        ).all()
    ]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的关系")

    await db.execute(
        delete(KnowledgeRelation).where(KnowledgeRelation.id.in_(existing_ids))
    )
    await db.commit()
    return ApiResponse(
        message="删除成功",
        data={
            "deleted_count": len(existing_ids),
            "requested_count": len(unique_ids),
        },
    )


@router.post("/review/relations/{relation_id}", response_model=ApiResponse)
async def review_relation(
    relation_id: str,
    review_status: str = Query(..., description="审核状态: approved/rejected"),
    relation_type: Optional[str] = None,
    directionality: Optional[str] = None,
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核知识点关系。"""
    try:
        result = await ReviewService(db).review_relation(
            relation_id=relation_id,
            review_status=review_status,
            relation_type=relation_type,
            directionality=directionality,
            review_notes=review_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.delete("/review/relations/{relation_id}", response_model=ApiResponse)
async def delete_review_relation(
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个知识点关系。"""
    relation = await db.get(KnowledgeRelation, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="关系不存在")

    await db.delete(relation)
    await db.commit()
    return ApiResponse(message="删除成功", data={"id": relation_id})
