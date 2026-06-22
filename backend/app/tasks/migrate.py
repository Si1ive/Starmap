"""
数据库迁移管理

提供数据库迁移脚本的自动执行功能。
在应用启动时检查并执行未执行的迁移脚本。
"""

import os
import re
from pathlib import Path
from typing import List, Optional

from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client

logger = get_logger(__name__)

# 迁移脚本目录
MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "scripts"

# 迁移记录表
MIGRATION_TABLE = "schema_migrations"


class MigrationManager:
    """数据库迁移管理器"""

    def __init__(self):
        self.migrations_dir = MIGRATIONS_DIR

    async def init_migration_table(self) -> None:
        """
        初始化迁移记录表
        
        如果表不存在则创建。
        """
        async with mysql_client.session() as session:
            # 检查表是否存在
            result = await session.execute(
                text(f"""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = DATABASE() 
                    AND table_name = '{MIGRATION_TABLE}'
                """)
            )
            exists = result.scalar() > 0
            
            if not exists:
                # 创建迁移记录表
                await session.execute(
                    text(f"""
                        CREATE TABLE {MIGRATION_TABLE} (
                            id INT PRIMARY KEY AUTO_INCREMENT,
                            version VARCHAR(50) NOT NULL UNIQUE,
                            description VARCHAR(255),
                            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            execution_time_ms INT,
                            success BOOLEAN DEFAULT TRUE
                        )
                    """)
                )
                await session.commit()
                logger.info(f"Created migration table: {MIGRATION_TABLE}")

    async def get_executed_migrations(self) -> List[str]:
        """
        获取已执行的迁移版本列表
        
        Returns:
            已执行的迁移版本号列表
        """
        async with mysql_client.session() as session:
            try:
                result = await session.execute(
                    text(f"SELECT version FROM {MIGRATION_TABLE} WHERE success = TRUE ORDER BY version")
                )
                return [row[0] for row in result.fetchall()]
            except Exception as e:
                logger.error(f"Failed to get executed migrations: {e}")
                return []

    async def execute_migration(self, version: str, sql_content: str, description: str = "") -> bool:
        """
        执行单个迁移脚本
        
        Args:
            version: 迁移版本号
            sql_content: SQL 内容
            description: 迁移描述
            
        Returns:
            是否成功
        """
        import time
        
        start_time = time.time()
        
        async with mysql_client.session() as session:
            try:
                # 执行迁移脚本
                await session.execute(text(sql_content))
                await session.commit()

                execution_time = int((time.time() - start_time) * 1000)

                # 记录迁移（upsert：避免之前失败记录占用 version 唯一键导致重复键错误）
                await session.execute(
                    text(f"""
                        INSERT INTO {MIGRATION_TABLE} (version, description, execution_time_ms, success)
                        VALUES (:version, :description, :execution_time, TRUE)
                        ON DUPLICATE KEY UPDATE
                            description = VALUES(description),
                            execution_time_ms = VALUES(execution_time_ms),
                            success = TRUE,
                            executed_at = CURRENT_TIMESTAMP
                    """),
                    {
                        "version": version,
                        "description": description,
                        "execution_time": execution_time,
                    }
                )
                await session.commit()

                logger.info(f"Executed migration {version} in {execution_time}ms")
                return True

            except Exception as e:
                await session.rollback()

                # 记录失败（upsert：同上）
                try:
                    await session.execute(
                        text(f"""
                            INSERT INTO {MIGRATION_TABLE} (version, description, success)
                            VALUES (:version, :description, FALSE)
                            ON DUPLICATE KEY UPDATE
                                description = VALUES(description),
                                success = FALSE,
                                executed_at = CURRENT_TIMESTAMP
                        """),
                        {
                            "version": version,
                            "description": f"{description} - Failed: {str(e)[:200]}",
                        }
                    )
                    await session.commit()
                except:
                    pass

                logger.error(f"Failed to execute migration {version}: {e}")
                return False

    def _parse_migration_file(self, filename: str) -> Optional[tuple]:
        """
        解析迁移文件名
        
        文件名格式: YYYYMMDDHHMMSS_description.sql
        
        Args:
            filename: 文件名
            
        Returns:
            (版本号, 描述) 或 None
        """
        match = re.match(r"^(\d{14})_(.+)\.sql$", filename)
        if match:
            return match.group(1), match.group(2).replace("_", " ")
        return None

    def _get_migration_files(self) -> List[tuple]:
        """
        获取所有迁移文件
        
        Returns:
            [(版本号, 描述, 文件路径), ...]
        """
        migrations = []
        
        if not self.migrations_dir.exists():
            logger.warning(f"Migrations directory not found: {self.migrations_dir}")
            return migrations
        
        for file_path in sorted(self.migrations_dir.glob("*.sql")):
            parsed = self._parse_migration_file(file_path.name)
            if parsed:
                version, description = parsed
                migrations.append((version, description, file_path))
        
        return migrations

    async def migrate(self) -> None:
        """
        执行所有未执行的迁移
        
        按版本号顺序执行所有未执行的迁移脚本。
        """
        logger.info("Starting database migration...")
        
        # 初始化迁移表
        await self.init_migration_table()
        
        # 获取已执行的迁移
        executed = await self.get_executed_migrations()
        logger.info(f"Found {len(executed)} executed migrations")
        
        # 获取所有迁移文件
        migrations = self._get_migration_files()
        logger.info(f"Found {len(migrations)} migration files")
        
        # 执行未执行的迁移
        executed_count = 0
        failed_count = 0
        
        for version, description, file_path in migrations:
            if version in executed:
                logger.debug(f"Migration already executed: {version}")
                continue
            
            logger.info(f"Executing migration: {version} - {description}")
            
            try:
                # 读取 SQL 文件
                sql_content = file_path.read_text(encoding="utf-8")
                
                # 执行迁移
                success = await self.execute_migration(version, sql_content, description)
                
                if success:
                    executed_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to read migration file {file_path}: {e}")
                failed_count += 1
        
        logger.info(
            f"Migration completed: {executed_count} executed, {failed_count} failed, "
            f"{len(executed)} already up-to-date"
        )

    async def rollback(self, version: str) -> bool:
        """
        回滚到指定版本
        
        Args:
            version: 目标版本号
            
        Returns:
            是否成功
        """
        logger.warning(f"Rollback to version {version} is not implemented yet")
        return False

    async def get_status(self) -> dict:
        """
        获取迁移状态
        
        Returns:
            迁移状态信息
        """
        executed = await self.get_executed_migrations()
        migrations = self._get_migration_files()
        
        pending = []
        for version, description, _ in migrations:
            if version not in executed:
                pending.append({"version": version, "description": description})
        
        return {
            "executed_count": len(executed),
            "pending_count": len(pending),
            "pending_migrations": pending,
            "last_executed": executed[-1] if executed else None,
        }


# 全局迁移管理器实例
_migration_manager: Optional[MigrationManager] = None


def get_migration_manager() -> MigrationManager:
    """获取全局迁移管理器实例（单例）"""
    global _migration_manager
    if _migration_manager is None:
        _migration_manager = MigrationManager()
    return _migration_manager


async def run_migrations() -> None:
    """
    运行数据库迁移
    
    便捷函数，用于在应用启动时调用。
    """
    manager = get_migration_manager()
    await manager.migrate()


async def get_migration_status() -> dict:
    """
    获取迁移状态
    
    Returns:
        迁移状态信息
    """
    manager = get_migration_manager()
    return await manager.get_status()
