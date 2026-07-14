from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.outline_llm_import_service import OutlineLLMImportService


def _single_result(item):
    return SimpleNamespace(scalar_one_or_none=Mock(return_value=item))


class _NestedTransaction:
    def __init__(self):
        self.exit_errors = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_errors.append(exc)
        return False


@pytest.mark.asyncio
async def test_llm_import_counts_runtime_subject_failure_as_partial(
    monkeypatch,
):
    transactions = []

    def begin_nested():
        transaction = _NestedTransaction()
        transactions.append(transaction)
        return transaction

    db = SimpleNamespace(
        add=Mock(),
        flush=AsyncMock(),
        execute=AsyncMock(return_value=_single_result(None)),
        commit=AsyncMock(),
        begin_nested=Mock(side_effect=begin_nested),
    )
    service = OutlineLLMImportService(db)
    service.persistence.upsert_outline_meta = AsyncMock(
        return_value=SimpleNamespace(
            id="outline-1",
            name="2026 年大纲",
            year=2026,
            version="v1.0",
        )
    )
    service.persistence.upsert_chapters = AsyncMock(
        side_effect=[
            (2, 0),
            RuntimeError("章节唯一键冲突"),
        ]
    )
    monkeypatch.setattr(
        "app.modules.retrieval.segment_service."
        "SegmentService.build_canonical_chapter_segments",
        AsyncMock(return_value={"segments_count": 2}),
    )

    result = await service.import_result(
        llm_result={
            "subjects": [
                {
                    "subject_id": "subject-1",
                    "subject_name": "数据结构",
                    "chapters": [{"name": "线性表"}],
                },
                {
                    "subject_id": "subject-2",
                    "subject_name": "操作系统",
                    "chapters": [{"name": "进程管理"}],
                },
            ]
        },
        name="2026 年大纲",
        year=2026,
    )

    run = db.add.call_args_list[0].args[0]
    assert result["partial"] is True
    assert result["successful_subjects"] == 1
    assert result["failed_subjects"] == 1
    assert run.status == "partial"
    assert run.processed_subjects == 2
    assert run.successful_subjects == 1
    assert run.created_chapters == 2
    assert len(transactions) == 3
    assert len(transactions[2].exit_errors) == 1
    assert str(transactions[2].exit_errors[0]) == "章节唯一键冲突"


@pytest.mark.asyncio
async def test_llm_import_rolls_back_outline_when_all_runtime_writes_fail(
    monkeypatch,
):
    transactions = []

    def begin_nested():
        transaction = _NestedTransaction()
        transactions.append(transaction)
        return transaction

    db = SimpleNamespace(
        add=Mock(),
        flush=AsyncMock(),
        execute=AsyncMock(return_value=_single_result(None)),
        commit=AsyncMock(),
        begin_nested=Mock(side_effect=begin_nested),
    )
    service = OutlineLLMImportService(db)
    service.persistence.upsert_outline_meta = AsyncMock(
        return_value=SimpleNamespace(
            id="outline-1",
            name="2026 年大纲",
            year=2026,
            version="v1.0",
        )
    )
    service.persistence.upsert_chapters = AsyncMock(
        side_effect=RuntimeError("章节写入失败")
    )
    build_segments = AsyncMock()
    monkeypatch.setattr(
        "app.modules.retrieval.segment_service."
        "SegmentService.build_canonical_chapter_segments",
        build_segments,
    )

    with pytest.raises(ValueError, match="所有科目入库均失败"):
        await service.import_result(
            llm_result={
                "subjects": [
                    {
                        "subject_id": "subject-1",
                        "subject_name": "数据结构",
                        "chapters": [{"name": "线性表"}],
                    }
                ]
            },
            name="2026 年大纲",
            year=2026,
        )

    run = db.add.call_args_list[0].args[0]
    assert run.status == "failed"
    assert run.outline_id is None
    assert run.processed_subjects == 1
    assert run.successful_subjects == 0
    assert run.created_chapters == 0
    assert run.result_summary["subjects"][0]["status"] == "failed"
    assert len(transactions) == 2
    assert isinstance(transactions[0].exit_errors[0], Exception)
    build_segments.assert_not_awaited()
