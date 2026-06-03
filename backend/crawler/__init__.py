"""StarMap 数据采集模块

提供维基百科爬虫、数据解析、清洗、验证和导入功能。
"""

from .base import BaseCrawler, CrawlerError
from .wikipedia import WikipediaCrawler
from .parser import WikipediaParser
from .cleaner import DataCleaner
from .validator import DataValidator
from .models import Person, Work, Relation

__all__ = [
    "BaseCrawler",
    "CrawlerError",
    "WikipediaCrawler",
    "WikipediaParser",
    "DataCleaner",
    "DataValidator",
    "Person",
    "Work",
    "Relation",
]
