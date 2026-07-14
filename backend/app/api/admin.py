"""
后台管理 API 路由。

当前保留尚未按业务域迁移的看板、对话等后台接口。
"""

import os
import asyncio
import uuid
from pathlib import Path
from typing import Optional, List, Any, Dict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.core.logging import get_logger
from app.db import get_db

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["后台管理"])



# ========== 看板相关 ==========

class DashboardStats(BaseModel):
    """看板统计数据"""
    subject_count: int
    chapter_count: int
    knowledge_point_count: int
    question_count: int
    today_chat_count: int


@router.get("/dashboard/stats", response_model=ApiResponse)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """获取看板统计数据（408考研平台）"""
    from app.models.mysql_models import Subject, Chapter, KnowledgePoint, Question, ChatSession
    from sqlalchemy import func
    from datetime import datetime as _dt, time as _time

    subject_count = await db.scalar(
        select(func.count()).select_from(Subject).where(Subject.status == "active")
    ) or 0

    chapter_count = await db.scalar(
        select(func.count()).select_from(Chapter).where(Chapter.status == "active")
    ) or 0

    knowledge_point_count = await db.scalar(
        select(func.count()).select_from(KnowledgePoint).where(KnowledgePoint.status != "deleted")
    ) or 0

    question_count = await db.scalar(
        select(func.count()).select_from(Question).where(Question.status != "deleted")
    ) or 0

    today_start = _dt.combine(_dt.utcnow().date(), _time.min)
    today_chat_count = await db.scalar(
        select(func.count()).select_from(ChatSession).where(ChatSession.created_at >= today_start)
    ) or 0

    return ApiResponse(
        code=200,
        message="success",
        data={
            "subject_count": subject_count,
            "chapter_count": chapter_count,
            "knowledge_point_count": knowledge_point_count,
            "question_count": question_count,
            "today_chat_count": today_chat_count,
        }
    )


@router.get("/dashboard/charts", response_model=ApiResponse)
async def get_dashboard_charts(db: AsyncSession = Depends(get_db)):
    """获取看板图表数据（408考研平台）"""
    from app.models.mysql_models import Subject, KnowledgePoint, Question
    from sqlalchemy import func

    # 各学科知识点分布
    subject_rows = await db.execute(
        select(Subject.name, func.count(KnowledgePoint.id))
        .outerjoin(KnowledgePoint, Subject.id == KnowledgePoint.subject_id)
        .where(Subject.status == "active")
        .group_by(Subject.id, Subject.name)
        .order_by(Subject.sort_order)
    )
    subject_distribution = [
        {"name": row[0], "value": row[1] or 0}
        for row in subject_rows
    ]

    # 知识点难度分布
    difficulty_rows = await db.execute(
        select(KnowledgePoint.difficulty, func.count())
        .where(KnowledgePoint.status != "deleted")
        .group_by(KnowledgePoint.difficulty)
    )
    difficulty_name_map = {"easy": "简单", "medium": "中等", "hard": "困难"}
    difficulty_distribution = [
        {"name": difficulty_name_map.get(d, d), "value": c}
        for d, c in difficulty_rows
    ]

    # 题目类型分布
    type_rows = await db.execute(
        select(Question.type, func.count())
        .where(Question.status != "deleted")
        .group_by(Question.type)
    )
    type_name_map = {
        "choice": "选择题",
        "fill": "填空题",
        "judge": "判断题",
        "short_answer": "简答题",
        "design": "设计题",
        "analysis": "分析题"
    }
    question_type_distribution = [
        {"name": type_name_map.get(t, t), "value": c}
        for t, c in type_rows
    ]

    return ApiResponse(
        code=200,
        message="success",
        data={
            "subject_distribution": subject_distribution,
            "difficulty_distribution": difficulty_distribution,
            "question_type_distribution": question_type_distribution
        }
    )


# ========== PDF入库 ==========

class IngestPdfRequest(BaseModel):
    """PDF入库请求"""
    pdf_path: str = Field(..., description="PDF文件路径")
    subject_id: str = Field(..., description="学科ID")
    chapter_id: str = Field(..., description="章节ID")
    source: Optional[str] = Field(default=None, description="来源说明，如 王道2025/数据结构")


@router.post("/knowledge/ingest", response_model=ApiResponse)
async def ingest_pdf(
    req: IngestPdfRequest,
    db: AsyncSession = Depends(get_db)
):
    """触发PDF入库任务"""
    import uuid
    from app.models.mysql_models import CrawlTask, Subject, Chapter

    # Validate subject exists
    subject = await db.scalar(
        select(Subject).where(Subject.id == req.subject_id)
    )
    if not subject:
        raise HTTPException(status_code=404, detail="学科不存在")

    # Validate chapter exists
    chapter = await db.scalar(
        select(Chapter).where(Chapter.id == req.chapter_id, Chapter.subject_id == req.subject_id)
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在或不属于该学科")

    # Create crawl task
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

    # Publish to Scrapy queue
    from app.modules.crawler.scrapy_bridge import ScrapyBridgeService
    bridge = ScrapyBridgeService(db)
    published = await bridge.publish_task(task)
    await bridge.close()

    if not published:
        raise HTTPException(status_code=500, detail="任务发布失败")

    return ApiResponse(
        message="PDF入库任务已创建",
        data={"task_id": task_id}
    )


@router.get("/knowledge/ingest/tasks", response_model=ApiResponse)
async def get_ingest_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """获取PDF入库任务列表"""
    from app.models.mysql_models import CrawlTask

    query = select(CrawlTask).where(
        CrawlTask.source == "pdf"
    ).order_by(CrawlTask.created_at.desc())

    total = await db.scalar(
        select(func.count()).select_from(query.subquery())
    )

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tasks = result.scalars().all()

    return ApiResponse(data={
        "items": [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "progress": float(t.progress) if t.progress else 0,
                "success_count": t.success_count,
                "failed_count": t.failed_count,
                "config": t.config,
                "error_message": t.error_message,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    })


# ========== 已下载文件 ==========

DOWNLOAD_STORE = os.getenv("DOWNLOAD_STORE", str(Path(__file__).parent.parent.parent / "downloads"))


@router.get("/files/downloaded", response_model=ApiResponse)
async def get_downloaded_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    file_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """获取已下载文件列表"""
    from app.models.mysql_models import DownloadedFile

    query = select(DownloadedFile)

    if file_type:
        query = query.where(DownloadedFile.file_type == file_type)
    if status:
        query = query.where(DownloadedFile.status == status)
    if task_id:
        query = query.where(DownloadedFile.task_id == task_id)
    if keyword:
        like_pattern = f"%{keyword}%"
        query = query.where(
            (DownloadedFile.file_name.like(like_pattern)) |
            (DownloadedFile.repo_name.like(like_pattern))
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = query.order_by(DownloadedFile.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    files = result.scalars().all()

    return ApiResponse(data={
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
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in files
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/files/downloaded/{file_id}", response_model=ApiResponse)
async def get_downloaded_file_detail(
    file_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取已下载文件详情"""
    from app.models.mysql_models import DownloadedFile

    result = await db.execute(
        select(DownloadedFile).where(DownloadedFile.id == file_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")

    return ApiResponse(data={
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
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
    })


@router.get("/files/downloaded/{file_id}/preview")
async def preview_downloaded_file(
    file_id: str,
    db: AsyncSession = Depends(get_db)
):
    """预览/下载已下载的文件"""
    from app.models.mysql_models import DownloadedFile

    result = await db.execute(
        select(DownloadedFile).where(DownloadedFile.id == file_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")

    if not f.local_path:
        raise HTTPException(status_code=404, detail="文件路径不存在")

    local_path = Path(f.local_path).resolve()
    download_store = Path(DOWNLOAD_STORE).resolve()

    # 路径安全校验：确保文件在下载目录内
    if not str(local_path).startswith(str(download_store)):
        raise HTTPException(status_code=403, detail="文件路径不允许访问")

    if not local_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在于磁盘")

    media_type = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "ppt": "application/vnd.ms-powerpoint",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }.get(f.file_type or "", "application/octet-stream")

    return FileResponse(
        path=str(local_path),
        media_type=media_type,
        filename=f.file_name,
    )


# ========== 标准章节管理 ==========


@router.post("/canonical-chapters/init", response_model=ApiResponse)
async def init_canonical_chapters(
    subject_id: str = Query(..., description="学科ID"),
    chapters: List[dict] = [],
    db: AsyncSession = Depends(get_db),
):
    """初始化学科的标准章节体系"""
    from app.modules.catalog.canonical_chapter_service import CanonicalChapterService

    service = CanonicalChapterService(db)
    try:
        result = await service.init_chapters(subject_id, chapters)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(data=result)


@router.get("/canonical-chapters", response_model=ApiResponse)
async def get_canonical_chapters(
    subject_id: str = Query(..., description="学科ID"),
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
):
    """获取学科的标准章节"""
    from app.modules.catalog.canonical_chapter_service import CanonicalChapterService

    service = CanonicalChapterService(db)
    if tree:
        result = await service.get_chapters(subject_id)
    else:
        result = await service.get_chapters_flat(subject_id)

    return ApiResponse(data=result)


# ========== 审核相关 ==========


@router.get("/review/sections", response_model=ApiResponse, deprecated=True)
async def list_pending_section_mappings(
    subject_id: Optional[str] = None,
    review_status: Optional[str] = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核的 section 映射列表。已废弃，仅保留回滚兼容。"""
    from app.models.mysql_models import DocumentSectionMapping, DocumentSection, Document, CanonicalChapter
    from sqlalchemy import and_

    query = (
        select(DocumentSectionMapping, DocumentSection, CanonicalChapter)
        .join(DocumentSection, DocumentSectionMapping.document_section_id == DocumentSection.id)
        .join(Document, DocumentSection.document_id == Document.id)
        .join(CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id)
    )
    count_query = select(func.count()).select_from(DocumentSectionMapping)

    conditions = []
    if review_status:
        conditions.append(DocumentSectionMapping.review_status == review_status)
    if subject_id:
        conditions.append(
            or_(
                Document.subject_id == subject_id,
                CanonicalChapter.subject_id == subject_id,
            )
        )

    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.join(
            DocumentSection, DocumentSectionMapping.document_section_id == DocumentSection.id
        ).join(
            Document, DocumentSection.document_id == Document.id
        ).join(
            CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id
        ).where(and_(*conditions))

    total = await db.scalar(count_query) or 0
    query = query.order_by(DocumentSectionMapping.created_at.desc(), DocumentSectionMapping.id.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    items = [
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
            "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
        }
        for mapping, section, chapter in rows
    ]

    return ApiResponse(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.post("/review/sections/{mapping_id}", response_model=ApiResponse, deprecated=True)
async def review_section_mapping(
    mapping_id: str,
    review_status: str = Query(..., description="审核状态: approved/rejected"),
    canonical_chapter_id: Optional[str] = None,
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核 section 映射。已废弃，仅保留回滚兼容。"""
    from app.modules.catalog.chapter_mapping_service import ChapterMappingService

    service = ChapterMappingService(db)
    try:
        result = await service.review_mapping(
            mapping_id=mapping_id,
            review_status=review_status,
            canonical_chapter_id=canonical_chapter_id,
            review_notes=review_notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ApiResponse(data=result)


@router.delete("/review/sections/{mapping_id}", response_model=ApiResponse, deprecated=True)
async def delete_section_mapping(
    mapping_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个 section 映射。已废弃，仅保留回滚兼容。"""
    from app.models.mysql_models import DocumentSectionMapping

    mapping = await db.get(DocumentSectionMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="映射不存在")

    await db.delete(mapping)
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": mapping_id})


@router.post("/review/sections/batch-delete", response_model=ApiResponse, deprecated=True)
async def batch_delete_section_mappings(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除 section 映射。已废弃，仅保留回滚兼容。"""
    from app.models.mysql_models import DocumentSectionMapping

    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(DocumentSectionMapping.id).where(DocumentSectionMapping.id.in_(unique_ids))
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的映射")

    await db.execute(
        delete(DocumentSectionMapping).where(DocumentSectionMapping.id.in_(existing_ids))
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={"deleted_count": len(existing_ids), "requested_count": len(unique_ids)}
    )


@router.get("/review/relations", response_model=ApiResponse)
async def list_relations_for_review(
    relation_type: Optional[str] = None,
    review_status: Optional[str] = "pending",
    subject_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核的关系列表"""
    from app.modules.content.review_service import ReviewService

    service = ReviewService(db)
    result = await service.get_relations_for_review(
        relation_type=relation_type,
        review_status=review_status,
        subject_id=subject_id,
        page=page,
        page_size=page_size,
    )

    return ApiResponse(data=result)


@router.post("/review/relations/{relation_id}", response_model=ApiResponse)
async def review_relation(
    relation_id: str,
    review_status: str = Query(..., description="审核状态: approved/rejected"),
    relation_type: Optional[str] = None,
    directionality: Optional[str] = None,
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核关系"""
    from app.modules.content.review_service import ReviewService

    service = ReviewService(db)
    try:
        result = await service.review_relation(
            relation_id=relation_id,
            review_status=review_status,
            relation_type=relation_type,
            directionality=directionality,
            review_notes=review_notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ApiResponse(data=result)


@router.delete("/review/relations/{relation_id}", response_model=ApiResponse)
async def delete_review_relation(
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个知识点关系"""
    from app.models.mysql_models import KnowledgeRelation

    relation = await db.get(KnowledgeRelation, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="关系不存在")

    await db.delete(relation)
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": relation_id})


@router.post("/review/relations/batch-delete", response_model=ApiResponse)
async def batch_delete_review_relations(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除知识点关系"""
    from app.models.mysql_models import KnowledgeRelation

    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(KnowledgeRelation.id).where(KnowledgeRelation.id.in_(unique_ids))
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的关系")

    await db.execute(
        delete(KnowledgeRelation).where(KnowledgeRelation.id.in_(existing_ids))
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={"deleted_count": len(existing_ids), "requested_count": len(unique_ids)}
    )


@router.get("/review/stats", response_model=ApiResponse)
async def get_review_stats(
    subject_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取审核统计"""
    from app.modules.content.review_service import ReviewService

    service = ReviewService(db)
    result = await service.get_review_stats(subject_id)

    return ApiResponse(data=result)


# ========== 关系构建 ==========


@router.post("/relations/build", response_model=ApiResponse)
async def build_knowledge_relations(
    subject_id: Optional[str] = None,
    knowledge_point_ids: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db),
):
    """构建知识点关系（规则 + 语义相似度边）。"""
    from app.modules.retrieval.relation_service import RelationService

    service = RelationService(db)
    try:
        result = await service.build_relations(
            subject_id=subject_id, knowledge_point_ids=knowledge_point_ids
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"关系构建失败: {str(e)[:200]}")
    return ApiResponse(data=result)


# ========== 考点关系管理 ==========


@router.post("/chapter-relations/build", response_model=ApiResponse)
async def build_chapter_relations(
    subject_id: Optional[str] = None,
    outline_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    构建考点间直接关系（从 cross_references + embedding 相似度）

    1. 读取 CanonicalChapter.cross_references（LLM 标注的跨章关联）
    2. 双向写入 ChapterRelation（source_type="llm"）
    3. 对无 cross_references 的考点，用 embedding 相似度兜底（source_type="embedding"）
    """
    from app.modules.retrieval.outline_service import (
        validate_cross_references, fallback_chapter_similarity,
    )
    from app.models.mysql_models import CanonicalChapter, ChapterRelation

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
    chapter_map = {ch.id: ch for ch in chapters}
    relation_keys = {
        (row[0], row[1], row[2])
        for row in (await db.execute(
            select(
                ChapterRelation.source_chapter_id,
                ChapterRelation.target_chapter_id,
                ChapterRelation.relation_type,
            )
        )).all()
    }

    for chapter in chapters:
        cross_refs = getattr(chapter, "cross_references", None)

        # Layer 1: 从 LLM cross_references 创建关系
        if cross_refs:
            valid_refs = await validate_cross_references(db, cross_refs)
            for ref in valid_refs:
                target_id = ref["target_chapter_id"]
                if target_id not in chapter_map:
                    continue
                # 双向各写一条（source → target 和 target → source）
                for src, tgt in [(chapter.id, target_id), (target_id, chapter.id)]:
                    relation_type = ref.get("relation_type", "similar_to")
                    relation_key = (src, tgt, relation_type)
                    if src == tgt or relation_key in relation_keys:
                        continue
                    relation_keys.add(relation_key)
                    db.add(ChapterRelation(
                        id=_gen_chrel_id(),
                        source_chapter_id=src,
                        target_chapter_id=tgt,
                        relation_type=relation_type,
                        confidence=0.9,
                        source_type="llm",
                        evidence_text=ref.get("reason"),
                        review_status="pending",
                    ))
                    llm_created += 1
                    created += 1

        # Layer 2: 无 cross_references 的考点用 embedding 相似度兜底
        if not cross_refs:
            sims = await fallback_chapter_similarity(db, chapter.id, top_k=3)
            for target_id, score in sims:
                if target_id not in chapter_map:
                    continue
                relation_key = (chapter.id, target_id, "similar_to")
                if chapter.id == target_id or relation_key in relation_keys:
                    continue
                relation_keys.add(relation_key)
                db.add(ChapterRelation(
                    id=_gen_chrel_id(),
                    source_chapter_id=chapter.id,
                    target_chapter_id=target_id,
                    relation_type="similar_to",
                    confidence=round(score, 4),
                    source_type="embedding",
                    evidence_text=f"语义相似度 {score:.4f}",
                    review_status="pending",
                ))
                embedding_created += 1
                created += 1

    await db.commit()

    return ApiResponse(data={
        "created": created,
        "llm_created": llm_created,
        "embedding_created": embedding_created,
        "chapters_processed": len(chapters),
    })


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
    """查询考点关系列表（用于审核面板）"""
    from app.models.mysql_models import ChapterRelation, CanonicalChapter

    query = (
        select(
            ChapterRelation,
            CanonicalChapter.name.label("source_name"),
            CanonicalChapter.name.label("target_name"),
        )
        .join(CanonicalChapter, ChapterRelation.source_chapter_id == CanonicalChapter.id)
    )
    # 注意：上面的 join 只拿到了 source_name，需要额外查 target
    conditions = []
    if source_chapter_id:
        conditions.append(ChapterRelation.source_chapter_id == source_chapter_id)
    if target_chapter_id:
        conditions.append(ChapterRelation.target_chapter_id == target_chapter_id)
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

    query = query.order_by(ChapterRelation.created_at.desc(), ChapterRelation.id.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).all()

    items = []
    for row in rows:
        rel, source_name, _ = row
        # 获取 target chapter name
        target_ch = await db.get(CanonicalChapter, rel.target_chapter_id)
        items.append({
            "id": rel.id,
            "source_chapter_id": rel.source_chapter_id,
            "source_chapter_name": source_name,
            "target_chapter_id": rel.target_chapter_id,
            "target_chapter_name": target_ch.name if target_ch else "",
            "relation_type": rel.relation_type,
            "confidence": float(rel.confidence) if rel.confidence else None,
            "source_type": rel.source_type,
            "evidence_text": rel.evidence_text,
            "review_status": rel.review_status,
            "review_notes": rel.review_notes,
            "created_at": rel.created_at.isoformat() if rel.created_at else None,
        })

    return ApiResponse(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.post("/chapter-relations/{relation_id}/review", response_model=ApiResponse)
async def review_chapter_relation(
    relation_id: str,
    review_status: str = Query(..., description="approved / rejected"),
    review_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """审核考点关系"""
    from app.models.mysql_models import ChapterRelation

    rel = await db.get(ChapterRelation, relation_id)
    if not rel:
        raise HTTPException(status_code=404, detail="关系不存在")

    rel.review_status = review_status
    if review_notes:
        rel.review_notes = review_notes
    rel.reviewed_at = datetime.utcnow()
    await db.commit()

    return ApiResponse(data={"id": relation_id, "review_status": review_status})


@router.delete("/chapter-relations/{relation_id}", response_model=ApiResponse)
async def delete_chapter_relation(
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个考点关系"""
    from app.models.mysql_models import ChapterRelation

    relation = await db.get(ChapterRelation, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="关系不存在")

    await db.delete(relation)
    await db.commit()

    return ApiResponse(message="删除成功", data={"id": relation_id})


@router.post("/chapter-relations/batch-delete", response_model=ApiResponse)
async def batch_delete_chapter_relations(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除考点关系"""
    from app.models.mysql_models import ChapterRelation

    unique_ids = list(dict.fromkeys(req.ids))
    result = await db.execute(
        select(ChapterRelation.id).where(ChapterRelation.id.in_(unique_ids))
    )
    existing_ids = [row[0] for row in result.all()]
    if not existing_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的关系")

    await db.execute(
        delete(ChapterRelation).where(ChapterRelation.id.in_(existing_ids))
    )
    await db.commit()

    return ApiResponse(
        message="删除成功",
        data={"deleted_count": len(existing_ids), "requested_count": len(unique_ids)}
    )


def _gen_chrel_id() -> str:
    import uuid
    return uuid.uuid4().hex[:32]



# ===== 大纲（考试章节体系）独立入库 =====


class OutlinePreviewRequest(BaseModel):
    content: str = Field(..., max_length=2_000_000)
    filename: Optional[str] = ""


class OutlineImportRequest(BaseModel):
    subject_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    year: int = Field(..., ge=2000, le=2100)
    content: str = Field(..., max_length=2_000_000)
    filename: Optional[str] = ""
    version: Optional[str] = "v1.0"
    description: Optional[str] = None
    set_default: bool = False


class OutlineFromDocumentRequest(BaseModel):
    subject_id: str
    document_id: str
    name: str
    year: int = Field(..., ge=2000, le=2100)
    version: Optional[str] = "v1.0"
    set_default: bool = False


class OutlineFromLLMRequest(BaseModel):
    """携带 LLM 拆分结果整体入库（四门课一次入）。"""
    name: str = Field(..., min_length=1, max_length=200)
    year: int = Field(..., ge=2000, le=2100)
    version: Optional[str] = "v1.0"
    description: Optional[str] = None
    set_default: bool = False
    subjects: List[Dict[str, Any]] = Field(..., min_length=1)


@router.get("/outlines", response_model=ApiResponse)
async def list_outlines_endpoint(db: AsyncSession = Depends(get_db)):
    """列出所有大纲"""
    from app.modules.catalog.outline_import_service import list_outlines
    return ApiResponse(data=await list_outlines(db))


@router.get("/outlines/{outline_id}/chapters", response_model=ApiResponse)
async def get_outline_chapters_endpoint(
    outline_id: str,
    subject_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取大纲下章节树（含原文考点 description + 复习指导 exam_guidance，可按 subject_id 过滤）"""
    from app.modules.catalog.outline_import_service import get_outline_chapters
    return ApiResponse(data=await get_outline_chapters(db, outline_id, subject_id=subject_id))


@router.get("/outlines/{outline_id}/subjects", response_model=ApiResponse)
async def get_outline_subjects_endpoint(outline_id: str, db: AsyncSession = Depends(get_db)):
    """获取大纲下各门课的考察目标 + 复习指导生成状态"""
    from app.modules.catalog.outline_import_service import get_outline_subjects
    return ApiResponse(data=await get_outline_subjects(db, outline_id))


@router.post("/outlines/preview", response_model=ApiResponse)
async def preview_outline_import(request: OutlinePreviewRequest, db: AsyncSession = Depends(get_db)):
    """解析大纲文本但不入库（用于前端预览）"""
    from app.modules.catalog.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.preview(content=request.content, filename=request.filename or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/outlines/import", response_model=ApiResponse)
async def import_outline_endpoint(request: OutlineImportRequest, db: AsyncSession = Depends(get_db)):
    """导入大纲（创建 exam_outlines + canonical_chapters 树）"""
    from app.modules.catalog.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.import_outline(
            subject_id=request.subject_id,
            name=request.name,
            year=request.year,
            content=request.content,
            filename=request.filename or "",
            version=request.version or "v1.0",
            description=request.description,
            set_default=request.set_default,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/outlines/import-from-document", response_model=ApiResponse)
async def import_outline_from_document(
    request: OutlineFromDocumentRequest,
    db: AsyncSession = Depends(get_db),
):
    """从已解析文档的 document_sections 转换为大纲"""
    from app.modules.catalog.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.import_from_document_sections(
            subject_id=request.subject_id,
            document_id=request.document_id,
            outline_name=request.name,
            year=request.year,
            version=request.version or "v1.0",
            set_default=request.set_default,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/outlines/document/{document_id}/preview", response_model=ApiResponse)
async def preview_outline_from_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """预览某文档标题树转成的大纲章节树（不入库）。"""
    from app.modules.catalog.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.preview_from_document_sections(document_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/outlines/import-from-llm", response_model=ApiResponse)
async def import_outline_from_llm(request: OutlineFromLLMRequest, db: AsyncSession = Depends(get_db)):
    """
    把 LLM 拆分出的四门课结果整体入库（含考察目标 + 多层章节树 + 原文考点）。

    改进：支持部分成功，如果某些科目失败但其他成功，仍然入库成功的部分。
    返回 partial=true 标识部分成功。
    """
    from app.modules.catalog.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        result = await service.import_from_llm_result(
            llm_result={"subjects": request.subjects},
            name=request.name,
            year=request.year,
            version=request.version or "v1.0",
            description=request.description,
            set_default=request.set_default,
        )
        # 如果是部分成功，返回 200 但带 warning 标识
        if result.get("partial"):
            return ApiResponse(
                data=result,
                message=f"部分成功：{result['successful_subjects']}/{result['total_subjects']} 个科目入库成功"
            )
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/outlines/{outline_id}", response_model=ApiResponse)
async def delete_outline(outline_id: str, db: AsyncSession = Depends(get_db)):
    """
    删除大纲及其所有关联数据

    删除内容:
    - ExamOutline 记录
    - ExamOutlineSubject 关联
    - CanonicalChapter 所有章节（级联删除会自动清理关联表）
    """
    from app.models.mysql_models import ExamOutline, ExamOutlineSubject, CanonicalChapter

    outline = await db.get(ExamOutline, outline_id)
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")

    # 统计删除数量
    chapters_count = await db.scalar(
        select(func.count()).select_from(CanonicalChapter).where(
            CanonicalChapter.outline_id == outline_id
        )
    )

    # 删除章节（级联删除会自动清理 chapter links 等）
    await db.execute(
        delete(CanonicalChapter).where(CanonicalChapter.outline_id == outline_id)
    )

    # 删除科目关联
    await db.execute(
        delete(ExamOutlineSubject).where(ExamOutlineSubject.outline_id == outline_id)
    )

    # 删除大纲
    await db.delete(outline)
    await db.commit()

    return ApiResponse(data={
        "outline_id": outline_id,
        "outline_name": outline.name,
        "deleted_chapters": chapters_count,
        "message": "大纲已删除"
    })


@router.post(
    "/outlines/{outline_id}/subjects/{subject_id}/generate-guidance",
    response_model=ApiResponse,
)
async def generate_outline_guidance(
    outline_id: str, subject_id: str, db: AsyncSession = Depends(get_db)
):
    """为某门课的所有章节批量生成复习指导（结合考察目标，写回 exam_guidance）。"""
    from app.modules.catalog.outline_import_service import OutlineImportService
    service = OutlineImportService(db)
    try:
        return ApiResponse(data=await service.generate_guidance_for_subject(outline_id, subject_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/outlines/upload-parse", response_model=ApiResponse)
async def upload_parse_outline(
    file: UploadFile = File(...),
    parser_name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    上传大纲 PDF 并异步执行「注册 → 解析 → LLM 拆分」，立即返回 run_id。

    前端轮询 GET /outlines/runs/{run_id} 获取进度，完成后再调 /outlines/import-from-llm 入库。
    """
    from app.modules.corpus.file_service import (
        CorpusFileService,
        SUPPORTED_EXTENSIONS,
    )
    from app.models.mysql_models import OutlineIngestionRun
    import asyncio

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，仅支持 {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    # 1) 保存文件
    upload_dir = Path(__file__).parent.parent.parent / "uploads"
    upload_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_path = upload_dir / f"{timestamp}_{file.filename}"
    file_path.write_bytes(await file.read())

    # 2) 注册文件
    corpus_service = CorpusFileService(db)
    reg = await corpus_service.register_single_file(
        file_path=str(file_path),
        batch_label=f"outline-{timestamp}",
    )
    corpus_file_id = reg["corpus_file_id"]

    # 3) 立即创建 OutlineIngestionRun（document_id 可空），让任务列表立即可见
    from app.modules.corpus.document_parse_service import generate_id
    run_id = generate_id()
    run = OutlineIngestionRun(
        id=run_id,
        document_id=None,  # 解析完成后由后台任务填充
        outline_name=file.filename,
        status="processing",
        current_stage="parsing",
        stage_detail=f"文件已上传：{file.filename}",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    await db.commit()

    # 4) 后台异步执行解析 + LLM 拆分
    async def _run_outline_parse_in_background(
        run_id: str, corpus_file_id: str, parser_name: Optional[str], is_new: bool, file_name: str
    ):
        from app.db.mysql import mysql_client
        from app.modules.corpus.document_parse_service import DocumentParseService
        from app.modules.catalog.outline_llm_service import OutlineLLMService
        from app.models.mysql_models import DocumentBlock

        async with mysql_client.session() as bg_session:
            try:
                bg_run = await bg_session.get(OutlineIngestionRun, run_id)
                if not bg_run:
                    logger.error("OutlineIngestionRun 不存在", run_id=run_id)
                    return

                # 解析阶段
                bg_run.current_stage = "parsing"
                bg_run.stage_detail = "正在解析 PDF..."
                await bg_session.commit()

                document_id: Optional[str] = None
                parse_service = DocumentParseService(bg_session)

                # 复用既有文档（如果已解析）
                if not is_new:
                    existing_doc = await parse_service._get_document_by_corpus_file_id(corpus_file_id)
                    if existing_doc:
                        block_count = (await bg_session.execute(
                            select(func.count()).select_from(DocumentBlock)
                            .where(DocumentBlock.document_id == existing_doc.id)
                        )).scalar_one()
                        if block_count > 0:
                            document_id = existing_doc.id

                if document_id is None:
                    parse_result = await parse_service.parse_document(corpus_file_id, parser_name=parser_name)
                    document_id = parse_result["document_id"]

                # 更新 run：解析完成，进入拆分
                bg_run.document_id = document_id
                bg_run.current_stage = "splitting"
                bg_run.stage_detail = "正在用 LLM 拆分大纲..."
                await bg_session.commit()

                # LLM 拆分阶段
                llm_service = OutlineLLMService(bg_session)
                split = await llm_service.split_outline_with_progress(run_id, document_id)

                # 完成
                bg_run.status = "done"
                bg_run.current_stage = "completed"
                bg_run.stage_detail = f"拆分完成，共 {len(split['subjects'])} 个科目"
                bg_run.total_subjects = len(split["subjects"])
                bg_run.processed_subjects = len(split["subjects"])
                bg_run.successful_subjects = len([s for s in split["subjects"] if not s.get("error")])
                # 把 file_name 存进 result_summary 方便列表展示
                split_with_meta = {**split, "file_name": file_name}
                bg_run.result_summary = split_with_meta
                bg_run.completed_at = datetime.utcnow()
                await bg_session.commit()

                logger.info("大纲解析+拆分完成", run_id=run_id, document_id=document_id)

            except Exception as e:
                logger.error("大纲后台任务失败", run_id=run_id, error=str(e))
                bg_run = await bg_session.get(OutlineIngestionRun, run_id)
                if bg_run:
                    bg_run.status = "failed"
                    bg_run.current_stage = "failed"
                    bg_run.error_detail = str(e)[:500]
                    bg_run.stage_detail = f"失败：{str(e)[:100]}"
                    bg_run.completed_at = datetime.utcnow()
                    await bg_session.commit()

    asyncio.ensure_future(_run_outline_parse_in_background(
        run_id, corpus_file_id, parser_name, reg["is_new"], file.filename
    ))

    return ApiResponse(message="大纲解析任务已启动", data={
        "run_id": run_id,
        "corpus_file_id": corpus_file_id,
        "file_name": file.filename,
        "status": "processing",
    })


@router.get("/outlines/runs/{run_id}", response_model=ApiResponse)
async def get_outline_run_detail(run_id: str, db: AsyncSession = Depends(get_db)):
    """获取大纲入库任务详情（用于进度轮询）"""
    from app.models.mysql_models import OutlineIngestionRun

    run = await db.get(OutlineIngestionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")

    progress = 0
    if run.total_subjects > 0:
        progress = round((run.processed_subjects / run.total_subjects) * 100, 1)

    return ApiResponse(data={
        "id": run.id,
        "document_id": run.document_id,
        "outline_id": run.outline_id,
        "outline_name": run.outline_name,
        "year": run.year,
        "version": run.version,
        "status": run.status,
        "current_stage": run.current_stage,
        "stage_detail": run.stage_detail,
        "progress": progress,
        "total_subjects": run.total_subjects,
        "processed_subjects": run.processed_subjects,
        "successful_subjects": run.successful_subjects,
        "current_subject_name": run.current_subject_name,
        "created_chapters": run.created_chapters,
        "updated_chapters": run.updated_chapters,
        "error_detail": run.error_detail,
        "result_summary": run.result_summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    })


@router.get("/outlines/runs", response_model=ApiResponse)
async def list_outline_runs(
    document_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """列出大纲入库任务（支持按 document_id 和 status 过滤）"""
    from app.models.mysql_models import OutlineIngestionRun

    query = select(OutlineIngestionRun).order_by(OutlineIngestionRun.created_at.desc()).limit(limit)
    if document_id:
        query = query.where(OutlineIngestionRun.document_id == document_id)
    if status:
        query = query.where(OutlineIngestionRun.status == status)

    runs = (await db.execute(query)).scalars().all()

    return ApiResponse(data={
        "items": [
            {
                "id": r.id,
                "document_id": r.document_id,
                "outline_id": r.outline_id,
                "outline_name": r.outline_name,
                "file_name": (r.result_summary or {}).get("file_name") if isinstance(r.result_summary, dict) else None,
                "status": r.status,
                "current_stage": r.current_stage,
                "stage_detail": r.stage_detail,
                "progress": round((r.processed_subjects / r.total_subjects * 100), 1) if r.total_subjects > 0 else 0,
                "total_subjects": r.total_subjects,
                "processed_subjects": r.processed_subjects,
                "successful_subjects": r.successful_subjects,
                "current_subject_name": r.current_subject_name,
                "created_chapters": r.created_chapters,
                "updated_chapters": r.updated_chapters,
                "error_detail": r.error_detail,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ]
    })


@router.delete("/outlines/runs/{run_id}", response_model=ApiResponse)
async def delete_outline_run(run_id: str, db: AsyncSession = Depends(get_db)):
    """删除大纲入库任务记录（不影响已入库的大纲数据）"""
    from app.models.mysql_models import OutlineIngestionRun

    run = await db.get(OutlineIngestionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")

    await db.delete(run)
    await db.commit()
    return ApiResponse(message="任务记录已删除", data={"run_id": run_id})


@router.post("/outlines/runs/batch-delete", response_model=ApiResponse)
async def batch_delete_outline_runs(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除大纲入库任务记录"""
    from app.models.mysql_models import OutlineIngestionRun

    if not req.ids:
        return ApiResponse(data={"deleted_count": 0, "requested_count": 0})

    result = await db.execute(
        select(OutlineIngestionRun).where(OutlineIngestionRun.id.in_(req.ids))
    )
    runs = result.scalars().all()
    for run in runs:
        await db.delete(run)
    await db.commit()

    return ApiResponse(
        message="批量删除成功",
        data={
            "deleted_count": len(runs),
            "requested_count": len(set(req.ids)),
        },
    )



# ===== 资产托管 =====

@router.get("/assets/{asset_id}/file")
async def serve_asset_file(asset_id: str, db: AsyncSession = Depends(get_db)):
    """根据 asset_id 返回资产文件（图片）"""
    from fastapi.responses import FileResponse
    from app.models.mysql_models import DocumentAsset

    asset = await db.get(DocumentAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    if not asset.file_path:
        raise HTTPException(status_code=404, detail="该资产无文件（可能是公式或表格 HTML）")

    file_path = Path(asset.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {asset.file_path}")
    return FileResponse(path=str(file_path))


@router.get("/assets/{asset_id}", response_model=ApiResponse)
async def get_asset_metadata(asset_id: str, db: AsyncSession = Depends(get_db)):
    """获取资产元数据（不含二进制文件）"""
    from app.models.mysql_models import DocumentAsset

    asset = await db.get(DocumentAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    return ApiResponse(data={
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
        "file_url": f"/api/v1/admin/assets/{asset.id}/file" if asset.file_path else None,
    })


# ===== 章节关联 =====

@router.post("/knowledge/{kp_id}/link-chapters", response_model=ApiResponse)
async def link_knowledge_point_to_chapters(kp_id: str, db: AsyncSession = Depends(get_db)):
    """手动触发知识点关联大纲章节"""
    from app.modules.catalog.chapter_link_service import ChapterLinkService
    service = ChapterLinkService(db)
    try:
        result = await service.link_knowledge_point_to_chapters(kp_id)
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/questions/{question_id}/link-chapters", response_model=ApiResponse)
async def link_question_to_chapters(question_id: str, db: AsyncSession = Depends(get_db)):
    """手动触发题目关联大纲章节"""
    from app.modules.catalog.chapter_link_service import ChapterLinkService
    service = ChapterLinkService(db)
    try:
        result = await service.link_question_to_chapters(question_id)
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{document_id}/link-chapters", response_model=ApiResponse)
async def batch_link_document_chapters(document_id: str, db: AsyncSession = Depends(get_db)):
    """批量关联文档下所有已审核实体到大纲章节"""
    from app.modules.catalog.chapter_link_service import ChapterLinkService
    service = ChapterLinkService(db)
    try:
        result = await service.batch_link_document(document_id)
        return ApiResponse(data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chapters/{chapter_id}/entities", response_model=ApiResponse)
async def get_chapter_entities(
    chapter_id: str,
    entity_type: Optional[str] = Query(None, description="实体类型: knowledge_point / question"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """获取某章节下的知识点和题目"""
    from app.models.mysql_models import (
        KnowledgePointChapterLink, QuestionChapterLink,
        KnowledgePoint, Question
    )

    result = {"knowledge_points": [], "questions": []}

    # 查询知识点
    if not entity_type or entity_type == "knowledge_point":
        kp_links = (await db.execute(
            select(KnowledgePointChapterLink, KnowledgePoint)
            .join(KnowledgePoint, KnowledgePoint.id == KnowledgePointChapterLink.knowledge_point_id)
            .where(
                KnowledgePointChapterLink.canonical_chapter_id == chapter_id,
                KnowledgePoint.status == "active"
            )
            .order_by(KnowledgePointChapterLink.relevance.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )).all()

        result["knowledge_points"] = [
            {
                "id": kp.id,
                "title": kp.title,
                "content": kp.content[:200] if kp.content else None,
                "relevance": float(link.relevance),
                "source": link.source,
                "is_primary": link.is_primary,
            }
            for link, kp in kp_links
        ]

    # 查询题目
    if not entity_type or entity_type == "question":
        q_links = (await db.execute(
            select(QuestionChapterLink, Question)
            .join(Question, Question.id == QuestionChapterLink.question_id)
            .where(
                QuestionChapterLink.canonical_chapter_id == chapter_id,
                Question.status == "active"
            )
            .order_by(QuestionChapterLink.relevance.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )).all()

        result["questions"] = [
            {
                "id": q.id,
                "content": q.content[:200] if q.content else None,
                "type": q.type,
                "exam_year": q.exam_year,
                "relevance": float(link.relevance),
                "source": link.source,
                "is_primary": link.is_primary,
            }
            for link, q in q_links
        ]

    return ApiResponse(data=result)
