"""文档资产元数据与文件读取路由。"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import DocumentAsset

router = APIRouter(prefix="/admin", tags=["内容资产"])


@router.get("/assets/{asset_id}/file")
async def serve_asset_file(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """根据资产 ID 返回文件。"""
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
