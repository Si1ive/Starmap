"""
Neo4j连接测试

测试Neo4j客户端的连接管理和查询功能。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.neo4j import Neo4jClient, Neo4jConnectionError, Neo4jQueryError


class TestNeo4jClient:
    """Neo4j客户端测试"""
    
    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        return Neo4jClient()
    
    @pytest.mark.asyncio
    async def test_connect_success(self, client):
        """测试成功连接"""
        with patch("app.db.neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value.verify_connectivity = AsyncMock()
            
            await client.connect()
            
            assert client._driver is not None
            mock_driver.return_value.verify_connectivity.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connect_failure(self, client):
        """测试连接失败"""
        with patch("app.db.neo4j.AsyncGraphDatabase.driver") as mock_driver:
            from neo4j.exceptions import ServiceUnavailable
            mock_driver.return_value.verify_connectivity = AsyncMock(
                side_effect=ServiceUnavailable("Connection refused")
            )
            
            with pytest.raises(Neo4jConnectionError):
                await client.connect()
    
    @pytest.mark.asyncio
    async def test_health_check_success(self, client):
        """测试健康检查成功"""
        with patch("app.db.neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value.verify_connectivity = AsyncMock()
            client._driver = mock_driver.return_value
            
            result = await client.health_check()
            assert result is True
    
    @pytest.mark.asyncio
    async def test_health_check_no_driver(self, client):
        """测试无驱动时的健康检查"""
        result = await client.health_check()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_execute_query(self, client):
        """测试查询执行"""
        with patch.object(client, "session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.data = AsyncMock(return_value=[{"name": "周杰伦"}])
            mock_session.run = AsyncMock(return_value=mock_result)
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            
            client._driver = MagicMock()
            
            result = await client.execute_query(
                "MATCH (p:Person) RETURN p.name as name LIMIT 1"
            )
            
            assert len(result) == 1
            assert result[0]["name"] == "周杰伦"
    
    @pytest.mark.asyncio
    async def test_get_person_by_id(self, client):
        """测试获取人物"""
        with patch.object(client, "execute_query") as mock_query:
            mock_query.return_value = [{"person": {"id": "jay", "name": "周杰伦"}}]
            
            result = await client.get_person_by_id("jay")
            
            assert result is not None
            assert result["id"] == "jay"
            assert result["name"] == "周杰伦"
    
    @pytest.mark.asyncio
    async def test_get_person_by_id_not_found(self, client):
        """测试人物不存在"""
        with patch.object(client, "execute_query") as mock_query:
            mock_query.return_value = []
            
            result = await client.get_person_by_id("not-exist")
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_search_persons(self, client):
        """测试搜索人物"""
        with patch.object(client, "execute_query") as mock_query:
            mock_query.return_value = [
                {"person": {"id": "jay", "name": "周杰伦", "category": "singer"}},
                {"person": {"id": "jj", "name": "林俊杰", "category": "singer"}}
            ]
            
            results = await client.search_persons("周", category="singer")
            
            assert len(results) == 2
            assert results[0]["name"] == "周杰伦"


class TestNeo4jIntegration:
    """Neo4j集成测试（需要真实数据库）"""
    
    @pytest.fixture
    async def real_client(self):
        """创建真实连接客户端"""
        client = Neo4jClient()
        try:
            await client.connect()
            yield client
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_connection(self, real_client):
        """测试真实连接"""
        healthy = await real_client.health_check()
        # 如果Docker未启动，此测试会被跳过
        if not healthy:
            pytest.skip("Neo4j服务未启动")
        
        assert healthy is True
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_query(self, real_client):
        """测试真实查询"""
        if not await real_client.health_check():
            pytest.skip("Neo4j服务未启动")
        
        # 创建测试数据
        await real_client.execute_write("""
            CREATE (p:Person {id: 'test-person', name: '测试人物'})
        """)
        
        # 查询
        result = await real_client.get_person_by_id("test-person")
        assert result is not None
        assert result["name"] == "测试人物"
        
        # 清理
        await real_client.execute_write("""
            MATCH (p:Person {id: 'test-person'}) DELETE p
        """)
