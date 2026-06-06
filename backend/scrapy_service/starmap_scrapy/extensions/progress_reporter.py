"""
Progress Reporter Extension for Scrapy.

Reports crawl progress to Redis Pub/Sub channel for real-time monitoring.
"""

import json
import logging
import time
import redis
from scrapy import signals
from scrapy.exceptions import NotConfigured

logger = logging.getLogger(__name__)


class ProgressReporterExtension:
    """
    Reports crawl progress to Redis Pub/Sub.
    
    Publishes progress updates to 'starmap:crawl:progress' channel.
    Each message contains:
    - task_id: Task identifier
    - progress: Progress percentage (0-100)
    - items_scraped: Number of items scraped
    - requests_made: Number of requests made
    - status: running, completed, failed
    - timestamp: Current timestamp
    """

    def __init__(self, crawler, redis_url, progress_channel, log_channel):
        self.crawler = crawler
        self.redis_client = redis.from_url(redis_url)
        self.progress_channel = progress_channel
        self.log_channel = log_channel
        self.start_time = None
        self.stats = {
            "items_scraped": 0,
            "requests_made": 0,
            "responses_received": 0,
            "errors": 0,
        }

    @classmethod
    def from_crawler(cls, crawler):
        """Create extension instance from crawler settings."""
        redis_url = crawler.settings.get("REDIS_URL")
        progress_channel = crawler.settings.get("REDIS_PROGRESS_CHANNEL", "starmap:crawl:progress")
        log_channel = crawler.settings.get("REDIS_LOG_CHANNEL", "starmap:crawl:logs")
        
        if not redis_url:
            raise NotConfigured("REDIS_URL not set")
        
        ext = cls(crawler, redis_url, progress_channel, log_channel)
        
        # Connect signals
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        crawler.signals.connect(ext.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(ext.request_scheduled, signal=signals.request_scheduled)
        crawler.signals.connect(ext.response_received, signal=signals.response_received)
        crawler.signals.connect(ext.spider_error, signal=signals.spider_error)
        
        return ext

    def spider_opened(self, spider):
        """Called when spider is opened."""
        self.start_time = time.time()
        self._report_progress(spider, status="running", progress=0)
        logger.info(f"Progress reporter started for task: {getattr(spider, 'task_id', 'unknown')}")

    def spider_closed(self, spider, reason):
        """Called when spider is closed."""
        duration = time.time() - self.start_time if self.start_time else 0
        status = "completed" if reason == "finished" else "failed"
        
        self._report_progress(
            spider,
            status=status,
            progress=100,
            duration=duration,
        )
        logger.info(
            f"Progress reporter stopped for task: {getattr(spider, 'task_id', 'unknown')}, "
            f"reason: {reason}, duration: {duration:.2f}s"
        )

    def item_scraped(self, item, spider):
        """Called when an item is scraped."""
        self.stats["items_scraped"] += 1
        # Report progress every 5 items
        if self.stats["items_scraped"] % 5 == 0:
            progress = self._calculate_progress(spider)
            self._report_progress(spider, progress=progress)

    def request_scheduled(self, request, spider):
        """Called when a request is scheduled."""
        self.stats["requests_made"] += 1

    def response_received(self, response, request, spider):
        """Called when a response is received."""
        self.stats["responses_received"] += 1

    def spider_error(self, failure, response, spider):
        """Called when a spider error occurs."""
        self.stats["errors"] += 1
        self._report_log(
            spider,
            level="ERROR",
            message=f"Spider error: {failure.getErrorMessage()}",
            error_type=failure.type.__name__ if hasattr(failure, "type") else "Unknown",
            error_detail=str(failure.value) if hasattr(failure, "value") else "",
        )

    def _calculate_progress(self, spider):
        """Calculate progress percentage."""
        # Simple heuristic: assume 10 requests per keyword
        keywords_count = len(getattr(spider, "keywords", []))
        if keywords_count == 0:
            return 0
        
        expected_requests = keywords_count * 10
        progress = min(95, (self.stats["responses_received"] / expected_requests) * 100)
        return round(progress, 2)

    def _report_progress(self, spider, status="running", progress=None, duration=None):
        """Publish progress update to Redis."""
        task_id = getattr(spider, "task_id", None)
        if not task_id:
            return
        
        message = {
            "task_id": task_id,
            "status": status,
            "progress": progress if progress is not None else self._calculate_progress(spider),
            "items_scraped": self.stats["items_scraped"],
            "requests_made": self.stats["requests_made"],
            "responses_received": self.stats["responses_received"],
            "errors": self.stats["errors"],
            "duration": duration,
            "timestamp": time.time(),
        }
        
        try:
            self.redis_client.publish(self.progress_channel, json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to publish progress: {e}")

    def _report_log(self, spider, level, message, error_type=None, error_detail=None):
        """Publish log entry to Redis."""
        task_id = getattr(spider, "task_id", None)
        if not task_id:
            return
        
        log_entry = {
            "task_id": task_id,
            "level": level,
            "stage": "execution",
            "message": message,
            "error_type": error_type,
            "error_detail": error_detail,
            "timestamp": time.time(),
        }
        
        try:
            self.redis_client.publish(self.log_channel, json.dumps(log_entry))
        except Exception as e:
            logger.error(f"Failed to publish log: {e}")
