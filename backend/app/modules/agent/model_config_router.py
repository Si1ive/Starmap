"""管理员 Agent 多模型配置 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.infrastructure.ai.llm_client import ChatLLMClient
from app.modules.agent.model_config_schemas import (
    AgentModelAvailabilityUpdate,
    AgentModelConfigCreate,
    AgentModelConfigUpdate,
)
from app.modules.agent.model_configs import (
    AgentModelConfigError,
    AgentModelConfigNotFoundError,
    AgentModelConfigService,
)

router = APIRouter(prefix="/admin/agent-models", tags=["Agent 模型配置"])


def _raise_model_error(exc: Exception) -> None:
    if isinstance(exc, AgentModelConfigNotFoundError):
        raise HTTPException(status_code=404, detail="模型配置不存在") from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=ApiResponse)
async def list_agent_models(db: AsyncSession = Depends(get_db)):
    service = AgentModelConfigService(db)
    records = await service.list_all()
    return ApiResponse(
        data={"items": [service.to_admin_dict(item) for item in records]}
    )


@router.post("", response_model=ApiResponse, status_code=201)
async def create_agent_model(
    request: AgentModelConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    service = AgentModelConfigService(db)
    try:
        record = await service.create(request.model_dump())
        await db.commit()
    except (AgentModelConfigError, AgentModelConfigNotFoundError) as exc:
        await db.rollback()
        _raise_model_error(exc)
    return ApiResponse(message="模型配置创建成功", data=service.to_admin_dict(record))


@router.put("/{model_config_id}", response_model=ApiResponse)
async def update_agent_model(
    model_config_id: str,
    request: AgentModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = AgentModelConfigService(db)
    try:
        record = await service.update(
            model_config_id,
            request.model_dump(exclude_unset=True),
        )
        await db.commit()
    except (AgentModelConfigError, AgentModelConfigNotFoundError) as exc:
        await db.rollback()
        _raise_model_error(exc)
    return ApiResponse(message="模型配置更新成功", data=service.to_admin_dict(record))


@router.put("/{model_config_id}/availability", response_model=ApiResponse)
async def update_agent_model_availability(
    model_config_id: str,
    request: AgentModelAvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = AgentModelConfigService(db)
    try:
        record = await service.set_availability(
            model_config_id,
            online=request.online,
            selectable=request.selectable,
        )
        await db.commit()
    except (AgentModelConfigError, AgentModelConfigNotFoundError) as exc:
        await db.rollback()
        _raise_model_error(exc)
    return ApiResponse(message="模型状态更新成功", data=service.to_admin_dict(record))


@router.post("/{model_config_id}/default", response_model=ApiResponse)
async def set_default_agent_model(
    model_config_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = AgentModelConfigService(db)
    try:
        record = await service.set_default(model_config_id)
        await db.commit()
    except (AgentModelConfigError, AgentModelConfigNotFoundError) as exc:
        await db.rollback()
        _raise_model_error(exc)
    return ApiResponse(message="默认模型切换成功", data=service.to_admin_dict(record))


@router.post("/{model_config_id}/test", response_model=ApiResponse)
async def test_agent_model(
    model_config_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = AgentModelConfigService(db)
    try:
        record = await service.get(model_config_id)
    except AgentModelConfigNotFoundError as exc:
        _raise_model_error(exc)
    client = ChatLLMClient(service.to_runtime_dict(record))
    if not client.is_available:
        return ApiResponse(
            code=400,
            message="模型配置不可用",
            data={"success": False, "error": "请配置模型名称和 API Key"},
        )
    try:
        reply = await client.chat("请只回复：连接成功", purpose="agent_model_test")
    except Exception as exc:
        return ApiResponse(
            code=502,
            message="模型连通性测试失败",
            data={"success": False, "error": str(exc)[:500]},
        )
    return ApiResponse(
        data={
            "success": True,
            "model": record.model_name,
            "base_url": record.base_url,
            "reply": reply[:500],
        }
    )
