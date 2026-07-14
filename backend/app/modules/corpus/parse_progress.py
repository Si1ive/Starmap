"""MinerU parse progress extraction and persistence."""

import asyncio
import logging
import re
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import ParseRun

logger = get_logger(__name__)

MINERU_LOGGER_NAMES = ("", "mineru", "magic_pdf")
MINERU_PROGRESS_PATTERNS = (
    re.compile(r"batch\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s*/\s*(\d+)\s*pages", re.IGNORECASE),
    re.compile(r"page[^\d]{0,6}(\d+)\s*/\s*(\d+)", re.IGNORECASE),
)
MINERU_TOTAL_PAGES_PATTERN = re.compile(
    r"total_pages[=:\s]+(\d+)",
    re.IGNORECASE,
)


def extract_mineru_progress(
    message: str,
    known_total_pages: Optional[int] = None,
) -> Optional[tuple[Optional[int], Optional[int]]]:
    """Extract current and total pages from a MinerU log message."""
    lower = message.lower()
    if "page" not in lower and "batch" not in lower:
        return None

    total_pages = known_total_pages
    total_match = MINERU_TOTAL_PAGES_PATTERN.search(message)
    if total_match:
        total_pages = int(total_match.group(1))

    for pattern in MINERU_PROGRESS_PATTERNS:
        match = pattern.search(message)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None, total_pages


class MinerUProgressHandler(logging.Handler):
    """Persist embedded MinerU page progress from log records."""

    def __init__(
        self,
        run_id: str,
        db_session: AsyncSession,
        loop: asyncio.AbstractEventLoop,
    ):
        super().__init__()
        self.run_id = run_id
        self.db = db_session
        self.loop = loop
        self.last_update_time = 0
        self.update_interval = 2.0
        self.total_pages: Optional[int] = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            progress = extract_mineru_progress(
                record.getMessage(),
                self.total_pages,
            )
            if progress is None:
                return

            current_page, total_pages = progress
            if total_pages:
                self.total_pages = total_pages
            if current_page is None:
                return

            now = time.time()
            if now - self.last_update_time < self.update_interval:
                return
            self.last_update_time = now

            asyncio.run_coroutine_threadsafe(
                self._update_progress(current_page, total_pages),
                self.loop,
            )
        except Exception as exc:
            logger.warning(f"MinerU progress handler error: {exc}")

    async def _update_progress(
        self,
        current_page: int,
        total_pages: Optional[int],
    ) -> None:
        try:
            run = await self.db.get(ParseRun, self.run_id)
            if not run:
                return
            run.current_page = current_page
            if total_pages:
                run.total_pages = total_pages
                run.stage_detail = f"正在解析第 {current_page}/{total_pages} 页..."
            else:
                run.stage_detail = f"正在解析第 {current_page} 页..."
            await self.db.commit()
        except Exception as exc:
            logger.warning(f"Failed to update parse progress: {exc}")


def attach_mineru_progress_handler(
    run_id: str,
    db_session: AsyncSession,
    loop: asyncio.AbstractEventLoop,
) -> MinerUProgressHandler:
    """Attach a shared handler to supported embedded MinerU logger names."""
    handler = MinerUProgressHandler(run_id, db_session, loop)
    handler.setLevel(logging.DEBUG)
    for logger_name in MINERU_LOGGER_NAMES:
        logging.getLogger(logger_name).addHandler(handler)
    return handler


def detach_mineru_progress_handler(handler: MinerUProgressHandler) -> None:
    """Detach a previously attached embedded MinerU progress handler."""
    for logger_name in MINERU_LOGGER_NAMES:
        logging.getLogger(logger_name).removeHandler(handler)


__all__ = [
    "MINERU_LOGGER_NAMES",
    "MinerUProgressHandler",
    "attach_mineru_progress_handler",
    "detach_mineru_progress_handler",
    "extract_mineru_progress",
]
