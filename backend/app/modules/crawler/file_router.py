"""爬虫下载文件查询与预览路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import DownloadedFile
from app.modules.crawler.storage import resolve_download_path

router = APIRouter(prefix="/admin", tags=["爬虫管理"])


def _serialize_downloaded_file(file: DownloadedFile) -> dict:
    return {
        "id": file.id,
        "task_id": file.task_id,
        "repo_name": file.repo_name,
        "repo_url": file.repo_url,
        "file_path": file.file_path,
        "file_name": file.file_name,
        "file_type": file.file_type,
        "file_size": file.file_size,
        "download_url": file.download_url,
        "local_path": file.local_path,
        "status": file.status,
        "error_detail": file.error_detail,
        "created_at": file.created_at.isoformat() if file.created_at else None,
        "updated_at": file.updated_at.isoformat() if file.updated_at else None,
    }


@router.get("/files/downloaded", response_model=ApiResponse)
async def get_downloaded_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    file_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """分页查询爬虫已下载文件。"""
    query = select(DownloadedFile)

    if file_type:
        query = query.where(DownloadedFile.file_type == file_type)
    if status:
        query = query.where(DownloadedFile.status == status)
    if task_id:
        query = query.where(DownloadedFile.task_id == task_id)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            DownloadedFile.file_name.like(pattern)
            | DownloadedFile.repo_name.like(pattern)
        )

    total = (
        await db.scalar(select(func.count()).select_from(query.subquery()))
        or 0
    )
    files = (
        await db.execute(
            query.order_by(DownloadedFile.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return ApiResponse(
        data={
            "items": [_serialize_downloaded_file(file) for file in files],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/files/downloaded/{file_id}", response_model=ApiResponse)
async def get_downloaded_file_detail(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取已下载文件详情。"""
    file = (
        await db.execute(
            select(DownloadedFile).where(DownloadedFile.id == file_id)
        )
    ).scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")
    return ApiResponse(data=_serialize_downloaded_file(file))


@router.get("/files/downloaded/{file_id}/preview")
async def preview_downloaded_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """在下载根目录约束内预览或下载文件。"""
    file = (
        await db.execute(
            select(DownloadedFile).where(DownloadedFile.id == file_id)
        )
    ).scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")
    if not file.local_path:
        raise HTTPException(status_code=404, detail="文件路径不存在")

    try:
        local_path = resolve_download_path(file.local_path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="文件路径不允许访问") from exc

    if not local_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在于磁盘")

    media_type = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "ppt": "application/vnd.ms-powerpoint",
        "pptx": (
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
    }.get(file.file_type or "", "application/octet-stream")

    return FileResponse(
        path=str(local_path),
        media_type=media_type,
        filename=file.file_name,
    )
