"""Tests for chat retrieval context and citation construction."""

import pytest

from app.modules.chat.retrieval_context import build_retrieval_context


def test_build_retrieval_context_includes_outline_and_traceable_source():
    context_parts, sources = build_retrieval_context({
        "outline_expansion": {
            "matched_chapters": [
                {"name": "进程管理"},
                {"name": "处理机调度"},
            ],
        },
        "results": [{
            "entity_type": "question",
            "entity_id": "question-30",
            "context_text": "第30题及其选项和解析",
            "content_text": "第30题：选择正确选项。",
            "score": 0.91,
            "source": {
                "document_id": "document-1",
                "filename": "操作系统真题.pdf",
                "page_no": 12,
            },
        }],
    })

    assert context_parts == [
        "[大纲定位] 用户问题涉及考点: 进程管理, 处理机调度",
        "[1] [来源: 操作系统真题.pdf 第12页]\n第30题及其选项和解析",
    ]
    assert len(sources) == 1
    assert sources[0].type == "question"
    assert sources[0].entity_id == "question-30"
    assert sources[0].document_id == "document-1"
    assert sources[0].url == "/practice?question_id=question-30"
    assert sources[0].score == pytest.approx(0.91)


def test_build_retrieval_context_deduplicates_sources_but_keeps_context():
    result = {
        "results": [
            {
                "entity_type": "knowledge_point",
                "entity_id": "knowledge-1",
                "context_text": "上下文一",
                "content_text": "知识点一",
                "source": {"document_id": "document-1"},
            },
            {
                "entity_type": "knowledge_point",
                "entity_id": "knowledge-1",
                "context_text": "上下文二",
                "content_text": "知识点一的补充",
                "source": {"document_id": "document-1"},
            },
        ],
    }

    context_parts, sources = build_retrieval_context(result)

    assert context_parts == ["[1]\n上下文一", "[2]\n上下文二"]
    assert len(sources) == 1
    assert sources[0].title == "知识点"
    assert sources[0].url == "/knowledge/knowledge-1"


def test_build_retrieval_context_handles_document_only_and_invalid_items():
    context_parts, sources = build_retrieval_context({
        "results": [
            None,
            {
                "context_text": "文档片段",
                "source": {
                    "document_id": "document-1",
                    "filename": "教材.pdf",
                },
            },
            {
                "context_text": "无追溯标识的片段",
                "source": None,
            },
        ],
    })

    assert context_parts == [
        "[2] [来源: 教材.pdf]\n文档片段",
        "[3]\n无追溯标识的片段",
    ]
    assert len(sources) == 1
    assert sources[0].type == "document"
    assert sources[0].title == "教材.pdf"
    assert sources[0].document_id == "document-1"
