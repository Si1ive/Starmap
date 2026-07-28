"""Private learner library ingestion, reading, retrieval control, and deletion."""

from datetime import UTC, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import CorpusFile, Document
from app.modules.corpus.service import CorpusApplicationService
from app.modules.identity.dependencies import (
    require_csrf_session,
    require_csrf_upload_session,
    require_current_session,
)
from app.modules.identity.session import AuthenticatedSession

router = APIRouter(prefix="/app/library", tags=["用户资料库"])


class UpdateSourceRetrievalRequest(BaseModel):
    enabled: bool


def _visible_to(user_id: object):
    return or_(
        CorpusFile.owner_user_id.is_(None),
        CorpusFile.owner_user_id == user_id,
    )


@router.get("/sources", response_model=ApiResponse)
async def list_library_sources(
    keyword: Optional[str] = None,
    origin: str = Query("all", pattern="^(all|platform|personal)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current: AuthenticatedSession = Depends(require_current_session),
    db: AsyncSession = Depends(get_db),
):
    conditions = [_visible_to(current.user.id), CorpusFile.deleted_at.is_(None)]
    if origin == "platform":
        conditions.append(CorpusFile.owner_user_id.is_(None))
    elif origin == "personal":
        conditions.append(CorpusFile.owner_user_id == current.user.id)
    if keyword and keyword.strip():
        conditions.append(CorpusFile.file_name.ilike(f"%{keyword.strip()}%"))

    query = (
        select(CorpusFile, Document)
        .outerjoin(Document, Document.corpus_file_id == CorpusFile.id)
        .where(and_(*conditions))
    )
    total = (
        await db.scalar(
            select(func.count()).select_from(CorpusFile).where(and_(*conditions))
        )
        or 0
    )
    rows = (
        await db.execute(
            query.order_by(CorpusFile.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        {
            "id": corpus_file.id,
            "name": corpus_file.file_name,
            "origin": "personal" if corpus_file.owner_user_id else "platform",
            "status": corpus_file.status,
            "retrieval_enabled": corpus_file.retrieval_enabled,
            "error_detail": corpus_file.error_detail,
            "file_size": corpus_file.file_size,
            "file_type": corpus_file.file_ext,
            "doc_type": corpus_file.doc_type,
            "document_id": document.id if document else None,
            "page_count": document.page_count if document else None,
            "created_at": corpus_file.created_at.isoformat(),
            "updated_at": corpus_file.updated_at.isoformat(),
            "read_url": (
                f"/api/v1/app/library/documents/{document.id}/content"
                if document and corpus_file.file_ext == "pdf"
                else None
            ),
        }
        for corpus_file, document in rows
    ]
    return ApiResponse(data={"items": items, "total": total})


@router.post("/sources", response_model=ApiResponse)
async def upload_library_sources(
    files: List[UploadFile] = File(...),
    current: AuthenticatedSession = Depends(require_csrf_upload_session),
    db: AsyncSession = Depends(get_db),
):
    for upload in files:
        if not (upload.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="用户资料入库当前只支持 PDF")
        signature = await upload.read(5)
        await upload.seek(0)
        if signature != b"%PDF-":
            raise HTTPException(status_code=400, detail="文件内容不是有效的 PDF")
    service = CorpusApplicationService(db)
    result = await service.upload_files(
        files,
        batch_label=f"user:{current.user.id}",
        owner_user_id=current.user.id,
    )
    parse_runs = []
    for item in result["success_items"]:
        try:
            run = await service.start_parse(
                item["corpus_file_id"],
                parser_name=None,
                parse_mode="primary",
                auto_extract=True,
            )
            parse_runs.append(run)
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = f"入库任务启动失败: {str(exc)[:160]}"
    result["parse_runs"] = parse_runs
    return ApiResponse(message="资料已提交入库", data=result)


async def _owned_personal_source(
    db: AsyncSession,
    source_id: str,
    user_id: object,
) -> CorpusFile:
    source = await db.scalar(
        select(CorpusFile).where(
            CorpusFile.id == source_id,
            CorpusFile.owner_user_id == user_id,
            CorpusFile.deleted_at.is_(None),
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="个人资料不存在")
    return source


@router.patch("/sources/{source_id}/retrieval", response_model=ApiResponse)
async def update_source_retrieval(
    source_id: str,
    payload: UpdateSourceRetrievalRequest,
    current: AuthenticatedSession = Depends(require_csrf_session),
    db: AsyncSession = Depends(get_db),
):
    source = await _owned_personal_source(db, source_id, current.user.id)
    source.retrieval_enabled = payload.enabled
    await db.flush()
    return ApiResponse(
        message="已允许 Agent 使用" if payload.enabled else "已暂停 Agent 使用",
        data={"id": source.id, "retrieval_enabled": source.retrieval_enabled},
    )


@router.delete("/sources/{source_id}", response_model=ApiResponse)
async def delete_library_source(
    source_id: str,
    current: AuthenticatedSession = Depends(require_csrf_session),
    db: AsyncSession = Depends(get_db),
):
    source = await _owned_personal_source(db, source_id, current.user.id)
    source.retrieval_enabled = False
    source.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    source.status = "archived"
    await db.flush()
    return ApiResponse(
        message="资料已删除并立即退出检索",
        data={"id": source.id, "deletion_status": "completed"},
    )


@router.get("/documents/{document_id}/content")
async def read_original_pdf(
    document_id: str,
    current: AuthenticatedSession = Depends(require_current_session),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(Document, CorpusFile)
            .join(CorpusFile, CorpusFile.id == Document.corpus_file_id)
            .where(
                Document.id == document_id,
                _visible_to(current.user.id),
                CorpusFile.deleted_at.is_(None),
                CorpusFile.file_ext == "pdf",
            )
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="资料不存在或无权访问")
    _, corpus_file = row
    path = Path(corpus_file.local_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="原始 PDF 文件已不可用")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=corpus_file.file_name,
        content_disposition_type="inline",
    )
