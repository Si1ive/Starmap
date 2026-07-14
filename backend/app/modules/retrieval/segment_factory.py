"""检索 Segment 的文本、元数据和 Qdrant payload 构造。"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from qdrant_client.models import PointStruct

from app.models.mysql_models import RetrievalSegment


CHOICE_QUESTION_TYPES = {
    "choice",
    "single_choice",
    "multi_choice",
    "multiple_choice",
}


def _gen_id() -> str:
    return uuid.uuid4().hex[:32]


def _gen_qdrant_id() -> str:
    return str(uuid.uuid4())


@dataclass(slots=True)
class SegmentDraft:
    """尚未分配 ID 和向量的检索单元草稿。"""

    entity_type: str
    entity_id: str
    segment_type: str
    content_text: str
    embedding_text: str
    document_id: Optional[str] = None
    content_md: Optional[str] = None
    sparse_text: Optional[str] = None
    context_text: Optional[str] = None
    subject_id: Optional[str] = None
    chapter_ids: List[str] = field(default_factory=list)
    topic_terms: Optional[List[str]] = None
    metadata_json: Optional[Dict[str, Any]] = None
    payload_extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SegmentArtifacts:
    """可直接交给 SegmentStore 双写的实体和向量点。"""

    segments: List[RetrievalSegment]
    qdrant_points: List[PointStruct]


class SegmentFactory:
    """按实体类型构造 Segment 草稿并物化存储对象。"""

    def build_knowledge_drafts(
        self,
        knowledge_points: Sequence[Any],
        chapter_map: Mapping[str, List[str]],
    ) -> List[SegmentDraft]:
        drafts: List[SegmentDraft] = []

        for knowledge_point in knowledge_points:
            chapter_ids = chapter_map.get(knowledge_point.id, [])
            metadata = {
                "difficulty": knowledge_point.difficulty,
                "tags": knowledge_point.tags or [],
                "aliases": knowledge_point.aliases or [],
                "exam_frequency": knowledge_point.exam_frequency,
            }

            title_text = knowledge_point.title
            if knowledge_point.topic_terms:
                title_text += " " + " ".join(knowledge_point.topic_terms)
            if knowledge_point.aliases:
                title_text += " " + " ".join(knowledge_point.aliases)

            drafts.append(
                SegmentDraft(
                    entity_type="knowledge_point",
                    entity_id=knowledge_point.id,
                    document_id=knowledge_point.source_document_id,
                    segment_type="title",
                    content_text=title_text,
                    content_md=f"# {knowledge_point.title}",
                    sparse_text=title_text,
                    embedding_text=title_text,
                    subject_id=knowledge_point.subject_id,
                    chapter_ids=chapter_ids,
                    topic_terms=knowledge_point.topic_terms,
                    metadata_json=metadata,
                    payload_extra={
                        "subject_id": knowledge_point.subject_id,
                        "chapter_ids": chapter_ids,
                        "topic_terms": knowledge_point.topic_terms or [],
                        "content_preview": title_text[:200],
                        **metadata,
                    },
                )
            )

            if knowledge_point.content:
                summary = getattr(knowledge_point, "summary", None)
                summary_prefix = f"{summary}\n\n" if summary else ""
                context_text = (
                    f"{knowledge_point.title}\n\n"
                    f"{summary_prefix}{knowledge_point.content}"
                )
                drafts.append(
                    SegmentDraft(
                        entity_type="knowledge_point",
                        entity_id=knowledge_point.id,
                        document_id=knowledge_point.source_document_id,
                        segment_type="content",
                        content_text=knowledge_point.content,
                        content_md=knowledge_point.content,
                        sparse_text=self.build_sparse_text(
                            knowledge_point.title,
                            knowledge_point.content,
                            knowledge_point.topic_terms,
                        ),
                        context_text=context_text,
                        embedding_text=context_text,
                        subject_id=knowledge_point.subject_id,
                        chapter_ids=chapter_ids,
                        topic_terms=knowledge_point.topic_terms,
                        metadata_json=metadata,
                        payload_extra={
                            "subject_id": knowledge_point.subject_id,
                            "chapter_ids": chapter_ids,
                            "topic_terms": knowledge_point.topic_terms or [],
                            "content_preview": knowledge_point.content[:200],
                            **metadata,
                        },
                    )
                )

        return drafts

    def build_chapter_drafts(
        self,
        chapters: Sequence[Any],
    ) -> List[SegmentDraft]:
        drafts: List[SegmentDraft] = []

        for chapter in chapters:
            chapter_ids = [chapter.id]
            metadata = {
                "level": chapter.level,
                "outline_code": chapter.outline_code,
                "aliases": chapter.aliases or [],
            }

            title_text = chapter.name
            if chapter.keywords:
                title_text += " " + " ".join(chapter.keywords)
            if chapter.aliases:
                title_text += " " + " ".join(chapter.aliases)

            payload_extra = {
                "entity_type": "canonical_chapter",
                "subject_id": chapter.subject_id,
                "chapter_ids": chapter_ids,
            }
            drafts.append(
                SegmentDraft(
                    entity_type="canonical_chapter",
                    entity_id=chapter.id,
                    segment_type="title",
                    content_text=title_text,
                    content_md=f"# {chapter.name}",
                    sparse_text=title_text,
                    embedding_text=title_text,
                    subject_id=chapter.subject_id,
                    chapter_ids=chapter_ids,
                    metadata_json=metadata,
                    payload_extra=payload_extra,
                )
            )

            if chapter.enhanced_description or chapter.description:
                content_parts = [
                    text
                    for text in (
                        chapter.enhanced_description,
                        chapter.description,
                    )
                    if text
                ]
                content_text = "\n\n".join(content_parts)
                context_text = f"{chapter.name}\n\n{content_text}"
                drafts.append(
                    SegmentDraft(
                        entity_type="canonical_chapter",
                        entity_id=chapter.id,
                        segment_type="content",
                        content_text=content_text,
                        content_md=content_text,
                        sparse_text=f"{chapter.name} {content_text}",
                        context_text=context_text,
                        embedding_text=context_text,
                        subject_id=chapter.subject_id,
                        chapter_ids=chapter_ids,
                        metadata_json=metadata,
                        payload_extra=payload_extra,
                    )
                )

        return drafts

    def build_question_drafts(
        self,
        questions: Sequence[Any],
        chapter_map: Mapping[str, List[str]],
    ) -> List[SegmentDraft]:
        drafts: List[SegmentDraft] = []

        for question in questions:
            chapter_ids = chapter_map.get(question.id, [])
            metadata = {
                "exam_year": question.exam_year or 0,
                "exam_scope": question.exam_scope,
                "source": question.source,
                "paper_name": question.paper_name,
                "difficulty": question.difficulty,
                "question_type": question.type,
                "tags": question.tags or [],
                "answer_source": question.answer_source,
                "knowledge_point_ids": question.knowledge_point_ids or [],
            }
            payload_extra = {
                "subject_id": question.subject_id,
                "chapter_ids": chapter_ids,
                "topic_terms": question.topic_terms or [],
                "exam_year": metadata["exam_year"],
                "exam_scope": metadata["exam_scope"],
                "difficulty": metadata["difficulty"],
                "question_type": metadata["question_type"],
                "tags": metadata["tags"],
                "answer_source": metadata["answer_source"],
            }

            title_text = question.content or ""
            if question.question_no:
                title_text = f"[{question.question_no}] {title_text}"

            drafts.append(
                SegmentDraft(
                    entity_type="question",
                    entity_id=question.id,
                    document_id=question.source_document_id,
                    segment_type="title",
                    content_text=title_text,
                    sparse_text=title_text,
                    embedding_text=title_text,
                    subject_id=question.subject_id,
                    chapter_ids=chapter_ids,
                    topic_terms=question.topic_terms,
                    metadata_json=metadata,
                    payload_extra={
                        **payload_extra,
                        "content_preview": title_text[:200],
                    },
                )
            )

            if question.explanation:
                context_text = f"{title_text}\n\n解析：{question.explanation}"
                drafts.append(
                    SegmentDraft(
                        entity_type="question",
                        entity_id=question.id,
                        document_id=question.source_document_id,
                        segment_type="explanation",
                        content_text=question.explanation,
                        sparse_text=self.build_sparse_text(
                            title_text,
                            question.explanation,
                            question.topic_terms,
                        ),
                        context_text=context_text,
                        embedding_text=context_text,
                        subject_id=question.subject_id,
                        chapter_ids=chapter_ids,
                        topic_terms=question.topic_terms,
                        metadata_json=metadata,
                        payload_extra={
                            **payload_extra,
                            "content_preview": question.explanation[:200],
                        },
                    )
                )

            if question.options and question.type in CHOICE_QUESTION_TYPES:
                option_text = "\n".join(
                    (
                        f"{option.get('key') or option.get('label') or option.get('option_label') or ''}. "
                        f"{option.get('text', '')}"
                    )
                    for option in question.options
                    if isinstance(option, dict)
                )
                if option_text:
                    drafts.append(
                        SegmentDraft(
                            entity_type="question",
                            entity_id=question.id,
                            document_id=question.source_document_id,
                            segment_type="option",
                            content_text=option_text,
                            sparse_text=option_text,
                            embedding_text=option_text,
                            subject_id=question.subject_id,
                            chapter_ids=chapter_ids,
                            topic_terms=question.topic_terms,
                            metadata_json=metadata,
                            payload_extra={
                                **payload_extra,
                                "content_preview": option_text[:200],
                            },
                        )
                    )

        return drafts

    def materialize(
        self,
        drafts: Sequence[SegmentDraft],
        embeddings: Sequence[List[float]],
        *,
        entity_label: str,
    ) -> SegmentArtifacts:
        if len(embeddings) != len(drafts):
            raise RuntimeError(
                f"{entity_label} embedding 数量不匹配: "
                f"expected={len(drafts)}, actual={len(embeddings)}"
            )

        segments: List[RetrievalSegment] = []
        qdrant_points: List[PointStruct] = []
        for draft, vector in zip(drafts, embeddings):
            segment_id = _gen_id()
            qdrant_point_id = _gen_qdrant_id()
            segments.append(
                RetrievalSegment(
                    id=segment_id,
                    entity_type=draft.entity_type,
                    entity_id=draft.entity_id,
                    document_id=draft.document_id,
                    segment_type=draft.segment_type,
                    content_text=draft.content_text,
                    content_md=draft.content_md,
                    sparse_text=draft.sparse_text,
                    context_text=draft.context_text,
                    subject_id=draft.subject_id,
                    chapter_ids=draft.chapter_ids,
                    topic_terms=draft.topic_terms,
                    metadata_json=draft.metadata_json,
                    qdrant_point_id=qdrant_point_id,
                )
            )
            qdrant_points.append(
                PointStruct(
                    id=qdrant_point_id,
                    vector=vector,
                    payload={
                        "segment_id": segment_id,
                        "entity_id": draft.entity_id,
                        "segment_type": draft.segment_type,
                        **draft.payload_extra,
                    },
                )
            )

        return SegmentArtifacts(
            segments=segments,
            qdrant_points=qdrant_points,
        )

    @staticmethod
    def build_sparse_text(
        title: str,
        content: str,
        topic_terms: Optional[List[str]],
    ) -> str:
        parts = [title]
        if topic_terms:
            parts.extend(topic_terms)
        if content:
            parts.append(content[:500])
        return " ".join(parts)
