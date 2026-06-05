"""
StarMap 爬虫核心模块

基于 Scrapy 架构思想设计的异步爬虫框架。

核心组件:
- engine: 爬虫执行引擎，协调所有组件
- spiders: 爬虫实现集合
- pipelines: 数据处理管道

使用示例:
    >>> from crawler.engine import CrawlerEngine, Scheduler, Downloader
    >>> from crawler.spiders.person_spider import PersonSpider
    >>> from crawler.pipelines import DataCleaningPipeline, DatabaseStoragePipeline
    >>>
    >>> spider = PersonSpider(source="baike", keywords=["周杰伦"])
    >>> engine = CrawlerEngine(
    ...     spider=spider,
    ...     scheduler=Scheduler(),
    ...     downloader=Downloader(),
    ...     pipelines=[DataCleaningPipeline(), DatabaseStoragePipeline()],
    ... )
    >>> stats = await engine.start()
"""

__version__ = "1.0.0"

from .engine import (
    CrawlerEngine,
    Scheduler,
    Downloader,
    Spider,
    Pipeline,
    Request,
    Response,
    Item,
    TaskStatus,
)

__all__ = [
    "CrawlerEngine",
    "Scheduler",
    "Downloader",
    "Spider",
    "Pipeline",
    "Request",
    "Response",
    "Item",
    "TaskStatus",
]