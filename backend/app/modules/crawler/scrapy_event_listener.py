"""Application-level listener for Scrapy progress and log events."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.websocket import log_websocket_manager
from app.db.mysql import mysql_client
from app.models.mysql_models import CrawlTask
from app.modules.crawler.log_service import CrawlerLogService
from app.modules.crawler.scrapy_protocol import (
    LOG_CHANNEL,
    PROGRESS_CHANNEL,
)

logger = get_logger(__name__)


def _utcnow() -> datetime:
    """Return naive UTC for existing MySQL DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class ScrapyEventListener:
    """Persist and broadcast Scrapy events using owned database sessions."""

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start listening for Scrapy progress and log events."""
        if self._task and not self._task.done():
            return

        self._redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(PROGRESS_CHANNEL, LOG_CHANNEL)
        self._running = True
        self._task = asyncio.create_task(self._listen())
        logger.info("Scrapy Redis event listener started")

    async def stop(self) -> None:
        """Stop listening and close Redis resources."""
        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._pubsub:
            await self._pubsub.unsubscribe(
                PROGRESS_CHANNEL,
                LOG_CHANNEL,
            )
            await self._pubsub.close()
            self._pubsub = None

        if self._redis:
            await self._redis.close()
            self._redis = None

        logger.info("Scrapy Redis event listener stopped")

    async def _listen(self) -> None:
        """Listen for Redis pub/sub messages."""
        if not self._pubsub:
            return

        while self._running:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if not message or message.get("type") != "message":
                    continue

                try:
                    data = json.loads(message.get("data") or "{}")
                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid Scrapy event message: "
                        f"{message.get('data')}"
                    )
                    continue

                channel = message.get("channel")
                if channel == PROGRESS_CHANNEL:
                    await self._handle_progress(data)
                elif channel == LOG_CHANNEL:
                    await self._handle_log(data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Scrapy event listener error: {exc}")
                await asyncio.sleep(1)

    async def _handle_progress(self, data: Dict[str, Any]) -> None:
        """Persist Scrapy progress updates to crawl_tasks."""
        task_id = data.get("task_id")
        if not task_id:
            return

        source_id = None
        async with mysql_client.session() as session:
            result = await session.execute(
                select(CrawlTask).where(CrawlTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if not task:
                logger.warning(
                    f"Task not found for Scrapy progress: {task_id}"
                )
                return

            status = data.get("status") or task.status
            progress = data.get("progress")
            task.status = status
            if progress is not None:
                task.progress = min(max(float(progress), 0), 100)

            if "success_count" in data:
                task.success_count = int(
                    data.get("success_count") or 0
                )
            else:
                task.success_count = int(
                    data.get("items_scraped") or 0
                )
            if "failure_count" in data:
                task.failed_count = int(
                    data.get("failure_count") or 0
                )
            else:
                task.failed_count = int(data.get("errors") or 0)
            task.completed_count = (
                (task.success_count or 0)
                + (task.failed_count or 0)
            )

            if "requests_made" in data:
                task.total_requests = int(
                    data.get("requests_made") or 0
                )
            if data.get("error_message"):
                task.error_message = str(
                    data["error_message"]
                )[:500]
            if status in ("completed", "failed", "stopped"):
                task.completed_at = _utcnow()
            elif status == "running" and not task.started_at:
                task.started_at = _utcnow()
            source_id = task.source_id

        await log_websocket_manager.broadcast({
            "type": "progress",
            "task_id": task_id,
            "source_id": source_id,
            "level": "INFO",
            "stage": "execution",
            "status": data.get("status"),
            "message": (
                f"Task progress updated: {data.get('progress', 0)}%"
            ),
            "details": data,
            "created_at": _utcnow().isoformat(),
        })

    async def _handle_log(self, data: Dict[str, Any]) -> None:
        """Persist Scrapy logs and broadcast them to admin clients."""
        task_id = data.get("task_id")
        if not task_id:
            return

        source_id = data.get("source_id")
        if not source_id:
            async with mysql_client.session() as session:
                result = await session.execute(
                    select(CrawlTask.source_id).where(
                        CrawlTask.id == task_id
                    )
                )
                source_id = result.scalar_one_or_none()

        log_data = {
            "task_id": task_id,
            "source_id": source_id,
            "level": data.get("level", "INFO"),
            "stage": data.get("stage", "execution"),
            "resource_url": data.get("resource_url"),
            "resource_name": data.get("resource_name"),
            "resource_type": data.get("resource_type"),
            "action": data.get("action"),
            "status": data.get("status", "pending"),
            "duration_ms": data.get("duration_ms"),
            "message": data.get("message"),
            "error_type": data.get("error_type"),
            "error_detail": data.get("error_detail"),
            "retry_count": data.get("retry_count", 0),
            "details": data.get("details"),
        }

        async with mysql_client.session() as session:
            created_log = await CrawlerLogService(
                session
            ).create_log(log_data)

        await log_websocket_manager.broadcast({
            **log_data,
            "id": created_log.id if created_log else None,
            "created_at": (
                created_log.created_at.isoformat()
                if created_log and created_log.created_at
                else _utcnow().isoformat()
            ),
        })


_scrapy_event_listener: Optional[ScrapyEventListener] = None


async def start_scrapy_event_listener() -> None:
    """Start the global Scrapy Redis event listener."""
    global _scrapy_event_listener
    if _scrapy_event_listener is None:
        _scrapy_event_listener = ScrapyEventListener()
    await _scrapy_event_listener.start()


async def stop_scrapy_event_listener() -> None:
    """Stop the global Scrapy Redis event listener."""
    global _scrapy_event_listener
    if _scrapy_event_listener:
        await _scrapy_event_listener.stop()
        _scrapy_event_listener = None
