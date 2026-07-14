"""Administrative monitoring routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.modules.monitoring.llm_calls import (
    delete_llm_calls,
    get_llm_call_detail,
    get_llm_call_stats,
    list_llm_calls,
)
from app.modules.monitoring.vector_recalls import (
    delete_vector_recalls,
    get_vector_recall_stats,
    list_vector_recalls,
)

router = APIRouter(prefix="/admin/monitor", tags=["后台监控"])


@router.get("/llm-calls", response_model=ApiResponse)
async def list_llm_call_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    model: Optional[str] = None,
    status: Optional[str] = Query(
        None,
        description="success / error / timeout",
    ),
    called_by: Optional[str] = None,
    keyword: Optional[str] = Query(None, description="响应文本模糊搜索"),
    db: AsyncSession = Depends(get_db),
):
    result = await list_llm_calls(
        session=db,
        page=page,
        page_size=page_size,
        model=model,
        status=status,
        called_by=called_by,
        keyword=keyword,
    )
    return ApiResponse(data=result)


@router.get("/llm-calls/stats", response_model=ApiResponse)
async def get_llm_calls_stats(
    hours: int = Query(24, ge=1, le=720, description="时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
):
    result = await get_llm_call_stats(session=db, hours=hours)
    return ApiResponse(data=result)


@router.get("/llm-calls/{call_id}", response_model=ApiResponse)
async def get_llm_call_detail_endpoint(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await get_llm_call_detail(session=db, call_id=call_id)
    if not result:
        raise HTTPException(status_code=404, detail="调用记录不存在")
    return ApiResponse(data=result)


@router.delete("/llm-calls", response_model=ApiResponse)
async def delete_llm_call_logs(
    older_than_days: Optional[int] = Query(
        None,
        ge=0,
        description="按时间清理：删除 N 天前的记录",
    ),
    ids: Optional[str] = Query(None, description="按 ID 清理：逗号分隔"),
    db: AsyncSession = Depends(get_db),
):
    id_list = [item.strip() for item in (ids or "").split(",") if item.strip()]
    deleted = await delete_llm_calls(
        session=db,
        older_than_days=older_than_days,
        ids=id_list or None,
    )
    return ApiResponse(data={"deleted": deleted})


@router.get("/vector-recalls", response_model=ApiResponse)
async def list_vector_recall_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    called_by: Optional[str] = Query(
        None,
        description="question / knowledge_point",
    ),
    status: Optional[str] = Query(None, description="hit / miss / error"),
    keyword: Optional[str] = Query(None, description="查询文本模糊搜索"),
    db: AsyncSession = Depends(get_db),
):
    result = await list_vector_recalls(
        session=db,
        page=page,
        page_size=page_size,
        called_by=called_by,
        status=status,
        keyword=keyword,
    )
    return ApiResponse(data=result)


@router.get("/vector-recalls/stats", response_model=ApiResponse)
async def get_vector_recalls_stats(
    hours: int = Query(24, ge=1, le=720, description="时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
):
    result = await get_vector_recall_stats(session=db, hours=hours)
    return ApiResponse(data=result)


@router.delete("/vector-recalls", response_model=ApiResponse)
async def delete_vector_recall_logs(
    older_than_days: Optional[int] = Query(
        None,
        ge=0,
        description="按时间清理：删除 N 天前的记录",
    ),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_vector_recalls(
        session=db,
        older_than_days=older_than_days,
    )
    return ApiResponse(data={"deleted": deleted})
