"""Operational cleanup for the current crawler data model."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import CrawlLog, CrawlTask, DownloadedFile


class CrawlerCleanupService:
    """Clean crawler operational records without touching extracted content."""

    DEFAULT_TYPES = ("duplicate", "expired", "orphan")
    TYPE_ALIASES = {
        "duplicate": "duplicate",
        "duplicates": "duplicate",
        "expired": "expired",
        "orphan": "orphan",
        "orphans": "orphan",
    }
    TERMINAL_TASK_STATUSES = ("completed", "failed", "stopped")
    MIN_RETENTION_DAYS = 1
    MAX_RETENTION_DAYS = 3650

    def __init__(self, db: AsyncSession):
        self.db = db

    @classmethod
    def validate_options(
        cls,
        cleanup_types: Any,
        retention_days: Any,
    ) -> tuple[List[str], int]:
        """Normalize and validate cleanup configuration."""
        raw_types = cls.DEFAULT_TYPES if cleanup_types is None else cleanup_types
        if isinstance(raw_types, str):
            raw_types = [raw_types]
        if not isinstance(raw_types, Iterable) or isinstance(raw_types, (dict, bytes)):
            raise ValueError("cleanup_types 必须是清理类型列表")

        normalized: List[str] = []
        unsupported: List[str] = []
        for raw_type in raw_types:
            cleanup_type = cls.TYPE_ALIASES.get(str(raw_type).strip().lower())
            if not cleanup_type:
                unsupported.append(str(raw_type))
            elif cleanup_type not in normalized:
                normalized.append(cleanup_type)

        if unsupported:
            raise ValueError(f"不支持的清理类型: {', '.join(unsupported)}")
        if not normalized:
            raise ValueError("至少选择一种清理类型")

        if isinstance(retention_days, bool) or (
            isinstance(retention_days, float) and not retention_days.is_integer()
        ):
            raise ValueError("retention_days 必须是整数")
        try:
            normalized_retention_days = int(
                retention_days
                if retention_days is not None
                else 90
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("retention_days 必须是整数") from exc

        if not cls.MIN_RETENTION_DAYS <= normalized_retention_days <= cls.MAX_RETENTION_DAYS:
            raise ValueError(
                "retention_days 必须在 "
                f"{cls.MIN_RETENTION_DAYS}-{cls.MAX_RETENTION_DAYS} 之间"
            )
        return normalized, normalized_retention_days

    async def run(
        self,
        *,
        cleanup_types: Any = None,
        retention_days: Any = 90,
    ) -> Dict[str, Any]:
        """Execute selected cleanup operations as one database transaction."""
        selected_types, normalized_retention_days = self.validate_options(
            cleanup_types,
            retention_days,
        )
        stats: Dict[str, int] = {
            "duplicate_downloads": 0,
            "expired_logs": 0,
            "expired_failed_downloads": 0,
            "orphan_logs": 0,
            "detached_downloads": 0,
        }

        try:
            if "duplicate" in selected_types:
                stats["duplicate_downloads"] = (
                    await self._remove_duplicate_download_records()
                )
            if "expired" in selected_types:
                expired_stats = await self._remove_expired_records(
                    normalized_retention_days
                )
                stats.update(expired_stats)
            if "orphan" in selected_types:
                orphan_stats = await self._remove_orphan_references()
                stats.update(orphan_stats)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        total_cleaned = sum(stats.values())
        return {
            "cleanup_types": selected_types,
            "retention_days": normalized_retention_days,
            "total_cleaned": total_cleaned,
            **stats,
        }

    async def _remove_duplicate_download_records(self) -> int:
        """
        Remove duplicate download rows while preserving the most useful record.

        A file is identified by repository URL/name plus repository-relative path.
        Successful records take precedence over failed records, then the newest row.
        """
        repository_identity = func.coalesce(
            func.nullif(DownloadedFile.repo_url, ""),
            func.nullif(DownloadedFile.repo_name, ""),
        )
        status_priority = case(
            (DownloadedFile.status == "processed", 5),
            (DownloadedFile.status == "downloaded", 4),
            (DownloadedFile.status == "processing", 3),
            (DownloadedFile.status == "skipped", 2),
            (DownloadedFile.status == "failed", 1),
            else_=0,
        )
        ranked = (
            select(
                DownloadedFile.id.label("id"),
                func.row_number()
                .over(
                    partition_by=(
                        repository_identity,
                        DownloadedFile.file_path,
                    ),
                    order_by=(
                        status_priority.desc(),
                        DownloadedFile.updated_at.desc(),
                        DownloadedFile.created_at.desc(),
                        DownloadedFile.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(repository_identity.is_not(None))
            .subquery()
        )
        result = await self.db.execute(
            select(ranked.c.id).where(ranked.c.row_number > 1)
        )
        duplicate_ids = list(result.scalars().all())
        if not duplicate_ids:
            return 0

        await self.db.execute(
            delete(DownloadedFile).where(DownloadedFile.id.in_(duplicate_ids))
        )
        return len(duplicate_ids)

    async def _remove_expired_records(self, retention_days: int) -> Dict[str, int]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).replace(tzinfo=None)
        terminal_task_ids = select(CrawlTask.id).where(
            CrawlTask.status.in_(self.TERMINAL_TASK_STATUSES)
        )

        expired_logs = await self.db.execute(
            delete(CrawlLog).where(
                CrawlLog.created_at < cutoff,
                CrawlLog.task_id.in_(terminal_task_ids),
            )
        )
        expired_failed_downloads = await self.db.execute(
            delete(DownloadedFile).where(
                DownloadedFile.updated_at < cutoff,
                DownloadedFile.status.in_(("failed", "skipped")),
            )
        )
        return {
            "expired_logs": self._rowcount(expired_logs),
            "expired_failed_downloads": self._rowcount(expired_failed_downloads),
        }

    async def _remove_orphan_references(self) -> Dict[str, int]:
        existing_task_ids = select(CrawlTask.id)
        orphan_logs = await self.db.execute(
            delete(CrawlLog).where(
                CrawlLog.task_id.not_in(existing_task_ids)
            )
        )
        detached_downloads = await self.db.execute(
            update(DownloadedFile)
            .where(
                DownloadedFile.task_id.is_not(None),
                DownloadedFile.task_id.not_in(existing_task_ids),
            )
            .values(task_id=None)
        )
        return {
            "orphan_logs": self._rowcount(orphan_logs),
            "detached_downloads": self._rowcount(detached_downloads),
        }

    @staticmethod
    def _rowcount(result: Any) -> int:
        rowcount = getattr(result, "rowcount", 0)
        return rowcount if isinstance(rowcount, int) and rowcount > 0 else 0
