"""
Work Spider for StarMap project.

Scrapes work (movie, TV, music, book) information from various sources.
"""

import logging
from urllib.parse import quote, urljoin

import scrapy
from bs4 import BeautifulSoup

from starmap_scrapy.items import WorkItem, PersonItem, RelationItem

logger = logging.getLogger(__name__)


class WorkSpider(scrapy.Spider):
    """
    Spider for scraping work information.
    
    Supports multiple data sources and work types.
    """
    
    name = "work"
    
    # Source configurations
    SOURCES = {
        "douban": {
            "base_url": "https://movie.douban.com",
            "search_url": "https://movie.douban.com/subject_search?search_text={keyword}",
        },
        "baike": {
            "base_url": "https://baike.baidu.com",
            "search_url": "https://baike.baidu.com/search/word?word={keyword}",
        },
    }
    
    # Task context
    task_id = None
    source_id = None
    source = "douban"
    keywords = []
    work_type = "movie"
    task_config = {}
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if "task_id" in kwargs:
            self.task_id = kwargs["task_id"]
        if "source_id" in kwargs:
            self.source_id = kwargs["source_id"]
        if "source" in kwargs:
            self.source = kwargs["source"]
        if "keywords" in kwargs:
            self.keywords = kwargs["keywords"].split(",") if isinstance(kwargs["keywords"], str) else kwargs["keywords"]
        if "work_type" in kwargs:
            self.work_type = kwargs["work_type"]
    
    def start_requests(self):
        """Generate initial requests."""
        if not self.keywords:
            logger.warning("No keywords provided for work spider")
            return
        
        source_config = self.SOURCES.get(self.source, self.SOURCES["douban"])
        
        for keyword in self.keywords:
            search_url = source_config["search_url"].format(keyword=quote(keyword))
            yield scrapy.Request(
                url=search_url,
                callback=self.parse_search,
                meta={
                    "task_id": self.task_id,
                    "keyword": keyword,
                    "source": self.source,
                    "work_type": self.work_type,
                },
                errback=self.handle_error,
            )
    
    def parse_search(self, response):
        """Parse search results."""
        source = response.meta.get("source", "douban")
        
        if source == "douban":
            yield from self._parse_douban_search(response)
        elif source == "baike":
            yield from self._parse_baike_search(response)
    
    def _parse_douban_search(self, response):
        """Parse Douban search results."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find movie/TV links
        results = soup.select(".result .title a")
        
        for result in results[:3]:
            href = result.get("href", "")
            if "/subject/" in href:
                yield scrapy.Request(
                    url=href,
                    callback=self.parse_work,
                    meta=response.meta,
                )
    
    def _parse_baike_search(self, response):
        """Parse Baidu Baike search results."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        results = soup.select(".search-list dd a")
        
        for result in results[:3]:
            href = result.get("href", "")
            if href:
                url = urljoin("https://baike.baidu.com", href)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_work,
                    meta=response.meta,
                )
    
    def parse_work(self, response):
        """Parse work detail page."""
        source = response.meta.get("source", "douban")
        
        if source == "douban":
            yield from self._parse_douban_work(response)
        elif source == "baike":
            yield from self._parse_baike_work(response)
    
    def _parse_douban_work(self, response):
        """Parse Douban movie/TV page."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extract basic info
        title = soup.select_one("h1 span")
        title = title.get_text(strip=True) if title else ""
        
        # Extract info
        info_text = soup.select_one("#info")
        info_dict = {}
        if info_text:
            for line in info_text.get_text().split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    info_dict[key.strip()] = value.strip()
        
        # Extract rating
        rating_elem = soup.select_one(".rating_num")
        rating = None
        if rating_elem:
            try:
                rating = float(rating_elem.get_text(strip=True))
            except ValueError:
                pass
        
        # Extract summary
        summary_elem = soup.select_one("#link-report .short")
        if not summary_elem:
            summary_elem = soup.select_one("#link-report")
        summary = summary_elem.get_text(strip=True) if summary_elem else ""
        
        # Extract poster
        poster_elem = soup.select_one("#mainpic img")
        poster = poster_elem.get("src") if poster_elem else None
        
        # Determine work type
        work_type = self._determine_work_type(info_dict.get("集数"), response.meta.get("work_type", "movie"))
        
        work = WorkItem(
            title=title,
            type=work_type,
            release_date=info_dict.get("上映日期") or info_dict.get("首播"),
            genre=info_dict.get("类型"),
            rating=rating,
            poster=poster,
            summary=summary,
            director=self._parse_list(info_dict.get("导演", "")),
            actors=self._parse_list(info_dict.get("主演", "")),
            episodes=self._extract_episodes(info_dict.get("集数", "")),
            source="douban",
            source_url=response.url,
            crawl_task_id=self.task_id,
            raw_data={
                "info": info_dict,
            },
        )
        
        yield work
        
        # Extract related persons
        for director in work.get("director", []):
            yield RelationItem(
                source_id=None,
                target_id=None,
                relation_type="directed",
                role="导演",
                source="douban",
                crawl_task_id=self.task_id,
            )
        
        for actor in work.get("actors", []):
            yield RelationItem(
                source_id=None,
                target_id=None,
                relation_type="acted_in",
                role="演员",
                source="douban",
                crawl_task_id=self.task_id,
            )
    
    def _parse_baike_work(self, response):
        """Parse Baidu Baike work page."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extract basic info
        title = self._extract_baike_name(soup)
        summary = self._extract_baike_summary(soup)
        info_dict = self._extract_baike_info_box(soup)
        
        work = WorkItem(
            title=title,
            type=self.work_type,
            release_date=info_dict.get("上映时间") or info_dict.get("首播时间"),
            genre=info_dict.get("类型"),
            summary=summary,
            director=self._parse_list(info_dict.get("导演", "")),
            actors=self._parse_list(info_dict.get("主演", "")),
            source="baike",
            source_url=response.url,
            crawl_task_id=self.task_id,
            raw_data={
                "info_box": info_dict,
            },
        )
        
        yield work
    
    def _determine_work_type(self, episodes_str, default_type):
        """Determine work type based on episodes."""
        if episodes_str:
            return "tv"
        return default_type
    
    def _extract_episodes(self, episodes_str):
        """Extract episode count from string."""
        if not episodes_str:
            return None
        
        import re
        match = re.search(r'(\d+)', episodes_str)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        return None
    
    def _parse_list(self, text):
        """Parse comma-separated list."""
        if not text:
            return []
        return [item.strip() for item in text.split("/") if item.strip()]
    
    def _extract_baike_name(self, soup):
        """Extract name from Baidu Baike page."""
        elem = soup.select_one("h1.lemma-title")
        if elem:
            return elem.get_text(strip=True)
        return ""
    
    def _extract_baike_summary(self, soup):
        """Extract summary from Baidu Baike page."""
        elem = soup.select_one(".lemma-summary .para")
        if elem:
            return elem.get_text(strip=True)
        return ""
    
    def _extract_baike_info_box(self, soup):
        """Extract info box from Baidu Baike page."""
        info_dict = {}
        info_box = soup.select_one(".basic-info")
        if info_box:
            items = info_box.select("dt, dd")
            for i in range(0, len(items) - 1, 2):
                key = items[i].get_text(strip=True).replace("\xa0", "").rstrip(":")
                value = items[i + 1].get_text(strip=True)
                if key and value:
                    info_dict[key] = value
        return info_dict
    
    def handle_error(self, failure):
        """Handle request errors."""
        logger.error(f"Request failed: {failure.getErrorMessage()}")
