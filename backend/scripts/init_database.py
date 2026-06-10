"""
数据库初始化脚本

初始化 MySQL 数据库表结构。

使用方法:
    python scripts/init_database.py --all
    python scripts/init_database.py --mysql
"""

import os
import sys
import asyncio
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.mysql import mysql_client, init_mysql_tables
from app.core.logging import get_logger

logger = get_logger(__name__)


async def init_mysql():
    """初始化 MySQL 数据库"""
    logger.info("开始初始化 MySQL...")
    try:
        await init_mysql_tables()
        logger.info("MySQL 初始化完成")
        return True
    except Exception as e:
        logger.error(f"MySQL 初始化失败: {e}")
        return False


async def check_connections():
    """检查数据库连接"""
    results = {}

    # 检查 MySQL
    try:
        if not mysql_client._engine:
            await mysql_client.connect()
        results["MySQL"] = await mysql_client.health_check()
    except Exception as e:
        results["MySQL"] = False
        logger.error(f"MySQL 连接检查失败: {e}")

    return results


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Initialize StarMap databases")
    parser.add_argument("--all", action="store_true", help="初始化所有数据库")
    parser.add_argument("--mysql", action="store_true", help="仅初始化 MySQL")
    parser.add_argument("--check", action="store_true", help="仅检查连接")

    args = parser.parse_args()

    # 如果没有参数，默认检查连接
    if not any([args.all, args.mysql, args.check]):
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

    print("\n" + "=" * 50)
    print("初始化结果")
    print("=" * 50)
    for db, status in results.items():
        symbol = "✓" if status else "✗"
        print(f"  {symbol} {db}: {'成功' if status else '失败'}")

    # 关闭连接
    if mysql_client._engine:
        await mysql_client.close()


if __name__ == "__main__":
    asyncio.run(main())
