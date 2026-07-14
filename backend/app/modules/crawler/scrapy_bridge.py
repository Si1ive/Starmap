"""
Scrapy Bridge Service

Bridges FastAPI with the Scrapy service via Redis.
Handles task publishing, progress subscription, and status synchronization.
"""

import asyncio
import hashlib
import json
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.websocket import log_websocket_manager
from app.db.mysql import mysql_client
from app.models.mysql_models import CrawlSource, CrawlTask
from app.modules.crawler.log_service import CrawlerLogService
from app.services.system_settings_service import SystemSettingsService

logger = get_logger(__name__)


TASK_QUEUE = "crawler:tasks"
PROGRESS_CHANNEL = "crawler:progress"
LOG_CHANNEL = "crawler:logs"


class ScrapyBridgeService:
    """
    Bridge service between FastAPI and Scrapy.
    
    Uses Redis for task queue and progress pub/sub.
    """
    
    # Redis key constants
    TASK_QUEUE = TASK_QUEUE
    PROGRESS_CHANNEL = PROGRESS_CHANNEL
    LOG_CHANNEL = LOG_CHANNEL
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.log_service = CrawlerLogService(db)
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._progress_callbacks: Dict[str, Callable] = {}
        self._running = False
    
    async def _get_redis(self) -> aioredis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    async def publish_task(self, task: CrawlTask) -> bool:
        """
        Publish a crawl task to Redis queue for Scrapy to consume.
        
        Args:
            task: CrawlTask instance to publish
            
        Returns:
            bool: True if published successfully
        """
        try:
            redis = await self._get_redis()
            config = task.config or {}
            keywords = config.get("keywords") or config.get("targets") or []
            if isinstance(keywords, str):
                keywords = [keyword.strip() for keyword in keywords.split(",") if keyword.strip()]
            
            source_id = task.source_id or (config.get("source_ids") or [None])[0]
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
                    .where(CrawlSource.code.in_(self._source_code_candidates(source_code)))
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

            # Build task message
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
            
            # Push to Redis queue
            await redis.lpush(self.TASK_QUEUE, json.dumps(task_message, ensure_ascii=False))
            
            logger.info(f"Published task to Scrapy: {task.id}")
            
            # Log the publish action
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
            
        except Exception as e:
            logger.error(f"Failed to publish task {task.id}: {e}")
            await self.log_service.create_log({
                "task_id": task.id,
                "level": "ERROR",
                "stage": "execution",
                "status": "failed",
                "message": f"Failed to publish task to Scrapy: {str(e)}",
            })
            return False

    @staticmethod
    def _get_spider_key(source: Optional[CrawlSource], fallback_code: Optional[str] = None) -> str:
        """Get scrapy spider key from source config."""
        if source and isinstance(source.config, dict) and source.config.get("spider_key"):
            return source.config["spider_key"]
        code = (source.code if source else None) or fallback_code or "github"
        return code

    @staticmethod
    def _source_code_candidates(source_code: Optional[str]) -> list[str]:
        """Return database source code candidates for a Scrapy source key."""
        if not source_code:
            return []
        return [source_code]
    
    async def subscribe_progress(self, task_id: str, callback: Optional[Callable] = None):
        """
        Subscribe to progress updates for a specific task.
        
        Args:
            task_id: Task ID to subscribe to
            callback: Optional callback function for progress updates
        """
        try:
            redis = await self._get_redis()
            
            # Create pubsub connection
            self._pubsub = redis.pubsub()
            await self._pubsub.subscribe(self.PROGRESS_CHANNEL)
            
            if callback:
                self._progress_callbacks[task_id] = callback
            
            self._running = True
            
            logger.info(f"Subscribed to progress for task: {task_id}")
            
            # Start listening for messages
            asyncio.create_task(self._listen_progress(task_id))
            
        except Exception as e:
            logger.error(f"Failed to subscribe to progress: {e}")
    
    async def _listen_progress(self, task_id: str):
        """Listen for progress updates from Scrapy."""
        try:
            while self._running:
                message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                
                if message and message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        
                        # Check if this message is for our task
                        if data.get("task_id") == task_id:
                            await self._handle_progress_update(task_id, data)
                            
                            # Call user callback if provided
                            if task_id in self._progress_callbacks:
                                callback = self._progress_callbacks[task_id]
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(data)
                                else:
                                    callback(data)
                    
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid progress message: {message['data']}")
                        
        except Exception as e:
            logger.error(f"Progress listener error: {e}")
        finally:
            if self._pubsub:
                await self._pubsub.unsubscribe(self.PROGRESS_CHANNEL)
    
    async def _handle_progress_update(self, task_id: str, data: Dict[str, Any]):
        """Handle progress update from Scrapy."""
        try:
            # Get task from database
            result = await self.db.execute(
                select(CrawlTask).where(CrawlTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            
            if not task:
                logger.warning(f"Task not found for progress update: {task_id}")
                return
            
            # Update task status
            status = data.get("status", "running")
            progress = data.get("progress", 0)
            
            task.status = status
            task.progress = min(progress, 100)
            
            if "success_count" in data:
                task.success_count = data["success_count"]
            elif "items_scraped" in data:
                task.success_count = data["items_scraped"]
            if "failure_count" in data:
                task.failed_count = data["failure_count"]
            elif "errors" in data:
                task.failed_count = data["errors"]
            task.completed_count = (task.success_count or 0) + (task.failed_count or 0)
            if "requests_made" in data:
                task.total_requests = data["requests_made"]
            if "error_message" in data:
                task.error_message = str(data["error_message"])[:500]
            
            # If completed or failed, set completed_at
            if status in ("completed", "failed"):
                task.completed_at = datetime.utcnow()
            
            await self.db.commit()
            
            logger.info(
                f"Task {task_id} progress: {progress}%, status: {status}, "
                f"items: {data.get('items_scraped', 0)}"
            )
            
        except Exception as e:
            logger.error(f"Failed to handle progress update: {e}")
    
    async def unsubscribe_progress(self, task_id: str):
        """Unsubscribe from progress updates."""
        self._progress_callbacks.pop(task_id, None)
        
        if not self._progress_callbacks and self._pubsub:
            self._running = False
            await self._pubsub.unsubscribe(self.PROGRESS_CHANNEL)
            logger.info("Unsubscribed from progress updates")
    
    async def get_queue_length(self) -> int:
        """Get the number of tasks in the Redis queue."""
        try:
            redis = await self._get_redis()
            return await redis.llen(self.TASK_QUEUE)
        except Exception as e:
            logger.error(f"Failed to get queue length: {e}")
            return 0
    
    async def get_scrapy_status(self) -> Dict[str, Any]:
        """
        Get Scrapy service status.
        
        Returns:
            Dict with queue length, connection status, etc.
        """
        try:
            redis = await self._get_redis()
            queue_length = await redis.llen(self.TASK_QUEUE)
            
            # Check if Scrapy is running by checking if it's consuming tasks
            # This is a simple heuristic - Scrapy should be actively consuming
            
            return {
                "status": "connected" if queue_length >= 0 else "disconnected",
                "queue_length": queue_length,
                "redis_connected": True,
            }
            
        except Exception as e:
            logger.error(f"Failed to get Scrapy status: {e}")
            return {
                "status": "error",
                "error": str(e),
                "redis_connected": False,
            }
    
    async def close(self):
        """Close Redis connections."""
        self._running = False
        
        if self._pubsub:
            await self._pubsub.close()
        
        if self._redis:
            await self._redis.close()
        
        logger.info("Scrapy bridge service closed")


class ScrapyEventListener:
    """
    Application-level Redis event listener for Scrapy progress and logs.

    The listener owns its own database sessions so task updates do not depend on
    short-lived request sessions.
    """

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start listening for Scrapy progress/log events."""
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
            await self._pubsub.unsubscribe(PROGRESS_CHANNEL, LOG_CHANNEL)
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
                    logger.warning(f"Invalid Scrapy event message: {message.get('data')}")
                    continue

                channel = message.get("channel")
                if channel == PROGRESS_CHANNEL:
                    await self._handle_progress(data)
                elif channel == LOG_CHANNEL:
                    await self._handle_log(data)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Scrapy event listener error: {e}")
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
                logger.warning(f"Task not found for Scrapy progress: {task_id}")
                return

            status = data.get("status") or task.status
            progress = data.get("progress")

            task.status = status
            if progress is not None:
                task.progress = min(max(float(progress), 0), 100)

            # Use explicit success/failure counts if available
            if "success_count" in data:
                task.success_count = int(data.get("success_count") or 0)
            else:
                task.success_count = int(data.get("items_scraped") or 0)
            if "failure_count" in data:
                task.failed_count = int(data.get("failure_count") or 0)
            else:
                task.failed_count = int(data.get("errors") or 0)
            task.completed_count = (task.success_count or 0) + (task.failed_count or 0)

            if "requests_made" in data:
                task.total_requests = int(data.get("requests_made") or 0)
            if data.get("error_message"):
                task.error_message = str(data["error_message"])[:500]
            if status in ("completed", "failed", "stopped"):
                task.completed_at = datetime.utcnow()
            elif status == "running" and not task.started_at:
                task.started_at = datetime.utcnow()
            source_id = task.source_id

        await log_websocket_manager.broadcast({
            "type": "progress",
            "task_id": task_id,
            "source_id": source_id,
            "level": "INFO",
            "stage": "execution",
            "status": data.get("status"),
            "message": f"Task progress updated: {data.get('progress', 0)}%",
            "details": data,
            "created_at": datetime.utcnow().isoformat(),
        })

    async def _handle_log(self, data: Dict[str, Any]) -> None:
        """Persist Scrapy log entries and broadcast them to admin clients."""
        task_id = data.get("task_id")
        if not task_id:
            return

        source_id = data.get("source_id")
        if not source_id:
            async with mysql_client.session() as session:
                result = await session.execute(
                    select(CrawlTask.source_id).where(CrawlTask.id == task_id)
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
            log_service = CrawlerLogService(session)
            created_log = await log_service.create_log(log_data)

        broadcast_data = {
            **log_data,
            "id": created_log.id if created_log else None,
            "created_at": (
                created_log.created_at.isoformat()
                if created_log and created_log.created_at
                else datetime.utcnow().isoformat()
            ),
        }
        await log_websocket_manager.broadcast(broadcast_data)


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
