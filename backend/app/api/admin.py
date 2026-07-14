"""尚未完成领域迁移的后台管理兼容路由。"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import (
    DocumentAsset,
    KnowledgePoint,
    KnowledgePointChapterLink,
    Question,
    QuestionChapterLink,
)
from app.modules.catalog.chapter_link_service import ChapterLinkService

router = APIRouter(prefix="/admin", tags=["后台管理"])


# ===== 资产托管 =====


@router.get("/assets/{asset_id}/file")
async def serve_asset_file(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """根据 asset_id 返回资产文件。"""
    asset = await db.get(DocumentAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    if not asset.file_path:
        raise HTTPException(
            status_code=404,
            detail="该资产无文件（可能是公式或表格 HTML）",
        )

    file_path = Path(asset.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"文件不存在: {asset.file_path}",
        )
    return FileResponse(path=str(file_path))


@router.get("/assets/{asset_id}", response_model=ApiResponse)
async def get_asset_metadata(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取资产元数据。"""
    asset = await db.get(DocumentAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    return ApiResponse(
        data={
            "id": asset.id,
            "document_id": asset.document_id,
            "page_no": asset.page_no,
            "asset_type": asset.asset_type,
            "file_path": asset.file_path,
            "thumbnail_path": asset.thumbnail_path,
            "caption_text": asset.caption_text,
            "ocr_text": asset.ocr_text,
            "bbox": asset.bbox,
            "metadata": asset.metadata_json,
            "file_url": (
                f"/api/v1/admin/assets/{asset.id}/file"
                if asset.file_path
                else None
            ),
        }
    )


# ===== 章节关联 =====


@router.post(
    "/knowledge/{kp_id}/link-chapters",
    response_model=ApiResponse,
)
async def link_knowledge_point_to_chapters(
    kp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动触发知识点关联大纲章节。"""
    service = ChapterLinkService(db)
    try:
        result = await service.link_knowledge_point_to_chapters(kp_id)
        return ApiResponse(data=result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/questions/{question_id}/link-chapters",
    response_model=ApiResponse,
)
async def link_question_to_chapters(
    question_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动触发题目关联大纲章节。"""
    service = ChapterLinkService(db)
    try:
        result = await service.link_question_to_chapters(question_id)
        return ApiResponse(data=result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/documents/{document_id}/link-chapters",
    response_model=ApiResponse,
)
async def batch_link_document_chapters(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """批量关联文档下所有已审核实体到大纲章节。"""
    service = ChapterLinkService(db)
    try:
        result = await service.batch_link_document(document_id)
        return ApiResponse(data=result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/chapters/{chapter_id}/entities",
    response_model=ApiResponse,
)
async def get_chapter_entities(
    chapter_id: str,
    entity_type: Optional[str] = Query(
        None,
        description="实体类型: knowledge_point / question",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取某章节下的知识点和题目。"""
    result = {"knowledge_points": [], "questions": []}

    if not entity_type or entity_type == "knowledge_point":
        knowledge_point_links = (
            await db.execute(
                select(KnowledgePointChapterLink, KnowledgePoint)
                .join(
                    KnowledgePoint,
                    KnowledgePoint.id
                    == KnowledgePointChapterLink.knowledge_point_id,
                )
                .where(
                    KnowledgePointChapterLink.canonical_chapter_id
                    == chapter_id,
                    KnowledgePoint.status == "active",
                )
                .order_by(
                    KnowledgePointChapterLink.relevance.desc()
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        result["knowledge_points"] = [
            {
                "id": knowledge_point.id,
                "title": knowledge_point.title,
                "content": (
                    knowledge_point.content[:200]
                    if knowledge_point.content
                    else None
                ),
                "relevance": float(link.relevance),
                "source": link.source,
                "is_primary": link.is_primary,
            }
            for link, knowledge_point in knowledge_point_links
        ]

    if not entity_type or entity_type == "question":
        question_links = (
            await db.execute(
                select(QuestionChapterLink, Question)
                .join(
                    Question,
                    Question.id == QuestionChapterLink.question_id,
                )
                .where(
                    QuestionChapterLink.canonical_chapter_id == chapter_id,
                    Question.status == "active",
                )
                .order_by(QuestionChapterLink.relevance.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        result["questions"] = [
            {
                "id": question.id,
                "content": (
                    question.content[:200] if question.content else None
                ),
                "type": question.type,
                "exam_year": question.exam_year,
                "relevance": float(link.relevance),
                "source": link.source,
                "is_primary": link.is_primary,
            }
            for link, question in question_links
        ]

    return ApiResponse(data=result)
