#!/usr/bin/env python3
"""
修复卡住的解析任务

问题诊断：
1. 文件状态卡在 parsing
2. ParseRun 状态卡在 running，但实际已经超时或失败
3. 可能原因：解析服务超时、崩溃、或前端关闭导致状态未更新

解决方案：
1. 标记超时的 ParseRun 为 failed
2. 重置 CorpusFile 状态为 pending，允许重新解析
3. 提供选项清理或重试
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mysql import mysql_client
from app.models.mysql_models import CorpusFile, ParseRun
from sqlalchemy import select, update


async def fix_stuck_parsing():
    """修复卡住的解析任务"""
    print("=" * 80)
    print("修复卡住的文件解析任务")
    print("=" * 80)

    async with mysql_client.session() as db:
        # 步骤 1：查找卡住的文件
        print("\n[1/3] 查找卡住的文件...")
        stuck_files = (await db.execute(
            select(CorpusFile)
            .where(CorpusFile.status == 'parsing')
            .order_by(CorpusFile.updated_at.desc())
        )).scalars().all()

        if not stuck_files:
            print("  ✓ 没有卡住的文件")
            return

        print(f"  找到 {len(stuck_files)} 个卡住的文件")
        for f in stuck_files:
            print(f"    - {f.file_name} (更新于: {f.updated_at})")

        # 步骤 2：处理卡住的 ParseRun
        print("\n[2/3] 处理卡住的解析任务...")

        # 定义超时时间：超过 30 分钟的 running 任务视为超时
        timeout_threshold = datetime.utcnow() - timedelta(minutes=30)

        for corpus_file in stuck_files:
            print(f"\n  处理文件：{corpus_file.file_name}")

            # 查找该文件的所有 running 状态的解析任务
            stuck_runs = (await db.execute(
                select(ParseRun)
                .where(
                    ParseRun.corpus_file_id == corpus_file.id,
                    ParseRun.status == 'running',
                    ParseRun.started_at < timeout_threshold
                )
            )).scalars().all()

            if stuck_runs:
                print(f"    发现 {len(stuck_runs)} 个超时的解析任务")

                for run in stuck_runs:
                    # 计算运行时长
                    duration = datetime.utcnow() - run.started_at
                    minutes = duration.total_seconds() / 60

                    # 标记为失败
                    run.status = 'failed'
                    run.completed_at = datetime.utcnow()
                    run.error_detail = f"解析超时（运行了 {minutes:.1f} 分钟）。可能原因：解析服务崩溃、超时、或前端关闭导致状态未更新。"

                    print(f"      ✓ 标记任务为失败 (运行了 {minutes:.1f} 分钟)")

            # 重置文件状态
            corpus_file.status = 'pending'
            corpus_file.error_detail = "之前的解析任务超时，已重置状态，可以重新解析"

            print(f"    ✓ 重置文件状态为 pending")

        await db.commit()
        print("\n  ✓ 所有卡住的任务已处理")

        # 步骤 3：显示统计
        print("\n[3/3] 统计信息...")

        for corpus_file in stuck_files:
            # 统计该文件的解析历史
            all_runs = (await db.execute(
                select(ParseRun)
                .where(ParseRun.corpus_file_id == corpus_file.id)
                .order_by(ParseRun.created_at.desc())
            )).scalars().all()

            success_count = sum(1 for r in all_runs if r.status == 'success')
            failed_count = sum(1 for r in all_runs if r.status == 'failed')
            running_count = sum(1 for r in all_runs if r.status == 'running')

            print(f"\n  {corpus_file.file_name}:")
            print(f"    解析历史：成功 {success_count} 次，失败 {failed_count} 次，进行中 {running_count} 次")
            print(f"    文件大小：{corpus_file.file_size / 1024 / 1024:.2f} MB" if corpus_file.file_size else "    文件大小：未知")
            print(f"    当前状态：{corpus_file.status}")

            # 如果之前有成功的解析
            if success_count > 0:
                print(f"    💡 建议：该文件曾经成功解析过，可能不需要重新解析")

        print("\n" + "=" * 80)
        print("✅ 修复完成！")
        print("=" * 80)
        print("\n📝 后续操作：")
        print("  1. 卡住的文件已重置为 pending 状态")
        print("  2. 可以在前端重新触发解析")
        print("  3. 如果仍然超时，可能需要：")
        print("     - 检查解析服务是否正常运行")
        print("     - 增加超时时间（当前 600 秒）")
        print("     - 检查文件是否过大或格式复杂")


async def main():
    """主函数"""
    try:
        await fix_stuck_parsing()
    except Exception as e:
        print(f"\n❌ 修复失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
