from types import SimpleNamespace

import pytest

from app.modules.retrieval import segment_factory as segment_factory_module
from app.modules.retrieval.segment_factory import SegmentDraft, SegmentFactory


def test_knowledge_drafts_include_summary_aliases_and_structured_metadata():
    knowledge_point = SimpleNamespace(
        id="knowledge-1",
        title="进程调度",
        content="调度算法正文",
        summary="比较周转时间与响应时间",
        topic_terms=["时间片"],
        aliases=["CPU 调度"],
        tags=["操作系统"],
        difficulty="medium",
        exam_frequency="high",
        source_document_id="document-1",
        subject_id="subject-1",
    )

    drafts = SegmentFactory().build_knowledge_drafts(
        [knowledge_point],
        {"knowledge-1": ["chapter-1"]},
    )

    assert [draft.segment_type for draft in drafts] == ["title", "content"]
    assert drafts[0].embedding_text == "进程调度 时间片 CPU 调度"
    assert drafts[0].payload_extra["aliases"] == ["CPU 调度"]
    assert drafts[1].embedding_text == (
        "进程调度\n\n比较周转时间与响应时间\n\n调度算法正文"
    )
    assert drafts[1].sparse_text == "进程调度 时间片 调度算法正文"
    assert drafts[1].chapter_ids == ["chapter-1"]


def test_short_answer_options_do_not_create_option_segment():
    question = _question(
        type="short_answer",
        options=[
            {"key": "A", "text": "寄存器 A"},
            {"key": "B", "text": "寄存器 B"},
        ],
    )

    drafts = SegmentFactory().build_question_drafts([question], {})

    assert [draft.segment_type for draft in drafts] == ["title"]


def test_choice_drafts_preserve_filter_payload_and_option_labels():
    question = _question(
        type="choice",
        explanation="队首位置由队尾和长度反推。",
        options=[
            {"key": "A", "text": "rear-length"},
            {"label": "B", "text": "(rear-length+m) MOD m"},
        ],
    )

    drafts = SegmentFactory().build_question_drafts(
        [question],
        {"question-1": ["chapter-1"]},
    )

    assert [draft.segment_type for draft in drafts] == [
        "title",
        "explanation",
        "option",
    ]
    assert drafts[2].content_text == (
        "A. rear-length\nB. (rear-length+m) MOD m"
    )
    assert drafts[2].payload_extra["exam_year"] == 2024
    assert drafts[2].payload_extra["question_type"] == "choice"
    assert drafts[2].payload_extra["chapter_ids"] == ["chapter-1"]
    assert drafts[2].metadata_json["knowledge_point_ids"] == ["knowledge-1"]


def test_chapter_drafts_prefer_enhanced_description_in_semantic_context():
    chapter = SimpleNamespace(
        id="chapter-1",
        name="数据结构",
        keywords=["线性表"],
        aliases=["DS"],
        enhanced_description="重点考查复杂度分析。",
        description="考试大纲原文。",
        level=1,
        outline_code="1",
        subject_id="subject-1",
    )

    drafts = SegmentFactory().build_chapter_drafts([chapter])

    assert [draft.segment_type for draft in drafts] == ["title", "content"]
    assert drafts[0].embedding_text == "数据结构 线性表 DS"
    assert drafts[1].embedding_text == (
        "数据结构\n\n重点考查复杂度分析。\n\n考试大纲原文。"
    )
    assert drafts[1].payload_extra["entity_type"] == "canonical_chapter"


def test_materialize_assigns_ids_and_merges_payload(monkeypatch):
    monkeypatch.setattr(segment_factory_module, "_gen_id", lambda: "segment-1")
    monkeypatch.setattr(
        segment_factory_module,
        "_gen_qdrant_id",
        lambda: "point-1",
    )
    draft = SegmentDraft(
        entity_type="question",
        entity_id="question-1",
        segment_type="title",
        content_text="题干",
        embedding_text="题干",
        subject_id="subject-1",
        chapter_ids=["chapter-1"],
        payload_extra={
            "subject_id": "subject-1",
            "chapter_ids": ["chapter-1"],
            "content_preview": "题干",
        },
    )

    artifacts = SegmentFactory().materialize(
        [draft],
        [[0.1, 0.2]],
        entity_label="题目",
    )

    assert artifacts.segments[0].id == "segment-1"
    assert artifacts.segments[0].qdrant_point_id == "point-1"
    assert artifacts.qdrant_points[0].id == "point-1"
    assert artifacts.qdrant_points[0].payload == {
        "segment_id": "segment-1",
        "entity_id": "question-1",
        "segment_type": "title",
        "subject_id": "subject-1",
        "chapter_ids": ["chapter-1"],
        "content_preview": "题干",
    }


def test_materialize_rejects_embedding_count_mismatch():
    draft = SegmentDraft(
        entity_type="canonical_chapter",
        entity_id="chapter-1",
        segment_type="title",
        content_text="数据结构",
        embedding_text="数据结构",
    )

    with pytest.raises(
        RuntimeError,
        match="大纲章节 embedding 数量不匹配: expected=1, actual=0",
    ):
        SegmentFactory().materialize(
            [draft],
            [],
            entity_label="大纲章节",
        )


def _question(**overrides):
    values = {
        "id": "question-1",
        "content": "循环队列的队首位置是（ ）。",
        "question_no": "1",
        "type": "choice",
        "options": None,
        "explanation": None,
        "exam_year": 2024,
        "exam_scope": "408",
        "source": "2024 真题",
        "paper_name": "试卷",
        "difficulty": "medium",
        "tags": ["数据结构"],
        "answer_source": "extracted",
        "knowledge_point_ids": ["knowledge-1"],
        "subject_id": "subject-1",
        "source_document_id": "document-1",
        "topic_terms": ["循环队列"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)
