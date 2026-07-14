"""标准章节关系构建与审核路由。"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.db import get_db
from app.models.mysql_models import CanonicalChapter, ChapterRelation
from app.modules.retrieval.chapter_relation_retrieval import (
    fallback_chapter_similarity,
    validate_cross_references,
)

router = APIRouter(prefix="/admin", tags=["考点关系"])


@router.post("/chapter-relations/build", response_model=ApiResponse)
async def build_chapter_relations(
    subject_id: Optional[str] = None,
    outline_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    构建考点间直接关系（从 cross_references + embedding 相似度）。

    1. 读取 CanonicalChapter.cross_references（LLM 标注的跨章关联）
    2. 双向写入 ChapterRelation（source_type="llm"）
    3. 对无 cross_references 的考点，用 embedding 相似度兜底
    """
    query = select(CanonicalChapter).where(CanonicalChapter.status == "active")
    if subject_id:
        query = query.where(CanonicalChapter.subject_id == subject_id)
    if outline_id:
        query = query.where(CanonicalChapter.outline_id == outline_id)

    chapters = (await db.execute(query)).scalars().all()
    if not chapters:
        return ApiResponse(data={"message": "没有可用考点", "created": 0})

    created = 0
    llm_created = 0
    embedding_created = 0
    chapter_map = {chapter.id: chapter for chapter in chapters}
    relation_keys = {
        (row[0], row[1], row[2])
        for row in (
            await db.execute(
                select(
                    ChapterRelation.source_chapter_id,
                    ChapterRelation.target_chapter_id,
                    ChapterRelation.relation_type,
                )
            )
        ).all()
    }

    for chapter in chapters:
        cross_refs = getattr(chapter, "cross_references", None)

        if cross_refs:
            valid_refs = await validate_cross_references(db, cross_refs)
            for ref in valid_refs:
                target_id = ref["target_chapter_id"]
                if target_id not in chapter_map:
                    continue
                for source_id, related_id in (
                    (chapter.id, target_id),
                    (target_id, chapter.id),
                ):
                    relation_type = ref.get("relation_type", "similar_to")
                    relation_key = (source_id, related_id, relation_type)
                    if source_id == related_id or relation_key in relation_keys:
                        continue
                    relation_keys.add(relation_key)
                    db.add(
                        ChapterRelation(
                            id=_generate_relation_id(),
                            source_chapter_id=source_id,
                            target_chapter_id=related_id,
                            relation_type=relation_type,
                            confidence=0.9,
                            source_type="llm",
                            evidence_text=ref.get("reason"),
                            review_status="pending",
                        )
                    )
                    llm_created += 1
                    created += 1

        if not cross_refs:
            similarities = await fallback_chapter_similarity(
                db,
                chapter.id,
                top_k=3,
            )
            for target_id, score in similarities:
                if target_id not in chapter_map:
                    continue
                relation_key = (chapter.id, target_id, "similar_to")
                if chapter.id == target_id or relation_key in relation_keys:
                    continue
                relation_keys.add(relation_key)
                db.add(
                    ChapterRelation(
                        id=_generate_relation_id(),
                        source_chapter_id=chapter.id,
                        target_chapter_id=target_id,
                        relation_type="similar_to",
                        confidence=round(score, 4),
                        source_type="embedding",
                        evidence_text=f"语义相似度 {score:.4f}",
                        review_status="pending",
                    )
                )
                embedding_created += 1
                created += 1

    await db.commit()

    return ApiResponse(
        data={
            "created": created,
            "llm_created": llm_created,
            "embedding_created": embedding_created,
            "chapters_processed": len(chapters),
        }
    )


@router.get("/chapter-relations", response_model=ApiResponse)
async def list_chapter_relations(
    source_chapter_id: Optional[str] = None,
    target_chapter_id: Optional[str] = None,
    relation_type: Optional[str] = None,
    review_status: Optional[str] = None,
    source_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询考点关系列表。"""
    query = (
        select(
            ChapterRelation,
            CanonicalChapter.name.label("source_name"),
            CanonicalChapter.name.label("target_name"),
        )
        .join(
            CanonicalChapter,
            ChapterRelation.source_chapter_id == CanonicalChapter.id,
        )
    )
    conditions = []
    if source_chapter_id:
        conditions.append(
            ChapterRelation.source_chapter_id == source_chapter_id
        )
    if target_chapter_id:
        conditions.append(
            ChapterRelation.target_chapter_id == target_chapter_id
        )
    if relation_type:
        conditions.append(ChapterRelation.relation_type == relation_type)
    if review_status:
        conditions.append(ChapterRelation.review_status == review_status)
    if source_type:
        conditions.append(ChapterRelation.source_type == source_type)

    if conditions:
        query = query.where(and_(*conditions))

    count_query = select(func.count()).select_from(ChapterRelation)
    if conditions:
        count_query = count_query.where(and_(*conditions))
    total = await db.scalar(count_query) or 0

    query = query.order_by(
        ChapterRelation.created_at.desc(),
        ChapterRelation.id.desc(),
    )
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).all()

    items = []
    for relation, source_name, _ in rows:
        target_chapter = await db.get(
            CanonicalChapter,
            relation.target_chapter_id,
        )
        items.append(
            {
                "id": relation.id,
                "source_chapter_id": relation.source_chapter_id,
                "source_chapter_name": source_name,
                "target_chapter_id": relation.target_chapter_id,
                "target_chapter_name": (
                    target_chapter.name if target_chapter else ""
                ),
                "relation_type": relation.relation_type,
                "confidence": (
                    float(relation.confidence)
                    if relation.confidence
                    else None
                ),
                "source_type": relation.source_type,
                "evidence_text": relation.evidence_text,
                "review_status": relation.review_status,
                "review_notes": relation.review_notes,
                "created_at": (
                    relation.created_at.isoformat()
                    if relation.created_at
                    else None
                ),
            }
        )

    return ApiResponse(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post(
    "/chapter-relations/{relation_id}/review",
    response_model=ApiResponse,
)
async def review_chapter_relation(
    relation_id: str,
    review_status: str = Query(..., description="approved / rejected"),
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核考点关系。"""
    relation = await db.get(ChapterRelation, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="关系不存在")

    relation.review_status = review_status
    if review_notes:
        relation.review_notes = review_notes
    relation.reviewed_at = datetime.utcnow()
    await db.commit()

    return ApiResponse(
        data={"id": relation_id, "review_status": review_status}
    )


@router.delete(
    "/chapter-relations/{relation_id}",
    response_model=ApiResponse,
)
async def delete_chapter_relation(
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个考点关系。"""
    relation = await db.get(ChapterRelation, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="关系不存在")

    await db.delete(relation)
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": relation_id})


@router.post(
    "/chapter-relations/batch-delete",
    response_model=ApiResponse,
)
async def batch_delete_chapter_relations(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除考点关系。"""
    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(ChapterRelation.id).where(
            ChapterRelation.id.in_(unique_ids)
        )
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的关系")

    await db.execute(
        delete(ChapterRelation).where(
            ChapterRelation.id.in_(existing_ids)
        )
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={
            "deleted_count": len(existing_ids),
            "requested_count": len(unique_ids),
        },
    )


def _generate_relation_id() -> str:
    return uuid.uuid4().hex[:32]
