"""
定时任务管理服务层

提供定时任务的 CRUD、启用/禁用、执行历史查询等业务逻辑。
使用 APScheduler 进行任务调度。
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlSchedule, CrawlScheduleRun

logger = get_logger(__name__)

# 调度器实例（由 scheduler.py 初始化后设置）
_scheduler_instance = None


def set_scheduler_instance(scheduler):
    """设置调度器实例"""
    global _scheduler_instance
    _scheduler_instance = scheduler


def get_scheduler_instance():
    """获取调度器实例"""
    return _scheduler_instance


class CrawlerScheduleService:
    """定时任务管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_schedules(
        self,
        skip: int = 0,
        limit: int = 20,
        is_enabled: Optional[bool] = None,
    ) -> tuple[List[CrawlSchedule], int]:
        """获取定时任务列表"""
        query = select(CrawlSchedule)

        if is_enabled is not None:
            query = query.where(CrawlSchedule.is_enabled == is_enabled)

        # 统计总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # 分页查询
        query = query.offset(skip).limit(limit).order_by(CrawlSchedule.created_at.desc())
        result = await self.db.execute(query)
        schedules = result.scalars().all()

        return list(schedules), total

    async def get_schedule_by_id(self, schedule_id: str) -> Optional[CrawlSchedule]:
        """根据ID获取定时任务"""
        result = await self.db.execute(
            select(CrawlSchedule).where(CrawlSchedule.id == schedule_id)
        )
        return result.scalar_one_or_none()

    async def create_schedule(self, data: Dict[str, Any]) -> CrawlSchedule:
        """创建定时任务"""
        schedule = CrawlSchedule(
            id=f"sch_{uuid.uuid4().hex[:8]}",
            name=data["name"],
            description=data.get("description"),
            task_type=data["task_type"],
            source_ids=data.get("source_ids"),
            target_config=data.get("target_config"),
            cron_expression=data["cron_expression"],
            timezone=data.get("timezone", "Asia/Shanghai"),
            is_enabled=data.get("is_enabled", True),
            max_retries=data.get("max_retries", 3),
            retry_interval=data.get("retry_interval", 300),
            concurrent_limit=data.get("concurrent_limit", 1),
            timeout=data.get("timeout", 3600),
            notify_on_success=data.get("notify_on_success", False),
            notify_on_failure=data.get("notify_on_failure", True),
            notify_emails=data.get("notify_emails"),
            created_by=data.get("created_by"),
        )

        # 计算下次执行时间
        schedule.next_run_at = self._calculate_next_run(schedule.cron_expression, schedule.timezone)

        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        
        # 注册到调度器
        try:
            from app.tasks.scheduler import add_schedule_to_scheduler
            await add_schedule_to_scheduler(schedule)
        except Exception as e:
            logger.warning(f"注册到调度器失败: {e}")
        
        logger.info(f"Created crawl schedule: {schedule.name} ({schedule.id})")
        return schedule

    async def update_schedule(self, schedule_id: str, data: Dict[str, Any]) -> Optional[CrawlSchedule]:
        """更新定时任务"""
        schedule = await self.get_schedule_by_id(schedule_id)
        if not schedule:
            return None

        for key, value in data.items():
            if hasattr(schedule, key) and value is not None:
                setattr(schedule, key, value)

        # 如果修改了 cron 表达式，重新计算下次执行时间
        if "cron_expression" in data:
            schedule.next_run_at = self._calculate_next_run(
                schedule.cron_expression, schedule.timezone
            )

        schedule.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(schedule)
        
        # 更新调度器中的任务
        try:
            from app.tasks.scheduler import update_schedule_in_scheduler
            await update_schedule_in_scheduler(schedule)
        except Exception as e:
            logger.warning(f"更新调度器任务失败: {e}")
        
        logger.info(f"Updated crawl schedule: {schedule.name} ({schedule.id})")
        return schedule

    async def delete_schedule(self, schedule_id: str) -> bool:
        """删除定时任务"""
        schedule = await self.get_schedule_by_id(schedule_id)
        if not schedule:
            return False

        # 从调度器移除
        try:
            from app.tasks.scheduler import remove_schedule_from_scheduler
            await remove_schedule_from_scheduler(schedule_id)
        except Exception as e:
            logger.warning(f"从调度器移除任务失败: {e}")

        await self.db.delete(schedule)
        await self.db.commit()
        logger.info(f"Deleted crawl schedule: {schedule_id}")
        return True

    async def toggle_schedule(self, schedule_id: str, enabled: bool) -> Optional[CrawlSchedule]:
        """启用/禁用定时任务"""
        schedule = await self.get_schedule_by_id(schedule_id)
        if not schedule:
            return None

        schedule.is_enabled = enabled
        if enabled:
            schedule.next_run_at = self._calculate_next_run(
                schedule.cron_expression, schedule.timezone
            )
        else:
            schedule.next_run_at = None

        schedule.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(schedule)
        
        # 更新调度器
        try:
            from app.tasks.scheduler import update_schedule_in_scheduler
            await update_schedule_in_scheduler(schedule)
        except Exception as e:
            logger.warning(f"更新调度器任务状态失败: {e}")
        
        logger.info(f"Toggled crawl schedule {schedule_id}: enabled={enabled}")
        return schedule

    async def get_runs(
        self,
        schedule_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
        status: Optional[str] = None,
    ) -> tuple[List[CrawlScheduleRun], int]:
        """获取执行历史"""
        query = select(CrawlScheduleRun)

        if schedule_id:
            query = query.where(CrawlScheduleRun.schedule_id == schedule_id)
        if status:
            query = query.where(CrawlScheduleRun.status == status)

        # 统计总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # 分页查询
        query = query.offset(skip).limit(limit).order_by(CrawlScheduleRun.started_at.desc())
        result = await self.db.execute(query)
        runs = result.scalars().all()

        return list(runs), total

    async def record_run(
        self,
        schedule_id: str,
        status: str,
        started_at: datetime,
        completed_at: Optional[datetime] = None,
        duration: Optional[int] = None,
        total_requests: int = 0,
        success_count: int = 0,
        failed_count: int = 0,
        error_message: Optional[str] = None,
        log_summary: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> CrawlScheduleRun:
        """记录执行历史"""
        run = CrawlScheduleRun(
            schedule_id=schedule_id,
            task_id=task_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration=duration,
            total_requests=total_requests,
            success_count=success_count,
            failed_count=failed_count,
            error_message=error_message,
            log_summary=log_summary,
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)

        # 更新定时任务的执行统计
        schedule = await self.get_schedule_by_id(schedule_id)
        if schedule:
            schedule.total_runs += 1
            if status == "success":
                schedule.success_runs += 1
                schedule.last_run_status = "success"
            elif status == "failed":
                schedule.failed_runs += 1
                schedule.last_run_status = "failed"
            else:
                schedule.last_run_status = status

            schedule.last_run_at = started_at
            schedule.last_run_duration = duration
            schedule.next_run_at = self._calculate_next_run(
                schedule.cron_expression, schedule.timezone
            )
            await self.db.commit()

        logger.info(f"Recorded schedule run: {schedule_id} - {status}")
        return run

    @staticmethod
    def _calculate_next_run(cron_expression: str, timezone: str = "Asia/Shanghai") -> Optional[datetime]:
        """计算下次执行时间"""
        try:
            from apscheduler.triggers.cron import CronTrigger
            import pytz

            tz = pytz.timezone(timezone)
            trigger = CronTrigger.from_crontab(cron_expression, timezone=tz)
            next_run = trigger.get_next_fire_time(None, datetime.now(tz))
            return next_run.astimezone(pytz.UTC).replace(tzinfo=None) if next_run else None
        except Exception as e:
            logger.error(f"Failed to calculate next run: {e}")
            return None
