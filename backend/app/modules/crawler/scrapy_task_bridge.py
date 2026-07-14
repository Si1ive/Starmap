"""Request-scoped bridge for publishing Scrapy tasks through Redis."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.mysql_models import CrawlSource, CrawlTask
from app.modules.crawler.log_service import CrawlerLogService
from app.modules.crawler.scrapy_protocol import TASK_QUEUE
from app.modules.operations.settings_service import SystemSettingsService

logger = get_logger(__name__)


class ScrapyTaskBridge:
    """Publish crawl tasks and inspect the shared Redis task queue."""

    TASK_QUEUE = TASK_QUEUE

    def __init__(self, db: AsyncSession):
        self.db = db
        self.log_service = CrawlerLogService(db)
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        """Get or create the request-scoped Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def publish_task(self, task: CrawlTask) -> bool:
        """Publish one crawl task with a runtime configuration snapshot."""
        try:
            redis = await self._get_redis()
            config = task.config or {}
            keywords = config.get("keywords") or config.get("targets") or []
            if isinstance(keywords, str):
                keywords = [
                    keyword.strip()
                    for keyword in keywords.split(",")
                    if keyword.strip()
                ]

            source_id = task.source_id or (
                config.get("source_ids") or [None]
            )[0]
            source_code = config.get("source") or task.source
            source = None
            if source_id:
                result = await self.db.execute(
                    select(CrawlSource).where(CrawlSource.id == source_id)
                )
                source = result.scalar_one_or_none()
            if not source:
                result = await self.db.execute(
                    select(CrawlSource)
                    .where(
                        CrawlSource.code.in_(
                            self._source_code_candidates(source_code)
                        )
                    )
                    .limit(1)
                )
                source = result.scalar_one_or_none()
            if source:
                source_id = source.id
            source_code = self._get_spider_key(source, source_code)

            runtime_config = await SystemSettingsService(
                self.db
            ).get_crawler_runtime_config()
            runtime_fingerprint = hashlib.sha256(
                json.dumps(
                    runtime_config,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:16]
            published_at = datetime.now(timezone.utc).isoformat()
            task_message = {
                "task_id": task.id,
                "task_type": task.task_type,
                "spider_type": config.get("spider_type", "github"),
                "source": source_code,
                "source_id": source_id,
                "keywords": keywords,
                "config": config,
                "runtime_config": runtime_config,
                "runtime_config_fingerprint": runtime_fingerprint,
                "published_at": published_at,
            }

            await redis.lpush(
                self.TASK_QUEUE,
                json.dumps(task_message, ensure_ascii=False),
            )
            logger.info(f"Published task to Scrapy: {task.id}")
            await self.log_service.create_log({
                "task_id": task.id,
                "source_id": source_id,
                "level": "INFO",
                "stage": "execution",
                "status": "pending",
                "message": f"Task published to Scrapy queue: {task.name}",
                "details": {
                    "runtime_config": (
                        SystemSettingsService.redact_crawler_runtime_config(
                            runtime_config
                        )
                    ),
                    "runtime_config_fingerprint": runtime_fingerprint,
                    "published_at": published_at,
                },
            })
            return True
        except Exception as exc:
            logger.error(f"Failed to publish task {task.id}: {exc}")
            await self.log_service.create_log({
                "task_id": task.id,
                "level": "ERROR",
                "stage": "execution",
                "status": "failed",
                "message": (
                    f"Failed to publish task to Scrapy: {str(exc)}"
                ),
            })
            return False

    @staticmethod
    def _get_spider_key(
        source: Optional[CrawlSource],
        fallback_code: Optional[str] = None,
    ) -> str:
        """Get the Scrapy spider key from source configuration."""
        if (
            source
            and isinstance(source.config, dict)
            and source.config.get("spider_key")
        ):
            return source.config["spider_key"]
        return (source.code if source else None) or fallback_code or "github"

    @staticmethod
    def _source_code_candidates(
        source_code: Optional[str],
    ) -> list[str]:
        """Return database source-code candidates for a Scrapy source key."""
        if not source_code:
            return []
        return [source_code]

    async def get_queue_length(self) -> int:
        """Return the number of tasks waiting in Redis."""
        try:
            redis = await self._get_redis()
            return await redis.llen(self.TASK_QUEUE)
        except Exception as exc:
            logger.error(f"Failed to get queue length: {exc}")
            return 0

    async def get_scrapy_status(self) -> Dict[str, Any]:
        """Return Redis connectivity and task-queue status."""
        try:
            redis = await self._get_redis()
            queue_length = await redis.llen(self.TASK_QUEUE)
            return {
                "status": (
                    "connected"
                    if queue_length >= 0
                    else "disconnected"
                ),
                "queue_length": queue_length,
                "redis_connected": True,
            }
        except Exception as exc:
            logger.error(f"Failed to get Scrapy status: {exc}")
            return {
                "status": "error",
                "error": str(exc),
                "redis_connected": False,
            }

    async def close(self) -> None:
        """Close the request-scoped Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("Scrapy task bridge closed")
