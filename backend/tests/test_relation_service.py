"""Knowledge relation rule detector tests."""

from types import SimpleNamespace

import pytest

from app.modules.retrieval.relation_detector import KnowledgeRelationDetector


def make_knowledge_point(
    title: str,
    *,
    content: str = "",
    topic_terms: list[str] | None = None,
    chapter_id: str | None = None,
):
    return SimpleNamespace(
        title=title,
        content=content,
        topic_terms=topic_terms,
        primary_chapter_id=chapter_id,
    )


def test_relation_string_similarity_keeps_existing_jaccard_behavior():
    detector = KnowledgeRelationDetector()

    assert detector.string_similarity("进程调度", "进程调度") == 1.0
    assert detector.string_similarity("", "进程调度") == 0.0
    assert 0 < detector.string_similarity("进程调度", "进程管理") < 1


def test_relation_detector_links_unrelated_terms_only_within_same_chapter():
    detector = KnowledgeRelationDetector()
    first = make_knowledge_point("栈", chapter_id="chapter-1")
    second = make_knowledge_point("队列", chapter_id="chapter-1")

    assert detector.detect(first, second) == [
        ("similar_to", 0.5, "同一章节", "both")
    ]
    second.primary_chapter_id = "chapter-2"
    assert detector.detect(first, second) == []


def test_relation_detector_identifies_confusion_and_contrast_rules():
    detector = KnowledgeRelationDetector()
    first = make_knowledge_point(
        "进程调度算法",
        content="比较不同调度策略的响应时间。",
        topic_terms=["调度"],
    )
    second = make_knowledge_point(
        "进程调度方法",
        topic_terms=["调度"],
    )

    relations = detector.detect(first, second)

    assert [relation[0] for relation in relations] == [
        "common_confusion",
        "contrast_with",
    ]
    assert all(relation[3] == "both" for relation in relations)


def test_relation_detector_preserves_prerequisite_direction():
    detector = KnowledgeRelationDetector()
    target = make_knowledge_point(
        "进程调度",
        content="学习进程调度需要先了解进程状态。",
        topic_terms=["进程"],
    )
    prerequisite = make_knowledge_point(
        "进程状态",
        topic_terms=["进程"],
    )

    assert detector.detect(target, prerequisite) == [
        (
            "prerequisite",
            0.7,
            "内容提到需要先了解: 进程状态",
            "backward",
        )
    ]


def test_relation_detector_falls_back_to_shared_term_similarity():
    detector = KnowledgeRelationDetector()
    first = make_knowledge_point(
        "栈",
        topic_terms=["线性结构", "存储"],
    )
    second = make_knowledge_point(
        "队列",
        topic_terms=["线性结构", "存储"],
    )

    relations = detector.detect(first, second)

    assert len(relations) == 1
    assert relations[0][0] == "similar_to"
    assert relations[0][1] == pytest.approx(0.7)
    assert relations[0][3] == "both"
