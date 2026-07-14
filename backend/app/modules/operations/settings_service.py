"""
系统设置服务

当前用途：
1. 提供轻量级系统设置读写能力
2. 支持 MinerU PDF 解析服务的部署与运行配置

说明：
- 当前采用 MySQL `system_configs` 表持久化
- 后续可平滑迁移到独立配置中心
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import AuditLog, SystemConfig
from app.modules.corpus.parser_runtime import inspect_parser_health
from app.modules.operations.crawler_settings import (
    normalize_crawler_settings,
    redact_crawler_runtime_config,
)
from app.modules.operations.pdf_parser_settings import (
    build_pdf_parser_runtime_config,
    prepare_pdf_parser_update,
)
from app.modules.operations.system_settings_rules import (
    deep_merge_dicts,
    default_config_description,
    default_system_settings,
    merge_section_dicts,
    merge_settings_defaults,
    sanitize_settings_input,
)

logger = get_logger(__name__)

# 四个"对话型/向量型"LLM 配置块的 key，供 admin 遍历做 api_key 脱敏与泛化端点路由。
LLM_CONFIG_KEYS = ("llm", "pdf_structure_llm", "outline_llm", "embedding", "doc_meta_llm", "enrich_llm")


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
        """返回系统唯一支持的 PDF 解析器。"""
        return "mineru"

    async def get_pdf_parser_runtime_config(self) -> Dict[str, Any]:
        data = await self.load()
        return build_pdf_parser_runtime_config(data.get("pdf_parser", {}))

    async def get_crawler_runtime_config(self) -> Dict[str, Any]:
        """Return the validated crawler settings used for the next task run."""
        data = await self.load()
        crawler_config = data.get("crawler", {})
        return self.normalize_crawler_settings(
            crawler_config if isinstance(crawler_config, dict) else {},
            reject_unknown=False,
        )

    async def update_crawler_settings(
        self,
        crawler_config: Dict[str, Any],
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate and persist crawler settings with an audit record."""
        current = await self.load()
        old_config = self.normalize_crawler_settings(
            current.get("crawler", {}),
            reject_unknown=False,
        )
        next_config = self.normalize_crawler_settings(crawler_config)
        current["crawler"] = next_config
        saved = await self.save(current)

        if next_config != old_config:
            audit = AuditLog(
                user_id=user_id,
                action="crawler_settings_update",
                resource_type="system_config",
                resource_id="crawler",
                old_values=self.redact_crawler_runtime_config(old_config),
                new_values=self.redact_crawler_runtime_config(next_config),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            db = self._require_db()
            db.add(audit)
            await db.flush()

        return saved["crawler"]

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
        """更新 MinerU 解析服务配置，并记录审计日志。"""
        current = await self.load()
        current_parser_config = current.get("pdf_parser", {})
        plan = prepare_pdf_parser_update(
            current_parser_config,
            parser_name=parser_name,
            deployment_target=deployment_target,
            local_service_endpoint=local_service_endpoint,
            remote_service_endpoint=remote_service_endpoint,
            request_timeout_seconds=request_timeout_seconds,
            processing_window_size=processing_window_size,
            switch_notes=switch_notes,
        )

        if plan.requires_local_health_check:
            parser_health = inspect_parser_health(
                "mineru",
                plan.next_config,
            )
            if parser_health.get("health_status") != "ready":
                raise ValueError(
                    f"目标解析器 mineru 当前不可用：{parser_health.get('error_detail') or '未知错误'}。"
                    " 请先完成旧服务下线、新服务启动和依赖校验，再切换系统配置。"
                )

        current["pdf_parser"] = plan.next_config
        saved = await self.save(current)

        if plan.should_audit:
            audit = AuditLog(
                user_id=user_id,
                action="pdf_parser_switch",
                resource_type="system_config",
                resource_id="pdf_parser",
                old_values=plan.old_audit_values,
                new_values=plan.new_audit_values,
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
    def normalize_crawler_settings(
        cls,
        data: Optional[Dict[str, Any]],
        *,
        reject_unknown: bool = True,
    ) -> Dict[str, Any]:
        """Compatibility delegate for crawler runtime validation."""
        return normalize_crawler_settings(
            data,
            reject_unknown=reject_unknown,
        )

    @staticmethod
    def redact_crawler_runtime_config(data: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility delegate for crawler audit redaction."""
        return redact_crawler_runtime_config(data)

    @classmethod
    def _merge_defaults(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility delegate for default settings merging."""
        return merge_settings_defaults(data)

    @classmethod
    def _merge_section_dicts(cls, base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility delegate for section-level settings merging."""
        return merge_section_dicts(base, updates)

    @staticmethod
    def _deep_merge_dicts(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility delegate for recursive dictionary merging."""
        return deep_merge_dicts(base, updates)

    @classmethod
    def _sanitize_input(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility delegate for incremental settings input cleanup."""
        return sanitize_settings_input(data)

    @staticmethod
    def _default_settings() -> Dict[str, Any]:
        """Compatibility delegate for complete system defaults."""
        return default_system_settings()

    @staticmethod
    def _default_description(config_key: str) -> str:
        """Compatibility delegate for persisted section descriptions."""
        return default_config_description(config_key)
