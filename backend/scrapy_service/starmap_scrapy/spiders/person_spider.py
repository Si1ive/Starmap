"""
Person Spider for StarMap project.

Scrapes person information from various sources:
- Baidu Baike (百度百科)
- Douban Movie (豆瓣电影)
- Wikipedia (维基百科)
"""

import logging
import re
from urllib.parse import quote, urljoin

import scrapy
from bs4 import BeautifulSoup

from starmap_scrapy.items import PersonItem, WorkItem, RelationItem

logger = logging.getLogger(__name__)


class PersonSpider(scrapy.Spider):
    """
    Spider for scraping person information.
    
    Supports multiple data sources and handles task-based crawling.
    """
    
    name = "person"
    
    # Source configurations
    SOURCES = {
        "baike": {
            "base_url": "https://baike.baidu.com",
            "search_url": "https://baike.baidu.com/search/word?word={keyword}",
            "item_url": "https://baike.baidu.com/item/{keyword}",
        },
        "douban": {
            "base_url": "https://movie.douban.com",
            "search_url": "https://movie.douban.com/subject_search?search_text={keyword}",
        },
        "wikipedia": {
            "base_url": "https://zh.wikipedia.org",
            "search_url": "https://zh.wikipedia.org/w/index.php?search={keyword}",
            "item_url": "https://zh.wikipedia.org/wiki/{keyword}",
        },
    }
    
    # Task context (set by TaskConsumerExtension)
    task_id = None
    source = "baike"
    keywords = []
    task_config = {}
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Allow task parameters to be passed via command line
        if "task_id" in kwargs:
            self.task_id = kwargs["task_id"]
        if "source" in kwargs:
            self.source = kwargs["source"]
        if "keywords" in kwargs:
            self.keywords = kwargs["keywords"].split(",") if isinstance(kwargs["keywords"], str) else kwargs["keywords"]
    
    def start_requests(self):
        """Generate initial requests based on task configuration."""
        if not self.keywords:
            logger.warning("No keywords provided for person spider")
            return
        
        source_config = self.SOURCES.get(self.source, self.SOURCES["baike"])
        
        for keyword in self.keywords:
            # Try direct item URL first
            if "item_url" in source_config:
                item_url = source_config["item_url"].format(keyword=quote(keyword))
                yield scrapy.Request(
                    url=item_url,
                    callback=self.parse_person,
                    meta={
                        "task_id": self.task_id,
                        "keyword": keyword,
                        "source": self.source,
                    },
                    errback=self.handle_error,
                )
            else:
                # Use search URL
                search_url = source_config["search_url"].format(keyword=quote(keyword))
                yield scrapy.Request(
                    url=search_url,
                    callback=self.parse_search,
                    meta={
                        "task_id": self.task_id,
                        "keyword": keyword,
                        "source": self.source,
                    },
                    errback=self.handle_error,
                )
    
    def parse_search(self, response):
        """Parse search results page."""
        keyword = response.meta.get("keyword", "")
        source = response.meta.get("source", "baike")
        
        logger.info(f"Parsing search results for: {keyword} from {source}")
        
        if source == "baike":
            yield from self._parse_baike_search(response)
        elif source == "douban":
            yield from self._parse_douban_search(response)
        elif source == "wikipedia":
            yield from self._parse_wikipedia_search(response)
    
    def _parse_baike_search(self, response):
        """Parse Baidu Baike search results."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find search result links
        results = soup.select(".search-list dd a")
        
        for result in results[:3]:  # Limit to top 3 results
            href = result.get("href", "")
            title = result.get_text(strip=True)
            
            if href:
                url = urljoin("https://baike.baidu.com", href)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_person,
                    meta={
                        **response.meta,
                        "title": title,
                    },
                )
    
    def _parse_douban_search(self, response):
        """Parse Douban search results."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find celebrity links
        results = soup.select(".result .title a")
        
        for result in results[:3]:
            href = result.get("href", "")
            if "/celebrity/" in href:
                yield scrapy.Request(
                    url=href,
                    callback=self.parse_person,
                    meta=response.meta,
                )
    
    def _parse_wikipedia_search(self, response):
        """Parse Wikipedia search results."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find search result links
        results = soup.select(".mw-search-result-heading a")
        
        for result in results[:3]:
            href = result.get("href", "")
            if href:
                url = urljoin("https://zh.wikipedia.org", href)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_person,
                    meta=response.meta,
                )
    
    def parse_person(self, response):
        """Parse person detail page."""
        source = response.meta.get("source", "baike")
        keyword = response.meta.get("keyword", "")
        
        logger.info(f"Parsing person page: {response.url}")
        
        if source == "baike":
            yield from self._parse_baike_person(response)
        elif source == "douban":
            yield from self._parse_douban_person(response)
        elif source == "wikipedia":
            yield from self._parse_wikipedia_person(response)
    
    def _parse_baike_person(self, response):
        """Parse Baidu Baike person page."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extract basic info
        name = self._extract_baike_name(soup)
        summary = self._extract_baike_summary(soup)
        
        # Extract info box
        info_dict = self._extract_baike_info_box(soup)
        
        # Create person item
        person = PersonItem(
            name=name or response.meta.get("keyword", ""),
            name_en=info_dict.get("外文名"),
            avatar=self._extract_baike_avatar(soup),
            gender=self._normalize_gender(info_dict.get("性别")),
            birth_date=info_dict.get("出生日期"),
            birth_place=info_dict.get("出生地"),
            nationality=info_dict.get("国籍"),
            height=self._extract_height(info_dict.get("身高")),
            summary=summary,
            biography=summary,
            categories=self._extract_categories(info_dict.get("职业", "")),
            source="baike",
            source_url=response.url,
            crawl_task_id=self.task_id,
            raw_data={
                "info_box": info_dict,
                "keyword": response.meta.get("keyword"),
            },
        )
        
        yield person
        
        # Extract related works
        yield from self._extract_baike_works(soup, person.get("name"), response.url)
    
    def _parse_douban_person(self, response):
        """Parse Douban celebrity page."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extract basic info
        name = soup.select_one("h1").get_text(strip=True) if soup.select_one("h1") else ""
        info = soup.select_one("#headline .info")
        
        info_dict = {}
        if info:
            for li in info.select("li"):
                text = li.get_text(strip=True)
                if ":" in text:
                    key, value = text.split(":", 1)
                    info_dict[key.strip()] = value.strip()
        
        person = PersonItem(
            name=name,
            name_en=info_dict.get("英文名"),
            avatar=soup.select_one("#headline img").get("src") if soup.select_one("#headline img") else None,
            gender=self._normalize_gender(info_dict.get("性别")),
            birth_date=info_dict.get("出生日期"),
            birth_place=info_dict.get("出生地"),
            nationality=info_dict.get("出生地"),  # Douban often uses birthplace as nationality
            summary=soup.select_one(".bd p").get_text(strip=True) if soup.select_one(".bd p") else "",
            source="douban",
            source_url=response.url,
            crawl_task_id=self.task_id,
            raw_data={
                "info": info_dict,
            },
        )
        
        yield person
    
    def _parse_wikipedia_person(self, response):
        """Parse Wikipedia person page."""
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extract title
        title = soup.select_one("#firstHeading")
        name = title.get_text(strip=True) if title else ""
        
        # Extract info box
        info_dict = self._extract_wikipedia_info_box(soup)
        
        # Extract summary
        summary = ""
        content = soup.select_one("#mw-content-text .mw-parser-output")
        if content:
            first_para = content.find("p", class_=None)
            if first_para:
                summary = first_para.get_text(strip=True)
        
        person = PersonItem(
            name=name,
            name_en=info_dict.get("英文名"),
            avatar=self._extract_wikipedia_image(soup),
            gender=self._normalize_gender(info_dict.get("性别")),
            birth_date=info_dict.get("出生"),
            birth_place=info_dict.get("出生地"),
            nationality=info_dict.get("国籍"),
            summary=summary,
            biography=summary,
            categories=self._extract_wikipedia_categories(soup),
            source="wikipedia",
            source_url=response.url,
            crawl_task_id=self.task_id,
            raw_data={
                "info_box": info_dict,
            },
        )
        
        yield person
    
    def _extract_baike_name(self, soup):
        """Extract name from Baidu Baike page."""
        # Try multiple selectors
        selectors = [
            "h1.lemma-title",
            ".lemmaWgt-lemmaTitle-title h1",
            "h1",
        ]
        for selector in selectors:
            elem = soup.select_one(selector)
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
        
        # Try different info box selectors
        info_box = soup.select_one(".basic-info")
        if not info_box:
            info_box = soup.select_one(".lemmaWgt-baseInfo")
        
        if info_box:
            # Extract dt/dd pairs
            items = info_box.select("dt, dd")
            for i in range(0, len(items) - 1, 2):
                key = items[i].get_text(strip=True).replace("\xa0", "").rstrip(":")
                value = items[i + 1].get_text(strip=True)
                if key and value:
                    info_dict[key] = value
        
        return info_dict
    
    def _extract_baike_avatar(self, soup):
        """Extract avatar URL from Baidu Baike page."""
        elem = soup.select_one(".summary-pic img")
        if elem:
            return elem.get("src")
        return None
    
    def _extract_baike_works(self, soup, person_name, person_url):
        """Extract works from Baidu Baike page."""
        # Find works section
        works_section = soup.select_one("#works")
        if not works_section:
            return
        
        for item in works_section.select("li"):
            title_elem = item.select_one("a")
            if title_elem:
                work = WorkItem(
                    title=title_elem.get_text(strip=True),
                    type="movie",  # Default, could be improved
                    source="baike",
                    source_url=urljoin("https://baike.baidu.com", title_elem.get("href", "")),
                    crawl_task_id=self.task_id,
                )
                
                relation = RelationItem(
                    source_id=None,  # Will be set after person is stored
                    target_id=None,  # Will be set after work is stored
                    relation_type="acted_in",
                    role="演员",
                    source="baike",
                    crawl_task_id=self.task_id,
                )
                
                yield work
                yield relation
    
    def _extract_wikipedia_info_box(self, soup):
        """Extract info box from Wikipedia page."""
        info_dict = {}
        
        info_box = soup.select_one(".infobox")
        if info_box:
            for row in info_box.select("tr"):
                th = row.select_one("th")
                td = row.select_one("td")
                if th and td:
                    key = th.get_text(strip=True)
                    value = td.get_text(strip=True)
                    info_dict[key] = value
        
        return info_dict
    
    def _extract_wikipedia_image(self, soup):
        """Extract image URL from Wikipedia page."""
        elem = soup.select_one(".infobox img")
        if elem:
            src = elem.get("src", "")
            if src.startswith("//"):
                src = "https:" + src
            return src
        return None
    
    def _extract_wikipedia_categories(self, soup):
        """Extract categories from Wikipedia page."""
        categories = []
        for cat in soup.select("#catlinks li a"):
            text = cat.get_text(strip=True)
            if text and text not in ["分类", ""]:
                categories.append(text)
        return categories
    
    def _normalize_gender(self, gender_str):
        """Normalize gender string."""
        if not gender_str:
            return "unknown"
        
        gender_str = gender_str.lower().strip()
        
        if any(word in gender_str for word in ["男", "male", "m"]):
            return "male"
        elif any(word in gender_str for word in ["女", "female", "f"]):
            return "female"
        
        return "unknown"
    
    def _extract_height(self, height_str):
        """Extract height value from string."""
        if not height_str:
            return None
        
        # Extract numeric value
        match = re.search(r'(\d+(?:\.\d+)?)', height_str)
        if match:
            try:
                height = float(match.group(1))
                # Convert cm to meters if needed
                if height > 100:
                    height = height / 100
                return round(height, 2)
            except ValueError:
                pass
        
        return None
    
    def _extract_categories(self, categories_str):
        """Extract categories from string."""
        if not categories_str:
            return []
        
        # Split by common delimiters
        categories = re.split(r'[,，、/\\s]+', categories_str)
        return [c.strip() for c in categories if c.strip()]
    
    def handle_error(self, failure):
        """Handle request errors."""
        logger.error(f"Request failed: {failure.getErrorMessage()}")
        
        # Log error
        yield {
            "_type": "log",
            "task_id": self.task_id,
            "level": "ERROR",
            "stage": "fetch",
            "message": f"Request failed: {failure.getErrorMessage()}",
            "error_type": failure.type.__name__ if hasattr(failure, "type") else "Unknown",
        }
