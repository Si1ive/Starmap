"""文档章节映射审核兼容路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.db import get_db
from app.models.mysql_models import (
    CanonicalChapter,
    Document,
    DocumentSection,
    DocumentSectionMapping,
)
from app.modules.catalog.chapter_mapping_service import ChapterMappingService

router = APIRouter(prefix="/admin", tags=["学科与章节"])


@router.get("/review/sections", response_model=ApiResponse, deprecated=True)
async def list_pending_section_mappings(
    subject_id: Optional[str] = None,
    review_status: Optional[str] = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核的 section 映射列表。"""
    query = (
        select(DocumentSectionMapping, DocumentSection, CanonicalChapter)
        .join(
            DocumentSection,
            DocumentSectionMapping.document_section_id == DocumentSection.id,
        )
        .join(Document, DocumentSection.document_id == Document.id)
        .join(
            CanonicalChapter,
            DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id,
        )
    )
    count_query = select(func.count()).select_from(DocumentSectionMapping)

    conditions = []
    if review_status:
        conditions.append(
            DocumentSectionMapping.review_status == review_status
        )
    if subject_id:
        conditions.append(
            or_(
                Document.subject_id == subject_id,
                CanonicalChapter.subject_id == subject_id,
            )
        )

    if conditions:
        query = query.where(and_(*conditions))
        count_query = (
            count_query.join(
                DocumentSection,
                DocumentSectionMapping.document_section_id
                == DocumentSection.id,
            )
            .join(Document, DocumentSection.document_id == Document.id)
            .join(
                CanonicalChapter,
                DocumentSectionMapping.canonical_chapter_id
                == CanonicalChapter.id,
            )
            .where(and_(*conditions))
        )

    total = await db.scalar(count_query) or 0
    rows = (
        await db.execute(
            query.order_by(
                DocumentSectionMapping.created_at.desc(),
                DocumentSectionMapping.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    return ApiResponse(
        data={
            "items": [
                {
                    "mapping_id": mapping.id,
                    "section_id": section.id,
                    "section_title": section.title,
                    "section_path": section.section_path,
                    "document_id": section.document_id,
                    "canonical_chapter_id": chapter.id,
                    "canonical_chapter_name": chapter.name,
                    "canonical_chapter_code": chapter.code,
                    "mapping_type": mapping.mapping_type,
                    "confidence": float(mapping.confidence),
                    "review_status": mapping.review_status,
                    "review_notes": mapping.review_notes,
                    "created_at": (
                        mapping.created_at.isoformat()
                        if mapping.created_at
                        else None
                    ),
                }
                for mapping, section, chapter in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post(
    "/review/sections/batch-delete",
    response_model=ApiResponse,
    deprecated=True,
)
async def batch_delete_section_mappings(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除 section 映射。"""
    unique_ids = list(dict.fromkeys(req.ids))
    existing_ids = [
        row[0]
        for row in (
            await db.execute(
                select(DocumentSectionMapping.id).where(
                    DocumentSectionMapping.id.in_(unique_ids)
                )
            )
        ).all()
    ]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的映射")

    await db.execute(
        delete(DocumentSectionMapping).where(
            DocumentSectionMapping.id.in_(existing_ids)
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


@router.post(
    "/review/sections/{mapping_id}",
    response_model=ApiResponse,
    deprecated=True,
)
async def review_section_mapping(
    mapping_id: str,
    review_status: str = Query(..., description="审核状态: approved/rejected"),
    canonical_chapter_id: Optional[str] = None,
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核 section 映射。"""
    try:
        result = await ChapterMappingService(db).review_mapping(
            mapping_id=mapping_id,
            review_status=review_status,
            canonical_chapter_id=canonical_chapter_id,
            review_notes=review_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.delete(
    "/review/sections/{mapping_id}",
    response_model=ApiResponse,
    deprecated=True,
)
async def delete_section_mapping(
    mapping_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个 section 映射。"""
    mapping = await db.get(DocumentSectionMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="映射不存在")

    await db.delete(mapping)
    await db.commit()
    return ApiResponse(message="删除成功", data={"id": mapping_id})
