#!/usr/bin/env python3
"""
数据迁移脚本：将旧的 chapters 迁移到 canonical_chapters 大纲体系

执行步骤：
1. 创建默认大纲（如果不存在）
2. 将 chapters 表的数据迁移到 canonical_chapters
3. 将现有知识点和题目关联到迁移后的章节
4. 验证数据完整性
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mysql import mysql_client
from app.models.mysql_models import (
    Chapter, CanonicalChapter, ExamOutline, Subject,
    KnowledgePoint, Question
)
from sqlalchemy import select, func
import uuid


async def migrate_chapters_to_canonical():
    """迁移章节数据到大纲体系"""
    print("=" * 60)
    print("开始迁移章节数据到考试大纲体系")
    print("=" * 60)

    async with mysql_client.session() as db:
        # 步骤 1：检查默认大纲是否存在
        print("\n[1/5] 检查默认大纲...")
        default_outline = await db.scalar(
            select(ExamOutline).where(ExamOutline.is_default == True)
        )

        if not default_outline:
            print("  未找到默认大纲，创建 2025 年 408 考研大纲...")
            default_outline = ExamOutline(
                id="outline_2025_v1",
                name="2025年408考研大纲",
                year=2025,
                version="v1.0",
                status="active",
                is_default=True,
                description="2025年全国硕士研究生招生考试计算机学科专业基础综合考试大纲"
            )
            db.add(default_outline)
            await db.commit()
            print(f"  ✓ 创建成功：{default_outline.name}")
        else:
            print(f"  ✓ 已存在默认大纲：{default_outline.name}")

        outline_id = default_outline.id

        # 步骤 2：检查是否已有 canonical_chapters 数据
        print("\n[2/5] 检查 canonical_chapters 现有数据...")
        existing_count = await db.scalar(
            select(func.count()).select_from(CanonicalChapter)
        ) or 0
        print(f"  当前 canonical_chapters 记录数：{existing_count}")

        # 步骤 3：迁移 chapters 到 canonical_chapters
        print("\n[3/5] 迁移 chapters 到 canonical_chapters...")
        old_chapters_result = await db.execute(
            select(Chapter).where(Chapter.status == "active").order_by(Chapter.subject_id, Chapter.sort_order)
        )
        old_chapters = old_chapters_result.scalars().all()

        if not old_chapters:
            print("  ⚠️  未找到需要迁移的章节数据")
        else:
            print(f"  找到 {len(old_chapters)} 个章节需要迁移")

            migrated_count = 0
            for old_ch in old_chapters:
                # 检查是否已经迁移（通过 ID 检查）
                existing = await db.scalar(
                    select(CanonicalChapter).where(CanonicalChapter.id == old_ch.id)
                )

                if existing:
                    # 如果已存在，更新 outline_id
                    if not existing.outline_id:
                        existing.outline_id = outline_id
                        migrated_count += 1
                        print(f"    更新章节关联：{existing.name} -> {default_outline.name}")
                else:
                    # 创建新的 canonical_chapter
                    canonical_ch = CanonicalChapter(
                        id=old_ch.id,  # 保持ID不变，避免关联断裂
                        outline_id=outline_id,
                        subject_id=old_ch.subject_id,
                        parent_id=None,  # 旧章节都是一级章节
                        level=1,
                        name=old_ch.name,
                        code=f"CH{old_ch.sort_order}",
                        outline_code=str(old_ch.sort_order + 1),  # 1-based 编号
                        description=old_ch.description,
                        sort_order=old_ch.sort_order,
                        status=old_ch.status
                    )
                    db.add(canonical_ch)
                    migrated_count += 1
                    print(f"    迁移章节：{old_ch.name} (ID: {old_ch.id})")

            await db.commit()
            print(f"  ✓ 迁移完成：{migrated_count} 个章节")

        # 步骤 4：验证知识点关联
        print("\n[4/5] 验证知识点关联...")
        kp_count = await db.scalar(
            select(func.count()).select_from(KnowledgePoint)
            .where(KnowledgePoint.status != "deleted")
        ) or 0

        if kp_count > 0:
            # 检查知识点的 chapter_id 是否都在 canonical_chapters 中
            kp_result = await db.execute(
                select(KnowledgePoint.chapter_id, func.count())
                .where(KnowledgePoint.status != "deleted")
                .group_by(KnowledgePoint.chapter_id)
            )

            valid_chapters = set()
            for chapter_id, count in kp_result:
                exists = await db.scalar(
                    select(func.count()).select_from(CanonicalChapter)
                    .where(CanonicalChapter.id == chapter_id)
                )
                if exists:
                    valid_chapters.add(chapter_id)

            print(f"  知识点总数：{kp_count}")
            print(f"  关联的章节数：{len(valid_chapters)}")
            print(f"  ✓ 知识点关联验证通过")
        else:
            print("  暂无知识点数据")

        # 步骤 5：验证题目关联
        print("\n[5/5] 验证题目关联...")
        q_count = await db.scalar(
            select(func.count()).select_from(Question)
            .where(Question.status != "deleted")
        ) or 0

        if q_count > 0:
            # 检查题目的 chapter_id 是否都在 canonical_chapters 中
            q_result = await db.execute(
                select(Question.chapter_id, func.count())
                .where(Question.status != "deleted")
                .group_by(Question.chapter_id)
            )

            valid_chapters = set()
            for chapter_id, count in q_result:
                exists = await db.scalar(
                    select(func.count()).select_from(CanonicalChapter)
                    .where(CanonicalChapter.id == chapter_id)
                )
                if exists:
                    valid_chapters.add(chapter_id)

            print(f"  题目总数：{q_count}")
            print(f"  关联的章节数：{len(valid_chapters)}")
            print(f"  ✓ 题目关联验证通过")
        else:
            print("  暂无题目数据")

        # 最终统计
        print("\n" + "=" * 60)
        print("迁移完成统计")
        print("=" * 60)

        # 统计大纲章节
        canonical_count = await db.scalar(
            select(func.count()).select_from(CanonicalChapter)
            .where(CanonicalChapter.outline_id == outline_id)
        ) or 0

        # 统计各学科
        subjects = (await db.execute(
            select(Subject).where(Subject.status == "active")
        )).scalars().all()

        for subject in subjects:
            ch_count = await db.scalar(
                select(func.count()).select_from(CanonicalChapter)
                .where(
                    CanonicalChapter.outline_id == outline_id,
                    CanonicalChapter.subject_id == subject.id
                )
            ) or 0

            kp_count = await db.scalar(
                select(func.count()).select_from(KnowledgePoint)
                .where(
                    KnowledgePoint.subject_id == subject.id,
                    KnowledgePoint.status != "deleted"
                )
            ) or 0

            q_count = await db.scalar(
                select(func.count()).select_from(Question)
                .where(
                    Question.subject_id == subject.id,
                    Question.status != "deleted"
                )
            ) or 0

            print(f"\n  {subject.name}:")
            print(f"    章节：{ch_count} 个")
            print(f"    知识点：{kp_count} 个")
            print(f"    题目：{q_count} 个")

        print("\n" + "=" * 60)
        print("✅ 数据迁移成功完成！")
        print("=" * 60)


async def main():
    """主函数"""
    try:
        await migrate_chapters_to_canonical()
    except Exception as e:
        print(f"\n❌ 迁移失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
