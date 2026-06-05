"""数据库模块"""

from app.db.mysql import mysql_client, get_mysql_client, MySQLClient


async def get_db():
    """
    获取数据库会话（用于 FastAPI Depends）
    
    使用独立的会话管理器，避免与 mysql_client.session() 冲突。
    """
    if not mysql_client._session_maker:
        await mysql_client.connect()
    
    from sqlalchemy.ext.asyncio import AsyncSession
    session = mysql_client._session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
