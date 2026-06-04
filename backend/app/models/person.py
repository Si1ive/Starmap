"""
人物数据模型

定义人物相关的Pydantic模型，用于：
- API请求/响应验证
- 数据序列化
- 文档生成
"""

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


class PersonBase(BaseModel):
    """人物基础模型"""
    
    name: str = Field(..., min_length=1, max_length=100, description="人物姓名")
    name_en: Optional[str] = Field(
        default=None,
        max_length=100,
        description="英文名"
    )
    gender: Optional[str] = Field(
        default=None,
        description="性别",
        examples=["male", "female"]
    )
    categories: List[str] = Field(
        default=["other"],
        description="人物分类列表",
        examples=[["actor"], ["singer", "songwriter"]]
    )
    summary: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="人物简介"
    )
    nationality: Optional[str] = Field(
        default=None,
        max_length=50,
        description="国籍"
    )
    birth_date: Optional[str] = Field(
        default=None,
        description="出生日期（YYYY-MM-DD格式）"
    )
    birth_place: Optional[str] = Field(
        default=None,
        max_length=100,
        description="出生地"
    )
    popularity_score: Optional[float] = Field(
        default=0.0,
        ge=0,
        le=100,
        description="人气分数"
    )
    avatar_url: Optional[str] = Field(
        default=None,
        description="头像URL"
    )
    aliases: Optional[List[str]] = Field(
        default=None,
        description="别名列表"
    )


class PersonCreate(PersonBase):
    """创建人物请求模型"""
    
    id: Optional[str] = Field(
        default=None,
        description="人物唯一标识（可选，不传则自动生成）"
    )
    # 兼容旧字段
    category: Optional[str] = Field(
        default=None,
        description="人物分类（兼容旧版，优先使用categories）"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="人物简介（兼容旧版，优先使用summary）"
    )


class PersonUpdate(BaseModel):
    """更新人物请求模型"""
    
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    name_en: Optional[str] = Field(default=None, max_length=100)
    gender: Optional[str] = None
    categories: Optional[List[str]] = None
    summary: Optional[str] = Field(default=None, max_length=5000)
    nationality: Optional[str] = Field(default=None, max_length=50)
    birth_date: Optional[str] = None
    birth_place: Optional[str] = Field(default=None, max_length=100)
    popularity_score: Optional[float] = Field(default=None, ge=0, le=100)
    avatar_url: Optional[str] = None
    aliases: Optional[List[str]] = None
    # 兼容旧字段
    category: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=5000)


class Person(PersonBase):
    """人物完整模型（响应用）"""
    
    id: str = Field(..., description="人物唯一标识")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "jay-chou",
                "name": "周杰伦",
                "name_en": "Jay Chou",
                "gender": "male",
                "categories": ["singer", "actor", "director"],
                "summary": "华语流行乐男歌手、音乐人...",
                "nationality": "中国",
                "birth_date": "1979-01-18",
                "birth_place": "台湾省新北市",
                "popularity_score": 95.5,
                "avatar_url": "https://example.com/avatar.jpg",
                "aliases": ["Jay Chou", "周董"]
            }
        }
    }


class PersonListItem(BaseModel):
    """人物列表项（简化版）"""
    
    id: str = Field(..., description="人物唯一标识")
    name: str = Field(..., description="人物姓名")
    categories: List[str] = Field(default=["other"], description="人物分类列表")
    avatar_url: Optional[str] = Field(default=None, description="头像URL")
    summary: Optional[str] = Field(
        default=None,
        max_length=200,
        description="人物简介（摘要）"
    )
    popularity_score: Optional[float] = Field(
        default=0.0,
        description="人气分数"
    )
    # 兼容旧字段
    category: Optional[str] = Field(
        default=None,
        description="人物分类（兼容旧版）"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=200,
        description="人物简介（兼容旧版）"
    )


class PersonSearchResult(BaseModel):
    """人物搜索结果"""
    
    items: List[PersonListItem] = Field(default=[], description="人物列表")
    total: int = Field(..., ge=0, description="总数")
    page: int = Field(..., ge=1, description="当前页码")
    page_size: int = Field(..., ge=1, le=100, description="每页数量")
    total_pages: int = Field(..., ge=0, description="总页数")


class RelationNode(BaseModel):
    """关系图谱节点"""
    
    id: str = Field(..., description="节点ID")
    name: str = Field(..., description="节点名称")
    category: Optional[str] = Field(default="other", description="节点分类")
    avatar_url: Optional[str] = Field(default=None, description="头像URL")


class RelationEdge(BaseModel):
    """关系图谱边"""
    
    source: str = Field(..., description="源节点ID")
    target: str = Field(..., description="目标节点ID")
    type: str = Field(..., description="关系类型")
    properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description="关系属性"
    )


class PersonRelationGraph(BaseModel):
    """人物关系图谱"""
    
    center: RelationNode = Field(..., description="中心人物")
    nodes: List[RelationNode] = Field(default=[], description="所有节点")
    edges: List[RelationEdge] = Field(default=[], description="所有边")


class SimilarPerson(BaseModel):
    """相似人物"""
    
    id: str = Field(..., description="人物ID")
    name: str = Field(..., description="人物姓名")
    category: str = Field(..., description="人物分类")
    avatar_url: Optional[str] = Field(default=None, description="头像URL")
    similarity_score: int = Field(..., ge=0, description="相似度分数")
    common_connections: List[str] = Field(
        default=[],
        description="共同关联"
    )


class SimilarPersonResult(BaseModel):
    """相似人物推荐结果"""
    
    items: List[SimilarPerson] = Field(default=[], description="相似人物列表")
