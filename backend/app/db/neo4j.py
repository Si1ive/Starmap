"""
Neo4j 图数据库连接封装

提供连接池管理、基础CRUD操作和Cypher查询执行。
支持连接健康检查和自动重连。
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Neo4jConnectionError(Exception):
    """Neo4j连接异常"""
    pass


class Neo4jQueryError(Exception):
    """Neo4j查询异常"""
    pass


class Neo4jClient:
    """
    Neo4j 异步客户端
    
    封装了连接池管理和常用查询操作，支持：
    - 异步连接管理
    - 连接池配置
    - 事务支持
    - 健康检查
    - 自动重试
    """
    
    def __init__(self):
        self._driver: Optional[AsyncDriver] = None
        self._uri = settings.NEO4J_URI
        self._user = settings.NEO4J_USER
        self._password = settings.NEO4J_PASSWORD
        
    async def connect(self) -> None:
        """
        建立Neo4j连接
        
        创建异步驱动实例并验证连接可用性。
        如果连接失败会抛出 Neo4jConnectionError。
        """
        try:
            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
                max_connection_pool_size=50,
                connection_acquisition_timeout=30,
                connection_timeout=30
            )
            # 验证连接
            await self._driver.verify_connectivity()
            logger.info("Neo4j连接成功", uri=self._uri)
        except ServiceUnavailable as e:
            logger.error("Neo4j服务不可用", error=str(e), uri=self._uri)
            raise Neo4jConnectionError(f"无法连接到Neo4j: {e}")
        except Neo4jError as e:
            logger.error("Neo4j连接失败", error=str(e), uri=self._uri)
            raise Neo4jConnectionError(f"Neo4j连接错误: {e}")
    
    async def close(self) -> None:
        """关闭Neo4j连接"""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j连接已关闭")
    
    async def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            bool: 连接正常返回True，否则返回False
        """
        if not self._driver:
            return False
        try:
            await self._driver.verify_connectivity()
            return True
        except Exception:
            return False
    
    @asynccontextmanager
    async def session(self):
        """
        异步会话上下文管理器
        
        Usage:
            async with neo4j_client.session() as session:
                result = await session.run("MATCH (n) RETURN n LIMIT 1")
        """
        if not self._driver:
            await self.connect()
        
        session = self._driver.session()
        try:
            yield session
        finally:
            await session.close()
    
    async def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        执行Cypher查询
        
        Args:
            query: Cypher查询语句
            parameters: 查询参数
            database: 目标数据库（默认使用默认数据库）
            
        Returns:
            List[Dict]: 查询结果列表
            
        Raises:
            Neo4jQueryError: 查询执行失败
        """
        parameters = parameters or {}
        
        try:
            async with self.session() as session:
                result = await session.run(query, parameters)
                records = await result.data()
                return records
        except Neo4jError as e:
            logger.error(
                "Cypher查询失败",
                error=str(e),
                query=query,
                parameters=parameters
            )
            raise Neo4jQueryError(f"查询执行失败: {e}")
    
    async def execute_write(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        执行写操作（自动使用写事务）
        
        Args:
            query: Cypher写语句
            parameters: 查询参数
            
        Returns:
            List[Dict]: 操作结果
        """
        parameters = parameters or {}
        
        try:
            async with self.session() as session:
                result = await session.execute_write(
                    self._run_query_tx, query, parameters
                )
                return result
        except Neo4jError as e:
            logger.error(
                "Cypher写操作失败",
                error=str(e),
                query=query,
                parameters=parameters
            )
            raise Neo4jQueryError(f"写操作失败: {e}")
    
    @staticmethod
    async def _run_query_tx(tx, query: str, parameters: Dict[str, Any]):
        """事务内执行查询"""
        result = await tx.run(query, parameters)
        return await result.data()
    
    # ========== 常用查询封装 ==========
    
    async def get_person_by_id(self, person_id: str) -> Optional[Dict[str, Any]]:
        """
        根据ID获取人物
        
        Args:
            person_id: 人物唯一标识
            
        Returns:
            Dict: 人物信息，不存在返回None
        """
        query = """
        MATCH (p:Person {id: $person_id})
        RETURN p {
            .id,
            .name,
            .name_en,
            .gender,
            .categories,
            .birth_date,
            .birth_place,
            .nationality,
            .summary,
            .popularity_score
        } AS person
        """
        results = await self.execute_query(query, {"person_id": person_id})
        return results[0]["person"] if results else None
    
    async def search_persons(
        self,
        keyword: str,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        搜索人物
        
        Args:
            keyword: 搜索关键词
            category: 分类过滤
            skip: 跳过数量
            limit: 返回数量
            
        Returns:
            List[Dict]: 人物列表
        """
        if category and category != "all":
            query = """
            MATCH (p:Person)
            WHERE (p.name CONTAINS $keyword 
               OR p.summary CONTAINS $keyword
               OR p.name_en CONTAINS $keyword)
            AND $category IN p.categories
            RETURN p {
                .id,
                .name,
                .categories,
                .summary,
                .popularity_score
            } AS person
            SKIP $skip LIMIT $limit
            """
            params = {
                "keyword": keyword,
                "category": category,
                "skip": skip,
                "limit": limit
            }
        else:
            query = """
            MATCH (p:Person)
            WHERE p.name CONTAINS $keyword 
               OR p.summary CONTAINS $keyword
               OR p.name_en CONTAINS $keyword
            RETURN p {
                .id,
                .name,
                .categories,
                .summary,
                .popularity_score
            } AS person
            SKIP $skip LIMIT $limit
            """
            params = {"keyword": keyword, "skip": skip, "limit": limit}
        
        results = await self.execute_query(query, params)
        return [r["person"] for r in results]
    
    async def get_person_relations(
        self,
        person_id: str,
        depth: int = 1,
        relation_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取人物关系网络
        
        Args:
            person_id: 中心人物ID
            depth: 关系深度（1-3）
            relation_type: 关系类型过滤
            
        Returns:
            Dict: 包含nodes和edges的关系网络
        """
        depth = min(max(depth, 1), 3)
        
        if relation_type:
            query = """
            MATCH path = (center:Person {id: $person_id})-[r:%s*1..%d]-(related:Person)
            RETURN center, related, r, relationships(path) as rels
            LIMIT 100
            """ % (relation_type, depth)
        else:
            query = """
            MATCH path = (center:Person {id: $person_id})-[r*1..%d]-(related:Person)
            RETURN center, related, r, relationships(path) as rels
            LIMIT 100
            """ % depth
        
        results = await self.execute_query(query, {"person_id": person_id})
        
        # 构建节点和边
        nodes = {}
        edges = []
        
        for record in results:
            center = record["center"]
            related = record["related"]
            rels = record["rels"]
            
            # 添加节点
            for node in [center, related]:
                node_id = node["id"]
                if node_id not in nodes:
                    nodes[node_id] = {
                        "id": node_id,
                        "name": node.get("name", ""),
                        "category": node.get("category", ""),
                        "avatar_url": node.get("avatar_url", "")
                    }
            
            # 添加边
            for rel in rels:
                edges.append({
                    "source": rel.start_node["id"],
                    "target": rel.end_node["id"],
                    "type": rel.type,
                    "properties": dict(rel)
                })
        
        return {
            "center": {"id": center["id"], "name": center.get("name", "")},
            "nodes": list(nodes.values()),
            "edges": edges
        }
    
    async def get_similar_persons(
        self,
        person_id: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        获取相似人物（基于共同关系）
        
        Args:
            person_id: 参考人物ID
            limit: 返回数量
            
        Returns:
            List[Dict]: 相似人物列表（含相似度分数）
        """
        query = """
        MATCH (p:Person {id: $person_id})-[r1]-(common)-[r2]-(similar:Person)
        WHERE p <> similar
        WITH similar, 
             COUNT(common) as common_count,
             COLLECT(DISTINCT common.name) as common_names
        RETURN similar {
            .id,
            .name,
            .category,
            .avatar_url
        } as person,
        common_count as score,
        common_names
        ORDER BY common_count DESC
        LIMIT $limit
        """
        
        results = await self.execute_query(
            query, 
            {"person_id": person_id, "limit": limit}
        )
        
        return [
            {
                **r["person"],
                "similarity_score": r["score"],
                "common_connections": r["common_names"]
            }
            for r in results
        ]


# 全局客户端实例
neo4j_client = Neo4jClient()


async def get_neo4j_client() -> Neo4jClient:
    """
    获取Neo4j客户端（依赖注入用）
    
    Returns:
        Neo4jClient: 已连接的客户端实例
    """
    if not neo4j_client._driver:
        await neo4j_client.connect()
    return neo4j_client
