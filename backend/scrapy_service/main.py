"""
StarMap Scrapy Service Entry Point.

This script starts the Scrapy service and connects to Redis for task consumption.
Can be run standalone or inside a container.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, List

import redis

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

TASK_QUEUE = os.getenv("REDIS_TASK_QUEUE", "starmap:crawl:tasks")
PROGRESS_CHANNEL = os.getenv("REDIS_PROGRESS_CHANNEL", "starmap:crawl:progress")
LOG_CHANNEL = os.getenv("REDIS_LOG_CHANNEL", "starmap:crawl:logs")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _publish_progress(task_id: str, status: str, progress: float, **extra: Any) -> None:
    """Publish task progress to Redis."""
    if not task_id:
        return

    message = {
        "task_id": task_id,
        "status": status,
        "progress": progress,
        **extra,
    }
    try:
        redis.from_url(REDIS_URL).publish(
            PROGRESS_CHANNEL,
            json.dumps(message, ensure_ascii=False),
        )
    except Exception as e:
        logger.warning(f"Failed to publish progress for task {task_id}: {e}")


def _publish_log(task_id: str, level: str, message: str, **extra: Any) -> None:
    """Publish task log to Redis."""
    if not task_id:
        return

    log_entry = {
        "task_id": task_id,
        "level": level,
        "stage": extra.pop("stage", "execution"),
        "status": extra.pop("status", "pending"),
        "message": message,
        **extra,
    }
    try:
        redis.from_url(REDIS_URL).publish(
            LOG_CHANNEL,
            json.dumps(log_entry, ensure_ascii=False, default=str),
        )
    except Exception as e:
        logger.warning(f"Failed to publish log for task {task_id}: {e}")


def _normalize_keywords(keywords: Any) -> List[str]:
    """Normalize Redis task keywords into a list."""
    if isinstance(keywords, list):
        return [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
    if isinstance(keywords, str):
        return [keyword.strip() for keyword in keywords.split(",") if keyword.strip()]
    return []


def start_service(spider_name="person", **kwargs):
    """
    Start the Scrapy service.
    
    Args:
        spider_name: Name of the spider to run (person, work)
        **kwargs: Additional arguments passed to spider
    """
    logger.info(f"Starting StarMap Scrapy service with spider: {spider_name}")
    
    # Get project settings
    settings = get_project_settings()
    
    # Override settings from environment
    if os.getenv("LOG_LEVEL"):
        settings.set("LOG_LEVEL", os.getenv("LOG_LEVEL"))
    
    # Create crawler process
    process = CrawlerProcess(settings)
    
    # Schedule spider
    process.crawl(spider_name, **kwargs)
    
    # Start the reactor
    logger.info("Starting crawler reactor...")
    process.start()
    
    logger.info("Scrapy service stopped")


def start_task_consumer():
    """
    Start the task consumer mode.
    
    This mode continuously listens for tasks from Redis queue.
    """
    logger.info("Starting StarMap Scrapy service in task consumer mode")

    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info(f"Task consumer connected to Redis queue: {TASK_QUEUE}")

    while True:
        _, task_json = redis_client.brpop(TASK_QUEUE)
        try:
            task = json.loads(task_json)
        except json.JSONDecodeError:
            logger.error(f"Invalid task payload: {task_json}")
            continue

        task_id = task.get("task_id")
        spider_type = task.get("spider_type", "person")
        source = task.get("source", "baike")
        source_id = task.get("source_id")
        keywords = _normalize_keywords(task.get("keywords"))
        config = task.get("config") or {}

        logger.info(
            f"Received task: {task_id}, spider={spider_type}, "
            f"source={source}, keywords={keywords}"
        )

        if not task_id:
            logger.error(f"Task payload missing task_id: {task}")
            continue

        if not keywords and task.get("task_type") in {"full", "incremental", "targeted"}:
            error_message = "No keywords provided"
            _publish_log(task_id, "ERROR", error_message, status="failed")
            _publish_progress(task_id, "failed", 100, error_message=error_message)
            continue

        _publish_log(task_id, "INFO", "Task received by Scrapy consumer", status="pending")
        _publish_progress(task_id, "running", 0)

        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--mode",
            "single",
            "--task-id",
            task_id,
            "--spider",
            spider_type,
            "--source",
            source,
            "--keywords",
            ",".join(keywords),
        ]

        if source_id:
            command.extend(["--source-id", str(source_id)])

        if config.get("work_type"):
            command.extend(["--work-type", str(config["work_type"])])

        completed = subprocess.run(command, cwd=str(project_root), check=False)
        if completed.returncode == 0:
            _publish_log(task_id, "INFO", "Task subprocess completed", status="success")
        else:
            error_message = f"Task subprocess failed with exit code {completed.returncode}"
            _publish_log(task_id, "ERROR", error_message, status="failed")
            _publish_progress(task_id, "failed", 100, error_message=error_message)


def run_single_task(task_id, spider_type, source, keywords, source_id=None, work_type=None):
    """
    Run a single task directly.
    
    Args:
        task_id: Task identifier
        spider_type: Type of spider (person, work)
        source: Data source (baike, douban, wikipedia)
        keywords: Comma-separated keywords
    """
    logger.info(f"Running single task: {task_id}")
    
    settings = get_project_settings()
    settings.set("EXTENSIONS", {
        "starmap_scrapy.extensions.progress_reporter.ProgressReporterExtension": 200,
    }, priority="cmdline")
    process = CrawlerProcess(settings)

    spider_kwargs = {
        "task_id": task_id,
        "source": source,
        "source_id": source_id,
        "keywords": keywords,
    }
    if work_type:
        spider_kwargs["work_type"] = work_type

    process.crawl(spider_type, **spider_kwargs)
    
    process.start()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="StarMap Scrapy Service")
    parser.add_argument(
        "--mode",
        choices=["consumer", "single"],
        default="consumer",
        help="Run mode: consumer (wait for Redis tasks) or single (run one task)",
    )
    parser.add_argument(
        "--spider",
        choices=["person", "work"],
        default="person",
        help="Spider type",
    )
    parser.add_argument(
        "--source",
        choices=["baike", "douban", "wikipedia"],
        default="baike",
        help="Data source",
    )
    parser.add_argument(
        "--keywords",
        default="周杰伦",
        help="Comma-separated keywords",
    )
    parser.add_argument(
        "--task-id",
        default="manual_task",
        help="Task identifier",
    )
    parser.add_argument(
        "--source-id",
        default=None,
        help="Crawl source identifier",
    )
    parser.add_argument(
        "--work-type",
        default=None,
        help="Work type for work spider",
    )
    
    args = parser.parse_args()
    
    if args.mode == "consumer":
        start_task_consumer()
    else:
        run_single_task(
            task_id=args.task_id,
            spider_type=args.spider,
            source=args.source,
            keywords=args.keywords,
            source_id=args.source_id,
            work_type=args.work_type,
        )


if __name__ == "__main__":
    main()
