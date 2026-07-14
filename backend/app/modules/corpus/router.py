"""Admin routes for corpus files and document parse runs."""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse, BatchIdsRequest
from app.db import get_db
from app.modules.corpus.schemas import (
    ParseCorpusFileRequest,
    RegisterByDownloadRequest,
    RegisterFileRequest,
    ScanRequest,
)
from app.modules.corpus.service import (
    CorpusApplicationService,
    CorpusFileNotFoundError,
    ParseConflictError,
    ParseRunNotFoundError,
)
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
