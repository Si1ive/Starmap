from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.infrastructure.ai.llm_client import OutlineLLMClient
from app.modules.catalog.outline_guidance_service import OutlineGuidanceService
from app.modules.catalog.outline_llm_runtime import load_outline_llm_client
from app.modules.operations.settings_service import SystemSettingsService


def _single_result(item):
    return SimpleNamespace(scalar_one_or_none=Mock(return_value=item))


def _multiple_result(items):
    return SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=items),
            )
        )
    )


def _chapter(chapter_id: str, name: str):
    return SimpleNamespace(
        id=chapter_id,
        outline_code=chapter_id,
        name=name,
        description=f"{name}考点",
        exam_guidance=None,
    )


@pytest.mark.asyncio
async def test_generate_guidance_updates_dict_and_list_responses_in_batches():
    link = SimpleNamespace(
        exam_objective="掌握核心概念",
        guidance_status="pending",
    )
    chapters = [
        _chapter("chapter-1", "线性表"),
        _chapter("chapter-2", "树"),
        _chapter("chapter-3", "图"),
    ]
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _single_result(link),
                _multiple_result(chapters),
            ]
        ),
        commit=AsyncMock(),
    )
    client = SimpleNamespace(
        is_available=True,
        chat=AsyncMock(
            side_effect=[
                '{"guidance":{"chapter-1":" 先掌握定义 ","chapter-2":"练习遍历"}}',
                '[{"id":"chapter-3","guidance":"掌握图算法"}]',
            ]
        ),
    )

    result = await OutlineGuidanceService(db, client=client).generate_for_subject(
        "outline-1",
        "subject-1",
        batch_size=2,
    )

    assert result == {
        "outline_id": "outline-1",
        "subject_id": "subject-1",
        "guidance_status": "done",
        "updated_chapters": 3,
        "total_chapters": 3,
    }
    assert [chapter.exam_guidance for chapter in chapters] == [
        "先掌握定义",
        "练习遍历",
        "掌握图算法",
    ]
    assert client.chat.await_count == 2
    assert all(
        call.kwargs["purpose"] == "大纲章节复习指导生成"
        for call in client.chat.await_args_list
    )
    assert db.commit.await_count == 4


@pytest.mark.asyncio
async def test_generate_guidance_keeps_successful_batches_when_later_batch_fails():
    link = SimpleNamespace(exam_objective="", guidance_status="pending")
    chapters = [
        _chapter("chapter-1", "进程"),
        _chapter("chapter-2", "内存"),
    ]
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _single_result(link),
                _multiple_result(chapters),
            ]
        ),
        commit=AsyncMock(),
    )
    client = SimpleNamespace(
        is_available=True,
        chat=AsyncMock(
            side_effect=[
                '{"guidance":{"chapter-1":"掌握状态转换"}}',
                RuntimeError("上游超时"),
            ]
        ),
    )

    result = await OutlineGuidanceService(db, client=client).generate_for_subject(
        "outline-1",
        "subject-1",
        batch_size=1,
    )

    assert result["guidance_status"] == "done"
    assert result["updated_chapters"] == 1
    assert chapters[0].exam_guidance == "掌握状态转换"
    assert chapters[1].exam_guidance is None
    assert link.guidance_status == "done"


@pytest.mark.asyncio
async def test_generate_guidance_marks_all_failed_batches_as_failed():
    link = SimpleNamespace(exam_objective="", guidance_status="pending")
    chapters = [_chapter("chapter-1", "网络层")]
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _single_result(link),
                _multiple_result(chapters),
            ]
        ),
        commit=AsyncMock(),
    )
    client = SimpleNamespace(
        is_available=True,
        chat=AsyncMock(return_value='{"unexpected":true}'),
    )

    result = await OutlineGuidanceService(db, client=client).generate_for_subject(
        "outline-1",
        "subject-1",
    )

    assert result["guidance_status"] == "failed"
    assert result["updated_chapters"] == 0
    assert link.guidance_status == "failed"


@pytest.mark.asyncio
async def test_load_outline_llm_client_uses_outline_settings(monkeypatch):
    load = AsyncMock(
        return_value={
            "outline_llm": {
                "enabled": True,
                "api_key": "test-key",
                "model": "test-model",
                "max_tokens": 4096,
            }
        }
    )
    monkeypatch.setattr(SystemSettingsService, "load", load)

    client = await load_outline_llm_client(SimpleNamespace())

    assert isinstance(client, OutlineLLMClient)
    assert client.is_available is True
    assert client.max_tokens == 4096
    load.assert_awaited_once()
