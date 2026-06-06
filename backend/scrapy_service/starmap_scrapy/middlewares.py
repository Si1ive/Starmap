"""
Scrapy middlewares for StarMap project.

This module contains spider and downloader middlewares.
"""

import logging
import random
from urllib.parse import urlparse

from scrapy import signals
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Request

logger = logging.getLogger(__name__)


class StarMapSpiderMiddleware:
    """Spider middleware for StarMap project."""

    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware

    def process_spider_input(self, response, spider):
        """Called for each response that goes through the spider middleware and into the spider."""
        return None

    async def process_spider_output_async(self, response, result, spider):
        """Called with the results returned from the Spider, after it has processed the response."""
        async for item in result:
            yield item

    def process_spider_exception(self, response, exception, spider):
        """Called when a spider or process_spider_input() method raises an exception."""
        logger.error(f"Spider exception: {exception}", extra={"spider": spider.name})

    def spider_opened(self, spider):
        logger.info(f"Spider opened: {spider.name}")


class StarMapDownloaderMiddleware:
    """Downloader middleware for StarMap project."""

    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware

    def process_request(self, request, spider):
        """Called for each request that goes through the downloader middleware."""
        # Add task_id to request meta if available
        if hasattr(spider, "task_id") and spider.task_id:
            request.meta["task_id"] = spider.task_id
        return None

    def process_response(self, request, response, spider):
        """Called with the response returned from the downloader."""
        # Log non-200 responses
        if response.status != 200:
            logger.warning(
                f"Non-200 response: {response.status} for {request.url}",
                extra={"spider": spider.name, "status": response.status}
            )
        return response

    def process_exception(self, request, exception, spider):
        """Called when a download handler or a process_request() raises an exception."""
        logger.error(
            f"Download exception: {exception} for {request.url}",
            extra={"spider": spider.name}
        )

    def spider_opened(self, spider):
        logger.info(f"Spider opened: {spider.name}")


class RotateUserAgentMiddleware:
    """
    Rotate User-Agent for each request to avoid being blocked.
    """

    # Common user agents
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]

    def __init__(self):
        self.user_agents = self.USER_AGENTS.copy()

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_request(self, request, spider):
        """Rotate user agent for each request."""
        user_agent = random.choice(self.user_agents)
        request.headers["User-Agent"] = user_agent
        return None


class DomainSpecificRetryMiddleware(RetryMiddleware):
    """
    Custom retry middleware with domain-specific settings.
    """

    # Domain-specific retry settings
    DOMAIN_RETRY_TIMES = {
        "baike.baidu.com": 5,
        "movie.douban.com": 3,
        "zh.wikipedia.org": 3,
    }

    def __init__(self, settings):
        super().__init__(settings)

    def _get_retry_times(self, request):
        """Get retry times based on domain."""
        domain = urlparse(request.url).netloc
        return self.DOMAIN_RETRY_TIMES.get(domain, self.max_retry_times)

    def process_response(self, request, response, spider):
        """Process response and retry if needed."""
        if request.meta.get("dont_retry", False):
            return response

        retry_times = self._get_retry_times(request)
        retries = request.meta.get("retry_times", 0) + 1

        if retries <= retry_times and response.status in self.retry_http_codes:
            logger.warning(
                f"Retrying {request.url} (failed {retries} times)",
                extra={"spider": spider.name}
            )
            retryreq = self._retry(request, response.status, spider)
            if retryreq:
                retryreq.meta["retry_times"] = retries
                return retryreq

        return response
