"""数据清洗模块

提供数据标准化、格式化、缺失值处理等功能。
所有数据在导入前必须经过清洗。
"""

import re
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from .models import Person, Work, Relation, VALID_GENDERS, VALID_WORK_TYPES
from .base import CrawlerError

logger = logging.getLogger(__name__)


class DataCleaner:
    """数据清洗器

    对爬取的原始数据进行清洗和标准化处理。

    使用示例:
        >>> cleaner = DataCleaner()
        >>> person = cleaner.clean_person(raw_data)
        >>> works = cleaner.clean_works(raw_works)
    """

    # 文本字段最大长度
    MAX_SUMMARY_LENGTH = 2000
    MAX_BIOGRAPHY_LENGTH = 10000
    MAX_NAME_LENGTH = 100

    # 日期范围限制
    MIN_DATE = "1900-01-01"
    MAX_DATE = datetime.now().strftime("%Y-%m-%d")

    def __init__(self):
        """初始化清洗器"""
        logger.info("DataCleaner initialized")

    def clean_person(self, person: Person) -> Person:
        """清洗人物数据

        对人物数据进行标准化处理，包括：
        - 去除空白字符
        - 标准化日期格式
        - 验证必填字段
        - 截断过长文本

        Args:
            person: 原始人物数据

        Returns:
            Person: 清洗后的人物数据

        Raises:
            ValueError: 数据验证失败
        """
        # 创建副本以避免修改原始数据
        data = person.to_dict()

        # 清洗名称
        if data.get("name"):
            data["name"] = self._clean_text(data["name"])
            data["name"] = data["name"][: self.MAX_NAME_LENGTH]
        else:
            raise ValueError("人物姓名不能为空")

        # 清洗英文名
        if data.get("name_en"):
            data["name_en"] = self._clean_text(data["name_en"])

        # 清洗性别
        if data.get("gender"):
            data["gender"] = self._clean_gender(data["gender"])

        # 清洗日期
        if data.get("birth_date"):
            data["birth_date"] = self._clean_date(data["birth_date"])

        # 清洗出生地
        if data.get("birth_place"):
            data["birth_place"] = self._clean_text(data["birth_place"])

        # 清洗国籍
        if data.get("nationality"):
            data["nationality"] = self._clean_text(data["nationality"])

        # 清洗身高
        if data.get("height") is not None:
            data["height"] = self._clean_height(data["height"])

        # 清洗摘要
        if data.get("summary"):
            data["summary"] = self._clean_text(data["summary"])
            data["summary"] = self._truncate_text(data["summary"], self.MAX_SUMMARY_LENGTH)

        # 清洗传记
        if data.get("biography"):
            data["biography"] = self._clean_text(data["biography"])
            data["biography"] = self._truncate_text(
                data["biography"], self.MAX_BIOGRAPHY_LENGTH
            )

        # 清洗分类
        if data.get("categories"):
            data["categories"] = self._clean_categories(data["categories"])

        # 更新时间
        data["updated_at"] = datetime.now().isoformat()

        cleaned_person = Person.from_dict(data)
        logger.info(f"Cleaned person: {cleaned_person.name}")
        return cleaned_person

    def clean_work(self, work: Work) -> Work:
        """清洗作品数据

        Args:
            work: 原始作品数据

        Returns:
            Work: 清洗后的作品数据

        Raises:
            ValueError: 数据验证失败
        """
        data = work.to_dict()

        # 清洗标题
        if data.get("title"):
            data["title"] = self._clean_text(data["title"])
        else:
            raise ValueError("作品标题不能为空")

        # 清洗类型
        if data.get("type"):
            data["type"] = self._clean_work_type(data["type"])
        else:
            raise ValueError("作品类型不能为空")

        # 清洗英文标题
        if data.get("title_en"):
            data["title_en"] = self._clean_text(data["title_en"])

        # 清洗发布日期
        if data.get("release_date"):
            data["release_date"] = self._clean_date(data["release_date"])

        # 清洗流派
        if data.get("genre"):
            data["genre"] = self._clean_text(data["genre"])

        # 清洗评分
        if data.get("rating") is not None:
            data["rating"] = self._clean_rating(data["rating"])

        # 清洗简介
        if data.get("summary"):
            data["summary"] = self._clean_text(data["summary"])
            data["summary"] = self._truncate_text(data["summary"], self.MAX_SUMMARY_LENGTH)

        cleaned_work = Work.from_dict(data)
        logger.info(f"Cleaned work: {cleaned_work.title}")
        return cleaned_work

    def clean_relation(self, relation: Relation) -> Relation:
        """清洗关系数据

        Args:
            relation: 原始关系数据

        Returns:
            Relation: 清洗后的关系数据

        Raises:
            ValueError: 数据验证失败
        """
        data = relation.to_dict()

        # 验证源和目标
        if not data.get("source"):
            raise ValueError("关系源实体不能为空")
        if not data.get("target"):
            raise ValueError("关系目标实体不能为空")

        # 不能自环
        if data["source"] == data["target"]:
            raise ValueError("关系不能指向自身")

        # 清洗关系类型
        if not data.get("type"):
            raise ValueError("关系类型不能为空")

        data["type"] = data["type"].upper().strip()

        # 清洗属性
        if data.get("properties"):
            data["properties"] = self._clean_properties(data["properties"])

        cleaned_relation = Relation.from_dict(data)
        logger.info(f"Cleaned relation: {cleaned_relation.type}")
        return cleaned_relation

    def clean_persons(self, persons: List[Person]) -> List[Person]:
        """批量清洗人物数据

        Args:
            persons: 人物列表

        Returns:
            List[Person]: 清洗后的人物列表
        """
        cleaned = []
        for person in persons:
            try:
                cleaned_person = self.clean_person(person)
                cleaned.append(cleaned_person)
            except Exception as e:
                logger.warning(f"Failed to clean person {person.name}: {e}")

        logger.info(f"Cleaned {len(cleaned)}/{len(persons)} persons")
        return cleaned

    def clean_works(self, works: List[Work]) -> List[Work]:
        """批量清洗作品数据

        Args:
            works: 作品列表

        Returns:
            List[Work]: 清洗后的作品列表
        """
        cleaned = []
        for work in works:
            try:
                cleaned_work = self.clean_work(work)
                cleaned.append(cleaned_work)
            except Exception as e:
                logger.warning(f"Failed to clean work {work.title}: {e}")

        logger.info(f"Cleaned {len(cleaned)}/{len(works)} works")
        return cleaned

    def clean_relations(self, relations: List[Relation]) -> List[Relation]:
        """批量清洗关系数据

        Args:
            relations: 关系列表

        Returns:
            List[Relation]: 清洗后的关系列表
        """
        cleaned = []
        for relation in relations:
            try:
                cleaned_relation = self.clean_relation(relation)
                cleaned.append(cleaned_relation)
            except Exception as e:
                logger.warning(f"Failed to clean relation {relation.type}: {e}")

        logger.info(f"Cleaned {len(cleaned)}/{len(relations)} relations")
        return cleaned

    def _clean_text(self, text: str) -> str:
        """清洗文本

        - 去除首尾空白
        - 统一换行符
        - 去除多余空白
        - 去除特殊控制字符

        Args:
            text: 原始文本

        Returns:
            str: 清洗后的文本
        """
        if not text:
            return ""

        # 去除首尾空白
        text = text.strip()

        # 统一换行符
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 去除多余空白（保留段落间的空行）
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            cleaned_line = re.sub(r"\s+", " ", line).strip()
            if cleaned_line:
                cleaned_lines.append(cleaned_line)

        text = "\n".join(cleaned_lines)

        # 去除特殊控制字符
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        return text

    def _truncate_text(self, text: str, max_length: int) -> str:
        """截断文本

        Args:
            text: 原始文本
            max_length: 最大长度

        Returns:
            str: 截断后的文本
        """
        if len(text) <= max_length:
            return text

        # 在句子边界截断
        truncated = text[:max_length]
        last_period = max(
            truncated.rfind("。"),
            truncated.rfind("."),
            truncated.rfind("!"),
            truncated.rfind("?"),
        )

        if last_period > max_length * 0.8:  # 如果能在80%长度内找到句子边界
            return truncated[: last_period + 1]

        return truncated + "..."

    def _clean_gender(self, gender: str) -> Optional[str]:
        """清洗性别

        Args:
            gender: 原始性别值

        Returns:
            Optional[str]: 标准化性别值
        """
        if not gender:
            return None

        gender = gender.lower().strip()

        gender_map = {
            "male": "male",
            "m": "male",
            "男": "male",
            "男性": "male",
            "female": "female",
            "f": "female",
            "女": "female",
            "女性": "female",
        }

        return gender_map.get(gender)

    def _clean_date(self, date_str: str) -> Optional[str]:
        """清洗日期

        将各种日期格式转换为ISO格式（YYYY-MM-DD）。

        Args:
            date_str: 日期字符串

        Returns:
            Optional[str]: ISO格式日期或None
        """
        if not date_str:
            return None

        date_str = date_str.strip()

        # 已经是ISO格式
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            if self._is_valid_date(date_str):
                return date_str
            return None

        # YYYY年MM月DD日
        match = re.match(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", date_str)
        if match:
            year, month, day = match.groups()
            iso_date = f"{year}-{int(month):02d}-{int(day):02d}"
            if self._is_valid_date(iso_date):
                return iso_date

        # YYYY/MM/DD
        match = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_str)
        if match:
            iso_date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
            if self._is_valid_date(iso_date):
                return iso_date

        # 只有年份
        match = re.match(r"(\d{4})年?", date_str)
        if match:
            iso_date = f"{match.group(1)}-01-01"
            if self._is_valid_date(iso_date):
                return iso_date

        logger.warning(f"Could not parse date: {date_str}")
        return None

    def _is_valid_date(self, date_str: str) -> bool:
        """验证日期是否在有效范围内

        Args:
            date_str: ISO格式日期字符串

        Returns:
            bool: 是否有效
        """
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            min_date = datetime.strptime(self.MIN_DATE, "%Y-%m-%d")
            max_date = datetime.strptime(self.MAX_DATE, "%Y-%m-%d")
            return min_date <= date_obj <= max_date
        except ValueError:
            return False

    def _clean_height(self, height: Any) -> Optional[float]:
        """清洗身高

        Args:
            height: 身高值（可能是数字或字符串）

        Returns:
            Optional[float]: 清洗后的身高（厘米）
        """
        if height is None:
            return None

        if isinstance(height, (int, float)):
            value = float(height)
            if 50 <= value <= 300:
                return value
            return None

        if isinstance(height, str):
            # 匹配数字+单位
            match = re.search(r"(\d+\.?\d*)\s*(cm|厘米|公分|m|米)?", height)
            if match:
                value = float(match.group(1))
                unit = match.group(2) if match.group(2) else ""

                if unit in ("m", "米"):
                    value *= 100

                if 50 <= value <= 300:
                    return value

        return None

    def _clean_work_type(self, work_type: str) -> str:
        """清洗作品类型

        Args:
            work_type: 原始类型

        Returns:
            str: 标准化类型
        """
        if not work_type:
            return "album"

        work_type = work_type.lower().strip()

        type_map = {
            "album": "album",
            "专辑": "album",
            "single": "single",
            "单曲": "single",
            "ep": "ep",
            "movie": "movie",
            "电影": "movie",
            "tv": "tv",
            "电视剧": "tv",
            "drama": "drama",
            "戏剧": "drama",
            "book": "book",
            "书籍": "book",
            "著作": "book",
        }

        return type_map.get(work_type, "album")

    def _clean_rating(self, rating: Any) -> Optional[float]:
        """清洗评分

        Args:
            rating: 原始评分

        Returns:
            Optional[float]: 清洗后的评分（0-10）
        """
        if rating is None:
            return None

        try:
            value = float(rating)
            if 0 <= value <= 10:
                return round(value, 1)
            elif 0 <= value <= 100:  # 可能是百分制
                return round(value / 10, 1)
        except (ValueError, TypeError):
            pass

        return None

    def _clean_categories(self, categories: List[str]) -> List[str]:
        """清洗分类列表

        Args:
            categories: 原始分类列表

        Returns:
            List[str]: 清洗后的分类列表
        """
        cleaned = []
        for cat in categories:
            cat = self._clean_text(cat)
            if cat and cat not in cleaned:
                cleaned.append(cat)
        return cleaned

    def _clean_properties(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """清洗关系属性

        Args:
            properties: 原始属性

        Returns:
            Dict[str, Any]: 清洗后的属性
        """
        cleaned = {}
        for key, value in properties.items():
            if value is not None:
                if isinstance(value, str):
                    cleaned[key] = self._clean_text(value)
                else:
                    cleaned[key] = value
        return cleaned
