"""
爬虫执行引擎 (CrawlerEngine)

基于 Scrapy 架构思想设计的 StarMap 爬虫核心引擎。
负责协调调度器、下载器、爬虫和数据管道的数据流。

数据流:
1. Engine 从 Spider 获取初始 Requests
2. Engine 将 Requests 送入 Scheduler
3. Scheduler 返回下一个 Request 给 Engine
4. Engine 将 Request 发送给 Downloader
5. Downloader 下载完成后返回 Response 给 Engine
6. Engine 将 Response 发送给 Spider 解析
7. Spider 返回 Items 和新的 Requests
8. Engine 将 Items 发送给 Pipeline，Requests 发送给 Scheduler
9. 循环直到 Scheduler 没有更多 Requests
"""

import asyncio
import time
from typing import Optional, Dict, Any, List, Callable, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.core.logging import get_logger

logger = get_logger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class Request:
    """爬取请求"""
    url: str
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    callback: Optional[str] = None
    errback: Optional[str] = None
    priority: int = 0
    dont_filter: bool = False


@dataclass
class Response:
    """爬取响应"""
    url: str
    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    request: Optional[Request] = None
    duration: float = 0.0


@dataclass
class Item:
    """爬取数据项"""
    item_type: str
    data: Dict[str, Any] = field(default_factory=dict)
    source_url: str = ""
    crawled_at: datetime = field(default_factory=datetime.utcnow)


class Scheduler:
    """
    请求调度器
    
    管理待爬取的请求队列，支持优先级排序和去重。
    """

    def __init__(self):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seen: set = set()
        self._count: int = 0

    async def enqueue(self, request: Request) -> bool:
        """
        将请求加入队列
        
        Args:
            request: 爬取请求
            
        Returns:
            是否成功加入（False表示已存在）
        """
        # 去重检查
        if not request.dont_filter:
            fingerprint = self._request_fingerprint(request)
            if fingerprint in self._seen:
                return False
            self._seen.add(fingerprint)
        
        # 加入优先级队列（优先级数字越小越优先）
        await self._queue.put((-request.priority, self._count, request))
        self._count += 1
        return True

    async def dequeue(self) -> Optional[Request]:
        """
        从队列取出下一个请求
        
        Returns:
            下一个请求，如果队列为空返回 None
        """
        try:
            _, _, request = self._queue.get_nowait()
            return request
        except asyncio.QueueEmpty:
            return None

    def has_pending(self) -> bool:
        """是否有待处理的请求"""
        return not self._queue.empty()

    def get_stats(self) -> Dict[str, int]:
        """获取调度器统计"""
        return {
            "pending": self._queue.qsize(),
            "total_seen": len(self._seen),
        }

    @staticmethod
    def _request_fingerprint(request: Request) -> str:
        """生成请求指纹用于去重"""
        return f"{request.method}:{request.url}"


class Downloader:
    """
    下载器
    
    负责执行 HTTP 请求，支持并发控制、重试、限速。
    """

    def __init__(
        self,
        concurrent_limit: int = 5,
        delay: float = 1.0,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.concurrent_limit = concurrent_limit
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self._semaphore = asyncio.Semaphore(concurrent_limit)
        self._last_request_time: Optional[float] = None
        self._stats = {
            "total_requests": 0,
            "success_count": 0,
            "failed_count": 0,
            "total_duration": 0.0,
        }

    async def fetch(self, request: Request) -> Response:
        """
        执行单个请求
        
        Args:
            request: 爬取请求
            
        Returns:
            响应对象
        """
        async with self._semaphore:
            # 限速控制
            await self._apply_delay()
            
            start_time = time.time()
            self._stats["total_requests"] += 1
            
            try:
                # 实际 HTTP 请求
                response = await self._do_request(request)
                self._stats["success_count"] += 1
                self._stats["total_duration"] += response.duration
                return response
            except Exception as e:
                self._stats["failed_count"] += 1
                logger.error(f"Request failed: {request.url}, error: {e}")
                return Response(
                    url=request.url,
                    status_code=0,
                    body="",
                    request=request,
                    duration=time.time() - start_time,
                )

    async def _do_request(self, request: Request) -> Response:
        """执行实际 HTTP 请求"""
        import aiohttp
        
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=request.method,
                url=request.url,
                headers=request.headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                body = await resp.text()
                duration = time.time() - start_time
                
                return Response(
                    url=str(resp.url),
                    status_code=resp.status,
                    headers=dict(resp.headers),
                    body=body,
                    request=request,
                    duration=duration,
                )

    async def _apply_delay(self):
        """应用请求延迟"""
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
        self._last_request_time = time.time()

    def get_stats(self) -> Dict[str, Any]:
        """获取下载器统计"""
        stats = self._stats.copy()
        if stats["total_requests"] > 0:
            stats["avg_duration"] = stats["total_duration"] / stats["total_requests"]
            stats["success_rate"] = stats["success_count"] / stats["total_requests"]
        return stats


class Spider:
    """
    爬虫基类
    
    所有具体爬虫必须继承此类，实现 parse 方法。
    参考 Scrapy 的 Spider 设计。
    """

    name: str = "base_spider"
    start_urls: List[str] = []
    custom_settings: Dict[str, Any] = {}

    def __init__(self, **kwargs):
        self.settings = {**self.custom_settings, **kwargs}
        self._crawler: Optional["CrawlerEngine"] = None

    def set_crawler(self, crawler: "CrawlerEngine"):
        """设置关联的引擎"""
        self._crawler = crawler

    async def start(self) -> AsyncIterator[Request]:
        """
        生成初始请求
        
        子类可以覆盖此方法自定义起始请求。
        """
        for url in self.start_urls:
            yield Request(url=url, callback="parse", dont_filter=True)

    async def parse(self, response: Response) -> AsyncIterator[Any]:
        """
        解析响应
        
        子类必须实现此方法，返回 Item 或 Request。
        
        Args:
            response: 下载的响应
            
        Yields:
            Item 或 Request 对象
        """
        raise NotImplementedError("Spider must implement parse method")

    async def handle_error(self, failure: Exception, request: Request):
        """处理请求错误"""
        logger.error(f"Spider error: {failure}, url: {request.url}")

    def closed(self, reason: str):
        """爬虫关闭时调用"""
        logger.info(f"Spider closed: {self.name}, reason: {reason}")


class Pipeline:
    """
    数据处理管道
    
    处理 Spider 提取的 Item，支持清洗、验证、存储。
    """

    async def process_item(self, item: Item, spider: Spider) -> Optional[Item]:
        """
        处理单个 Item
        
        Args:
            item: 数据项
            spider: 来源爬虫
            
        Returns:
            处理后的 Item，如果返回 None 则丢弃
        """
        return item

    async def open(self):
        """打开管道"""
        pass

    async def close(self):
        """关闭管道"""
        pass


class CrawlerEngine:
    """
    爬虫执行引擎
    
    协调所有组件，控制数据流。
    """

    def __init__(
        self,
        spider: Spider,
        scheduler: Optional[Scheduler] = None,
        downloader: Optional[Downloader] = None,
        pipelines: Optional[List[Pipeline]] = None,
        max_concurrent: int = 5,
    ):
        self.spider = spider
        self.scheduler = scheduler or Scheduler()
        self.downloader = downloader or Downloader(concurrent_limit=max_concurrent)
        self.pipelines = pipelines or []
        self.max_concurrent = max_concurrent
        
        self._status = TaskStatus.PENDING
        self._task: Optional[asyncio.Task] = None
        self._stats = {
            "items_scraped": 0,
            "requests_scheduled": 0,
            "responses_received": 0,
            "start_time": None,
            "end_time": None,
        }
        
        # 设置爬虫关联
        self.spider.set_crawler(self)

    async def start(self) -> Dict[str, Any]:
        """
        启动爬虫
        
        Returns:
            执行统计
        """
        if self._status == TaskStatus.RUNNING:
            logger.warning("Engine already running")
            return self._stats
        
        self._status = TaskStatus.RUNNING
        self._stats["start_time"] = datetime.utcnow()
        
        logger.info(f"Starting crawler: {self.spider.name}")
        
        # 打开管道
        for pipeline in self.pipelines:
            await pipeline.open()
        
        # 获取初始请求
        initial_count = 0
        async for request in self.spider.start():
            await self.scheduler.enqueue(request)
            self._stats["requests_scheduled"] += 1
            initial_count += 1
            logger.info(f"Scheduled initial request: {request.url}")
        
        logger.info(f"Spider generated {initial_count} initial requests, scheduler pending: {self.scheduler.has_pending()}")
        
        # 主循环
        try:
            await self._main_loop()
            self._status = TaskStatus.COMPLETED
        except asyncio.CancelledError:
            self._status = TaskStatus.STOPPED
            logger.info("Crawler stopped by user")
        except Exception as e:
            self._status = TaskStatus.FAILED
            logger.error(f"Crawler failed: {e}")
        finally:
            self._stats["end_time"] = datetime.utcnow()
            await self._close()
        
        return self._stats

    async def stop(self):
        """停止爬虫"""
        if self._task:
            self._task.cancel()
        self._status = TaskStatus.STOPPED

    async def _main_loop(self):
        """主循环"""
        loop_count = 0
        while self.scheduler.has_pending() and self._status == TaskStatus.RUNNING:
            loop_count += 1
            # 获取下一个请求
            request = await self.scheduler.dequeue()
            if not request:
                await asyncio.sleep(0.1)
                continue
            
            logger.info(f"[Loop {loop_count}] Processing request: {request.url}")
            
            # 下载
            response = await self.downloader.fetch(request)
            self._stats["responses_received"] += 1
            
            logger.info(f"[Loop {loop_count}] Response: status={response.status_code}, url={response.url}, duration={response.duration:.2f}s")
            
            if response.status_code == 0:
                # 下载失败，调用错误处理
                logger.warning(f"[Loop {loop_count}] Download failed: {request.url}")
                if request.errback:
                    await getattr(self.spider, request.errback)(response)
                continue
            
            # 解析
            callback_name = request.callback or "parse"
            callback = getattr(self.spider, callback_name)
            
            try:
                result_count = 0
                async for result in callback(response):
                    result_count += 1
                    if isinstance(result, Request):
                        # 新的请求
                        await self.scheduler.enqueue(result)
                        self._stats["requests_scheduled"] += 1
                        logger.info(f"[Loop {loop_count}] New request scheduled: {result.url}")
                    elif isinstance(result, Item):
                        # 数据项
                        await self._process_item(result)
                        self._stats["items_scraped"] += 1
                        logger.info(f"[Loop {loop_count}] Item scraped: type={result.item_type}, source={result.source_url}")
                
                logger.info(f"[Loop {loop_count}] Parsed {result_count} results from {response.url}")
            except Exception as e:
                logger.error(f"[Loop {loop_count}] Parse error: {e}, url: {response.url}")
                await self.spider.handle_error(e, request)
        
        logger.info(f"Main loop finished after {loop_count} iterations. Status: {self._status.value}")

    async def _process_item(self, item: Item):
        """处理数据项"""
        for pipeline in self.pipelines:
            try:
                item = await pipeline.process_item(item, self.spider)
                if item is None:
                    break
            except Exception as e:
                logger.error(f"Pipeline error: {e}")
                break

    async def _close(self):
        """关闭引擎"""
        # 关闭管道
        for pipeline in self.pipelines:
            await pipeline.close()
        
        # 关闭爬虫
        self.spider.closed(self._status.value)
        
        logger.info(f"Crawler finished: {self.spider.name}, stats: {self._stats}")

    def get_status(self) -> TaskStatus:
        """获取当前状态"""
        return self._status

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self._stats.copy()
        stats["scheduler"] = self.scheduler.get_stats()
        stats["downloader"] = self.downloader.get_stats()
        stats["status"] = self._status.value
        return stats
