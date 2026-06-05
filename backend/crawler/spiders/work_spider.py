"""
作品信息爬虫

爬取作品（Work）相关信息的爬虫实现。
支持从豆瓣电影、IMDb 等数据源爬取作品信息。
"""

from typing import AsyncIterator, Optional, Dict, Any, List
from datetime import datetime

from crawler.engine import Spider, Request, Response, Item
from app.core.logging import get_logger

logger = get_logger(__name__)


class WorkSpider(Spider):
    """
    作品信息爬虫
    
    从多个数据源爬取作品（电影、电视剧、音乐等）信息。
    """

    name = "work"
    
    SOURCES = {
        "douban": {
            "base_url": "https://movie.douban.com/subject/",
            "search_url": "https://movie.douban.com/subject_search?search_text={keyword}",
        },
        "imdb": {
            "base_url": "https://www.imdb.com/title/",
            "search_url": "https://www.imdb.com/find?q={keyword}",
        },
    }

    def __init__(self, source: str = "douban", keywords: Optional[List[str]] = None, **kwargs):
        super().__init__(**kwargs)
        self.source = source
        self.keywords = keywords or []
        self.source_config = self.SOURCES.get(source, self.SOURCES["douban"])
        
        if keywords:
            self.start_urls = [
                self.source_config["search_url"].format(keyword=kw)
                for kw in keywords
            ]

    async def start(self) -> AsyncIterator[Request]:
        """生成初始请求"""
        if not self.keywords:
            logger.warning("No keywords provided for WorkSpider")
            return
        
        for keyword in self.keywords:
            url = self.source_config["search_url"].format(keyword=keyword)
            yield Request(
                url=url,
                callback="parse_search",
                meta={"keyword": keyword, "source": self.source},
                dont_filter=True,
            )

    async def parse_search(self, response: Response) -> AsyncIterator[Any]:
        """解析搜索结果"""
        if self.source == "douban":
            async for result in self._parse_douban_search(response):
                yield result
        elif self.source == "imdb":
            async for result in self._parse_imdb_search(response):
                yield result

    async def _parse_douban_search(self, response: Response) -> AsyncIterator[Any]:
        """解析豆瓣搜索"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        results = soup.select(".result .title a")
        
        for result in results[:5]:
            href = result.get("href", "")
            title = result.get_text(strip=True)
            
            if href and "/subject/" in href:
                yield Request(
                    url=href,
                    callback="parse_work_detail",
                    meta={
                        "keyword": response.meta.get("keyword"),
                        "source": "douban",
                        "title": title,
                    },
                )

    async def _parse_imdb_search(self, response: Response) -> AsyncIterator[Any]:
        """解析 IMDb 搜索"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        results = soup.select(".findResult a")
        
        for result in results[:5]:
            href = result.get("href", "")
            if href and "/title/" in href:
                if href.startswith("/"):
                    href = f"https://www.imdb.com{href}"
                
                yield Request(
                    url=href,
                    callback="parse_work_detail",
                    meta={
                        "keyword": response.meta.get("keyword"),
                        "source": "imdb",
                    },
                )

    async def parse_work_detail(self, response: Response) -> AsyncIterator[Item]:
        """解析作品详情"""
        source = response.meta.get("source", "unknown")
        
        if source == "douban":
            async for item in self._parse_douban_detail(response):
                yield item
        elif source == "imdb":
            async for item in self._parse_imdb_detail(response):
                yield item

    async def _parse_douban_detail(self, response: Response) -> AsyncIterator[Item]:
        """解析豆瓣详情"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        
        title = self._extract_text(soup, "h1 span")
        year = self._extract_text(soup, "h1 .year")
        rating = self._extract_text(soup, "#interest_sectl .rating_num")
        summary = self._extract_text(soup, "#link-report .all")
        if not summary:
            summary = self._extract_text(soup, "#link-report")
        
        # 提取导演、演员
        directors = []
        actors = []
        info_text = self._extract_text(soup, "#info")
        
        work_data = {
            "title": title,
            "year": year.strip("()"),
            "rating": rating,
            "summary": summary,
            "source": "douban",
            "source_url": response.url,
            "directors": directors,
            "actors": actors,
            "raw_info": info_text,
            "crawled_at": datetime.utcnow().isoformat(),
        }
        
        yield Item(
            item_type="work",
            data=work_data,
            source_url=response.url,
        )

    async def _parse_imdb_detail(self, response: Response) -> AsyncIterator[Item]:
        """解析 IMDb 详情"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(response.body, "html.parser")
        
        title = self._extract_text(soup, "h1")
        rating = self._extract_text(soup, "[data-testid='hero-rating-bar__aggregate-rating__score'] span")
        summary = self._extract_text(soup, "[data-testid='plot']")
        
        work_data = {
            "title": title,
            "rating": rating,
            "summary": summary,
            "source": "imdb",
            "source_url": response.url,
            "crawled_at": datetime.utcnow().isoformat(),
        }
        
        yield Item(
            item_type="work",
            data=work_data,
            source_url=response.url,
        )

    @staticmethod
    def _extract_text(soup, selector: str) -> str:
        """提取文本"""
        element = soup.select_one(selector)
        return element.get_text(strip=True) if element else ""
