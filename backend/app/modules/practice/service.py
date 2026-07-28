"""Practice domain service shared by HTTP entrypoints and Agent workflows."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import Question
from app.modules.agent.models import AgentRun

from .models import PracticeSession, PracticeSessionQuestion


class PracticeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_agent_draft(
        self,
        *,
        run_id: str,
        user_id: str,
        title: str,
        questions: list[dict[str, Any]],
        duration_seconds: int = 1500,
    ) -> PracticeSession:
        """Idempotently freeze workflow questions into a user-owned draft session."""
        existing = await self.db.scalar(
            select(PracticeSession).where(PracticeSession.agent_run_id == run_id)
        )
        if existing is not None:
            return existing

        run = await self.db.scalar(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.user_id == user_id,
            )
        )
        if run is None:
            raise ValueError("Agent Run 不存在或不属于当前用户")
        if not questions:
            raise ValueError("练习草稿至少需要一道题")

        candidate_ids = [
            str(item.get("entity_id") or "").strip()
            for item in questions
            if not (item.get("question_meta") or {}).get("generated")
            and str(item.get("entity_id") or "").strip()
        ]
        stored_questions = {
            item.id: item
            for item in (
                (
                    await self.db.scalars(
                        select(Question).where(Question.id.in_(candidate_ids))
                    )
                ).all()
                if candidate_ids
                else []
            )
        }
        session = PracticeSession(
            id=uuid.uuid4().hex,
            user_id=user_id,
            source_document_id=None,
            source_type="agent",
            agent_thread_id=run.thread_id,
            agent_run_id=run.id,
            mode="practice",
            title=title[:255] or "Agent 专项练习",
            status="draft",
            duration_seconds=duration_seconds,
            question_count=len(questions),
            total_score=len(questions),
            started_at=None,
        )
        self.db.add(session)
        await self.db.flush()

        for order_no, item in enumerate(questions, start=1):
            meta = item.get("question_meta") or {}
            original_id = str(item.get("entity_id") or "").strip()
            stored = stored_questions.get(original_id)
            question_id = stored.id if stored is not None else None
            source_type = "agent_generated" if meta.get("generated") else "question_bank"
            if source_type == "question_bank" and stored is None:
                raise ValueError("题库候选已失效，请重新生成练习")
            snapshot = {
                "type": stored.type if stored else meta.get("question_type") or "choice",
                "content": stored.content if stored else item.get("content_text") or item.get("entity_title") or "",
                "options": list(stored.options or []) if stored else list(meta.get("options") or []),
                "answer": stored.answer if stored else meta.get("answer"),
                "explanation": stored.explanation if stored else meta.get("explanation"),
                "source": stored.source if stored else meta.get("source") or (item.get("source") or {}).get("title"),
                "question_no": stored.question_no if stored else meta.get("question_no"),
                "chapter_id": (stored.primary_chapter_id or stored.chapter_id) if stored else meta.get("chapter_id"),
                "answer_source": stored.answer_source if stored else meta.get("answer_source"),
                "explanation_source": stored.explanation_source if stored else meta.get("explanation_source"),
                "topic_terms": list(stored.topic_terms or []) if stored else list(meta.get("topic_terms") or ([meta["topic"]] if meta.get("topic") else [])),
                "tags": list(stored.tags or []) if stored else list(meta.get("tags") or []),
                "knowledge_point_ids": list(stored.knowledge_point_ids or []) if stored else list(meta.get("knowledge_point_ids") or []),
                "difficulty": stored.difficulty if stored else meta.get("difficulty"),
                "provenance": {
                    "source_type": source_type,
                    "agent_run_id": run.id,
                    "original_entity_id": original_id or None,
                },
            }
            self.db.add(
                PracticeSessionQuestion(
                    item_id=uuid.uuid4().hex,
                    session_id=session.id,
                    question_id=question_id,
                    source_type=source_type,
                    order_no=order_no,
                    max_score=1,
                    snapshot_json=snapshot,
                )
            )
        await self.db.flush()
        return session
