import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.corpus import parse_progress
from app.modules.corpus.document_parse_service import (
    MinerUProgressHandler as CompatibilityMinerUProgressHandler,
)
from app.modules.corpus.parse_progress import (
    MinerUProgressHandler,
    attach_mineru_progress_handler,
    detach_mineru_progress_handler,
    extract_mineru_progress,
)


def test_extract_mineru_progress_from_batch_and_page_logs():
    assert extract_mineru_progress(
        "Pipeline processing window batch 2/11: 2/11 pages"
    ) == (2, 11)
    assert extract_mineru_progress("processing page 4/9") == (4, 9)
    assert extract_mineru_progress("ordinary parser log") is None


def test_extract_mineru_progress_keeps_total_page_discovery():
    assert extract_mineru_progress("multi-file run. total_pages=13, window_size=1") == (
        None,
        13,
    )
    assert extract_mineru_progress(
        "processing started for page assets",
        known_total_pages=13,
    ) == (None, 13)


@pytest.mark.asyncio
async def test_progress_handler_persists_page_progress():
    run = SimpleNamespace(
        current_page=0,
        total_pages=None,
        stage_detail=None,
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=run),
        commit=AsyncMock(),
    )
    handler = MinerUProgressHandler(
        "run-1",
        db,
        asyncio.get_running_loop(),
    )

    await handler._update_progress(3, 10)

    assert run.current_page == 3
    assert run.total_pages == 10
    assert run.stage_detail == "正在解析第 3/10 页..."
    db.commit.assert_awaited_once()


def test_progress_handler_attach_and_detach_all_mineru_loggers():
    handler = attach_mineru_progress_handler(
        "run-1",
        Mock(),
        Mock(),
    )
    target_loggers = [
        logging.getLogger(name) for name in parse_progress.MINERU_LOGGER_NAMES
    ]

    try:
        assert all(
            handler in target_logger.handlers for target_logger in target_loggers
        )
    finally:
        detach_mineru_progress_handler(handler)

    assert all(
        handler not in target_logger.handlers for target_logger in target_loggers
    )


def test_document_parse_service_keeps_progress_handler_compatibility_export():
    assert CompatibilityMinerUProgressHandler is MinerUProgressHandler
