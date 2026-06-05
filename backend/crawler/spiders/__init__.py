"""
爬虫集合

提供各种预定义的爬虫实现。
"""

from .person_spider import PersonSpider
from .work_spider import WorkSpider

__all__ = ["PersonSpider", "WorkSpider"]
