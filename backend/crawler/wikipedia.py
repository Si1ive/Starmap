"""维基百科爬虫

实现针对中文维基百科的人物页面爬取功能。
支持：
- 按人物名称搜索/爬取
- 信息框（Infobox）解析
- 页面分类提取
- 重定向处理
"""

import re
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import BaseCrawler, CrawlResult, FetchError
from .models import Person

logger = logging.getLogger(__name__)


class WikipediaCrawler(BaseCrawler):
    """维基百科爬虫

    用于爬取中文维基百科的人物页面信息。

    使用示例:
        >>> crawler = WikipediaCrawler()
        >>> result = crawler.crawl_person("周杰伦")
        >>> print(result["name"])
        '周杰伦'
    """

    BASE_URL = "https://zh.wikipedia.org/wiki/"
    API_URL = "https://zh.wikipedia.org/w/api.php"

    # 维基百科人物分类关键词
    PERSON_CATEGORIES = [
        "演员",
        "歌手",
        "音乐人",
        "导演",
        "编剧",
        "作家",
        "运动员",
        "政治家",
        "企业家",
        "艺术家",
    ]

    def __init__(self, delay: float = 1.0, **kwargs):
        """初始化维基百科爬虫

        Args:
            delay: 请求间隔（秒），默认1.0
            **kwargs: 传递给BaseCrawler的其他参数
        """
        super().__init__(delay=delay, **kwargs)
        logger.info("WikipediaCrawler initialized")

    def _build_url(self, name: str) -> str:
        """构建人物页面URL

        Args:
            name: 人物名称

        Returns:
            str: 完整的维基百科URL
        """
        encoded_name = quote(name)
        return f"{self.BASE_URL}{encoded_name}"

    def crawl_person(self, name: str) -> Dict[str, Any]:
        """爬取人物页面

        Args:
            name: 人物名称（中文）

        Returns:
            Dict: 包含原始HTML和解析后数据的字典

        Raises:
            FetchError: 获取页面失败
        """
        url = self._build_url(name)
        result = self.fetch_with_retry(url)

        if not result.success:
            raise FetchError(f"Failed to crawl person: {name}, error: {result.error}")

        # 检查是否是重定向页面
        soup = BeautifulSoup(result.html, "lxml")
        redirect = soup.find("div", class_="redirect-in-category")
        if redirect:
            # 处理重定向
            redirect_link = soup.find("a", class_="mw-redirect")
            if redirect_link:
                redirect_name = redirect_link.get_text(strip=True)
                logger.info(f"Redirect: {name} -> {redirect_name}")
                return self.crawl_person(redirect_name)

        return {
            "name": name,
            "url": url,
            "html": result.html,
            "status_code": result.status_code,
        }

    def search_persons(self, query: str, limit: int = 10) -> List[Dict[str, str]]:
        """搜索人物

        使用维基百科API搜索相关人物页面。

        Args:
            query: 搜索关键词
            limit: 返回结果数量

        Returns:
            List[Dict]: 搜索结果列表，每个结果包含title和snippet
        """
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "origin": "*",
        }

        try:
            self._wait_for_rate_limit()
            response = self.session.get(self.API_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("query", {}).get("search", []):
                results.append({
                    "title": item["title"],
                    "snippet": self._clean_snippet(item["snippet"]),
                })

            logger.info(f"Search '{query}' returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def _clean_snippet(self, snippet: str) -> str:
        """清理搜索摘要中的HTML标签"""
        # 移除span标签
        snippet = re.sub(r'<span[^>]*>', '', snippet)
        snippet = re.sub(r'</span>', '', snippet)
        # 移除其他HTML标签
        snippet = re.sub(r'<[^>]+>', '', snippet)
        return snippet.strip()

    def get_page_categories(self, title: str) -> List[str]:
        """获取页面分类

        Args:
            title: 页面标题

        Returns:
            List[str]: 分类列表
        """
        params = {
            "action": "query",
            "prop": "categories",
            "titles": title,
            "cllimit": 50,
            "format": "json",
            "origin": "*",
        }

        try:
            self._wait_for_rate_limit()
            response = self.session.get(self.API_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            categories = []
            pages = data.get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                for cat in page_data.get("categories", []):
                    cat_name = cat["title"].replace("Category:", "").replace("分类:", "")
                    categories.append(cat_name)

            return categories

        except Exception as e:
            logger.error(f"Failed to get categories for {title}: {e}")
            return []

    def is_person_page(self, title: str) -> bool:
        """判断页面是否是人物页面

        通过检查页面分类来判断。

        Args:
            title: 页面标题

        Returns:
            bool: 是否是人物页面
        """
        categories = self.get_page_categories(title)

        for cat in categories:
            for keyword in self.PERSON_CATEGORIES:
                if keyword in cat:
                    return True

        return False

    def crawl_multiple(self, names: List[str]) -> List[Dict[str, Any]]:
        """批量爬取多个人物

        Args:
            names: 人物名称列表

        Returns:
            List[Dict]: 爬取结果列表
        """
        results = []
        for name in names:
            try:
                result = self.crawl_person(name)
                results.append(result)
                logger.info(f"Successfully crawled: {name}")
            except Exception as e:
                logger.error(f"Failed to crawl {name}: {e}")
                results.append({
                    "name": name,
                    "error": str(e),
                })

        return results
