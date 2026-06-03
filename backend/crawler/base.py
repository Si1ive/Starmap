"""爬虫基类

提供所有爬虫的基础功能，包括：
- 请求频率控制（≤1 req/s）
- User-Agent 池轮换
- 重试机制
- 日志记录
- 响应缓存
"""

import time
import random
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志
logger = logging.getLogger(__name__)


class CrawlerError(Exception):
    """爬虫基础异常"""

    pass


class FetchError(CrawlerError):
    """获取页面失败"""

    pass


class ParseError(CrawlerError):
    """解析页面失败"""

    pass


class RateLimitError(CrawlerError):
    """请求频率超限"""

    pass


@dataclass
class CrawlResult:
    """爬取结果"""

    url: str
    html: Optional[str] = None
    status_code: Optional[int] = None
    headers: Optional[Dict[str, str]] = None
    error: Optional[str] = None
    duration: float = 0.0

    @property
    def success(self) -> bool:
        """是否成功"""
        return self.html is not None and self.error is None


class BaseCrawler:
    """爬虫基类

    所有具体爬虫的基类，提供通用的HTTP请求、频率控制、重试等功能。

    使用示例:
        >>> class MyCrawler(BaseCrawler):
        ...     def parse(self, html: str) -> dict:
        ...         # 实现解析逻辑
        ...         pass
        ...
        >>> crawler = MyCrawler(delay=1.5)
        >>> result = crawler.fetch("https://example.com")
        >>> data = crawler.parse(result.html)
    """

    # User-Agent 池
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    # 默认请求头
    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(
        self,
        delay: float = 1.0,
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        use_proxy: bool = False,
        proxy_url: Optional[str] = None,
    ):
        """初始化爬虫

        Args:
            delay: 请求间隔（秒），默认1.0，必须≥1.0以遵守规范
            timeout: 请求超时（秒）
            max_retries: 最大重试次数
            retry_delay: 重试间隔（秒）
            use_proxy: 是否使用代理
            proxy_url: 代理URL
        """
        # 确保请求频率不超过1 req/s
        self.delay = max(delay, 1.0)
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url

        # 上次请求时间
        self._last_request_time: Optional[float] = None

        # 创建Session
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)

        # 配置重试策略
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        logger.info(
            f"BaseCrawler initialized: delay={delay}s, timeout={timeout}s, "
            f"max_retries={max_retries}"
        )

    def _get_random_user_agent(self) -> str:
        """获取随机User-Agent"""
        return random.choice(self.USER_AGENTS)

    def _wait_for_rate_limit(self):
        """等待以控制请求频率"""
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.delay:
                wait_time = self.delay - elapsed
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                time.sleep(wait_time)
        self._last_request_time = time.time()

    def _get_proxies(self) -> Optional[Dict[str, str]]:
        """获取代理配置"""
        if self.use_proxy and self.proxy_url:
            return {
                "http": self.proxy_url,
                "https": self.proxy_url,
            }
        return None

    def fetch(self, url: str, headers: Optional[Dict[str, str]] = None) -> CrawlResult:
        """获取页面内容

        Args:
            url: 目标URL
            headers: 额外的请求头

        Returns:
            CrawlResult: 爬取结果

        Raises:
            FetchError: 获取失败时抛出
            RateLimitError: 被限流时抛出
        """
        self._wait_for_rate_limit()

        # 设置请求头
        request_headers = {"User-Agent": self._get_random_user_agent()}
        if headers:
            request_headers.update(headers)

        start_time = time.time()

        try:
            logger.info(f"Fetching: {url}")
            response = self.session.get(
                url,
                headers=request_headers,
                timeout=self.timeout,
                proxies=self._get_proxies(),
            )
            duration = time.time() - start_time

            # 检查状态码
            if response.status_code == 429:
                logger.warning(f"Rate limited: {url}")
                raise RateLimitError(f"Rate limited by {url}")

            response.raise_for_status()

            logger.info(
                f"Fetched: {url} - Status {response.status_code} - {duration:.2f}s"
            )

            return CrawlResult(
                url=url,
                html=response.text,
                status_code=response.status_code,
                headers=dict(response.headers),
                duration=duration,
            )

        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            logger.error(f"Failed to fetch {url}: {e}")
            return CrawlResult(
                url=url,
                error=str(e),
                duration=duration,
            )

    def fetch_with_retry(self, url: str, headers: Optional[Dict[str, str]] = None) -> CrawlResult:
        """带重试的页面获取

        Args:
            url: 目标URL
            headers: 额外的请求头

        Returns:
            CrawlResult: 爬取结果
        """
        for attempt in range(self.max_retries + 1):
            result = self.fetch(url, headers)
            if result.success:
                return result

            if attempt < self.max_retries:
                wait = self.retry_delay * (2 ** attempt)  # 指数退避
                logger.warning(
                    f"Retry {attempt + 1}/{self.max_retries} for {url} after {wait:.1f}s"
                )
                time.sleep(wait)

        logger.error(f"Failed to fetch {url} after {self.max_retries + 1} attempts")
        return result

    def parse(self, html: str) -> Any:
        """解析页面内容

        子类必须实现此方法。

        Args:
            html: 页面HTML内容

        Returns:
            解析结果，类型由子类决定

        Raises:
            NotImplementedError: 基类未实现
        """
        raise NotImplementedError("Subclasses must implement parse()")

    def close(self):
        """关闭Session"""
        self.session.close()
        logger.info("Crawler session closed")

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
        return False
