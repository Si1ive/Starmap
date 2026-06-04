"""数据库模块"""

from app.db.mysql import mysql_client, get_mysql_client, MySQLClient


async def get_db():
    """获取数据库会话（用于 FastAPI Depends）"""
    async with mysql_client.session() as session:
        yield session
