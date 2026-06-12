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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mysql_models import AuditLog, SystemConfig
from app.services.document_parsers import inspect_parser_health


class SystemSettingsService:
    """系统设置读写服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def load(self) -> Dict[str, Any]:
        """读取系统设置并补齐默认值。"""
        data: Dict[str, Any] = {}
        result = await self.db.execute(select(SystemConfig))
        rows = result.scalars().all()
        for row in rows:
            data[row.config_key] = row.config_value or {}
        return self._merge_defaults(data)

    async def save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """保存系统设置。"""
        merged = self._merge_defaults(data)
        for key, value in merged.items():
            result = await self.db.execute(
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
                self.db.add(row)
        await self.db.flush()
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

    async def update_pdf_parser(
        self,
        parser_name: str,
        switch_notes: str = "",
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新当前激活的 PDF 解析器配置，并记录审计日志。"""
        normalized = str(parser_name).strip().lower()
        if normalized not in {"docling", "mineru"}:
            raise ValueError("pdf_parser.active_parser 仅支持 docling 或 mineru")

        current = await self.load()
        old_parser = current.get("pdf_parser", {}).get("active_parser", "")
        is_switching = normalized != old_parser
        notes = (switch_notes or "").strip()

        if is_switching and not notes:
            raise ValueError("切换 PDF 解析器必须填写切换备注，说明原因、部署步骤和回滚方案")

        if is_switching:
            parser_health = inspect_parser_health(normalized)
            if parser_health.get("health_status") != "ready":
                raise ValueError(
                    f"目标解析器 {normalized} 当前不可用：{parser_health.get('error_detail') or '未知错误'}。"
                    " 请先完成旧服务下线、新服务启动和依赖校验，再切换系统配置。"
                )

        current["pdf_parser"] = {
            "active_parser": normalized,
            "service_mode": "single_active",
            "service_switch_notes": notes,
        }
        saved = await self.save(current)

        if is_switching or notes:
            audit = AuditLog(
                user_id=user_id,
                action="pdf_parser_switch",
                resource_type="system_config",
                resource_id="pdf_parser",
                old_values={"active_parser": old_parser},
                new_values={"active_parser": normalized, "switch_notes": notes},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.add(audit)
            await self.db.flush()

        return saved

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
            },
        }

    @staticmethod
    def _default_description(config_key: str) -> str:
        if config_key == "pdf_parser":
            return "PDF 解析器单活切换配置"
        if config_key == "llm":
            return "LLM 参数配置"
        if config_key == "search":
            return "搜索参数配置"
        if config_key == "crawler":
            return "爬虫运行配置"
        if config_key == "system":
            return "系统基础配置"
        return "系统配置"
