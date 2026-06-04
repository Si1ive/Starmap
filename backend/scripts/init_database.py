"""
数据库初始化脚本

初始化所有数据库：
1. MySQL - 创建表结构
2. Neo4j - 创建约束和索引
3. ChromaDB - 创建集合

使用方法:
    python scripts/init_database.py --all
    python scripts/init_database.py --mysql
    python scripts/init_database.py --neo4j
    python scripts/init_database.py --chroma
"""

import os
import sys
import asyncio
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.mysql import mysql_client, init_mysql_tables
from app.db.neo4j import neo4j_client
from app.db.chroma import chroma_client
from app.core.logging import get_logger

logger = get_logger(__name__)


async def init_mysql():
    """初始化 MySQL 数据库"""
    logger.info("开始初始化 MySQL...")
    try:
        await init_mysql_tables()
        logger.info("MySQL 初始化完成 ✓")
        return True
    except Exception as e:
        logger.error(f"MySQL 初始化失败: {e}")
        return False


async def init_neo4j():
    """初始化 Neo4j 数据库"""
    logger.info("开始初始化 Neo4j...")
    try:
        if not neo4j_client._driver:
            await neo4j_client.connect()
        
        # 创建约束
        constraints = [
            "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE",
        ]
        
        for constraint in constraints:
            try:
                await neo4j_client.execute_write(constraint)
                logger.info(f"创建约束: {constraint}")
            except Exception as e:
                logger.warning(f"约束可能已存在: {e}")
        
        # 创建索引
        indexes = [
            "CREATE INDEX person_name IF NOT EXISTS FOR (p:Person) ON (p.name)",
            "CREATE INDEX work_title IF NOT EXISTS FOR (w:Work) ON (w.title)",
            "CREATE INDEX person_category IF NOT EXISTS FOR (p:Person) ON (p.category)",
        ]
        
        for index in indexes:
            try:
                await neo4j_client.execute_write(index)
                logger.info(f"创建索引: {index}")
            except Exception as e:
                logger.warning(f"索引可能已存在: {e}")
        
        logger.info("Neo4j 初始化完成 ✓")
        return True
        
    except Exception as e:
        logger.error(f"Neo4j 初始化失败: {e}")
        return False


async def init_chroma():
    """初始化 ChromaDB 集合"""
    logger.info("开始初始化 ChromaDB...")
    try:
        if not chroma_client._client:
            await chroma_client.connect()
        
        # 创建集合
        collections = ["persons", "works", "knowledge"]
        
        for collection_name in collections:
            try:
                await chroma_client.get_or_create_collection(collection_name)
                logger.info(f"创建集合: {collection_name}")
            except Exception as e:
                logger.warning(f"集合可能已存在: {e}")
        
        logger.info("ChromaDB 初始化完成 ✓")
        return True
        
    except Exception as e:
        logger.error(f"ChromaDB 初始化失败: {e}")
        return False


async def check_connections():
    """检查所有数据库连接"""
    results = {}
    
    # 检查 MySQL
    try:
        if not mysql_client._engine:
            await mysql_client.connect()
        results["MySQL"] = await mysql_client.health_check()
    except Exception as e:
        results["MySQL"] = False
        logger.error(f"MySQL 连接检查失败: {e}")
    
    # 检查 Neo4j
    try:
        if not neo4j_client._driver:
            await neo4j_client.connect()
        results["Neo4j"] = True  # 如果连接成功则设为True
    except Exception as e:
        results["Neo4j"] = False
        logger.error(f"Neo4j 连接检查失败: {e}")
    
    # 检查 ChromaDB
    try:
        if not chroma_client._client:
            await chroma_client.connect()
        results["ChromaDB"] = True
    except Exception as e:
        results["ChromaDB"] = False
        logger.error(f"ChromaDB 连接检查失败: {e}")
    
    return results


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Initialize StarMap databases")
    parser.add_argument("--all", action="store_true", help="初始化所有数据库")
    parser.add_argument("--mysql", action="store_true", help="仅初始化 MySQL")
    parser.add_argument("--neo4j", action="store_true", help="仅初始化 Neo4j")
    parser.add_argument("--chroma", action="store_true", help="仅初始化 ChromaDB")
    parser.add_argument("--check", action="store_true", help="仅检查连接")
    
    args = parser.parse_args()
    
    # 如果没有参数，默认检查连接
    if not any([args.all, args.mysql, args.neo4j, args.chroma, args.check]):
        args.check = True
    
    print("=" * 50)
    print("StarMap 数据库初始化工具")
    print("=" * 50)
    
    if args.check:
        print("\n检查数据库连接...")
        results = await check_connections()
        for db, status in results.items():
            symbol = "✓" if status else "✗"
            print(f"  {symbol} {db}: {'已连接' if status else '未连接'}")
        return
    
    results = {}
    
    if args.all or args.mysql:
        results["MySQL"] = await init_mysql()
    
    if args.all or args.neo4j:
        results["Neo4j"] = await init_neo4j()
    
    if args.all or args.chroma:
        results["ChromaDB"] = await init_chroma()
    
    print("\n" + "=" * 50)
    print("初始化结果")
    print("=" * 50)
    for db, status in results.items():
        symbol = "✓" if status else "✗"
        print(f"  {symbol} {db}: {'成功' if status else '失败'}")
    
    # 关闭连接
    if mysql_client._engine:
        await mysql_client.close()
    if neo4j_client._driver:
        await neo4j_client.close()


if __name__ == "__main__":
    asyncio.run(main())
