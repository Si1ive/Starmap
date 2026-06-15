#!/usr/bin/env python3
"""
直接执行数据库迁移 SQL
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mysql import mysql_client
from sqlalchemy import text


async def run_migration():
    """执行迁移 SQL"""
    print("=" * 60)
    print("执行数据库迁移：添加考试大纲系统")
    print("=" * 60)

    async with mysql_client.session() as db:
        try:
            # 1. 创建 exam_outlines 表
            print("\n[1/4] 创建 exam_outlines 表...")
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS exam_outlines (
                    id VARCHAR(32) NOT NULL COMMENT '大纲ID',
                    name VARCHAR(100) NOT NULL COMMENT '大纲名称，如：2025年408考研大纲',
                    year INT NOT NULL COMMENT '考试年份',
                    version VARCHAR(20) NOT NULL DEFAULT 'v1.0' COMMENT '版本号',
                    description TEXT COMMENT '大纲说明',
                    release_date DATE COMMENT '发布日期',
                    effective_date DATE COMMENT '生效日期',
                    status ENUM('draft', 'active', 'archived') NOT NULL DEFAULT 'draft' COMMENT '状态',
                    is_default BOOLEAN NOT NULL DEFAULT 0 COMMENT '是否默认大纲',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_outline_year_version (year, version),
                    INDEX idx_outline_year (year),
                    INDEX idx_outline_status (status),
                    INDEX idx_outline_default (is_default)
                ) COMMENT='考试大纲元信息表'
            """))
            print("  ✓ exam_outlines 表创建成功")

            # 2. 扩展 canonical_chapters 表
            print("\n[2/4] 扩展 canonical_chapters 表...")

            # 检查列是否已存在
            result = await db.execute(text("""
                SELECT COUNT(*) as cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'canonical_chapters'
                AND COLUMN_NAME = 'outline_id'
            """))
            outline_id_exists = result.scalar() > 0

            if not outline_id_exists:
                await db.execute(text("""
                    ALTER TABLE canonical_chapters
                    ADD COLUMN outline_id VARCHAR(32) COMMENT '所属大纲ID' AFTER id,
                    ADD COLUMN outline_code VARCHAR(50) COMMENT '大纲中的编号，如：1.1.1' AFTER code
                """))
                print("  ✓ 添加 outline_id 和 outline_code 列")
            else:
                print("  ✓ outline_id 列已存在，跳过")

            # 添加外键（如果不存在）
            result = await db.execute(text("""
                SELECT COUNT(*) as cnt
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'canonical_chapters'
                AND CONSTRAINT_NAME = 'fk_canonical_chapters_outline'
            """))
            fk_exists = result.scalar() > 0

            if not fk_exists:
                await db.execute(text("""
                    ALTER TABLE canonical_chapters
                    ADD CONSTRAINT fk_canonical_chapters_outline
                    FOREIGN KEY (outline_id) REFERENCES exam_outlines(id) ON DELETE CASCADE
                """))
                print("  ✓ 添加外键约束")
            else:
                print("  ✓ 外键约束已存在，跳过")

            # 添加索引（如果不存在）
            result = await db.execute(text("""
                SELECT COUNT(*) as cnt
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'canonical_chapters'
                AND INDEX_NAME = 'idx_canonical_chapters_outline'
            """))
            idx_exists = result.scalar() > 0

            if not idx_exists:
                await db.execute(text("""
                    CREATE INDEX idx_canonical_chapters_outline
                    ON canonical_chapters(outline_id)
                """))
                print("  ✓ 添加索引")
            else:
                print("  ✓ 索引已存在，跳过")

            # 3. 初始化默认大纲
            print("\n[3/4] 初始化默认大纲...")
            result = await db.execute(text("""
                SELECT COUNT(*) as cnt FROM exam_outlines WHERE id = 'outline_2025_v1'
            """))
            outline_exists = result.scalar() > 0

            if not outline_exists:
                await db.execute(text("""
                    INSERT INTO exam_outlines (id, name, year, version, status, is_default, created_at, updated_at)
                    VALUES ('outline_2025_v1', '2025年408考研大纲', 2025, 'v1.0', 'active', 1, NOW(), NOW())
                """))
                print("  ✓ 创建默认大纲：2025年408考研大纲")
            else:
                print("  ✓ 默认大纲已存在，跳过")

            # 4. 提交事务
            print("\n[4/4] 提交事务...")
            await db.commit()
            print("  ✓ 事务提交成功")

            print("\n" + "=" * 60)
            print("✅ 数据库迁移成功完成！")
            print("=" * 60)

        except Exception as e:
            await db.rollback()
            print(f"\n❌ 迁移失败：{e}")
            raise


async def main():
    try:
        await run_migration()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
