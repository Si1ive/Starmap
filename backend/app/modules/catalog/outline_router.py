"""考试大纲导入、解析任务与章节树管理路由。"""

from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.db import get_db

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
    from app.modules.catalog.outline_llm_import_service import (
        OutlineLLMImportService,
    )
    service = OutlineLLMImportService(db)
    try:
        result = await service.import_result(
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
    """删除大纲、科目关联和章节树。"""
    from app.modules.catalog.outline_maintenance_service import (
        OutlineMaintenanceService,
    )

    result = await OutlineMaintenanceService(db).delete_outline(outline_id)
    if not result:
        raise HTTPException(status_code=404, detail="大纲不存在")
    return ApiResponse(data=result)


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
    from app.modules.catalog.outline_parse_service import (
        OutlineParseTaskService,
    )
    try:
        data = await OutlineParseTaskService(db).start(
            file,
            parser_name=parser_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ApiResponse(message="大纲解析任务已启动", data=data)


@router.get("/outlines/runs/{run_id}", response_model=ApiResponse)
async def get_outline_run_detail(run_id: str, db: AsyncSession = Depends(get_db)):
    """获取大纲入库任务详情（用于进度轮询）"""
    from app.modules.catalog.outline_run_service import OutlineRunService

    data = await OutlineRunService(db).get_detail(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ApiResponse(data=data)


@router.get("/outlines/runs", response_model=ApiResponse)
async def list_outline_runs(
    document_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """列出大纲入库任务（支持按 document_id 和 status 过滤）"""
    from app.modules.catalog.outline_run_service import OutlineRunService

    return ApiResponse(
        data=await OutlineRunService(db).list_runs(
            document_id=document_id,
            status=status,
            limit=limit,
        )
    )


@router.delete("/outlines/runs/{run_id}", response_model=ApiResponse)
async def delete_outline_run(run_id: str, db: AsyncSession = Depends(get_db)):
    """删除大纲入库任务记录（不影响已入库的大纲数据）"""
    from app.modules.catalog.outline_run_service import OutlineRunService

    if not await OutlineRunService(db).delete_run(run_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return ApiResponse(message="任务记录已删除", data={"run_id": run_id})


@router.post("/outlines/runs/batch-delete", response_model=ApiResponse)
async def batch_delete_outline_runs(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除大纲入库任务记录"""
    from app.modules.catalog.outline_run_service import OutlineRunService

    return ApiResponse(
        message="批量删除成功",
        data=await OutlineRunService(db).batch_delete(req.ids),
    )
