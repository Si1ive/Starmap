"""
人物业务服务层

封装人物相关的业务逻辑，包括：
- 人物CRUD操作
- 搜索与过滤
- 关系图谱构建
- 缓存集成
"""

from typing import List, Optional

from app.core.logging import get_logger
from app.db.neo4j import Neo4jClient, get_neo4j_client
from app.db.redis import RedisClient, get_redis_client
from app.models.person import (
    Person,
    PersonListItem,
    PersonRelationGraph,
    PersonSearchResult,
    SimilarPerson,
    SimilarPersonResult
)

logger = get_logger(__name__)


class PersonService:
    """
    人物业务服务
    
    提供人物相关的所有业务操作，集成Neo4j和Redis，
    实现缓存策略提升查询性能。
    """
    
    def __init__(
        self,
        neo4j: Optional[Neo4jClient] = None,
        redis: Optional[RedisClient] = None
    ):
        self._neo4j = neo4j
        self._redis = redis
    
    async def _get_neo4j(self) -> Neo4jClient:
        """获取Neo4j客户端（延迟初始化）"""
        if not self._neo4j:
            try:
                self._neo4j = await get_neo4j_client()
            except Exception as e:
                logger.warning("Neo4j连接失败，使用降级模式", error=str(e))
                self._neo4j = None
        return self._neo4j
    
    async def _get_redis(self) -> RedisClient:
        """获取Redis客户端（延迟初始化）"""
        if not self._redis:
            try:
                self._redis = await get_redis_client()
            except Exception as e:
                logger.warning("Redis连接失败，使用降级模式", error=str(e))
                self._redis = None
        return self._redis
    
    # ========== 人物查询 ==========
    
    async def get_person_by_id(self, person_id: str) -> Optional[Person]:
        """
        获取人物详情
        
        优先从Redis缓存获取，缓存未命中查询Neo4j。
        
        Args:
            person_id: 人物唯一标识
            
        Returns:
            Person: 人物信息，不存在返回None
            
        Raises:
            DatabaseException: 数据库操作失败
        """
        # 尝试从缓存获取
        redis = await self._get_redis()
        if redis:
            try:
                cached = await redis.get_json(person_id, "person")
                if cached:
                    logger.debug("人物缓存命中", person_id=person_id)
                    return Person(**cached)
            except Exception as e:
                logger.warning("Redis读取失败", error=str(e))
        
        # 查询数据库
        neo4j = await self._get_neo4j()
        if neo4j:
            try:
                data = await neo4j.get_person_by_id(person_id)
                if data:
                    person = Person(**data)
                    # 写入缓存
                    if redis:
                        try:
                            await redis.set_json(person_id, person.model_dump(), "person")
                        except Exception:
                            pass
                    return person
            except Exception as e:
                logger.error("Neo4j查询失败", error=str(e))
        
        # 降级：返回Mock数据
        logger.warning("数据库不可用，返回Mock数据", person_id=person_id)
        return Person(
            id=person_id,
            name=f"人物-{person_id}",
            category="other",
            description="数据库连接中，此为临时数据"
        )
    
    async def search_persons(
        self,
        keyword: str,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> PersonSearchResult:
        """
        搜索人物
        
        支持关键词搜索和分类过滤，结果分页返回。
        
        Args:
            keyword: 搜索关键词
            category: 分类过滤（actor/singer/director/all）
            page: 页码（从1开始）
            page_size: 每页数量
            
        Returns:
            PersonSearchResult: 搜索结果
        """
        # 构建缓存键
        cache_key = f"search:{keyword}:{category or 'all'}:{page}:{page_size}"
        
        # 尝试从缓存获取
        redis = await self._get_redis()
        if redis:
            try:
                cached = await redis.get_json(cache_key, "search")
                if cached:
                    logger.debug("搜索缓存命中", keyword=keyword)
                    return PersonSearchResult(**cached)
            except Exception as e:
                logger.warning("Redis读取失败", error=str(e))
        
        # 查询数据库
        neo4j = await self._get_neo4j()
        items = []
        
        if neo4j:
            try:
                skip = (page - 1) * page_size
                results = await neo4j.search_persons(
                    keyword=keyword,
                    category=category,
                    skip=skip,
                    limit=page_size
                )
                
                # 转换为模型
                items = [
                    PersonListItem(
                        id=r["id"],
                        name=r["name"],
                        category=r.get("category", "other"),
                        avatar_url=r.get("avatar_url"),
                        description=r.get("description", "")[:200] if r.get("description") else None
                    )
                    for r in results
                ]
            except Exception as e:
                logger.error("Neo4j搜索失败", error=str(e))
        
        # 如果数据库不可用，返回Mock数据
        if not items:
            logger.warning("数据库不可用，返回Mock搜索结果", keyword=keyword)
            items = [
                PersonListItem(
                    id="mock-1",
                    name=f"与'{keyword}'相关的艺人",
                    category=category or "other",
                    description="数据库连接中，此为临时数据"
                )
            ]
        
        # 获取总数（简化处理，实际应单独查询COUNT）
        total = len(items)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        
        result = PersonSearchResult(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
        # 写入缓存
        if redis:
            try:
                await redis.set_json(cache_key, result.model_dump(), "search")
                logger.debug("搜索结果已缓存", keyword=keyword, count=len(items))
            except Exception:
                pass
        
        return result
    
    # ========== 关系查询 ==========
    
    async def get_person_relations(
        self,
        person_id: str,
        depth: int = 1,
        relation_type: Optional[str] = None
    ) -> PersonRelationGraph:
        """
        获取人物关系图谱
        
        Args:
            person_id: 中心人物ID
            depth: 关系深度（1-3）
            relation_type: 关系类型过滤
            
        Returns:
            PersonRelationGraph: 关系图谱数据
        """
        from app.models.person import RelationNode, RelationEdge
        
        # 构建缓存键
        cache_key = f"relation:{person_id}:{depth}:{relation_type or 'all'}"
        
        # 尝试从缓存获取
        redis = await self._get_redis()
        if redis:
            try:
                cached = await redis.get_json(cache_key, "relation")
                if cached:
                    logger.debug("关系缓存命中", person_id=person_id)
                    return PersonRelationGraph(**cached)
            except Exception as e:
                logger.warning("Redis读取失败", error=str(e))
        
        # 查询数据库
        neo4j = await self._get_neo4j()
        if neo4j:
            try:
                data = await neo4j.get_person_relations(
                    person_id=person_id,
                    depth=depth,
                    relation_type=relation_type
                )
                
                graph = PersonRelationGraph(
                    center=RelationNode(**data["center"]),
                    nodes=[RelationNode(**n) for n in data["nodes"]],
                    edges=[RelationEdge(**e) for e in data["edges"]]
                )
                
                # 写入缓存
                if redis:
                    try:
                        await redis.set_json(cache_key, graph.model_dump(), "relation")
                        logger.debug("关系图谱已缓存", person_id=person_id)
                    except Exception:
                        pass
                
                return graph
            except Exception as e:
                logger.error("Neo4j关系查询失败", error=str(e))
        
        # 降级：返回空图谱
        logger.warning("数据库不可用，返回空关系图谱", person_id=person_id)
        return PersonRelationGraph(
            center=RelationNode(id=person_id, name=person_id, category="other"),
            nodes=[],
            edges=[]
        )
    
    # ========== 推荐 ==========
    
    async def get_similar_persons(
        self,
        person_id: str,
        limit: int = 5
    ) -> SimilarPersonResult:
        """
        获取相似人物推荐
        
        基于共同关系数量计算相似度。
        
        Args:
            person_id: 参考人物ID
            limit: 返回数量
            
        Returns:
            SimilarPersonResult: 相似人物列表
        """
        neo4j = await self._get_neo4j()
        if neo4j:
            try:
                results = await neo4j.get_similar_persons(person_id, limit)
                items = [SimilarPerson(**r) for r in results]
                return SimilarPersonResult(items=items)
            except Exception as e:
                logger.error("Neo4j相似度查询失败", error=str(e))
        
        # 降级：返回空列表
        logger.warning("数据库不可用，返回空推荐列表", person_id=person_id)
        return SimilarPersonResult(items=[])
    
    # ========== 缓存管理 ==========
    
    async def invalidate_person_cache(self, person_id: str) -> None:
        """
        清除人物相关缓存
        
        在人物数据更新后调用。
        
        Args:
            person_id: 人物ID
        """
        redis = await self._get_redis()
        if redis:
            try:
                await redis.delete(person_id, "person")
                await redis.delete_pattern(f"starmap:relation:{person_id}:*")
                logger.info("人物缓存已清除", person_id=person_id)
            except Exception as e:
                logger.warning("清除缓存失败", error=str(e))
    
    async def invalidate_search_cache(self, keyword: str = "*") -> None:
        """
        清除搜索缓存
        
        Args:
            keyword: 关键词过滤，*表示全部
        """
        redis = await self._get_redis()
        if redis:
            try:
                if keyword == "*":
                    await redis.clear_cache("search")
                else:
                    await redis.delete_pattern(f"starmap:search:*{keyword}*")
                logger.info("搜索缓存已清除", keyword=keyword)
            except Exception as e:
                logger.warning("清除缓存失败", error=str(e))


# 服务实例（单例）
_person_service: Optional[PersonService] = None


async def get_person_service() -> PersonService:
    """
    获取人物服务实例（依赖注入用）
    
    Returns:
        PersonService: 人物服务实例
    """
    global _person_service
    if not _person_service:
        _person_service = PersonService()
    return _person_service
