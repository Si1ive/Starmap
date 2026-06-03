"""数据模型定义

定义人物、作品、关系等核心数据模型，与 docs/tech/data-model.md 保持一致。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, List, Dict, Any
import uuid


@dataclass
class Person:
    """人物实体"""

    id: str
    name: str
    name_en: Optional[str] = None
    avatar: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[str] = None
    birth_place: Optional[str] = None
    nationality: Optional[str] = None
    height: Optional[float] = None
    summary: Optional[str] = None
    biography: Optional[str] = None
    popularity_score: Optional[float] = None
    categories: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def generate_id(cls) -> str:
        """生成唯一ID"""
        return f"person_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "name_en": self.name_en,
            "avatar": self.avatar,
            "gender": self.gender,
            "birth_date": self.birth_date,
            "birth_place": self.birth_place,
            "nationality": self.nationality,
            "height": self.height,
            "summary": self.summary,
            "biography": self.biography,
            "popularity_score": self.popularity_score,
            "categories": self.categories,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Person":
        """从字典创建"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Work:
    """作品实体"""

    id: str
    title: str
    type: str
    title_en: Optional[str] = None
    release_date: Optional[str] = None
    genre: Optional[str] = None
    rating: Optional[float] = None
    poster: Optional[str] = None
    summary: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def generate_id(cls) -> str:
        """生成唯一ID"""
        return f"work_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "title": self.title,
            "title_en": self.title_en,
            "type": self.type,
            "release_date": self.release_date,
            "genre": self.genre,
            "rating": self.rating,
            "poster": self.poster,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Work":
        """从字典创建"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Relation:
    """关系实体"""

    source: str  # 源实体ID
    target: str  # 目标实体ID
    type: str  # 关系类型
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Relation":
        """从字典创建"""
        return cls(
            source=data["source"],
            target=data["target"],
            type=data["type"],
            properties=data.get("properties", {}),
        )


# 有效的关系类型
VALID_RELATION_TYPES = {
    "MARRIED_TO",
    "COLLABORATED_WITH",
    "MENTOR_OF",
    "RELATIVE",
    "ACTED_IN",
    "DIRECTED",
    "SINGS",
    "COMPOSED",
    "WROTE_LYRICS",
    "PRODUCED",
    "WORKS_FOR",
    "SIGNED_WITH",
    "WON",
}

# 有效的作品类型
VALID_WORK_TYPES = {"album", "movie", "tv", "drama", "book", "single", "ep"}

# 有效的性别
VALID_GENDERS = {"male", "female", None}
