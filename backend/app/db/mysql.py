"""
MySQL 数据库连接封装

提供异步连接池管理、ORM模型基础和常用查询操作。
使用 SQLAlchemy 2.0 + asyncmy 驱动。
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, TypeVar, Generic

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 声明式基类
Base = declarative_base()

# 泛型类型
T = TypeVar("T", bound=Base)


class MySQLConnectionError(Exception):
    """MySQL连接异常"""
    pass


class MySQLQueryError(Exception):
    """MySQL查询异常"""
    pass


class MySQLClient:
    """
    MySQL 异步客户端
    
    封装了连接池管理和常用CRUD操作，支持：
    - 异步连接池
    - 事务支持
    - 自动重试
    - 健康检查
    
    使用示例:
        >>> async with mysql_client.session() as session:
        ...     person = await session.get(Person, "person_001")
        ...     print(person.name)
    """
    
    def __init__(self):
        self._engine: Optional[AsyncEngine] = None
        self._session_maker: Optional[async_sessionmaker] = None
        
    async def connect(self) -> None:
        """
        建立MySQL连接池
        
        创建异步引擎和会话工厂。
        如果连接失败会抛出 MySQLConnectionError。
        """
        try:
            # 构建数据库URL
            database_url = (
                f"mysql+asyncmy://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
                f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DATABASE}"
                f"?charset=utf8mb4"
            )
            
            # 创建异步引擎
            self._engine = create_async_engine(
                database_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,  # 自动检测连接是否有效
                pool_recycle=3600,   # 连接回收时间
                echo=settings.ENV == "development",  # 开发环境打印SQL
            )
            
            # 创建会话工厂
            self._session_maker = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
            
            # 验证连接
            async with self._engine.connect() as conn:
                await conn.execute(select(1))
            
            logger.info("MySQL连接成功", host=settings.MYSQL_HOST, database=settings.MYSQL_DATABASE)
            
        except Exception as e:
            logger.error("MySQL连接失败", error=str(e))
            raise MySQLConnectionError(f"无法连接到MySQL: {e}")
    
    async def close(self) -> None:
        """关闭MySQL连接池"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            logger.info("MySQL连接已关闭")
    
    async def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            bool: 连接正常返回True，否则返回False
        """
        if not self._engine:
            return False
        try:
            async with self._engine.connect() as conn:
                await conn.execute(select(1))
            return True
        except Exception:
            return False
    
    @asynccontextmanager
    async def session(self):
        """
        异步会话上下文管理器
        
        自动管理会话生命周期和事务。
        
        Usage:
            async with mysql_client.session() as session:
                result = await session.execute(select(Person).where(Person.id == "xxx"))
                person = result.scalar_one_or_none()
        """
        if not self._session_maker:
            await self.connect()
        
        session = self._session_maker()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("数据库事务回滚", error=str(e))
            raise
        finally:
            await session.close()
    
    @asynccontextmanager
    async def transaction(self):
        """
        显式事务上下文管理器
        
        用于需要手动控制事务的场景。
        
        Usage:
            async with mysql_client.transaction() as session:
                session.add(person)
                # 手动控制commit时机
                await session.commit()
        """
        if not self._session_maker:
            await self.connect()
        
        session = self._session_maker()
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error("事务回滚", error=str(e))
            raise
        finally:
            await session.close()
    
    # ========== 常用CRUD封装 ==========
    
    async def get_by_id(self, model_class: type[T], id: str) -> Optional[T]:
        """
        根据ID获取记录
        
        Args:
            model_class: 模型类
            id: 主键ID
            
        Returns:
            记录对象，不存在返回None
        """
        async with self.session() as session:
            result = await session.get(model_class, id)
            return result
    
    async def get_by_ids(self, model_class: type[T], ids: List[str]) -> List[T]:
        """
        根据ID列表批量获取记录
        
        Args:
            model_class: 模型类
            ids: 主键ID列表
            
        Returns:
            记录列表
        """
        async with self.session() as session:
            result = await session.execute(
                select(model_class).where(model_class.id.in_(ids))
            )
            return result.scalars().all()
    
    async def create(self, model_instance: T) -> T:
        """
        创建记录
        
        Args:
            model_instance: 模型实例
            
        Returns:
            创建后的模型实例（包含生成的ID）
        """
        async with self.session() as session:
            session.add(model_instance)
            await session.flush()  # 刷新以获取生成的ID
            await session.refresh(model_instance)  # 重新加载数据
            return model_instance
    
    async def create_many(self, model_instances: List[T]) -> List[T]:
        """
        批量创建记录
        
        Args:
            model_instances: 模型实例列表
            
        Returns:
            创建后的模型实例列表
        """
        async with self.session() as session:
            session.add_all(model_instances)
            await session.flush()
            for instance in model_instances:
                await session.refresh(instance)
            return model_instances
    
    async def update(self, model_class: type[T], id: str, update_data: Dict[str, Any]) -> Optional[T]:
        """
        更新记录
        
        Args:
            model_class: 模型类
            id: 主键ID
            update_data: 更新数据字典
            
        Returns:
            更新后的模型实例，不存在返回None
        """
        async with self.session() as session:
            result = await session.execute(
                update(model_class)
                .where(model_class.id == id)
                .values(**update_data)
            )
            if result.rowcount == 0:
                return None
            
            # 重新查询获取更新后的数据
            updated = await session.get(model_class, id)
            return updated
    
    async def delete(self, model_class: type[T], id: str) -> bool:
        """
        删除记录
        
        Args:
            model_class: 模型类
            id: 主键ID
            
        Returns:
            是否删除成功
        """
        async with self.session() as session:
            result = await session.execute(
                delete(model_class).where(model_class.id == id)
            )
            return result.rowcount > 0
    
    async def count(self, model_class: type[T], filters: Optional[Dict[str, Any]] = None) -> int:
        """
        统计记录数
        
        Args:
            model_class: 模型类
            filters: 过滤条件
            
        Returns:
            记录数
        """
        async with self.session() as session:
            query = select(func.count()).select_from(model_class)
            
            if filters:
                for key, value in filters.items():
                    if hasattr(model_class, key) and value is not None:
                        query = query.where(getattr(model_class, key) == value)
            
            result = await session.execute(query)
            return result.scalar()
    
    async def execute_raw(self, sql: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行原始SQL
        
        Args:
            sql: SQL语句
            parameters: 参数
            
        Returns:
            查询结果列表
        """
        async with self.session() as session:
            result = await session.execute(sql, parameters or {})
            rows = result.mappings().all()
            return [dict(row) for row in rows]


# 全局客户端实例
mysql_client = MySQLClient()


async def get_mysql_client() -> MySQLClient:
    """
    获取MySQL客户端（依赖注入用）
    
    Returns:
        MySQLClient: 已连接的客户端实例
    """
    if not mysql_client._engine:
        await mysql_client.connect()
    return mysql_client


async def init_mysql_tables():
    """
    初始化MySQL表结构
    
    根据SQLAlchemy模型自动创建表。
    """
    client = await get_mysql_client()
    async with client._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("MySQL表结构初始化完成")


async def drop_mysql_tables():
    """
    删除所有MySQL表
    
    危险操作！仅用于测试环境。
    """
    client = await get_mysql_client()
    async with client._engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.warning("MySQL表已删除")
