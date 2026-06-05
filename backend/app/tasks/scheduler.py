"""
APScheduler 定时任务调度器

提供定时任务的调度、执行和管理功能。
使用 APScheduler 的 AsyncIOScheduler 实现异步任务调度。
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.models.mysql_models import CrawlSchedule, CrawlScheduleRun
from app.services.schedule_service import CrawlerScheduleService

logger = get_logger(__name__)

# 全局调度器实例
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """获取全局调度器实例"""
    return _scheduler


async def init_scheduler() -> AsyncIOScheduler:
    """
    初始化 APScheduler 调度器
    
    从数据库加载所有启用的定时任务并注册到调度器。
    """
    global _scheduler
    
    if _scheduler is not None:
        logger.warning("调度器已初始化，跳过")
        return _scheduler
    
    logger.info("正在初始化 APScheduler 调度器...")
    
    # 创建调度器
    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    
    # 添加事件监听器
    _scheduler.add_listener(
        _on_job_executed,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
    )
    
    # 从数据库加载启用的定时任务
    try:
        async with mysql_client.session() as session:
            service = CrawlerScheduleService(session)
            schedules, _ = await service.get_schedules(
                skip=0,
                limit=1000,
                is_enabled=True
            )
            
            for schedule in schedules:
                _register_job(schedule)
                logger.info(f"已注册定时任务: {schedule.name} ({schedule.id})")
    except Exception as e:
        logger.error(f"加载定时任务失败: {e}")
    
    # 启动调度器
    _scheduler.start()
    logger.info("APScheduler 调度器已启动")
    
    return _scheduler


async def shutdown_scheduler() -> None:
    """
    关闭调度器
    
    优雅停止所有正在运行的任务并关闭调度器。
    """
    global _scheduler
    
    if _scheduler is None:
        logger.warning("调度器未初始化，跳过关闭")
        return
    
    logger.info("正在关闭 APScheduler 调度器...")
    
    try:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("APScheduler 调度器已关闭")
    except Exception as e:
        logger.error(f"关闭调度器失败: {e}")


def _register_job(schedule: CrawlSchedule) -> None:
    """
    注册单个定时任务到调度器
    
    Args:
        schedule: 定时任务配置
    """
    global _scheduler
    
    if _scheduler is None:
        logger.error("调度器未初始化，无法注册任务")
        return
    
    job_id = f"schedule_{schedule.id}"
    
    # 如果任务已存在，先移除
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    
    try:
        # 创建 Cron 触发器
        trigger = CronTrigger.from_crontab(
            schedule.cron_expression,
            timezone=schedule.timezone
        )
        
        # 添加任务
        _scheduler.add_job(
            func=_execute_schedule_wrapper,
            trigger=trigger,
            id=job_id,
            name=schedule.name,
            args=[schedule.id],
            max_instances=1,  # 同一任务同时只能运行一个实例
            misfire_grace_time=300,  # 错过执行时间后5分钟内仍可执行
        )
        
        logger.debug(f"已注册任务: {job_id}")
    except Exception as e:
        logger.error(f"注册任务失败 {schedule.id}: {e}")


def _unregister_job(schedule_id: str) -> None:
    """
    从调度器移除定时任务
    
    Args:
        schedule_id: 定时任务ID
    """
    global _scheduler
    
    if _scheduler is None:
        return
    
    job_id = f"schedule_{schedule_id}"
    
    try:
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
            logger.debug(f"已移除任务: {job_id}")
    except Exception as e:
        logger.error(f"移除任务失败 {schedule_id}: {e}")


async def _execute_schedule_wrapper(schedule_id: str) -> None:
    """
    定时任务执行包装器
    
    包装同步任务执行，提供异常处理和日志记录。
    
    Args:
        schedule_id: 定时任务ID
    """
    logger.info(f"开始执行定时任务: {schedule_id}")
    started_at = datetime.utcnow()
    
    try:
        # 创建数据库会话并执行任务
        async with mysql_client.session() as session:
            service = CrawlerScheduleService(session)
            
            # 获取任务配置
            schedule = await service.get_schedule_by_id(schedule_id)
            if not schedule:
                logger.error(f"定时任务不存在: {schedule_id}")
                return
            
            if not schedule.is_enabled:
                logger.warning(f"定时任务已禁用，跳过执行: {schedule_id}")
                return
            
            # 执行实际任务
            await _execute_schedule_task(session, schedule)
            
            # 记录成功
            await service.record_run(
                schedule_id=schedule_id,
                status="success",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )
            
            logger.info(f"定时任务执行成功: {schedule_id}")
            
    except Exception as e:
        logger.error(f"定时任务执行失败 {schedule_id}: {e}")
        
        # 记录失败
        try:
            async with mysql_client.session() as session:
                service = CrawlerScheduleService(session)
                await service.record_run(
                    schedule_id=schedule_id,
                    status="failed",
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    error_message=str(e)[:500],
                )
        except Exception as record_error:
            logger.error(f"记录任务失败状态失败: {record_error}")


async def _execute_schedule_task(session: AsyncSession, schedule: CrawlSchedule) -> None:
    """
    执行定时任务的具体逻辑
    
    Args:
        session: 数据库会话
        schedule: 定时任务配置
    """
    logger.info(f"执行任务类型: {schedule.task_type}, 源: {schedule.source_ids}")
    
    # 创建爬虫任务执行服务
    from app.services.task_service import CrawlerTaskService
    task_service = CrawlerTaskService(session)
    
    # 根据任务类型执行不同的逻辑
    if schedule.task_type in ("full", "incremental", "targeted", "health_check", "cleanup"):
        # 创建任务
        task = await task_service.create_task_from_schedule(
            schedule_id=schedule.id,
            schedule_name=schedule.name,
            task_type=schedule.task_type,
            source_ids=schedule.source_ids or [],
            target_config=schedule.target_config,
        )
        
        # 执行任务
        await task_service.execute_task(task.id)
        
    else:
        logger.warning(f"未知的任务类型: {schedule.task_type}")


def _on_job_executed(event) -> None:
    """
    任务执行完成事件处理
    
    Args:
        event: APScheduler 事件对象
    """
    if event.exception:
        logger.error(f"任务执行失败: {event.job_id}, 异常: {event.exception}")
    else:
        logger.debug(f"任务执行完成: {event.job_id}")


async def add_schedule_to_scheduler(schedule: CrawlSchedule) -> None:
    """
    添加新的定时任务到调度器
    
    Args:
        schedule: 定时任务配置
    """
    global _scheduler
    
    if _scheduler is None:
        logger.error("调度器未初始化")
        return
    
    if schedule.is_enabled:
        _register_job(schedule)
        logger.info(f"已添加定时任务到调度器: {schedule.name}")
    else:
        logger.debug(f"任务已禁用，不添加到调度器: {schedule.name}")


async def remove_schedule_from_scheduler(schedule_id: str) -> None:
    """
    从调度器移除定时任务
    
    Args:
        schedule_id: 定时任务ID
    """
    _unregister_job(schedule_id)
    logger.info(f"已从调度器移除定时任务: {schedule_id}")


async def update_schedule_in_scheduler(schedule: CrawlSchedule) -> None:
    """
    更新调度器中的定时任务
    
    Args:
        schedule: 定时任务配置
    """
    # 先移除旧任务
    _unregister_job(schedule.id)
    
    # 如果启用，重新注册
    if schedule.is_enabled:
        _register_job(schedule)
        logger.info(f"已更新调度器中的定时任务: {schedule.name}")
    else:
        logger.info(f"任务已禁用，从调度器移除: {schedule.name}")


async def get_scheduler_status() -> Dict[str, Any]:
    """
    获取调度器状态
    
    Returns:
        调度器状态信息
    """
    global _scheduler
    
    if _scheduler is None:
        return {
            "running": False,
            "jobs": [],
        }
    
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    
    return {
        "running": _scheduler.running,
        "jobs": jobs,
    }
