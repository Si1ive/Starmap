"""System-settings administration routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db, get_optional_db
from app.modules.operations.security import get_request_admin_id

router = APIRouter(prefix="/admin", tags=["系统配置"])

SECRET_KEEP_MASK = "__KEEP_EXISTING__"


# ========== 系统配置相关 ==========


@router.get("/settings", response_model=ApiResponse)
async def get_settings(db: Optional[AsyncSession] = Depends(get_optional_db)):
    """
    获取系统配置

    返回当前系统配置，优先读取数据库持久化内容。
    """
    from app.modules.corpus.parser_runtime import (
        get_supported_parser_names,
        inspect_parser_health,
    )
    from app.modules.operations.settings_service import (
        SystemSettingsService,
        LLM_CONFIG_KEYS,
    )

    runtime_settings = await SystemSettingsService(db).load()
    # 对所有 LLM 配置块统一脱敏 api_key
    masked_llm: Dict[str, Any] = {}
    for key in LLM_CONFIG_KEYS:
        block = dict(runtime_settings.get(key, {}) or {})
        if block.get("api_key"):
            block["api_key"] = SECRET_KEEP_MASK
        masked_llm[key] = block

    active_parser = runtime_settings["pdf_parser"]["active_parser"]
    parser_runtime_config = runtime_settings["pdf_parser"]
    available_parsers = []
    for parser_name in get_supported_parser_names():
        parser_status = inspect_parser_health(parser_name, parser_runtime_config)
        parser_status["is_active"] = parser_name == active_parser
        available_parsers.append(parser_status)
    active_runtime_status = next(
        (item for item in available_parsers if item["is_active"]),
        None,
    )

    return ApiResponse(
        code=200,
        message="success",
        data={
            "llm": masked_llm["llm"],
            "pdf_structure_llm": masked_llm["pdf_structure_llm"],
            "outline_llm": masked_llm["outline_llm"],
            "embedding": masked_llm["embedding"],
            "doc_meta_llm": masked_llm["doc_meta_llm"],
            "enrich_llm": masked_llm["enrich_llm"],
            "pdf_parser": {
                "active_parser": active_parser,
                "service_mode": runtime_settings["pdf_parser"]["service_mode"],
                "service_switch_notes": runtime_settings["pdf_parser"][
                    "service_switch_notes"
                ],
                "deployment_target": runtime_settings["pdf_parser"][
                    "deployment_target"
                ],
                "local_service_endpoint": runtime_settings["pdf_parser"][
                    "local_service_endpoint"
                ],
                "remote_service_endpoint": runtime_settings["pdf_parser"][
                    "remote_service_endpoint"
                ],
                "request_timeout_seconds": runtime_settings["pdf_parser"][
                    "request_timeout_seconds"
                ],
                "processing_window_size": runtime_settings["pdf_parser"][
                    "processing_window_size"
                ],
                "active_runtime_status": active_runtime_status,
                "available_parsers": available_parsers,
            },
        },
    )


@router.get("/settings/pdf-parser/history", response_model=ApiResponse)
async def get_pdf_parser_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取 PDF 解析器切换历史"""
    from app.models.mysql_models import AuditLog

    query = (
        select(AuditLog)
        .where(
            AuditLog.action == "pdf_parser_switch",
            AuditLog.resource_type == "system_config",
            AuditLog.resource_id == "pdf_parser",
        )
        .order_by(AuditLog.created_at.desc())
    )

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.scalars().all()

    items = [
        {
            "id": row.id,
            "old_parser": (
                row.old_values.get("active_parser") if row.old_values else None
            ),
            "new_parser": (
                row.new_values.get("active_parser") if row.new_values else None
            ),
            "old_target": (
                row.old_values.get("deployment_target") if row.old_values else None
            ),
            "new_target": (
                row.new_values.get("deployment_target") if row.new_values else None
            ),
            "switch_notes": (row.new_values or {}).get("switch_notes", ""),
            "user_id": row.user_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]

    return ApiResponse(
        code=200,
        message="success",
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


def _build_llm_client(kind: str, config: dict):
    """按配置块 kind 构造对应客户端。embedding 返回 EmbeddingService，其余返回 BaseLLMClient 子类。"""
    from app.infrastructure.ai.llm_client import (
        ChatLLMClient,
        PDFStructureLLMClient,
        OutlineLLMClient,
        DocMetaLLMClient,
        EnrichLLMClient,
    )

    if kind == "llm":
        return ChatLLMClient(config)
    if kind == "pdf_structure_llm":
        return PDFStructureLLMClient(config)
    if kind == "outline_llm":
        return OutlineLLMClient(config)
    if kind == "doc_meta_llm":
        return DocMetaLLMClient(config)
    if kind == "enrich_llm":
        return EnrichLLMClient(config)
    if kind == "embedding":
        from app.infrastructure.ai.embedding_service import EmbeddingService

        return EmbeddingService(config)
    raise HTTPException(status_code=400, detail=f"未知的 LLM 配置块: {kind}")


@router.get("/settings/llm/{kind}/status", response_model=ApiResponse)
async def get_llm_status(kind: str, db: AsyncSession = Depends(get_db)):
    """获取指定 LLM 配置块状态，不发起外部请求。kind ∈ llm/pdf_structure_llm/outline_llm/embedding。"""
    from app.modules.operations.settings_service import (
        SystemSettingsService,
        LLM_CONFIG_KEYS,
    )

    if kind not in LLM_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail=f"未知的 LLM 配置块: {kind}")

    runtime_settings = await SystemSettingsService(db).load()
    config = runtime_settings.get(kind, {}) or {}

    if kind == "embedding":
        from app.infrastructure.ai.embedding_service import EmbeddingService

        svc = EmbeddingService(config)
        is_local = svc.provider == "local_bge_m3"
        has_key = bool(svc.api_key)
        issues = []
        if not bool(config.get("enabled")):
            issues.append("未启用向量化配置")
        if not svc.model:
            issues.append("未配置模型")
        if not is_local and not has_key:
            issues.append("未配置 API Key，且 OPENAI_API_KEY 环境变量为空")
        is_available = bool(config.get("enabled")) and bool(
            svc.model and (is_local or has_key)
        )
        return ApiResponse(
            data={
                "enabled": bool(config.get("enabled")),
                "provider": svc.provider,
                "model": svc.model,
                "base_url": svc.base_url if not is_local else "(本地模型)",
                "dimension": svc.dimension,
                "has_api_key": has_key,
                "uses_env_api_key": not is_local
                and has_key
                and not bool(config.get("api_key")),
                "is_available": is_available,
                "issues": issues,
            }
        )

    client = _build_llm_client(kind, config if isinstance(config, dict) else {})
    issues = []
    if not client.enabled:
        issues.append("未启用该 LLM")
    if client.provider != "openai_compatible":
        issues.append("当前仅支持 OpenAI 兼容接口")
    if not client.model:
        issues.append("未配置模型")
    if not client.api_key:
        issues.append("未配置 API Key，且 OPENAI_API_KEY 环境变量为空")

    return ApiResponse(
        data={
            "enabled": client.enabled,
            "provider": client.provider,
            "model": client.model,
            "base_url": client.base_url,
            "has_api_key": bool(client.api_key),
            "uses_env_api_key": bool(client.api_key)
            and not bool((config or {}).get("api_key")),
            "is_available": client.is_available,
            "issues": issues,
        }
    )


@router.post("/settings/llm/{kind}/test", response_model=ApiResponse)
async def test_llm(
    kind: str,
    data: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
):
    """按当前表单或已保存配置测试指定 LLM 配置块的连通性。"""
    from app.modules.operations.settings_service import (
        SystemSettingsService,
        LLM_CONFIG_KEYS,
    )

    if kind not in LLM_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail=f"未知的 LLM 配置块: {kind}")

    runtime_service = SystemSettingsService(db)
    current_settings = await runtime_service.load()
    current_config = current_settings.get(kind, {})
    payload = dict(data or {})
    if payload.get("api_key") == SECRET_KEEP_MASK:
        payload["api_key"] = current_config.get("api_key", "")
    merged_config = dict(current_config if isinstance(current_config, dict) else {})
    merged_config.update(payload)

    if kind == "embedding":
        from app.infrastructure.ai.embedding_service import EmbeddingService

        svc = EmbeddingService(merged_config)
        is_local = svc.provider == "local_bge_m3"
        if not is_local and not (svc.model and svc.api_key):
            return ApiResponse(
                code=400,
                message="向量化配置不可用",
                data={
                    "success": False,
                    "model": svc.model,
                    "has_api_key": bool(svc.api_key),
                    "error": "请确认模型和 API Key 已配置（或设置 OPENAI_API_KEY 环境变量）。",
                },
            )
        if not svc.model:
            return ApiResponse(
                code=400,
                message="向量化配置不可用",
                data={
                    "success": False,
                    "model": svc.model,
                    "error": "请配置模型名称。",
                },
            )
        try:
            vec = await svc.embed_text("连通性测试")
        except Exception as e:
            return ApiResponse(
                code=502,
                message="向量化测试失败",
                data={
                    "success": False,
                    "model": svc.model,
                    "base_url": svc.base_url or "(本地模型)",
                    "error": str(e)[:500],
                },
            )
        return ApiResponse(
            data={
                "success": True,
                "model": svc.model,
                "base_url": svc.base_url or "(本地模型)",
                "dimension": len(vec),
                "configured_dimension": svc.dimension,
                "dimension_match": len(vec) == svc.dimension,
            }
        )

    client = _build_llm_client(kind, merged_config)
    if not client.is_available:
        return ApiResponse(
            code=400,
            message="LLM 配置不可用",
            data={
                "success": False,
                "enabled": client.enabled,
                "provider": client.provider,
                "model": client.model,
                "has_api_key": bool(client.api_key),
                "error": "请确认已启用、模型和 API Key 已配置，且服务类型为 OpenAI 兼容接口。",
            },
        )

    try:
        reply = await client.chat("请只回复：LLM_OK", purpose="配置连通性测试")
    except Exception as e:
        return ApiResponse(
            code=502,
            message="LLM 测试失败",
            data={
                "success": False,
                "provider": client.provider,
                "model": client.model,
                "base_url": client.base_url,
                "error": str(e)[:500],
            },
        )

    return ApiResponse(
        data={
            "success": True,
            "provider": client.provider,
            "model": client.model,
            "base_url": client.base_url,
            "reply": reply[:200],
        }
    )


@router.put("/settings", response_model=ApiResponse)
async def update_settings(
    data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    更新系统配置

    所有顶级 section 统一落库；PDF 解析器切换额外记录审计日志。
    """
    from app.modules.operations.settings_service import (
        SystemSettingsService,
        LLM_CONFIG_KEYS,
    )

    runtime_service = SystemSettingsService(db)
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    current_settings = await runtime_service.load()
    payload = dict(data or {})
    # 所有 LLM 配置块：api_key 为脱敏占位符时回填已保存的真实值
    for key in LLM_CONFIG_KEYS:
        section = payload.get(key)
        if isinstance(section, dict) and section.get("api_key") == SECRET_KEEP_MASK:
            section["api_key"] = current_settings.get(key, {}).get("api_key", "")
    parser_section = (
        payload.pop("pdf_parser", None)
        if isinstance(payload.get("pdf_parser"), dict)
        else None
    )
    try:
        saved_runtime = (
            await runtime_service.save_partial(payload) if payload else current_settings
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if parser_section is not None:
        try:
            saved_runtime = await runtime_service.update_pdf_parser(
                parser_name=parser_section.get(
                    "active_parser", current_settings["pdf_parser"]["active_parser"]
                ),
                deployment_target=parser_section.get(
                    "deployment_target",
                    current_settings["pdf_parser"]["deployment_target"],
                ),
                local_service_endpoint=parser_section.get(
                    "local_service_endpoint",
                    current_settings["pdf_parser"]["local_service_endpoint"],
                ),
                remote_service_endpoint=parser_section.get(
                    "remote_service_endpoint",
                    current_settings["pdf_parser"]["remote_service_endpoint"],
                ),
                request_timeout_seconds=parser_section.get(
                    "request_timeout_seconds",
                    current_settings["pdf_parser"]["request_timeout_seconds"],
                ),
                processing_window_size=parser_section.get(
                    "processing_window_size",
                    current_settings["pdf_parser"]["processing_window_size"],
                ),
                switch_notes=parser_section.get("service_switch_notes", ""),
                user_id=get_request_admin_id(request),
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    response_runtime = dict(saved_runtime)
    # 所有 LLM 配置块：响应里脱敏 api_key
    for key in LLM_CONFIG_KEYS:
        block = dict(response_runtime.get(key, {}) or {})
        if block.get("api_key"):
            block["api_key"] = SECRET_KEEP_MASK
            response_runtime[key] = block

    return ApiResponse(code=200, message="保存成功", data=response_runtime)
