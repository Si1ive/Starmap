"""
Scrapy Service Entry Point for 408考研学习平台.

Connects to Redis for task consumption. Can be run standalone or inside a container.
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

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from runtime_config import build_scrapy_setting_overrides, parse_runtime_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

TASK_QUEUE = os.getenv("REDIS_TASK_QUEUE", "crawler:tasks")
PROGRESS_CHANNEL = os.getenv("REDIS_PROGRESS_CHANNEL", "crawler:progress")
LOG_CHANNEL = os.getenv("REDIS_LOG_CHANNEL", "crawler:logs")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

SUPPORTED_SPIDERS = {"github", "knowledge"}


def _publish_progress(task_id: str, status: str, progress: float, **extra: Any) -> None:
    if not task_id:
        return
    message = {"task_id": task_id, "status": status, "progress": progress, **extra}
    try:
        redis.from_url(REDIS_URL).publish(PROGRESS_CHANNEL, json.dumps(message, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"Failed to publish progress for task {task_id}: {e}")


def _publish_log(task_id: str, level: str, message: str, **extra: Any) -> None:
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
        redis.from_url(REDIS_URL).publish(LOG_CHANNEL, json.dumps(log_entry, ensure_ascii=False, default=str))
    except Exception as e:
        logger.warning(f"Failed to publish log for task {task_id}: {e}")


def _normalize_keywords(keywords: Any) -> List[str]:
    if isinstance(keywords, list):
        return [str(k).strip() for k in keywords if str(k).strip()]
    if isinstance(keywords, str):
        return [k.strip() for k in keywords.split(",") if k.strip()]
    return []


def start_task_consumer():
    """Continuously listen for tasks from Redis queue."""
    logger.info("Starting crawler service in task consumer mode")

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
        spider_type = task.get("spider_type", "github")
        source = task.get("source", "github")
        source_id = task.get("source_id")
        config = task.get("config") or {}
        runtime_config = task.get("runtime_config") or {}

        logger.info(f"Received task: {task_id}, spider={spider_type}, source={source}")

        if not task_id:
            logger.error(f"Task payload missing task_id: {task}")
            continue

        if spider_type not in SUPPORTED_SPIDERS:
            error_message = f"Unsupported spider type: {spider_type}"
            _publish_log(task_id, "ERROR", error_message, status="failed", source_id=source_id)
            _publish_progress(task_id, "failed", 100, error_message=error_message)
            continue

        _publish_log(task_id, "INFO", "Task received by crawler service", status="pending", source_id=source_id)
        _publish_progress(task_id, "running", 0)

        command = [sys.executable, str(Path(__file__).resolve()), "--mode", "single", "--task-id", task_id, "--spider", spider_type, "--source", source]
        if source_id:
            command.extend(["--source-id", str(source_id)])

        # GitHub spider parameters
        if spider_type == "github":
            if config.get("repo_url"):
                command.extend(["--repo-url", config["repo_url"]])
            if config.get("search_query"):
                command.extend(["--search-query", config["search_query"]])
            if config.get("file_types"):
                ft = config["file_types"]
                command.extend(["--file-types", ",".join(ft) if isinstance(ft, list) else str(ft)])
            max_depth = config.get("max_depth") or runtime_config.get("max_depth")
            if max_depth:
                command.extend(["--max-depth", str(max_depth)])

        # Knowledge spider parameters
        if spider_type == "knowledge":
            if config.get("pdf_path"):
                command.extend(["--pdf-path", config["pdf_path"]])
            if config.get("subject_id"):
                command.extend(["--subject-id", config["subject_id"]])
            if config.get("chapter_id"):
                command.extend(["--chapter-id", config["chapter_id"]])

        child_env = os.environ.copy()
        if runtime_config:
            child_env["CRAWLER_RUNTIME_CONFIG_JSON"] = json.dumps(
                runtime_config,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        completed = subprocess.run(
            command,
            cwd=str(project_root),
            check=False,
            env=child_env,
        )
        if completed.returncode == 0:
            _publish_log(task_id, "INFO", "Task subprocess completed", status="success", source_id=source_id)
        else:
            error_message = f"Task subprocess failed with exit code {completed.returncode}"
            _publish_log(task_id, "ERROR", error_message, status="failed", source_id=source_id, error_type="subprocess_error")
            _publish_progress(task_id, "failed", 100, error_message=error_message)


def run_single_task(
    task_id,
    spider_type,
    source,
    source_id=None,
    repo_url=None,
    search_query=None,
    file_types="pdf",
    max_depth=5,
    pdf_path=None,
    subject_id=None,
    chapter_id=None,
    runtime_config=None,
):
    """Run a single task directly."""
    logger.info(f"Running single task: {task_id}, spider={spider_type}")

    settings = get_project_settings()
    settings.set("EXTENSIONS", {
        "starmap_scrapy.extensions.progress_reporter.ProgressReporterExtension": 200,
    }, priority="cmdline")
    for key, value in build_scrapy_setting_overrides(runtime_config or {}).items():
        settings.set(key, value, priority="cmdline")
    process = CrawlerProcess(settings)

    spider_kwargs = {"task_id": task_id, "source": source, "source_id": source_id}

    if spider_type == "github":
        if repo_url:
            spider_kwargs["repo_url"] = repo_url
        if search_query:
            spider_kwargs["search_query"] = search_query
        spider_kwargs["file_types"] = file_types
        spider_kwargs["max_depth"] = max_depth
    elif spider_type == "knowledge":
        spider_kwargs["pdf_path"] = pdf_path or ""
        spider_kwargs["subject_id"] = subject_id or ""
        spider_kwargs["chapter_id"] = chapter_id or ""

    process.crawl(spider_type, **spider_kwargs)
    process.start()


def main():
    parser = argparse.ArgumentParser(description="408考研学习平台 Scrapy Service")
    parser.add_argument("--mode", choices=["consumer", "single"], default="consumer")
    parser.add_argument("--spider", choices=list(SUPPORTED_SPIDERS), default="github")
    parser.add_argument("--source", default="github")
    parser.add_argument("--task-id", default="manual_task")
    parser.add_argument("--source-id", default=None)
    parser.add_argument("--repo-url", default=None, help="GitHub repo URL")
    parser.add_argument("--search-query", default=None, help="GitHub search query")
    parser.add_argument("--file-types", default="pdf", help="Comma-separated file types")
    parser.add_argument("--max-depth", type=int, default=5, help="Max directory depth")
    parser.add_argument("--pdf-path", default=None)
    parser.add_argument("--subject-id", default=None)
    parser.add_argument("--chapter-id", default=None)
    parser.add_argument(
        "--runtime-config-json",
        default=os.getenv("CRAWLER_RUNTIME_CONFIG_JSON"),
        help="JSON crawler runtime settings snapshot",
    )

    args = parser.parse_args()

    if args.mode == "consumer":
        start_task_consumer()
    else:
        try:
            runtime_config = parse_runtime_config(args.runtime_config_json)
        except (json.JSONDecodeError, ValueError) as exc:
            parser.error(f"invalid --runtime-config-json: {exc}")
        run_single_task(
            task_id=args.task_id,
            spider_type=args.spider,
            source=args.source,
            source_id=args.source_id,
            repo_url=args.repo_url,
            search_query=args.search_query,
            file_types=args.file_types,
            max_depth=args.max_depth,
            pdf_path=args.pdf_path,
            subject_id=args.subject_id,
            chapter_id=args.chapter_id,
            runtime_config=runtime_config,
        )


if __name__ == "__main__":
    main()
