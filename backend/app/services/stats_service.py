"""
爬虫统计服务层

以文件为单位，统计已下载文件的爬取情况。
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any

from sqlalchemy import select, func, and_, case, cast, Date, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import DownloadedFile

logger = get_logger(__name__)


class CrawlerStatsService:
    """爬虫统计服务（以文件为单位）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self) -> Dict[str, Any]:
        """获取总体概览"""
        today = datetime.now().date()

        # 总文件数
        total_files = await self.db.scalar(
            select(func.count()).select_from(DownloadedFile)
        ) or 0

        # 成功数
        total_success = await self.db.scalar(
            select(func.count()).select_from(DownloadedFile)
            .where(DownloadedFile.status != "failed")
        ) or 0

        # 失败数
        total_failed = await self.db.scalar(
            select(func.count()).select_from(DownloadedFile)
            .where(DownloadedFile.status == "failed")
        ) or 0

        # 今日下载数
        today_files = await self.db.scalar(
            select(func.count()).select_from(DownloadedFile)
            .where(cast(DownloadedFile.created_at, Date) == today)
        ) or 0

        # 今日成功数
        today_success = await self.db.scalar(
            select(func.count()).select_from(DownloadedFile)
            .where(
                and_(
                    cast(DownloadedFile.created_at, Date) == today,
                    DownloadedFile.status != "failed",
                )
            )
        ) or 0

        # 总文件大小
        total_size = await self.db.scalar(
            select(func.coalesce(func.sum(DownloadedFile.file_size), 0))
            .where(DownloadedFile.status != "failed")
        ) or 0

        # 仓库数
        repo_count = await self.db.scalar(
            select(func.count(func.distinct(DownloadedFile.repo_name)))
        ) or 0

        success_rate = round(total_success / total_files * 100, 2) if total_files > 0 else 0

        return {
            "total_files": total_files,
            "total_success": total_success,
            "total_failed": total_failed,
            "today_files": today_files,
            "today_success": today_success,
            "today_success_rate": round(today_success / today_files * 100, 2) if today_files > 0 else 0,
            "total_size": int(total_size),
            "repo_count": repo_count,
            "overall_success_rate": success_rate,
        }

    async def get_source_comparison(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取各仓库文件下载对比数据"""
        start_date = datetime.now().date() - timedelta(days=days)

        query = (
            select(
                DownloadedFile.repo_name,
                func.count().label("total"),
                func.sum(case((DownloadedFile.status != "failed", 1), else_=0)).label("success"),
                func.sum(case((DownloadedFile.status == "failed", 1), else_=0)).label("failed"),
                func.coalesce(func.sum(DownloadedFile.file_size), 0).label("total_size"),
            )
            .where(DownloadedFile.created_at >= start_date)
            .group_by(DownloadedFile.repo_name)
            .order_by(desc(func.count()))
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "name": row.repo_name or "未知仓库",
                "total": int(row.total or 0),
                "success": int(row.success or 0),
                "failed": int(row.failed or 0),
                "success_rate": round(
                    (int(row.success or 0)) / (int(row.total or 1)) * 100, 2
                ),
                "total_size": int(row.total_size or 0),
            }
            for row in rows
        ]

    async def get_suggestions(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取文件下载优化建议"""
        start_date = datetime.now().date() - timedelta(days=days)
        suggestions: List[Dict[str, Any]] = []

        # 按仓库统计失败率
        query = (
            select(
                DownloadedFile.repo_name,
                func.count().label("total"),
                func.sum(case((DownloadedFile.status == "failed", 1), else_=0)).label("failed"),
            )
            .where(DownloadedFile.created_at >= start_date)
            .group_by(DownloadedFile.repo_name)
            .having(func.count() >= 5)
        )
        result = await self.db.execute(query)

        for row in result.all():
            total = int(row.total or 0)
            failed = int(row.failed or 0)
            fail_rate = round(failed / total * 100, 2) if total > 0 else 0
            repo = row.repo_name or "未知仓库"

            if fail_rate >= 50:
                suggestions.append({
                    "source_name": repo,
                    "period_days": days,
                    "severity": "critical" if fail_rate >= 80 else "warning",
                    "category": "download_failure",
                    "title": f"{repo} 下载失败率偏高",
                    "reason": f"近 {days} 日共 {total} 个文件，失败 {failed} 个（{fail_rate}%）",
                    "action": "检查仓库是否存在速率限制、文件访问权限或网络问题",
                    "metric": "fail_rate",
                    "current": fail_rate,
                    "threshold": "< 50",
                })

        # 高频错误类型
        error_query = (
            select(
                DownloadedFile.error_detail,
                func.count().label("count"),
            )
            .where(
                and_(
                    DownloadedFile.created_at >= start_date,
                    DownloadedFile.status == "failed",
                    DownloadedFile.error_detail.isnot(None),
                )
            )
            .group_by(DownloadedFile.error_detail)
            .order_by(desc(func.count()))
            .limit(3)
        )
        error_result = await self.db.execute(error_query)

        for row in error_result.all():
            suggestions.append({
                "source_name": None,
                "period_days": days,
                "severity": "warning",
                "category": "error_classification",
                "title": f"高频错误：{row.error_detail}",
                "reason": f"近 {days} 日出现 {row.count} 次",
                "action": "根据错误原因调整爬虫配置或网络环境",
                "metric": "error_count",
                "current": int(row.count or 0),
                "threshold": "持续下降",
            })

        severity_order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(
            suggestions,
            key=lambda item: severity_order.get(str(item.get("severity")), 9),
        )[:20]

    async def get_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """获取文件下载趋势数据"""
        start_date = datetime.now().date() - timedelta(days=days)

        query = (
            select(
                cast(DownloadedFile.created_at, Date).label("date"),
                func.count().label("total"),
                func.sum(case((DownloadedFile.status != "failed", 1), else_=0)).label("success"),
                func.sum(case((DownloadedFile.status == "failed", 1), else_=0)).label("failed"),
            )
            .where(DownloadedFile.created_at >= start_date)
            .group_by(cast(DownloadedFile.created_at, Date))
            .order_by(cast(DownloadedFile.created_at, Date))
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "date": row.date.isoformat() if row.date else None,
                "total": int(row.total or 0),
                "successes": int(row.success or 0),
                "failures": int(row.failed or 0),
                "success_rate": round(
                    (int(row.success or 0)) / (int(row.total or 1)) * 100, 2
                ),
            }
            for row in rows
        ]

    async def get_file_type_distribution(self) -> List[Dict[str, Any]]:
        """获取文件类型分布"""
        query = (
            select(
                DownloadedFile.file_type,
                func.count().label("count"),
            )
            .where(DownloadedFile.status != "failed")
            .group_by(DownloadedFile.file_type)
            .order_by(desc(func.count()))
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {"name": row.file_type or "未知", "value": int(row.count or 0)}
            for row in rows
        ]
