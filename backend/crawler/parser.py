"""HTML解析器

解析维基百科页面HTML，提取人物信息、作品、关系等结构化数据。
"""

import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from .models import Person, Work, Relation, VALID_WORK_TYPES
from .base import ParseError

logger = logging.getLogger(__name__)


class WikipediaParser:
    """维基百科页面解析器

    从维基百科HTML页面中提取结构化数据。

    使用示例:
        >>> parser = WikipediaParser()
        >>> person = parser.parse_person(html, "周杰伦")
        >>> print(person.name, person.birth_date)
    """

    # 信息框字段映射
    INFOBOX_FIELD_MAP = {
        # 中文维基百科常见字段名 -> 标准字段名
        "姓名": "name",
        "本名": "name",
        "原名": "name",
        "英文名": "name_en",
        "外文名": "name_en",
        "昵称": "nickname",
        "性别": "gender",
        "出生": "birth_info",
        "出生日期": "birth_date",
        "出生地点": "birth_place",
        "逝世": "death_info",
        "逝世日期": "death_date",
        "国籍": "nationality",
        "籍贯": "origin",
        "职业": "occupation",
        "语言": "languages",
        "教育程度": "education",
        "母校": "alma_mater",
        "宗教信仰": "religion",
        "配偶": "spouse",
        "儿女": "children",
        "父母": "parents",
        "亲属": "relatives",
        "音乐类型": "music_genre",
        "演奏乐器": "instruments",
        "出道地点": "debut_place",
        "出道日期": "debut_date",
        "出道作品": "debut_work",
        "代表作品": "notable_works",
        "活跃年代": "active_years",
        "唱片公司": "record_label",
        "经纪公司": "agency",
        "网站": "website",
        "身高": "height",
        "体重": "weight",
        "血型": "blood_type",
        "星座": "zodiac",
    }

    # 性别映射
    GENDER_MAP = {
        "男": "male",
        "男性": "male",
        "女": "female",
        "女性": "female",
    }

    def __init__(self):
        """初始化解析器"""
        logger.info("WikipediaParser initialized")

    def parse_person(self, html: str, name: str) -> Person:
        """解析人物页面

        从维基百科HTML中提取人物信息。

        Args:
            html: 页面HTML内容
            name: 人物名称（用于fallback）

        Returns:
            Person: 人物数据对象

        Raises:
            ParseError: 解析失败
        """
        soup = BeautifulSoup(html, "lxml")

        # 提取信息框数据
        infobox_data = self._parse_infobox(soup)

        # 提取页面摘要
        summary = self._extract_summary(soup)

        # 提取传记内容
        biography = self._extract_biography(soup)

        # 提取分类
        categories = self._extract_categories(soup)

        # 构建Person对象
        person = Person(
            id=Person.generate_id(),
            name=infobox_data.get("name") or name,
            name_en=infobox_data.get("name_en"),
            gender=self._parse_gender(infobox_data.get("gender")),
            birth_date=self._parse_date(infobox_data.get("birth_date")),
            birth_place=infobox_data.get("birth_place"),
            nationality=infobox_data.get("nationality"),
            height=self._parse_height(infobox_data.get("height")),
            summary=summary,
            biography=biography,
            categories=categories,
        )

        logger.info(f"Parsed person: {person.name}")
        return person

    def _parse_infobox(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """解析信息框（Infobox）

        维基百科人物页面通常有一个信息框表格，包含人物的基本信息。

        Args:
            soup: BeautifulSoup对象

        Returns:
            Dict: 信息框字段数据
        """
        data = {}

        # 查找信息框 - 中文维基百科常见class
        infobox = soup.find("table", class_=re.compile(r"infobox.*biography", re.I))
        if not infobox:
            infobox = soup.find("table", class_=re.compile(r"infobox", re.I))
        if not infobox:
            infobox = soup.find("table", class_=re.compile(r"vcard", re.I))

        if not infobox:
            logger.warning("No infobox found")
            return data

        # 遍历信息框的所有行
        for row in infobox.find_all("tr"):
            # 查找表头（字段名）
            header = row.find(["th", "td"], class_=re.compile(r"infobox-label", re.I))
            if not header:
                header = row.find("th")

            if header:
                field_name = header.get_text(strip=True)
                field_name = field_name.rstrip("：").rstrip(":")

                # 查找对应的值
                value_cell = row.find("td", class_=re.compile(r"infobox-data", re.I))
                if not value_cell:
                    # 尝试找下一个td
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        value_cell = cells[1]
                    elif len(cells) == 1 and not header.name == "th":
                        value_cell = cells[0]

                if value_cell:
                    field_value = self._extract_cell_value(value_cell)

                    # 映射到标准字段名
                    standard_name = self.INFOBOX_FIELD_MAP.get(field_name)
                    if standard_name:
                        data[standard_name] = field_value
                    else:
                        # 保留原始字段
                        data[field_name] = field_value

        logger.debug(f"Infobox parsed: {len(data)} fields")
        return data

    def _extract_cell_value(self, cell: Tag) -> str:
        """提取单元格的值

        处理单元格中的链接、列表、换行等情况。

        Args:
            cell: 表格单元格Tag

        Returns:
            str: 提取的值
        """
        # 移除引用标记
        for sup in cell.find_all("sup", class_="reference"):
            sup.decompose()

        # 获取文本
        text = cell.get_text(separator=" ", strip=True)

        # 清理多余空白
        text = re.sub(r"\s+", " ", text)

        return text

    def _extract_summary(self, soup: BeautifulSoup) -> Optional[str]:
        """提取页面摘要

        提取页面第一段文字作为摘要。

        Args:
            soup: BeautifulSoup对象

        Returns:
            Optional[str]: 摘要文本
        """
        # 查找内容区域
        content = soup.find("div", id="mw-content-text")
        if not content:
            return None

        # 查找第一个段落（跳过信息框等）
        for p in content.find_all("p", recursive=False):
            text = p.get_text(strip=True)
            # 跳过空段落和只包含图片的段落
            if text and len(text) > 20:
                # 清理引用标记
                text = re.sub(r"\[\d+\]", "", text)
                return text

        return None

    def _extract_biography(self, soup: BeautifulSoup) -> Optional[str]:
        """提取传记内容

        提取页面的主要内容文本。

        Args:
            soup: BeautifulSoup对象

        Returns:
            Optional[str]: 传记文本
        """
        content = soup.find("div", id="mw-content-text")
        if not content:
            return None

        # 收集所有段落文本
        paragraphs = []
        for p in content.find_all("p"):
            text = p.get_text(strip=True)
            if text and len(text) > 10:
                # 清理引用标记
                text = re.sub(r"\[\d+\]", "", text)
                paragraphs.append(text)

        if paragraphs:
            return "\n\n".join(paragraphs)

        return None

    def _extract_categories(self, soup: BeautifulSoup) -> List[str]:
        """提取页面分类

        Args:
            soup: BeautifulSoup对象

        Returns:
            List[str]: 分类列表
        """
        categories = []

        # 查找分类区域
        cat_section = soup.find("div", id="catlinks")
        if cat_section:
            for link in cat_section.find_all("a"):
                text = link.get_text(strip=True)
                if text and text not in ["分类", "Categories"]:
                    categories.append(text)

        return categories

    def _parse_gender(self, gender_text: Optional[str]) -> Optional[str]:
        """解析性别

        Args:
            gender_text: 性别文本

        Returns:
            Optional[str]: 标准化性别值
        """
        if not gender_text:
            return None

        gender_text = gender_text.strip()
        return self.GENDER_MAP.get(gender_text)

    def _parse_date(self, date_text: Optional[str]) -> Optional[str]:
        """解析日期

        将各种日期格式转换为ISO格式（YYYY-MM-DD）。

        Args:
            date_text: 日期文本

        Returns:
            Optional[str]: ISO格式日期
        """
        if not date_text:
            return None

        date_text = date_text.strip()

        # 匹配 YYYY年MM月DD日
        pattern1 = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
        match = pattern1.search(date_text)
        if match:
            year, month, day = match.groups()
            return f"{year}-{int(month):02d}-{int(day):02d}"

        # 匹配 YYYY-MM-DD
        pattern2 = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
        match = pattern2.search(date_text)
        if match:
            return match.group(0)

        # 匹配 YYYY/MM/DD
        pattern3 = re.compile(r"(\d{4})/(\d{2})/(\d{2})")
        match = pattern3.search(date_text)
        if match:
            year, month, day = match.groups()
            return f"{year}-{month}-{day}"

        # 只匹配年份
        pattern4 = re.compile(r"(\d{4})年")
        match = pattern4.search(date_text)
        if match:
            return f"{match.group(1)}-01-01"

        return None

    def _parse_height(self, height_text: Optional[str]) -> Optional[float]:
        """解析身高

        提取身高数值（厘米）。

        Args:
            height_text: 身高文本

        Returns:
            Optional[float]: 身高（厘米）
        """
        if not height_text:
            return None

        # 匹配数字+cm/厘米
        pattern = re.compile(r"(\d+\.?\d*)\s*(cm|厘米|公分)")
        match = pattern.search(height_text)
        if match:
            return float(match.group(1))

        # 匹配数字+m/米（转换为厘米）
        pattern2 = re.compile(r"(\d+\.?\d*)\s*(m|米)")
        match = pattern2.search(height_text)
        if match:
            return float(match.group(1)) * 100

        # 只匹配数字
        pattern3 = re.compile(r"(\d{3})\s*")
        match = pattern3.search(height_text)
        if match:
            value = float(match.group(1))
            if 100 <= value <= 250:  # 合理的身高范围
                return value

        return None

    def extract_works(self, html: str, person_name: str) -> List[Work]:
        """提取作品信息

        从页面中提取人物的作品列表。

        Args:
            html: 页面HTML
            person_name: 人物名称

        Returns:
            List[Work]: 作品列表
        """
        soup = BeautifulSoup(html, "lxml")
        works = []

        # 查找作品相关的表格或列表
        # 常见标题：音乐作品、影视作品、专辑、单曲等
        work_sections = [
            "音乐作品",
            "影视作品",
            "专辑",
            "单曲",
            "参演电影",
            "参演电视剧",
            "书籍",
        ]

        for section_title in work_sections:
            section = self._find_section(soup, section_title)
            if section:
                section_works = self._parse_work_section(section, person_name)
                works.extend(section_works)

        logger.info(f"Extracted {len(works)} works for {person_name}")
        return works

    def _find_section(self, soup: BeautifulSoup, title: str) -> Optional[Tag]:
        """查找指定标题的章节

        Args:
            soup: BeautifulSoup对象
            title: 章节标题

        Returns:
            Optional[Tag]: 章节内容区域
        """
        # 查找标题
        for heading in soup.find_all(["h2", "h3", "h4"]):
            if title in heading.get_text(strip=True):
                # 返回标题后的内容
                content = []
                sibling = heading.find_next_sibling()
                while sibling and sibling.name not in ["h2", "h3", "h4"]:
                    content.append(sibling)
                    sibling = sibling.find_next_sibling()

                # 创建一个临时容器
                container = soup.new_tag("div")
                for item in content:
                    container.append(item)
                return container

        return None

    def _parse_work_section(self, section: Tag, person_name: str) -> List[Work]:
        """解析作品章节

        Args:
            section: 章节内容
            person_name: 人物名称

        Returns:
            List[Work]: 作品列表
        """
        works = []

        # 查找表格
        for table in section.find_all("table", class_=re.compile(r"wikitable", re.I)):
            for row in table.find_all("tr")[1:]:  # 跳过表头
                cells = row.find_all(["td", "th"])
                if len(cells) >= 1:
                    title = cells[0].get_text(strip=True)
                    if title:
                        work = Work(
                            id=Work.generate_id(),
                            title=title,
                            type=self._detect_work_type(section),
                        )
                        # 尝试提取年份
                        if len(cells) >= 2:
                            year_text = cells[1].get_text(strip=True)
                            work.release_date = self._parse_year(year_text)

                        works.append(work)

        # 查找列表
        for ul in section.find_all("ul"):
            for li in ul.find_all("li"):
                text = li.get_text(strip=True)
                if text and len(text) > 1:
                    # 尝试提取作品名（通常是列表项的主要文本）
                    title = text.split("(")[0].split("（")[0].strip()
                    if title:
                        work = Work(
                            id=Work.generate_id(),
                            title=title,
                            type=self._detect_work_type(section),
                        )
                        works.append(work)

        return works

    def _detect_work_type(self, section: Tag) -> str:
        """检测作品类型

        Args:
            section: 章节内容

        Returns:
            str: 作品类型
        """
        section_text = section.get_text()

        if "专辑" in section_text or "单曲" in section_text:
            return "album"
        elif "电影" in section_text:
            return "movie"
        elif "电视剧" in section_text or "戏剧" in section_text:
            return "tv"
        elif "书籍" in section_text or "著作" in section_text:
            return "book"

        return "album"  # 默认类型

    def _parse_year(self, year_text: str) -> Optional[str]:
        """解析年份

        Args:
            year_text: 年份文本

        Returns:
            Optional[str]: ISO格式日期
        """
        match = re.search(r"(\d{4})", year_text)
        if match:
            return f"{match.group(1)}-01-01"
        return None

    def extract_relations(self, html: str, person_name: str, person_id: str) -> List[Relation]:
        """提取人物关系

        从信息框和页面内容中提取人物关系。

        Args:
            html: 页面HTML
            person_name: 人物名称
            person_id: 人物ID

        Returns:
            List[Relation]: 关系列表
        """
        soup = BeautifulSoup(html, "lxml")
        relations = []

        # 从信息框提取关系
        infobox_data = self._parse_infobox(soup)

        # 配偶关系
        if infobox_data.get("spouse"):
            spouse_names = self._parse_name_list(infobox_data["spouse"])
            for spouse_name in spouse_names:
                if spouse_name and spouse_name != person_name:
                    relations.append(
                        Relation(
                            source=person_id,
                            target=spouse_name,  # 注意：这里需要后续实体链接
                            type="MARRIED_TO",
                        )
                    )

        # 亲属关系
        if infobox_data.get("relatives"):
            relative_names = self._parse_name_list(infobox_data["relatives"])
            for relative_name in relative_names:
                if relative_name and relative_name != person_name:
                    relations.append(
                        Relation(
                            source=person_id,
                            target=relative_name,
                            type="RELATIVE",
                            properties={"type": "relative"},
                        )
                    )

        logger.info(f"Extracted {len(relations)} relations for {person_name}")
        return relations

    def _parse_name_list(self, text: str) -> List[str]:
        """解析名称列表

        从逗号、顿号分隔的文本中提取名称。

        Args:
            text: 包含多个名称的文本

        Returns:
            List[str]: 名称列表
        """
        if not text:
            return []

        # 使用多种分隔符分割
        names = re.split(r"[,，、;/]", text)
        # 清理并过滤
        names = [name.strip() for name in names if name.strip()]
        # 移除括号内的内容
        names = [re.sub(r"[（(].*?[)）]", "", name).strip() for name in names]

        return names
