from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.retrieval import chapter_scope_retrieval


@pytest.mark.asyncio
async def test_expand_chapter_scope_includes_parent_and_siblings():
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _scalars_result(
                    [SimpleNamespace(id="chapter-1", parent_id="parent-1")]
                ),
                _scalars_result(["chapter-1", "chapter-2"]),
            ]
        )
    )

    result = await chapter_scope_retrieval.expand_chapter_scope(
        db,
        ["chapter-1"],
        upward_levels=0,
    )

    assert set(result) == {"chapter-1", "chapter-2", "parent-1"}
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_retrieve_by_chapters_groups_direct_link_rows_without_duplicates():
    question = SimpleNamespace(
        id="question-1",
        content="题干",
        question_no="1",
        exam_year=2024,
    )
    knowledge_point = SimpleNamespace(
        id="knowledge-1",
        title="循环队列",
        summary="队首和队尾下标计算",
    )
    chapters = [
        SimpleNamespace(
            id="chapter-1",
            name="线性表",
            level=2,
            outline_code="1.1",
        ),
        SimpleNamespace(
            id="chapter-2",
            name="队列",
            level=2,
            outline_code="1.2",
        ),
    ]
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _rows_result(
                    [
                        (question, "chapter-1"),
                        (question, "chapter-1"),
                        (question, "chapter-2"),
                    ]
                ),
                _rows_result(
                    [
                        (knowledge_point, "chapter-1"),
                        (knowledge_point, "chapter-1"),
                    ]
                ),
                _scalars_result(chapters),
            ]
        )
    )

    result = await chapter_scope_retrieval.retrieve_by_chapters(
        db,
        ["chapter-1", "chapter-1", "chapter-2"],
        expand_to_siblings=False,
        exclude_question_id="question-focus",
    )

    question_query = db.execute.await_args_list[0].args[0]
    compiled_question_query = str(
        question_query.compile(compile_kwargs={"literal_binds": True})
    )
    assert "questions.id != 'question-focus'" in compiled_question_query
    assert result["primary_chapters"] == [
        {"id": "chapter-1", "name": "线性表", "level": 2},
        {"id": "chapter-2", "name": "队列", "level": 2},
    ]
    assert result["questions_by_chapter"] == {
        "chapter-1": [
            {
                "id": "question-1",
                "content": "题干",
                "question_no": "1",
                "exam_year": 2024,
            }
        ],
        "chapter-2": [
            {
                "id": "question-1",
                "content": "题干",
                "question_no": "1",
                "exam_year": 2024,
            }
        ],
    }
    assert result["knowledge_points_by_chapter"] == {
        "chapter-1": [
            {
                "id": "knowledge-1",
                "title": "循环队列",
                "summary": "队首和队尾下标计算",
            }
        ]
    }


@pytest.mark.asyncio
async def test_retrieve_by_question_deduplicates_chapters_and_excludes_itself(
    monkeypatch,
):
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=_scalars_result(
                ["chapter-1", "chapter-1", "chapter-2"]
            )
        )
    )
    retrieve = AsyncMock(return_value={"questions_by_chapter": {}})
    monkeypatch.setattr(
        chapter_scope_retrieval,
        "retrieve_by_chapters",
        retrieve,
    )

    result = await chapter_scope_retrieval.retrieve_by_question(
        db,
        "question-1",
        expand_to_siblings=False,
        expand_upward_levels=2,
    )

    assert result == {"questions_by_chapter": {}}
    retrieve.assert_awaited_once_with(
        db,
        chapter_ids=["chapter-1", "chapter-2"],
        expand_to_siblings=False,
        expand_upward_levels=2,
        exclude_question_id="question-1",
    )


@pytest.mark.asyncio
async def test_empty_chapter_scope_returns_empty_groups_without_queries():
    db = SimpleNamespace(execute=AsyncMock())

    result = await chapter_scope_retrieval.retrieve_by_chapters(
        db,
        [],
    )

    assert result == {
        "primary_chapters": [],
        "all_chapters": [],
        "questions_by_chapter": {},
        "knowledge_points_by_chapter": {},
    }
    db.execute.assert_not_awaited()


def _scalars_result(items):
    return SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=items),
            )
        )
    )


def _rows_result(rows):
    return SimpleNamespace(all=Mock(return_value=rows))
