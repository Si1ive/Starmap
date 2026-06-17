"""
系统设置服务

当前用途：
1. 提供轻量级系统设置读写能力
2. 支持 PDF 解析器的单活切换配置

说明：
- 当前采用 MySQL `system_configs` 表持久化
- 后续可平滑迁移到独立配置中心
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.mysql_models import AuditLog, SystemConfig
from app.services.document_parsers import inspect_parser_health

logger = get_logger(__name__)


class SystemSettingsService:
    """系统设置读写服务"""

    def __init__(self, db: Optional[AsyncSession]):
        self.db = db

    async def load(self) -> Dict[str, Any]:
        """读取系统设置并补齐默认值。"""
        if self.db is None:
            return self._default_settings()

        data: Dict[str, Any] = {}
        try:
            result = await self.db.execute(select(SystemConfig))
            rows = result.scalars().all()
            for row in rows:
                data[row.config_key] = row.config_value or {}
        except SQLAlchemyError as exc:
            logger.warning("系统设置读取失败，回退默认配置", error=str(exc))
            return self._default_settings()
        return self._merge_defaults(data)

    async def save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """保存系统设置。"""
        db = self._require_db()
        merged = self._merge_defaults(data)
        for key, value in merged.items():
            result = await db.execute(
                select(SystemConfig).where(SystemConfig.config_key == key)
            )
            row = result.scalar_one_or_none()
            if row:
                row.config_value = value
            else:
                row = SystemConfig(
                    config_key=key,
                    config_value=value,
                    description=self._default_description(key),
                )
                db.add(row)
        await db.flush()
        return merged

    async def save_partial(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """按顶级 section 增量保存系统设置。"""
        current = await self.load()
        sanitized = self._sanitize_input(data)
        merged = self._merge_section_dicts(current, sanitized)
        return await self.save(merged)

    async def get_active_pdf_parser(self) -> str:
        """获取当前激活的 PDF 解析器。"""
        data = await self.load()
        parser_name = (
            data.get("pdf_parser", {}).get("active_parser") or self._default_settings()["pdf_parser"]["active_parser"]
        )
        normalized = str(parser_name).strip().lower()
        if normalized not in {"docling", "mineru"}:
            return self._default_settings()["pdf_parser"]["active_parser"]
        return normalized

    async def get_pdf_parser_runtime_config(self) -> Dict[str, Any]:
        data = await self.load()
        parser_config = data.get("pdf_parser", {})
        defaults = self._default_settings()["pdf_parser"]
        merged = copy.deepcopy(defaults)
        merged.update(parser_config if isinstance(parser_config, dict) else {})
        return merged

    async def update_pdf_parser(
        self,
        parser_name: str,
        deployment_target: str = "local",
        local_service_endpoint: Optional[str] = None,
        remote_service_endpoint: Optional[str] = None,
        request_timeout_seconds: Optional[int] = None,
        processing_window_size: Optional[int] = None,
        switch_notes: str = "",
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新当前激活的 PDF 解析器配置，并记录审计日志。"""
        normalized = str(parser_name).strip().lower()
        if normalized not in {"docling", "mineru"}:
            raise ValueError("pdf_parser.active_parser 仅支持 docling 或 mineru")
        target = str(deployment_target or "local").strip().lower()
        if target not in {"local", "remote"}:
            raise ValueError("pdf_parser.deployment_target 仅支持 local 或 remote")

        current = await self.load()
        current_parser_config = current.get("pdf_parser", {})
        old_parser = current_parser_config.get("active_parser", "")
        old_target = current_parser_config.get("deployment_target", "local")
        old_local_endpoint = current_parser_config.get(
            "local_service_endpoint",
            self._default_settings()["pdf_parser"]["local_service_endpoint"],
        )
        old_remote_endpoint = current_parser_config.get("remote_service_endpoint", "")
        old_timeout = int(
            current_parser_config.get(
                "request_timeout_seconds",
                self._default_settings()["pdf_parser"]["request_timeout_seconds"],
            )
        )
        old_processing_window_size = int(
            current_parser_config.get(
                "processing_window_size",
                self._default_settings()["pdf_parser"]["processing_window_size"],
            )
        )
        next_local_endpoint = (
            str(local_service_endpoint).strip()
            if local_service_endpoint is not None
            else str(old_local_endpoint or self._default_settings()["pdf_parser"]["local_service_endpoint"]).strip()
        )
        next_remote_endpoint = (
            str(remote_service_endpoint).strip()
            if remote_service_endpoint is not None
            else str(old_remote_endpoint or "").strip()
        )
        next_timeout = int(request_timeout_seconds or old_timeout or 600)
        if next_timeout < 5 or next_timeout > 600:
            raise ValueError("pdf_parser.request_timeout_seconds 仅支持 5-600 秒")
        next_processing_window_size = int(
            processing_window_size
            or current_parser_config.get(
                "processing_window_size",
                self._default_settings()["pdf_parser"]["processing_window_size"],
            )
            or self._default_settings()["pdf_parser"]["processing_window_size"]
        )
        if next_processing_window_size < 1 or next_processing_window_size > 64:
            raise ValueError("pdf_parser.processing_window_size 仅支持 1-64")

        is_switching = (
            normalized != old_parser
            or target != old_target
            or next_local_endpoint != str(old_local_endpoint or "")
            or next_remote_endpoint != str(old_remote_endpoint or "")
            or next_timeout != old_timeout
            or next_processing_window_size != old_processing_window_size
        )
        notes = (switch_notes or "").strip()

        if is_switching and not notes:
            raise ValueError("切换 PDF 解析器或部署位置必须填写切换备注，说明原因、部署步骤和回滚方案")

        if target == "remote":
            if not next_remote_endpoint:
                raise ValueError("远程解析服务模式必须填写 remote_service_endpoint")
            parsed = urlparse(next_remote_endpoint)
            if not (parsed.scheme and parsed.netloc):
                raise ValueError("remote_service_endpoint 地址格式不合法，需包含协议和主机")

        if is_switching and target == "local":
            parser_health = inspect_parser_health(
                normalized,
                {
                    "active_parser": normalized,
                    "deployment_target": target,
                    "local_service_endpoint": next_local_endpoint,
                    "remote_service_endpoint": next_remote_endpoint,
                    "request_timeout_seconds": next_timeout,
                    "processing_window_size": next_processing_window_size,
                },
            )
            if parser_health.get("health_status") != "ready":
                raise ValueError(
                    f"目标解析器 {normalized} 当前不可用：{parser_health.get('error_detail') or '未知错误'}。"
                    " 请先完成旧服务下线、新服务启动和依赖校验，再切换系统配置。"
                )

        current["pdf_parser"] = {
            "active_parser": normalized,
            "service_mode": "single_active",
            "service_switch_notes": notes,
            "deployment_target": target,
            "local_service_endpoint": next_local_endpoint,
            "remote_service_endpoint": next_remote_endpoint,
            "request_timeout_seconds": next_timeout,
            "processing_window_size": next_processing_window_size,
        }
        saved = await self.save(current)

        if is_switching or notes:
            audit = AuditLog(
                user_id=user_id,
                action="pdf_parser_switch",
                resource_type="system_config",
                resource_id="pdf_parser",
                old_values={
                    "active_parser": old_parser,
                    "deployment_target": old_target,
                    "local_service_endpoint": old_local_endpoint,
                    "remote_service_endpoint": old_remote_endpoint,
                    "request_timeout_seconds": old_timeout,
                    "processing_window_size": old_processing_window_size,
                },
                new_values={
                    "active_parser": normalized,
                    "deployment_target": target,
                    "local_service_endpoint": next_local_endpoint,
                    "remote_service_endpoint": next_remote_endpoint,
                    "request_timeout_seconds": next_timeout,
                    "processing_window_size": next_processing_window_size,
                    "switch_notes": notes,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            db = self._require_db()
            db.add(audit)
            await db.flush()

        return saved

    def _require_db(self) -> AsyncSession:
        if self.db is None:
            raise RuntimeError("数据库不可用，当前操作无法完成")
        return self.db

    @classmethod
    def _merge_defaults(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        defaults = cls._default_settings()
        merged = copy.deepcopy(defaults)
        for key, value in data.items():
            if key not in merged:
                merged[key] = value
                continue
            if isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = cls._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    @classmethod
    def _merge_section_dicts(cls, base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in updates.items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = cls._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _deep_merge_dicts(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in updates.items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = SystemSettingsService._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    @classmethod
    def _sanitize_input(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        defaults = cls._default_settings()
        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            if key == "pdf_parser":
                sanitized[key] = {
                    "active_parser": value.get(
                        "active_parser",
                        defaults["pdf_parser"]["active_parser"],
                    ),
                    "service_mode": "single_active",
                    "service_switch_notes": value.get("service_switch_notes", ""),
                    "deployment_target": value.get(
                        "deployment_target",
                        defaults["pdf_parser"]["deployment_target"],
                    ),
                    "local_service_endpoint": value.get(
                        "local_service_endpoint",
                        defaults["pdf_parser"]["local_service_endpoint"],
                    ),
                    "remote_service_endpoint": value.get("remote_service_endpoint", ""),
                    "request_timeout_seconds": value.get(
                        "request_timeout_seconds",
                        defaults["pdf_parser"]["request_timeout_seconds"],
                    ),
                    "processing_window_size": value.get(
                        "processing_window_size",
                        defaults["pdf_parser"]["processing_window_size"],
                    ),
                }
                continue
            sanitized[key] = value
        return sanitized

    @staticmethod
    def _default_settings() -> Dict[str, Any]:
        return {
            "llm": {
                "model": settings.OPENAI_MODEL,
                "temperature": 0.7,
                "max_tokens": 2000,
                "system_prompt": "你是一个专业的408考研学习助手，擅长解释知识点、题目分析与学习规划。",
            },
            "pdf_structure_llm": {
                "enabled": False,
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": settings.OPENAI_MODEL,
                "temperature": 0.1,
                "max_tokens": 2000,
                "timeout_seconds": 60,
                "system_prompt": "你是一个PDF题目结构分析专家，负责判断跨页、跨列导致的题目拆分和选项缺失问题。",
            },
            "search": {
                "default_page_size": 20,
                "max_results": 100,
                "similarity_threshold": 0.8,
                "weights": {
                    "name": 1.0,
                    "category": 0.8,
                    "relation": 0.6,
                },
                "cache_ttl": 300,
            },
            "crawler": {
                "request_interval": 1.0,
                "max_concurrency": 5,
                "timeout": 30,
                "user_agents": [],
                "proxy": None,
                "max_concurrent": 5,
                "request_delay": 1.0,
                "request_timeout": 30,
                "max_retries": 3,
                "retry_delay": 2.0,
                "user_agent": "408-Platform/1.0",
                "proxy_enabled": False,
                "proxy_url": "",
                "respect_robots_txt": True,
                "auto_detect_encoding": True,
                "follow_redirects": True,
                "max_redirects": 5,
                "max_depth": 3,
                "dedup_enabled": True,
                "storage_batch_size": 100,
                "log_level": settings.LOG_LEVEL,
                "data_sources": [],
            },
            "system": {
                "name": settings.APP_NAME,
                "logo": None,
                "announcement": "",
                "maintenance_mode": False,
                "log_level": settings.LOG_LEVEL,
            },
            "pdf_parser": {
                "active_parser": "mineru",
                "service_mode": "single_active",
                "service_switch_notes": "",
                "deployment_target": "local",
                "local_service_endpoint": settings.PDF_PARSER_LOCAL_ENDPOINT,
                "remote_service_endpoint": "",
                "request_timeout_seconds": 600,
                "processing_window_size": 1,
            },
        }

    @staticmethod
    def _default_description(config_key: str) -> str:
        if config_key == "pdf_parser":
            return "PDF 解析器单活切换配置"
        if config_key == "llm":
            return "LLM 参数配置"
        if config_key == "pdf_structure_llm":
            return "PDF 文档结构解析 LLM 配置"
        if config_key == "search":
            return "搜索参数配置"
        if config_key == "crawler":
            return "爬虫运行配置"
        if config_key == "system":
            return "系统基础配置"
        return "系统配置"
