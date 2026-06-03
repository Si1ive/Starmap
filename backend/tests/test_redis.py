"""
Redis连接测试

测试Redis客户端的连接管理和缓存功能。
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.db.redis import RedisClient, RedisConnectionError


class TestRedisClient:
    """Redis客户端测试"""
    
    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        return RedisClient()
    
    @pytest.mark.asyncio
    async def test_connect_success(self, client):
        """测试成功连接"""
        with patch("app.db.redis.aioredis.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_client
            
            await client.connect()
            
            assert client._client is not None
            mock_client.ping.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_health_check_success(self, client):
        """测试健康检查成功"""
        with patch("app.db.redis.aioredis.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_client
            
            await client.connect()
            result = await client.health_check()
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_health_check_no_client(self, client):
        """测试无客户端时的健康检查"""
        result = await client.health_check()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_set_and_get(self, client):
        """测试设置和获取"""
        with patch("app.db.redis.aioredis.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_client.setex = AsyncMock(return_value=True)
            mock_client.get = AsyncMock(return_value='{"name": "周杰伦"}')
            mock_from_url.return_value = mock_client
            
            await client.connect()
            
            # 设置
            result = await client.set("test-key", '{"name": "周杰伦"}', "person")
            assert result is True
            
            # 获取
            value = await client.get("test-key", "person")
            assert value == '{"name": "周杰伦"}'
    
    @pytest.mark.asyncio
    async def test_json_operations(self, client):
        """测试JSON操作"""
        with patch("app.db.redis.aioredis.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_client.setex = AsyncMock(return_value=True)
            mock_client.get = AsyncMock(return_value='{"id": "jay", "name": "周杰伦"}')
            mock_from_url.return_value = mock_client
            
            await client.connect()
            
            # 设置JSON
            data = {"id": "jay", "name": "周杰伦"}
            await client.set_json("person:jay", data, "person")
            
            # 获取JSON
            result = await client.get_json("person:jay", "person")
            assert result == data
    
    @pytest.mark.asyncio
    async def test_session_operations(self, client):
        """测试会话操作"""
        with patch("app.db.redis.aioredis.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_client.setex = AsyncMock(return_value=True)
            mock_client.get = AsyncMock(return_value='{"messages": []}')
            mock_client.delete = AsyncMock(return_value=1)
            mock_from_url.return_value = mock_client
            
            await client.connect()
            
            # 保存会话
            session_data = {"messages": [{"role": "user", "content": "你好"}]}
            await client.set_session("sess_123", session_data)
            
            # 获取会话
            result = await client.get_session("sess_123")
            assert result is not None
            
            # 删除会话
            deleted = await client.delete_session("sess_123")
            assert deleted == 1
    
    @pytest.mark.asyncio
    async def test_cache_key_generation(self, client):
        """测试缓存键生成"""
        key = client.cache_key("search", "周杰伦", category="singer")
        assert key == "search:周杰伦:category=singer"
    
    @pytest.mark.asyncio
    async def test_key_prefix(self, client):
        """测试键前缀"""
        key = client._make_key("person", "jay-chou")
        assert key == "starmap:person:jay-chou"
        
        key = client._make_key("search", "query:周杰伦")
        assert key == "starmap:search:query:周杰伦"


class TestRedisIntegration:
    """Redis集成测试（需要真实服务）"""
    
    @pytest.fixture
    async def real_client(self):
        """创建真实连接客户端"""
        client = RedisClient()
        try:
            await client.connect()
            yield client
        except RedisConnectionError:
            pytest.skip("Redis服务未启动")
        finally:
            if client._client:
                await client.close()
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_connection(self, real_client):
        """测试真实连接"""
        healthy = await real_client.health_check()
        assert healthy is True
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_set_get(self, real_client):
        """测试真实读写"""
        if not await real_client.health_check():
            pytest.skip("Redis服务未启动")
        
        # 设置
        await real_client.set("test", "value", "default", ttl=60)
        
        # 获取
        result = await real_client.get("test", "default")
        assert result == "value"
        
        # 清理
        await real_client.delete("test", "default")
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_json(self, real_client):
        """测试真实JSON操作"""
        if not await real_client.health_check():
            pytest.skip("Redis服务未启动")
        
        data = {"name": "周杰伦", "category": "singer"}
        
        # 设置
        await real_client.set_json("test:person", data, "person", ttl=60)
        
        # 获取
        result = await real_client.get_json("test:person", "person")
        assert result == data
        
        # 清理
        await real_client.delete("test:person", "person")
