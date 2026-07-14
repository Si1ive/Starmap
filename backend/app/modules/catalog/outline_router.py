"""考试大纲导入、解析任务与章节树管理路由。"""

import asyncio
from pathlib import Path
from typing import Optional, List, Any, Dict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.core.config import settings
from app.core.logging import get_logger
from app.db import get_db

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["考试大纲"])


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
    from app.modules.catalog.outline_query_service import list_outlines
    return ApiResponse(data=await list_outlines(db))


@router.get("/outlines/{outline_id}/chapters", response_model=ApiResponse)
async def get_outline_chapters_endpoint(
    outline_id: str,
    subject_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取大纲下章节树（含原文考点 description + 复习指导 exam_guidance，可按 subject_id 过滤）"""
    from app.modules.catalog.outline_query_service import get_outline_chapters
    return ApiResponse(data=await get_outline_chapters(db, outline_id, subject_id=subject_id))


@router.get("/outlines/{outline_id}/subjects", response_model=ApiResponse)
async def get_outline_subjects_endpoint(outline_id: str, db: AsyncSession = Depends(get_db)):
    """获取大纲下各门课的考察目标 + 复习指导生成状态"""
    from app.modules.catalog.outline_query_service import get_outline_subjects
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
    from app.modules.catalog.outline_guidance_service import OutlineGuidanceService
    service = OutlineGuidanceService(db)
    try:
        return ApiResponse(data=await service.generate_for_subject(outline_id, subject_id))
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

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    file_name = Path(file.filename).name
    ext = Path(file_name).suffix.lstrip(".").lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，仅支持 {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    # 1) 保存文件
    upload_dir = Path(settings.CORPUS_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_path = upload_dir / f"{timestamp}_{file_name}"
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
        outline_name=file_name,
        status="processing",
        current_stage="parsing",
        stage_detail=f"文件已上传：{file_name}",
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
        run_id, corpus_file_id, parser_name, reg["is_new"], file_name
    ))

    return ApiResponse(message="大纲解析任务已启动", data={
        "run_id": run_id,
        "corpus_file_id": corpus_file_id,
        "file_name": file_name,
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
