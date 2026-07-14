"""Crawler administration routes."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.core.logging import get_logger
from app.core.websocket import log_websocket_manager
from app.db import get_db
from app.models.mysql_models import DownloadedFile
from app.modules.crawler.log_service import CrawlerLogService
from app.modules.crawler.storage import DOWNLOAD_STORE

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/crawler", tags=["爬虫管理"])

# ========== 日志系统 ==========


@router.get("/logs", response_model=ApiResponse)
async def get_crawler_logs(
    task_id: Optional[str] = None,
    source_id: Optional[str] = None,
    level: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """获取爬虫日志"""
    service = CrawlerLogService(db)
    logs, total = await service.get_logs(
        task_id=task_id,
        source_id=source_id,
        level=level,
        status=status,
        resource_type=resource_type,
        start_time=start_time,
        end_time=end_time,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [
                {
                    "id": log.id,
                    "task_id": log.task_id,
                    "source_id": log.source_id,
                    "level": log.level,
                    "stage": log.stage,
                    "resource_url": log.resource_url,
                    "resource_name": log.resource_name,
                    "resource_type": log.resource_type,
                    "action": log.action,
                    "status": log.status,
                    "duration_ms": log.duration_ms,
                    "message": log.message,
                    "error_type": log.error_type,
                    "error_detail": log.error_detail,
                    "retry_count": log.retry_count,
                    "details": log.details,
                    "created_at": (
                        log.created_at.isoformat() if log.created_at else None
                    ),
                }
                for log in logs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get("/logs/export")
async def export_crawler_logs(
    task_id: Optional[str] = None,
    source_id: Optional[str] = None,
    level: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    file_format: str = Query("csv", alias="format"),
    limit: int = Query(5000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
):
    """导出爬虫日志"""
    normalized_format = file_format.lower()
    if normalized_format not in {"csv", "json"}:
        raise HTTPException(status_code=400, detail="format 仅支持 csv 或 json")

    service = CrawlerLogService(db)
    rows, total = await service.export_logs(
        task_id=task_id,
        source_id=source_id,
        level=level,
        status=status,
        resource_type=resource_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    exported_at = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"crawler_logs_{exported_at}.{normalized_format}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Total-Count": str(total),
        "X-Exported-Count": str(len(rows)),
    }

    if normalized_format == "json":
        return JSONResponse(
            content=jsonable_encoder(
                {
                    "items": rows,
                    "total": total,
                    "exported": len(rows),
                }
            ),
            headers=headers,
        )

    return Response(
        content=service.to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get("/file-logs", response_model=ApiResponse)
async def get_crawler_file_logs(
    task_id: Optional[str] = None,
    repo_name: Optional[str] = None,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """获取文件爬取日志（以文件为单位）"""
    query = select(DownloadedFile)
    count_query = select(func.count()).select_from(DownloadedFile)

    filters = []
    if task_id:
        filters.append(DownloadedFile.task_id == task_id)
    if repo_name:
        filters.append(DownloadedFile.repo_name == repo_name)
    if status:
        filters.append(DownloadedFile.status == status)
    if file_type:
        filters.append(DownloadedFile.file_type == file_type)
    if keyword:
        kw = f"%{keyword}%"
        filters.append(
            or_(
                DownloadedFile.file_name.ilike(kw),
                DownloadedFile.repo_name.ilike(kw),
                DownloadedFile.file_path.ilike(kw),
                DownloadedFile.error_detail.ilike(kw),
            )
        )

    for f in filters:
        query = query.where(f)
        count_query = count_query.where(f)

    total = await db.scalar(count_query) or 0

    # 成功/失败统计（同筛选条件下的全局统计）
    success_query = (
        select(func.count())
        .select_from(DownloadedFile)
        .where(DownloadedFile.status != "failed")
    )
    failed_query = (
        select(func.count())
        .select_from(DownloadedFile)
        .where(DownloadedFile.status == "failed")
    )
    for flt in filters:
        success_query = success_query.where(flt)
        failed_query = failed_query.where(flt)
    success_count = await db.scalar(success_query) or 0
    failed_count = await db.scalar(failed_query) or 0

    query = query.order_by(DownloadedFile.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    files = result.scalars().all()

    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": [
                {
                    "id": f.id,
                    "task_id": f.task_id,
                    "repo_name": f.repo_name,
                    "repo_url": f.repo_url,
                    "file_path": f.file_path,
                    "file_name": f.file_name,
                    "file_type": f.file_type,
                    "file_size": f.file_size,
                    "download_url": f.download_url,
                    "local_path": f.local_path,
                    "status": f.status,
                    "error_detail": f.error_detail,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in files
            ],
            "total": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get("/file-logs/repos", response_model=ApiResponse)
async def get_file_log_repos(db: AsyncSession = Depends(get_db)):
    """获取所有仓库名列表（用于筛选）"""
    result = await db.execute(
        select(DownloadedFile.repo_name)
        .where(DownloadedFile.repo_name.isnot(None))
        .distinct()
        .order_by(DownloadedFile.repo_name)
    )
    repos = [row[0] for row in result.all()]
    return ApiResponse(code=200, message="success", data=repos)


@router.get("/logs/analysis", response_model=ApiResponse)
async def get_log_analysis(days: int = 7, db: AsyncSession = Depends(get_db)):
    """获取日志分析"""
    service = CrawlerLogService(db)
    analysis = await service.get_analysis(days)
    return ApiResponse(code=200, message="success", data=analysis)


# ========== WebSocket 实时日志 ==========


@router.websocket("/logs/stream")
async def crawler_logs_stream(
    websocket: WebSocket,
    task_id: Optional[str] = None,
    source_id: Optional[str] = None,
    level: Optional[str] = None,
):
    """
    WebSocket 实时日志推送

    连接后自动接收符合条件的日志消息。
    支持通过 query 参数过滤：task_id, source_id, level
    """
    # 解析过滤条件
    task_ids = {task_id} if task_id else set()
    source_ids = {source_id} if source_id else set()
    levels = {level} if level else set()

    await log_websocket_manager.connect(
        websocket,
        task_ids=task_ids if task_ids else None,
        source_ids=source_ids if source_ids else None,
        levels=levels if levels else None,
    )

    try:
        while True:
            # 等待客户端消息（心跳或控制命令）
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "filter":
                    # 动态更新过滤条件
                    new_task_ids = set(message.get("task_ids", []))
                    new_source_ids = set(message.get("source_ids", []))
                    new_levels = set(message.get("levels", []))
                    log_websocket_manager.update_filters(
                        websocket,
                        task_ids=new_task_ids,
                        source_ids=new_source_ids,
                        levels=new_levels,
                    )
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "filter_updated",
                                "task_ids": list(new_task_ids),
                                "source_ids": list(new_source_ids),
                                "levels": list(new_levels),
                            }
                        )
                    )
            except json.JSONDecodeError:
                logger.warning(f"Invalid WebSocket message: {data}")

    except WebSocketDisconnect:
        await log_websocket_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await log_websocket_manager.disconnect(websocket)


@router.post("/file-logs/retry", response_model=ApiResponse)
async def retry_file_downloads(
    file_ids: List[str],
    db: AsyncSession = Depends(get_db),
):
    """重试下载指定文件"""
    import httpx

    if not file_ids:
        raise HTTPException(status_code=400, detail="请提供至少一个文件ID")
    if len(file_ids) > 50:
        raise HTTPException(status_code=400, detail="单次最多重试50个文件")

    result = await db.execute(
        select(DownloadedFile).where(DownloadedFile.id.in_(file_ids))
    )
    files = result.scalars().all()

    if not files:
        raise HTTPException(status_code=404, detail="未找到指定文件")

    download_store = Path(DOWNLOAD_STORE).resolve()
    success_count = 0
    fail_count = 0
    results = []

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for f in files:
            file_result = {"id": f.id, "file_name": f.file_name}
            try:
                if not f.download_url:
                    raise ValueError("文件无下载链接")

                # 标记为处理中
                await db.execute(
                    update(DownloadedFile)
                    .where(DownloadedFile.id == f.id)
                    .values(status="processing", error_detail=None)
                )
                await db.commit()

                # 下载文件
                resp = await client.get(f.download_url)
                resp.raise_for_status()

                # 确定保存路径（与 Scrapy 爬虫保持一致：DOWNLOAD_STORE/<task_id>/<safe_repo>/<file_path>）
                if f.local_path and Path(f.local_path).resolve().parent.exists():
                    save_path = Path(f.local_path)
                else:
                    safe_repo = (f.repo_name or "unknown").replace("/", "_")
                    task_dir = f.task_id or "manual"
                    repo_file_path = f.file_path or f.file_name
                    save_path = download_store / task_dir / safe_repo / repo_file_path

                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(resp.content)

                # 更新状态
                await db.execute(
                    update(DownloadedFile)
                    .where(DownloadedFile.id == f.id)
                    .values(
                        status="downloaded",
                        file_size=len(resp.content),
                        local_path=str(save_path),
                        error_detail=None,
                    )
                )
                await db.commit()

                file_result["status"] = "downloaded"
                success_count += 1

            except Exception as e:
                error_msg = str(e)[:500]
                try:
                    await db.execute(
                        update(DownloadedFile)
                        .where(DownloadedFile.id == f.id)
                        .values(status="failed", error_detail=error_msg)
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()

                file_result["status"] = "failed"
                file_result["error"] = error_msg
                fail_count += 1

            results.append(file_result)

    return ApiResponse(
        data={
            "total": len(files),
            "success_count": success_count,
            "fail_count": fail_count,
            "results": results,
        }
    )
