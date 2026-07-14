"""旧版 PDF 知识入库任务兼容路由。"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import Chapter, CrawlTask, Subject
from app.modules.crawler.scrapy_bridge import ScrapyBridgeService

router = APIRouter(prefix="/admin", tags=["爬虫管理"])


class IngestPdfRequest(BaseModel):
    """旧版 PDF 入库请求。"""

    pdf_path: str = Field(..., description="PDF文件路径")
    subject_id: str = Field(..., description="学科ID")
    chapter_id: str = Field(..., description="章节ID")
    source: Optional[str] = Field(
        default=None,
        description="来源说明，如 王道2025/数据结构",
    )


@router.post("/knowledge/ingest", response_model=ApiResponse)
async def ingest_pdf(
    req: IngestPdfRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建并发布旧版 PDF 知识爬取任务。"""
    subject = await db.scalar(select(Subject).where(Subject.id == req.subject_id))
    if not subject:
        raise HTTPException(status_code=404, detail="学科不存在")

    chapter = await db.scalar(
        select(Chapter).where(
            Chapter.id == req.chapter_id,
            Chapter.subject_id == req.subject_id,
        )
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在或不属于该学科")

    task_id = f"kp_{uuid.uuid4().hex[:12]}"
    task = CrawlTask(
        id=task_id,
        name=f"PDF入库: {subject.name} - {chapter.name}",
        task_type="targeted",
        source="pdf",
        status="pending",
        config={
            "spider_type": "knowledge",
            "pdf_path": req.pdf_path,
            "subject_id": req.subject_id,
            "chapter_id": req.chapter_id,
            "source": req.source or f"{subject.name}/{chapter.name}",
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    bridge = ScrapyBridgeService(db)
    try:
        published = await bridge.publish_task(task)
    finally:
        await bridge.close()

    if not published:
        raise HTTPException(status_code=500, detail="任务发布失败")

    return ApiResponse(
        message="PDF入库任务已创建",
        data={"task_id": task_id},
    )


@router.get("/knowledge/ingest/tasks", response_model=ApiResponse)
async def get_ingest_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """分页查询旧版 PDF 入库任务。"""
    query = (
        select(CrawlTask)
        .where(CrawlTask.source == "pdf")
        .order_by(CrawlTask.created_at.desc())
    )
    total = (
        await db.scalar(select(func.count()).select_from(query.subquery()))
        or 0
    )
    tasks = (
        await db.execute(
            query.offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()

    return ApiResponse(
        data={
            "items": [
                {
                    "id": task.id,
                    "name": task.name,
                    "status": task.status,
                    "progress": float(task.progress) if task.progress else 0,
                    "success_count": task.success_count,
                    "failed_count": task.failed_count,
                    "config": task.config,
                    "error_message": task.error_message,
                    "created_at": (
                        task.created_at.isoformat() if task.created_at else None
                    ),
                    "completed_at": (
                        task.completed_at.isoformat()
                        if task.completed_at
                        else None
                    ),
                }
                for task in tasks
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )
