"""
爬虫统计服务层

提供统计报表、趋势分析、效率分析等业务逻辑。
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlLog, CrawlSource, CrawlSourceStats, CrawlTask, Person

logger = get_logger(__name__)


class CrawlerStatsService:
    """爬虫统计服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self) -> Dict[str, Any]:
        """获取总体概览"""
        # 活跃源数
        active_sources = await self.db.scalar(
            select(func.count()).where(CrawlSource.status == "active")
        ) or 0

        # 今日请求数
        today = datetime.now().date()
        today_requests = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.total_requests), 0))
            .where(CrawlSourceStats.stat_date == today)
        ) or 0

        # 今日成功数
        today_success = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.success_requests), 0))
            .where(CrawlSourceStats.stat_date == today)
        ) or 0

        # 整体成功率
        total_requests = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.total_requests), 0))
        ) or 0
        total_success = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.success_requests), 0))
        ) or 0
        total_failed = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.failed_requests), 0))
        ) or 0
        total_tasks = await self.db.scalar(select(func.count(CrawlTask.id))) or 0

        success_rate = round(total_success / total_requests * 100, 2) if total_requests > 0 else 0
        recent_result = await self.db.execute(
            select(CrawlLog)
            .order_by(CrawlLog.created_at.desc())
            .limit(10)
        )
        recent_records = [
            {
                "id": log.id,
                "time": log.created_at.isoformat() if log.created_at else None,
                "resource": log.resource_name or log.resource_url or log.task_id,
                "action": log.action or log.stage or "-",
                "status": log.status or "pending",
                "duration": log.duration_ms or 0,
                "message": log.message,
            }
            for log in recent_result.scalars().all()
        ]
        category_result = await self.db.execute(
            select(Person.categories)
            .where(Person.categories.is_not(None))
            .order_by(Person.updated_at.desc())
            .limit(1000)
        )
        category_counts: Dict[str, int] = {}
        for categories in category_result.scalars().all():
            values = categories if isinstance(categories, list) else []
            for category in values:
                category_counts[str(category)] = category_counts.get(str(category), 0) + 1

        return {
            "active_sources": active_sources,
            "total_tasks": int(total_tasks),
            "today_requests": int(today_requests),
            "today_success": int(today_success),
            "today_success_rate": round(today_success / today_requests * 100, 2) if today_requests > 0 else 0,
            "total_requests": int(total_requests),
            "total_success": int(total_success),
            "total_failed": int(total_failed),
            "overall_success_rate": success_rate,
            "recent_records": recent_records,
            "category_distribution": [
                {"name": name, "value": value}
                for name, value in sorted(
                    category_counts.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:10]
            ],
        }

    async def get_source_comparison(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取各源对比数据"""
        start_date = datetime.now().date() - timedelta(days=days)

        query = (
            select(
                CrawlSource.id,
                CrawlSource.name,
                CrawlSource.type,
                CrawlSource.status,
                CrawlSource.health_status,
                func.coalesce(func.sum(CrawlSourceStats.total_requests), 0).label("total_requests"),
                func.coalesce(func.sum(CrawlSourceStats.success_requests), 0).label("success_requests"),
                func.coalesce(func.sum(CrawlSourceStats.failed_requests), 0).label("failed_requests"),
                func.coalesce(func.sum(CrawlSourceStats.timeout_requests), 0).label("timeout_requests"),
                func.coalesce(func.sum(CrawlSourceStats.rate_limited_requests), 0).label("rate_limited_requests"),
                func.coalesce(func.sum(CrawlSourceStats.valid_records), 0).label("valid_records"),
                func.avg(CrawlSourceStats.avg_response_time).label("avg_response_time"),
                func.avg(CrawlSourceStats.avg_completeness).label("avg_completeness"),
            )
            .outerjoin(
                CrawlSourceStats,
                and_(
                    CrawlSource.id == CrawlSourceStats.source_id,
                    CrawlSourceStats.stat_date >= start_date,
                ),
            )
            .group_by(CrawlSource.id)
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "source_id": row.id,
                "name": row.name,
                "type": row.type,
                "status": row.status,
                "health_status": row.health_status,
                "total_requests": int(row.total_requests or 0),
                "success_requests": int(row.success_requests or 0),
                "failed_requests": int(row.failed_requests or 0),
                "timeout_requests": int(row.timeout_requests or 0),
                "rate_limited_requests": int(row.rate_limited_requests or 0),
                "valid_records": int(row.valid_records or 0),
                "success_rate": round(
                    (row.success_requests or 0) / (row.total_requests or 1) * 100, 2
                ),
                "avg_response_time": round(row.avg_response_time or 0, 2),
                "avg_completeness": round(row.avg_completeness or 0, 2),
            }
            for row in rows
        ]

    async def get_suggestions(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取爬虫运营优化建议"""
        sources = await self.get_source_comparison(days)
        suggestions: List[Dict[str, Any]] = []

        for source in sources:
            total_requests = int(source["total_requests"])
            source_name = source["name"]
            base_payload = {
                "source_id": source["source_id"],
                "source_name": source_name,
                "period_days": days,
            }

            if source["health_status"] == "down":
                suggestions.append({
                    **base_payload,
                    "severity": "critical",
                    "category": "health",
                    "title": f"{source_name} 健康检查不可用",
                    "reason": "最近一次健康检查标记为 down",
                    "action": "检查 base_url、网络连通性和目标站点访问策略",
                    "metric": "health_status",
                    "current": source["health_status"],
                    "threshold": "healthy/degraded",
                })
            elif source["health_status"] == "degraded":
                suggestions.append({
                    **base_payload,
                    "severity": "warning",
                    "category": "health",
                    "title": f"{source_name} 健康状态降级",
                    "reason": "健康检查可达但响应状态异常",
                    "action": "确认站点是否限制 HEAD/GET，并调整健康检查或源配置",
                    "metric": "health_status",
                    "current": source["health_status"],
                    "threshold": "healthy",
                })

            if source["status"] == "active" and total_requests == 0:
                suggestions.append({
                    **base_payload,
                    "severity": "info",
                    "category": "coverage",
                    "title": f"{source_name} 近 {days} 日无请求",
                    "reason": "活跃数据源没有产生抓取请求",
                    "action": "确认任务调度是否覆盖该数据源",
                    "metric": "total_requests",
                    "current": 0,
                    "threshold": "> 0",
                })

            if total_requests >= 10 and source["success_rate"] < 80:
                suggestions.append({
                    **base_payload,
                    "severity": "critical" if source["success_rate"] < 60 else "warning",
                    "category": "success_rate",
                    "title": f"{source_name} 成功率偏低",
                    "reason": f"近 {days} 日成功率为 {source['success_rate']}%",
                    "action": "优先查看失败日志，调整重试次数、请求间隔或反爬配置",
                    "metric": "success_rate",
                    "current": source["success_rate"],
                    "threshold": ">= 80",
                })

            if source["rate_limited_requests"] > 0:
                suggestions.append({
                    **base_payload,
                    "severity": "warning",
                    "category": "rate_limit",
                    "title": f"{source_name} 出现限流",
                    "reason": f"近 {days} 日有 {source['rate_limited_requests']} 次 429 响应",
                    "action": "降低并发、增大 request_interval，并开启更保守的重试策略",
                    "metric": "rate_limited_requests",
                    "current": source["rate_limited_requests"],
                    "threshold": "0",
                })

            if source["timeout_requests"] > 0:
                suggestions.append({
                    **base_payload,
                    "severity": "warning",
                    "category": "timeout",
                    "title": f"{source_name} 出现超时",
                    "reason": f"近 {days} 日有 {source['timeout_requests']} 次超时",
                    "action": "检查代理/网络稳定性，并按源调整 timeout 与重试次数",
                    "metric": "timeout_requests",
                    "current": source["timeout_requests"],
                    "threshold": "0",
                })

            if source["avg_response_time"] > 5000:
                suggestions.append({
                    **base_payload,
                    "severity": "warning",
                    "category": "latency",
                    "title": f"{source_name} 响应耗时偏高",
                    "reason": f"平均响应耗时 {source['avg_response_time']}ms",
                    "action": "降低并发或拆分任务批次，避免慢源拖垮整体任务",
                    "metric": "avg_response_time",
                    "current": source["avg_response_time"],
                    "threshold": "<= 5000",
                })

            if source["valid_records"] > 0 and source["avg_completeness"] < 70:
                suggestions.append({
                    **base_payload,
                    "severity": "warning",
                    "category": "data_quality",
                    "title": f"{source_name} 数据完整度偏低",
                    "reason": f"平均字段完整度 {source['avg_completeness']}%",
                    "action": "检查解析选择器和字段映射，优先补齐名称、摘要、日期等核心字段",
                    "metric": "avg_completeness",
                    "current": source["avg_completeness"],
                    "threshold": ">= 70",
                })

        start_time = datetime.utcnow() - timedelta(days=days)
        error_result = await self.db.execute(
            select(CrawlLog.error_type, func.count().label("count"))
            .where(
                CrawlLog.created_at >= start_time,
                CrawlLog.error_type.isnot(None),
            )
            .group_by(CrawlLog.error_type)
            .order_by(desc(func.count()))
            .limit(3)
        )
        for row in error_result.all():
            suggestions.append({
                "source_id": None,
                "source_name": None,
                "period_days": days,
                "severity": "warning",
                "category": "error_classification",
                "title": f"高频错误：{row.error_type}",
                "reason": f"近 {days} 日出现 {row.count} 次",
                "action": "按错误类型定位请求、解析或存储链路，并补充对应的重试/降级策略",
                "metric": "error_type_count",
                "current": int(row.count or 0),
                "threshold": "持续下降",
            })

        severity_order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(
            suggestions,
            key=lambda item: (
                severity_order.get(str(item.get("severity")), 9),
                str(item.get("source_name") or ""),
            ),
        )[:20]

    async def get_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """获取趋势数据"""
        start_date = datetime.now().date() - timedelta(days=days)

        query = (
            select(
                CrawlSourceStats.stat_date,
                func.coalesce(func.sum(CrawlSourceStats.total_requests), 0).label("requests"),
                func.coalesce(func.sum(CrawlSourceStats.success_requests), 0).label("successes"),
                func.coalesce(func.sum(CrawlSourceStats.failed_requests), 0).label("failures"),
            )
            .where(CrawlSourceStats.stat_date >= start_date)
            .group_by(CrawlSourceStats.stat_date)
            .order_by(CrawlSourceStats.stat_date)
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "date": row.stat_date.isoformat(),
                "requests": int(row.requests or 0),
                "successes": int(row.successes or 0),
                "failures": int(row.failures or 0),
                "success_rate": round(
                    (row.successes or 0) / (row.requests or 1) * 100, 2
                ),
            }
            for row in rows
        ]

    async def get_efficiency(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取效率分析"""
        start_date = datetime.now().date() - timedelta(days=days)

        query = (
            select(
                CrawlSourceStats.source_id,
                CrawlSource.name,
                func.coalesce(func.sum(CrawlSourceStats.total_requests), 0).label("total_requests"),
                func.coalesce(func.sum(CrawlSourceStats.valid_records), 0).label("valid_records"),
                func.coalesce(func.sum(CrawlSourceStats.persons_extracted), 0).label("persons"),
                func.coalesce(func.sum(CrawlSourceStats.works_extracted), 0).label("works"),
                func.avg(CrawlSourceStats.avg_response_time).label("avg_response_time"),
                func.avg(CrawlSourceStats.avg_completeness).label("avg_completeness"),
            )
            .join(CrawlSource, CrawlSourceStats.source_id == CrawlSource.id)
            .where(CrawlSourceStats.stat_date >= start_date)
            .group_by(CrawlSourceStats.source_id)
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "source_id": row.source_id,
                "name": row.name,
                "total_requests": int(row.total_requests or 0),
                "valid_records": int(row.valid_records or 0),
                "efficiency": round(
                    (row.valid_records or 0) / (row.total_requests or 1), 4
                ),
                "persons": int(row.persons or 0),
                "works": int(row.works or 0),
                "avg_response_time": round(row.avg_response_time or 0, 2),
                "avg_completeness": round(row.avg_completeness or 0, 2),
            }
            for row in rows
        ]
