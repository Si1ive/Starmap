"""Admin routes for corpus files and document parse runs."""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.db import get_db
from app.modules.corpus.document_service import CorpusDocumentService
from app.modules.corpus.errors import (
    CorpusFileNotFoundError,
    DocumentNotFoundError,
    DocumentPageNotFoundError,
    EntityExtractionConflictError,
    EntityNotFoundError,
    EntitySourceUnavailableError,
    PageRenderError,
    ParseConflictError,
    ParseRunNotFoundError,
    SourceFileNotFoundError,
)
from app.modules.corpus.extraction_tasks import EntityExtractionTaskService
from app.modules.corpus.schemas import (
    ParseCorpusFileRequest,
    RegisterByDownloadRequest,
    RegisterFileRequest,
    ScanRequest,
)
from app.modules.corpus.service import CorpusApplicationService
from app.services.document_parsers import ParserUnavailableError

router = APIRouter(prefix="/admin", tags=["语料库"])


@router.post("/corpus/files/scan", response_model=ApiResponse)
async def scan_corpus_files(
    req: ScanRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).scan_files(
            root_path=req.root_path,
            file_types=req.file_types,
            batch_label=req.batch_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post("/corpus/files/register", response_model=ApiResponse)
async def register_corpus_file(
    req: RegisterFileRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).register_file(
            file_path=req.file_path,
            batch_label=req.batch_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post("/corpus/files/register-by-download", response_model=ApiResponse)
async def register_corpus_file_by_download(
    req: RegisterByDownloadRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).register_downloaded_file(
            downloaded_file_id=req.downloaded_file_id,
            batch_label=req.batch_label,
        )
    except CorpusFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post("/corpus/files/upload", response_model=ApiResponse)
async def upload_corpus_files(
    files: List[UploadFile] = File(...),
    batch_label: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).upload_files(
            files,
            batch_label=batch_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get("/corpus/files", response_model=ApiResponse)
async def list_corpus_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    file_ext: Optional[str] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    result = await CorpusApplicationService(db).list_files(
        page=page,
        page_size=page_size,
        status=status,
        source_type=source_type,
        file_ext=file_ext,
        keyword=keyword,
    )
    return ApiResponse(data=result)


@router.get("/corpus/documents/{document_id}", response_model=ApiResponse)
async def get_document_detail(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).get_document(document_id)
    except CorpusFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get("/corpus/files/{file_id}", response_model=ApiResponse)
async def get_corpus_file_detail(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).get_file(file_id)
    except CorpusFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post("/corpus/files/{file_id}/parse", response_model=ApiResponse)
async def parse_corpus_file(
    file_id: str,
    req: Optional[ParseCorpusFileRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    parse_req = req or ParseCorpusFileRequest()
    try:
        result = await CorpusApplicationService(db).start_parse(
            file_id,
            parser_name=parse_req.parser_name,
            parse_mode=parse_req.parse_mode,
        )
    except CorpusFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ParseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ParserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"创建解析任务失败: {str(exc)[:200]}",
        ) from exc
    return ApiResponse(message="解析任务已启动", data=result)


@router.delete("/corpus/files/{file_id}", response_model=ApiResponse)
async def delete_corpus_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).delete_files([file_id])
    except CorpusFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="语料文件不存在") from exc
    item = result["items"][0]
    return ApiResponse(message="删除成功", data=item)


@router.post("/corpus/files/batch-delete", response_model=ApiResponse)
async def batch_delete_corpus_files(
    req: BatchIdsRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).delete_files(req.ids)
    except CorpusFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(message="删除成功", data=result)


@router.get("/corpus/parse-runs", response_model=ApiResponse)
async def list_parse_runs(
    corpus_file_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await CorpusApplicationService(db).list_parse_runs(
        corpus_file_id=corpus_file_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result)


@router.get("/corpus/parse-runs/{run_id}", response_model=ApiResponse)
async def get_parse_run_detail(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusApplicationService(db).get_parse_run(run_id)
    except ParseRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get(
    "/corpus/documents/{document_id}/blocks",
    response_model=ApiResponse,
)
async def list_document_blocks(
    document_id: str,
    page_no: Optional[int] = None,
    block_type: Optional[str] = None,
    review_status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await CorpusDocumentService(db).list_blocks(
        document_id,
        page_no=page_no,
        block_type=block_type,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=result)


@router.get(
    "/corpus/documents/{document_id}/sections",
    response_model=ApiResponse,
)
async def get_document_sections(
    document_id: str,
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
):
    result = await CorpusDocumentService(db).get_sections(
        document_id,
        tree=tree,
    )
    return ApiResponse(data=result)


@router.get(
    "/corpus/documents/{document_id}/page-analysis",
    response_model=ApiResponse,
)
async def get_document_page_analysis(
    document_id: str,
    page_no: int = Query(..., ge=1, description="页码，从1开始"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusDocumentService(db).get_page_analysis(
            document_id,
            page_no=page_no,
        )
    except (
        DocumentNotFoundError,
        DocumentPageNotFoundError,
        SourceFileNotFoundError,
    ) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PageRenderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(
    "/corpus/documents/{document_id}/extract-sections",
    response_model=ApiResponse,
)
async def extract_document_sections(
    document_id: str,
    force: bool = Query(False, description="是否强制重建已有标题树"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusDocumentService(db).extract_sections(
            document_id,
            force=force,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail.startswith("文档不存在") else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"提取失败: {str(exc)[:200]}",
        ) from exc
    return ApiResponse(data=result)


@router.post(
    "/corpus/documents/{document_id}/map-chapters",
    response_model=ApiResponse,
)
async def map_document_chapters(
    document_id: str,
    subject_id: Optional[str] = Query(
        None,
        description="学科ID，不传则遍历所有学科匹配",
    ),
    outline_id: Optional[str] = Query(
        None,
        description="大纲ID；传入则只匹配该大纲下章节",
    ),
    auto_approve_threshold: float = Query(
        0.90,
        ge=0,
        le=1,
        description="自动通过阈值",
    ),
    force: bool = Query(False, description="是否强制重建已有章节映射"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusDocumentService(db).map_chapters(
            document_id,
            subject_id=subject_id,
            outline_id=outline_id,
            auto_approve_threshold=auto_approve_threshold,
            force=force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"映射失败: {str(exc)[:200]}",
        ) from exc
    return ApiResponse(data=result)


@router.get(
    "/corpus/documents/{document_id}/section-mappings",
    response_model=ApiResponse,
)
async def get_document_section_mappings(
    document_id: str,
    review_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    result = await CorpusDocumentService(db).get_section_mappings(
        document_id,
        review_status=review_status,
    )
    return ApiResponse(data=result)


@router.get(
    "/corpus/documents/{document_id}/chapter-diagnostics",
    response_model=ApiResponse,
)
async def get_document_chapter_diagnostics(
    document_id: str,
    page_no: Optional[int] = Query(None, ge=1, description="只查看指定页"),
    include_blocks: bool = Query(True, description="是否返回块级诊断明细"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusDocumentService(db).get_chapter_diagnostics(
            document_id,
            page_no=page_no,
            include_blocks=include_blocks,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail.startswith("文档不存在") else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"诊断失败: {str(exc)[:200]}",
        ) from exc
    return ApiResponse(data=result)


@router.get(
    "/corpus/documents/{document_id}/content-overview",
    response_model=ApiResponse,
)
async def get_document_content_overview(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await CorpusDocumentService(db).get_content_overview(
            document_id
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(
    "/corpus/documents/{document_id}/extract-entities",
    response_model=ApiResponse,
)
async def extract_document_entities(
    document_id: str,
    extract_knowledge: bool = Query(True, description="是否抽取知识点"),
    extract_questions: bool = Query(True, description="是否抽取题目"),
    subject_id: Optional[str] = Query(
        None,
        description="章节映射不足时使用的兜底学科ID",
    ),
    db: AsyncSession = Depends(get_db),
):
    service = EntityExtractionTaskService(db)
    try:
        run, created = await service.start(
            document_id,
            extract_knowledge=extract_knowledge,
            extract_questions=extract_questions,
            subject_id=subject_id,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"创建抽取任务失败: {str(exc)[:200]}",
        ) from exc
    return ApiResponse(
        message="抽取任务已启动" if created else "抽取任务正在执行",
        data=service.serialize(run),
    )


@router.get(
    "/corpus/documents/{document_id}/extraction-status",
    response_model=ApiResponse,
)
async def get_document_entity_extraction_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = EntityExtractionTaskService(db)
    try:
        run = await service.get_latest(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=service.serialize(run) if run else None)


@router.post(
    "/corpus/documents/{document_id}/entities/{entity_type}/{entity_id}/reextract",
    response_model=ApiResponse,
)
async def reextract_document_entity(
    document_id: str,
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = EntityExtractionTaskService(db)
    try:
        run, created = await service.start_entity(
            document_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except (DocumentNotFoundError, EntityNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        EntitySourceUnavailableError,
        EntityExtractionConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"创建单项重提取任务失败: {str(exc)[:200]}",
        ) from exc
    return ApiResponse(
        message="单项重提取任务已启动" if created else "该实体正在重新提取",
        data=service.serialize(run),
    )


@router.get(
    "/corpus/documents/{document_id}/entities/{entity_type}/{entity_id}/reextraction-status",
    response_model=ApiResponse,
)
async def get_document_entity_reextraction_status(
    document_id: str,
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = EntityExtractionTaskService(db)
    try:
        run = await service.get_latest_entity(
            document_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except (DocumentNotFoundError, EntityNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=service.serialize(run) if run else None)
