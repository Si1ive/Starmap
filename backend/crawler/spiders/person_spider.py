"""
人物信息爬虫

爬取艺人（Person）相关信息的爬虫实现。
支持从多个数据源（百度百科、豆瓣、维基百科等）爬取人物信息。
"""

import re
import json
from typing import AsyncIterator, Optional, Dict, Any, List
from datetime import datetime

from crawler.engine import Spider, Request, Response, Item
from app.core.logging import get_logger

logger = get_logger(__name__)


class PersonSpider(Spider):
    """
    人物信息爬虫
    
    从多个数据源爬取艺人信息，支持：
    - 百度百科
    - 豆瓣电影
    - 维基百科
    - 自定义数据源
    """

    name = "person"
    
    # 数据源配置
    SOURCES = {
        "baike": {
            "base_url": "https://baike.baidu.com/item/",
            "search_url": "https://baike.baidu.com/search/word?word={keyword}",
        },
        "douban": {
            "base_url": "https://movie.douban.com/celebrity/",
            "search_url": "https://movie.douban.com/subject_search?search_text={keyword}",
        },
        "wikipedia": {
            "base_url": "https://zh.wikipedia.org/wiki/",
            "search_url": "https://zh.wikipedia.org/w/index.php?search={keyword}",
        },
    }

    def __init__(self, source: str = "baike", keywords: Optional[List[str]] = None, **kwargs):
        """
        初始化人物爬虫
        
        Args:
            source: 数据源名称 (baike/douban/wikipedia)
            keywords: 搜索关键词列表
            **kwargs: 其他配置
        """
        super().__init__(**kwargs)
        self.source = source
        self.keywords = keywords or []
        self.source_config = self.SOURCES.get(source, self.SOURCES["baike"])
        
        # 设置起始 URL
        if keywords:
            self.start_urls = [
                self.source_config["search_url"].format(keyword=kw)
                for kw in keywords
            ]
        else:
            self.start_urls = []

    async def start(self) -> AsyncIterator[Request]:
        """
        生成初始请求
        
        根据关键词生成搜索请求。
        """
        if not self.keywords:
            logger.warning("No keywords provided for PersonSpider")
            return
        
        for keyword in self.keywords:
            url = self.source_config["search_url"].format(keyword=keyword)
            logger.info(f"PersonSpider starting search: {keyword}, url: {url}")
            yield Request(
                url=url,
                callback="parse_search",
                meta={"keyword": keyword, "source": self.source},
                dont_filter=True,
            )

    async def parse_search(self, response: Response) -> AsyncIterator[Any]:
        """
        解析搜索结果页
        
        提取搜索结果中的详情页链接。
        """
        keyword = response.meta.get("keyword", "")
        logger.info(f"Parsing search results for: {keyword}")
        
        if self.source == "baike":
            async for result in self._parse_baike_search(response):
                yield result
        elif self.source == "douban":
            async for result in self._parse_douban_search(response):
                yield result
        elif self.source == "wikipedia":
            async for result in self._parse_wikipedia_search(response):
                yield result

    async def _parse_baike_search(self, response: Response) -> AsyncIterator[Any]:
        """解析百度百科搜索结果"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        
        # 提取搜索结果中的链接
        results = soup.select(".search-list dd a")
        
        for i, result in enumerate(results[:5]):  # 限制前5个结果
            href = result.get("href", "")
            title = result.get_text(strip=True)
            
            if href and title:
                # 构建完整 URL
                if href.startswith("/"):
                    href = f"https://baike.baidu.com{href}"
                
                yield Request(
                    url=href,
                    callback="parse_person_detail",
                    meta={
                        "keyword": response.meta.get("keyword"),
                        "source": "baike",
                        "title": title,
                    },
                )

    async def _parse_douban_search(self, response: Response) -> AsyncIterator[Any]:
        """解析豆瓣搜索结果"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        
        # 提取搜索结果中的影人链接
        results = soup.select(".result .title a")
        
        for result in results[:5]:
            href = result.get("href", "")
            title = result.get_text(strip=True)
            
            if href and "/celebrity/" in href:
                yield Request(
                    url=href,
                    callback="parse_person_detail",
                    meta={
                        "keyword": response.meta.get("keyword"),
                        "source": "douban",
                        "title": title,
                    },
                )

    async def _parse_wikipedia_search(self, response: Response) -> AsyncIterator[Any]:
        """解析维基百科搜索结果"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        
        # 提取搜索结果
        results = soup.select(".mw-search-result-heading a")
        
        for result in results[:5]:
            href = result.get("href", "")
            title = result.get_text(strip=True)
            
            if href:
                if href.startswith("/"):
                    href = f"https://zh.wikipedia.org{href}"
                
                yield Request(
                    url=href,
                    callback="parse_person_detail",
                    meta={
                        "keyword": response.meta.get("keyword"),
                        "source": "wikipedia",
                        "title": title,
                    },
                )

    async def parse_person_detail(self, response: Response) -> AsyncIterator[Any]:
        """
        解析人物详情页
        
        提取人物的详细信息。
        """
        source = response.meta.get("source", "unknown")
        keyword = response.meta.get("keyword", "")
        
        logger.info(f"Parsing person detail: {keyword}, source: {source}")
        
        if source == "baike":
            async for item in self._parse_baike_detail(response):
                yield item
        elif source == "douban":
            async for item in self._parse_douban_detail(response):
                yield item
        elif source == "wikipedia":
            async for item in self._parse_wikipedia_detail(response):
                yield item

    async def _parse_baike_detail(self, response: Response) -> AsyncIterator[Item]:
        """解析百度百科详情"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        
        # 提取基本信息
        name = self._extract_text(soup, ".lemma-title")
        summary = self._extract_text(soup, ".lemma-summary")
        
        # 提取信息框
        info = {}
        info_rows = soup.select(".basicInfo-item")
        for i in range(0, len(info_rows), 2):
            if i + 1 < len(info_rows):
                key = info_rows[i].get_text(strip=True)
                value = info_rows[i + 1].get_text(strip=True)
                info[key] = value
        
        # 构建人物数据
        person_data = {
            "name": name,
            "source": "baike",
            "source_url": response.url,
            "summary": summary,
            "raw_info": info,
            "crawled_at": datetime.utcnow().isoformat(),
        }
        
        yield Item(
            item_type="person",
            data=person_data,
            source_url=response.url,
        )

    async def _parse_douban_detail(self, response: Response) -> AsyncIterator[Item]:
        """解析豆瓣详情"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        
        name = self._extract_text(soup, "h1")
        summary = self._extract_text(soup, "#intro .all")
        if not summary:
            summary = self._extract_text(soup, "#intro")
        
        # 提取影人信息
        info = {}
        info_items = soup.select(".info li")
        for item in info_items:
            text = item.get_text(strip=True)
            if ":" in text:
                key, value = text.split(":", 1)
                info[key.strip()] = value.strip()
        
        person_data = {
            "name": name,
            "source": "douban",
            "source_url": response.url,
            "summary": summary,
            "raw_info": info,
            "crawled_at": datetime.utcnow().isoformat(),
        }
        
        yield Item(
            item_type="person",
            data=person_data,
            source_url=response.url,
        )

    async def _parse_wikipedia_detail(self, response: Response) -> AsyncIterator[Item]:
        """解析维基百科详情"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        
        name = self._extract_text(soup, "#firstHeading")
        
        # 提取摘要段落
        summary = ""
        content = soup.select_one("#mw-content-text")
        if content:
            paragraphs = content.select("p")
            for p in paragraphs[:3]:
                text = p.get_text(strip=True)
                if text and len(text) > 20:
                    summary = text
                    break
        
        # 提取信息框
        info = {}
        infobox = soup.select_one(".infobox")
        if infobox:
            rows = infobox.select("tr")
            for row in rows:
                th = row.select_one("th")
                td = row.select_one("td")
                if th and td:
                    key = th.get_text(strip=True)
                    value = td.get_text(strip=True)
                    info[key] = value
        
        person_data = {
            "name": name,
            "source": "wikipedia",
            "source_url": response.url,
            "summary": summary,
            "raw_info": info,
            "crawled_at": datetime.utcnow().isoformat(),
        }
        
        yield Item(
            item_type="person",
            data=person_data,
            source_url=response.url,
        )

    @staticmethod
    def _extract_text(soup, selector: str) -> str:
        """从 HTML 中提取文本"""
        element = soup.select_one(selector)
        return element.get_text(strip=True) if element else ""

    async def handle_error(self, failure: Exception, request: Request):
        """处理错误"""
        logger.error(f"PersonSpider error: {failure}, url: {request.url}")
