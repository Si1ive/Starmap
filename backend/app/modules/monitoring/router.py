"""Administrative monitoring routes."""

from datetime import datetime
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
from app.modules.monitoring.queries import (
    archive_service_logs,
    delete_service_logs,
    get_api_stats_overview,
    get_database_status_extended,
    get_service_log_stats,
    get_system_metrics_latest,
    get_system_metrics_series,
    query_service_logs,
)
from app.modules.monitoring.vector_recalls import (
    delete_vector_recalls,
    get_vector_recall_stats,
    list_vector_recalls,
)

router = APIRouter(prefix="/admin/monitor", tags=["后台监控"])


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/api", response_model=ApiResponse)
async def get_api_monitor(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    """返回 API 延迟分布、接口排行和慢接口。"""
    return ApiResponse(data=await get_api_stats_overview(db, hours=hours))


@router.get("/database", response_model=ApiResponse)
async def get_database_monitor():
    """返回 MySQL、Redis 和 Qdrant 的连接状态。"""
    return ApiResponse(data=await get_database_status_extended())


async def _query_logs(
    *,
    db: AsyncSession,
    page: int,
    page_size: int,
    level: Optional[str],
    keyword: Optional[str],
    logger_name: Optional[str],
    request_id: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
):
    return await query_service_logs(
        session=db,
        page=page,
        page_size=page_size,
        level=level,
        logger_name=logger_name,
        keyword=keyword,
        request_id=request_id,
        start_time=_parse_datetime(start_time),
        end_time=_parse_datetime(end_time),
    )


@router.get("/errors", response_model=ApiResponse)
async def get_error_logs(
    level: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = None,
    logger_name: Optional[str] = None,
    request_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询服务日志，默认仅返回 ERROR 级别。"""
    result = await _query_logs(
        db=db,
        page=page,
        page_size=page_size,
        level=level or "ERROR",
        keyword=keyword,
        logger_name=logger_name,
        request_id=request_id,
        start_time=start_time,
        end_time=end_time,
    )
    return ApiResponse(data=result)


@router.get("/logs", response_model=ApiResponse)
async def get_service_logs(
    level: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    keyword: Optional[str] = None,
    logger_name: Optional[str] = None,
    request_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询包含所有级别的服务日志。"""
    result = await _query_logs(
        db=db,
        page=page,
        page_size=page_size,
        level=level,
        keyword=keyword,
        logger_name=logger_name,
        request_id=request_id,
        start_time=start_time,
        end_time=end_time,
    )
    return ApiResponse(data=result)


@router.get("/logs/stats", response_model=ApiResponse)
async def get_service_logs_stats(
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await get_service_log_stats(db, hours=hours))


@router.delete("/logs", response_model=ApiResponse)
async def delete_service_logs_endpoint(
    older_than_days: Optional[int] = Query(None, ge=0),
    level: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_service_logs(
        db,
        older_than_days=older_than_days,
        level=level,
    )
    return ApiResponse(data={"deleted": deleted})


@router.post("/logs/archive", response_model=ApiResponse)
async def archive_service_logs_endpoint(
    older_than_days: int = Query(30, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
):
    result = await archive_service_logs(db, older_than_days=older_than_days)
    return ApiResponse(data=result)


@router.get("/system", response_model=ApiResponse)
async def get_system_metrics(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    """返回系统资源最新值和时序数据。"""
    latest = await get_system_metrics_latest(db)
    series = await get_system_metrics_series(db, hours=hours)
    return ApiResponse(
        data={
            "latest": latest,
            "series": series,
            "window_hours": hours,
        }
    )


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
