"""数据库模块"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client, get_mysql_client, MySQLClient

logger = get_logger(__name__)


async def get_db():
    """
    获取数据库会话（用于 FastAPI Depends）
    
    使用独立的会话管理器，避免与 mysql_client.session() 冲突。
    """
    if not mysql_client._session_maker:
        await mysql_client.connect()
    
    session = mysql_client._session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_optional_db():
    """
    获取可选数据库会话。

    当 MySQL 不可用时返回 None，供支持降级模式的只读接口使用。
    """
    if not mysql_client._session_maker:
        try:
            await mysql_client.connect()
        except Exception as exc:
            logger.warning("MySQL不可用，当前请求降级为无数据库模式", error=str(exc))
            yield None
            return

    session: Optional[AsyncSession] = mysql_client._session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
