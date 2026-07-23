"""
Redis 缓存连接封装

提供连接池管理、常用缓存操作和序列化支持。
支持键前缀管理和TTL自动设置。
"""

import json
import pickle
from typing import Any, Dict, Optional, Union

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisConnectionError(Exception):
    """Redis连接异常"""
    pass


class RedisClient:
    """
    Redis 异步客户端
    
    封装了连接池和常用缓存操作，支持：
    - 异步连接管理
    - JSON/Pickle序列化
    - 键前缀管理
    - TTL自动设置
    - 连接健康检查
    """
    
    # 键前缀配置
    KEY_PREFIXES = {
        "session": "crawler:session",
        "llm": "crawler:llm",
        "task": "crawler:task",
    }

    # 默认TTL配置（秒）
    DEFAULT_TTL = {
        "session": 3600,     # 1小时
        "llm": 1800,         # 30分钟
        "task": 7200,        # 2小时
    }
    
    def __init__(self):
        self._client: Optional[Redis] = None
        self._url = settings.REDIS_URL
        
    async def connect(self) -> None:
        """
        建立Redis连接
        
        创建异步Redis客户端并验证连接可用性。
        """
        try:
            self._client = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30
            )
            # 验证连接
            await self._client.ping()
            logger.info("Redis连接成功", url=self._url)
        except Exception as e:
            logger.error("Redis连接失败", error=str(e), url=self._url)
            raise RedisConnectionError(f"无法连接到Redis: {e}")
    
    async def close(self) -> None:
        """关闭Redis连接"""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis连接已关闭")
    
    async def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            bool: 连接正常返回True
        """
        if not self._client:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    async def info(self) -> Dict[str, Any]:
        """返回 Redis INFO，供监控代码使用而不暴露底层客户端。"""
        if not self._client:
            await self.connect()
        return await self._client.info()
    
    def _make_key(self, key_type: str, key: str) -> str:
        """
        构建带前缀的键
        
        Args:
            key_type: 键类型（session/llm/task）
            key: 原始键
            
        Returns:
            str: 带前缀的键
        """
        prefix = self.KEY_PREFIXES.get(key_type, "crawler:default")
        return f"{prefix}:{key}"
    
    # ========== 基础操作 ==========
    
    async def get(self, key: str, key_type: str = "default") -> Optional[str]:
        """
        获取字符串值
        
        Args:
            key: 键
            key_type: 键类型
            
        Returns:
            str: 值，不存在返回None
        """
        full_key = self._make_key(key_type, key)
        return await self._client.get(full_key)
    
    async def set(
        self,
        key: str,
        value: str,
        key_type: str = "default",
        ttl: Optional[int] = None
    ) -> bool:
        """
        设置字符串值
        
        Args:
            key: 键
            value: 值
            key_type: 键类型
            ttl: 过期时间（秒），None使用默认配置
            
        Returns:
            bool: 设置成功返回True
        """
        full_key = self._make_key(key_type, key)
        if ttl is None:
            ttl = self.DEFAULT_TTL.get(key_type)
        
        if ttl:
            return bool(await self._client.set(full_key, value, ex=ttl))
        return bool(await self._client.set(full_key, value))
    
    async def delete(self, key: str, key_type: str = "default") -> int:
        """
        删除键
        
        Args:
            key: 键
            key_type: 键类型
            
        Returns:
            int: 删除的键数量
        """
        full_key = self._make_key(key_type, key)
        return await self._client.delete(full_key)
    
    async def exists(self, key: str, key_type: str = "default") -> bool:
        """
        检查键是否存在
        
        Args:
            key: 键
            key_type: 键类型
            
        Returns:
            bool: 存在返回True
        """
        full_key = self._make_key(key_type, key)
        return await self._client.exists(full_key) > 0
    
    # ========== JSON序列化操作 ==========
    
    async def get_json(
        self,
        key: str,
        key_type: str = "default"
    ) -> Optional[Any]:
        """
        获取JSON对象
        
        Args:
            key: 键
            key_type: 键类型
            
        Returns:
            Any: 反序列化后的对象
        """
        data = await self.get(key, key_type)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError as e:
                logger.warning("JSON反序列化失败", key=key, error=str(e))
        return None
    
    async def set_json(
        self,
        key: str,
        value: Any,
        key_type: str = "default",
        ttl: Optional[int] = None
    ) -> bool:
        """
        设置JSON对象
        
        Args:
            key: 键
            value: 可JSON序列化的对象
            key_type: 键类型
            ttl: 过期时间（秒）
            
        Returns:
            bool: 设置成功返回True
        """
        try:
            json_str = json.dumps(value, ensure_ascii=False, default=str)
            return await self.set(key, json_str, key_type, ttl)
        except (TypeError, ValueError) as e:
            logger.error("JSON序列化失败", key=key, error=str(e))
            return False
    
    # ========== 对象序列化操作（Pickle） ==========
    
    async def get_object(
        self,
        key: str,
        key_type: str = "default"
    ) -> Optional[Any]:
        """
        获取Pickle对象
        
        用于缓存复杂Python对象（如LLM响应）。
        
        Args:
            key: 键
            key_type: 键类型
            
        Returns:
            Any: 反序列化后的对象
        """
        # 使用bytes模式读取
        full_key = self._make_key(key_type, key)
        data = await self._client.get(full_key)
        if data and isinstance(data, bytes):
            try:
                return pickle.loads(data)
            except pickle.PickleError as e:
                logger.warning("Pickle反序列化失败", key=key, error=str(e))
        return None
    
    async def set_object(
        self,
        key: str,
        value: Any,
        key_type: str = "default",
        ttl: Optional[int] = None
    ) -> bool:
        """
        设置Pickle对象
        
        Args:
            key: 键
            value: Python对象
            key_type: 键类型
            ttl: 过期时间（秒）
            
        Returns:
            bool: 设置成功返回True
        """
        try:
            # 使用bytes模式写入
            data = pickle.dumps(value)
            full_key = self._make_key(key_type, key)
            if ttl is None:
                ttl = self.DEFAULT_TTL.get(key_type)
            
            if ttl:
                await self._client.set(full_key, data, ex=ttl)
            else:
                await self._client.set(full_key, data)
            return True
        except (pickle.PickleError, TypeError) as e:
            logger.error("Pickle序列化失败", key=key, error=str(e))
            return False
    
    # ========== 会话管理 ==========
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话数据
        
        Args:
            session_id: 会话ID
            
        Returns:
            Dict: 会话数据
        """
        return await self.get_json(session_id, "session")
    
    async def set_session(
        self,
        session_id: str,
        data: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """
        保存会话数据
        
        Args:
            session_id: 会话ID
            data: 会话数据
            ttl: 过期时间（秒），默认1小时
            
        Returns:
            bool: 保存成功返回True
        """
        return await self.set_json(session_id, data, "session", ttl)
    
    async def delete_session(self, session_id: str) -> int:
        """
        删除会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            int: 删除的键数量
        """
        return await self.delete(session_id, "session")
    
    # ========== 缓存装饰器支持 ==========
    
    def cache_key(self, prefix: str, *args, **kwargs) -> str:
        """
        生成缓存键
        
        Args:
            prefix: 键前缀
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            str: 缓存键
        """
        key_parts = [prefix]
        for arg in args:
            key_parts.append(str(arg))
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}={v}")
        return ":".join(key_parts)
    
    # ========== 批量操作 ==========
    
    async def delete_pattern(self, pattern: str) -> int:
        """
        按模式删除键
        
        Args:
            pattern: 匹配模式（如 starmap:search:*）
            
        Returns:
            int: 删除的键数量
        """
        keys = []
        async for key in self._client.scan_iter(match=pattern):
            keys.append(key)
        
        if keys:
            return await self._client.delete(*keys)
        return 0
    
    async def clear_cache(self, key_type: Optional[str] = None) -> int:
        """
        清除缓存
        
        Args:
            key_type: 键类型，None清除所有starmap缓存
            
        Returns:
            int: 删除的键数量
        """
        if key_type:
            pattern = f"{self.KEY_PREFIXES.get(key_type, 'crawler')}:*"
        else:
            pattern = "crawler:*"
        
        return await self.delete_pattern(pattern)


# 全局客户端实例
redis_client = RedisClient()


async def get_redis_client() -> RedisClient:
    """
    获取Redis客户端（依赖注入用）
    
    Returns:
        RedisClient: 已连接的客户端实例
    """
    if not redis_client._client:
        await redis_client.connect()
    return redis_client
