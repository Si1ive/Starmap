"""
数据处理管道

参考 Scrapy 的 Item Pipeline 设计，实现数据清洗、验证和存储。
"""

import re
from typing import Optional, Dict, Any, List
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from crawler.engine import Pipeline, Item, Spider
from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.models.mysql_models import Person, Work

logger = get_logger(__name__)


class DataCleaningPipeline(Pipeline):
    """数据清洗管道"""

    async def process_item(self, item: Item, spider: Spider) -> Optional[Item]:
        """清洗数据"""
        if item.item_type == "person":
            item.data = self._clean_person_data(item.data)
        elif item.item_type == "work":
            item.data = self._clean_work_data(item.data)
        
        return item

    def _clean_person_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """清洗人物数据"""
        cleaned = {}
        
        # 清洗名称
        if "name" in data:
            cleaned["name"] = self._clean_text(data["name"])
        
        # 清洗摘要
        if "summary" in data:
            cleaned["summary"] = self._clean_text(data["summary"])
        
        # 提取结构化信息
        raw_info = data.get("raw_info", {})
        
        # 提取出生日期
        if "birth_date" not in cleaned:
            for key in ["出生日期", "出生", "Birth date", "Born"]:
                if key in raw_info:
                    cleaned["birth_date"] = self._extract_date(raw_info[key])
                    break
        
        # 提取国籍
        if "nationality" not in cleaned:
            for key in ["国籍", "国家", "Nationality"]:
                if key in raw_info:
                    cleaned["nationality"] = raw_info[key]
                    break
        
        # 提取职业/分类
        if "categories" not in cleaned:
            categories = []
            for key in ["职业", "职业", "Occupation", "Profession"]:
                if key in raw_info:
                    categories = self._extract_categories(raw_info[key])
                    break
            if categories:
                cleaned["categories"] = categories
        
        # 保留原始数据
        cleaned["raw_data"] = data
        cleaned["source"] = data.get("source", "unknown")
        cleaned["source_url"] = data.get("source_url", "")
        cleaned["crawled_at"] = data.get("crawled_at", datetime.utcnow().isoformat())
        
        return cleaned

    def _clean_work_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """清洗作品数据"""
        cleaned = {}
        
        if "title" in data:
            cleaned["title"] = self._clean_text(data["title"])
        
        if "summary" in data:
            cleaned["summary"] = self._clean_text(data["summary"])
        
        # 提取评分
        if "rating" in data:
            cleaned["rating"] = self._extract_rating(data["rating"])
        
        # 提取年份
        if "year" in data:
            cleaned["year"] = self._extract_year(data["year"])
        
        cleaned["raw_data"] = data
        cleaned["source"] = data.get("source", "unknown")
        cleaned["source_url"] = data.get("source_url", "")
        cleaned["crawled_at"] = data.get("crawled_at", datetime.utcnow().isoformat())
        
        return cleaned

    @staticmethod
    def _clean_text(text: str) -> str:
        """清洗文本"""
        if not text:
            return ""
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)
        # 移除特殊字符
        text = text.strip()
        return text

    @staticmethod
    def _extract_date(text: str) -> Optional[str]:
        """提取日期"""
        # 匹配常见日期格式
        patterns = [
            r'(\d{4})年(\d{1,2})月(\d{1,2})日',
            r'(\d{4})-(\d{2})-(\d{2})',
            r'(\d{4})/(\d{2})/(\d{2})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"
        
        return None

    @staticmethod
    def _extract_categories(text: str) -> List[str]:
        """提取分类"""
        # 按常见分隔符分割
        categories = re.split(r'[,，、/\\s]+', text)
        return [c.strip() for c in categories if c.strip()]

    @staticmethod
    def _extract_rating(text: str) -> Optional[float]:
        """提取评分"""
        try:
            match = re.search(r'(\d+\.?\d*)', str(text))
            if match:
                return float(match.group(1))
        except:
            pass
        return None

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        """提取年份"""
        try:
            match = re.search(r'(\d{4})', str(text))
            if match:
                return int(match.group(1))
        except:
            pass
        return None


class DataValidationPipeline(Pipeline):
    """数据验证管道"""

    async def process_item(self, item: Item, spider: Spider) -> Optional[Item]:
        """验证数据"""
        if item.item_type == "person":
            if not self._validate_person(item.data):
                logger.warning(f"Invalid person data: {item.data.get('name')}")
                return None
        elif item.item_type == "work":
            if not self._validate_work(item.data):
                logger.warning(f"Invalid work data: {item.data.get('title')}")
                return None
        
        return item

    def _validate_person(self, data: Dict[str, Any]) -> bool:
        """验证人物数据"""
        # 必须有名称
        if not data.get("name"):
            return False
        
        # 名称长度检查
        if len(data["name"]) < 1 or len(data["name"]) > 100:
            return False
        
        return True

    def _validate_work(self, data: Dict[str, Any]) -> bool:
        """验证作品数据"""
        # 必须有标题
        if not data.get("title"):
            return False
        
        return True


class DatabaseStoragePipeline(Pipeline):
    """数据库存储管道"""

    def __init__(self):
        self._session: Optional[AsyncSession] = None

    async def open(self):
        """打开数据库连接"""
        # 数据库会话将在 process_item 中创建
        pass

    async def close(self):
        """关闭数据库连接"""
        pass

    async def process_item(self, item: Item, spider: Spider) -> Optional[Item]:
        """存储到数据库"""
        try:
            async with mysql_client.session() as session:
                if item.item_type == "person":
                    await self._store_person(session, item.data)
                elif item.item_type == "work":
                    await self._store_work(session, item.data)
                
                await session.commit()
                logger.info(f"Stored {item.item_type}: {item.data.get('name') or item.data.get('title')}")
        except Exception as e:
            logger.error(f"Failed to store item: {e}")
            return None
        
        return item

    async def _store_person(self, session: AsyncSession, data: Dict[str, Any]):
        """存储人物数据"""
        import uuid
        
        person = Person(
            id=f"person_{uuid.uuid4().hex[:8]}",
            name=data.get("name", ""),
            name_en=data.get("name_en"),
            gender=data.get("gender"),
            birth_date=data.get("birth_date"),
            birth_place=data.get("birth_place"),
            nationality=data.get("nationality"),
            summary=data.get("summary"),
            categories=data.get("categories", []),
            status="pending",  # 待审核
            crawl_source=data.get("source"),
            crawl_url=data.get("source_url"),
            raw_data=data.get("raw_data"),
        )
        
        session.add(person)

    async def _store_work(self, session: AsyncSession, data: Dict[str, Any]):
        """存储作品数据"""
        import uuid
        
        work = Work(
            id=f"work_{uuid.uuid4().hex[:8]}",
            title=data.get("title", ""),
            title_en=data.get("title_en"),
            type=data.get("type", "movie"),
            release_date=data.get("year"),
            rating=data.get("rating"),
            summary=data.get("summary"),
            status="pending",
            crawl_source=data.get("source"),
            crawl_url=data.get("source_url"),
            raw_data=data.get("raw_data"),
        )
        
        session.add(work)


class Neo4jStoragePipeline(Pipeline):
    """Neo4j 图数据库存储管道"""

    async def process_item(self, item: Item, spider: Spider) -> Optional[Item]:
        """存储到 Neo4j"""
        if item.item_type == "person":
            await self._store_person_to_neo4j(item.data)
        elif item.item_type == "work":
            await self._store_work_to_neo4j(item.data)
        
        return item

    async def _store_person_to_neo4j(self, data: Dict[str, Any]):
        """存储人物到 Neo4j"""
        from app.db.neo4j import neo4j_client
        
        try:
            query = """
            MERGE (p:Person {id: $id})
            SET p.name = $name,
                p.name_en = $name_en,
                p.gender = $gender,
                p.birth_date = $birth_date,
                p.nationality = $nationality,
                p.summary = $summary,
                p.categories = $categories,
                p.source = $source,
                p.updated_at = datetime()
            """
            
            await neo4j_client.run_query(query, {
                "id": data.get("id", f"person_{hash(data.get('name', ''))}"),
                "name": data.get("name", ""),
                "name_en": data.get("name_en", ""),
                "gender": data.get("gender", "unknown"),
                "birth_date": data.get("birth_date", ""),
                "nationality": data.get("nationality", ""),
                "summary": data.get("summary", ""),
                "categories": data.get("categories", []),
                "source": data.get("source", "unknown"),
            })
            
            logger.info(f"Stored person to Neo4j: {data.get('name')}")
        except Exception as e:
            logger.error(f"Failed to store person to Neo4j: {e}")

    async def _store_work_to_neo4j(self, data: Dict[str, Any]):
        """存储作品到 Neo4j"""
        from app.db.neo4j import neo4j_client
        
        try:
            query = """
            MERGE (w:Work {id: $id})
            SET w.title = $title,
                w.type = $type,
                w.year = $year,
                w.rating = $rating,
                w.summary = $summary,
                w.source = $source,
                w.updated_at = datetime()
            """
            
            await neo4j_client.run_query(query, {
                "id": data.get("id", f"work_{hash(data.get('title', ''))}"),
                "title": data.get("title", ""),
                "type": data.get("type", "movie"),
                "year": data.get("year", ""),
                "rating": data.get("rating", 0),
                "summary": data.get("summary", ""),
                "source": data.get("source", "unknown"),
            })
            
            logger.info(f"Stored work to Neo4j: {data.get('title')}")
        except Exception as e:
            logger.error(f"Failed to store work to Neo4j: {e}")


class LogPipeline(Pipeline):
    """日志记录管道"""

    async def process_item(self, item: Item, spider: Spider) -> Optional[Item]:
        """记录处理日志"""
        logger.info(
            f"Pipeline processed item: type={item.item_type}, "
            f"source={item.source_url}, "
            f"data_keys={list(item.data.keys())}"
        )
        return item
