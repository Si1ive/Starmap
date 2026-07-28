"""Real user-bound mock exams, review history, coverage stats, and focus timers."""

import re
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import CanonicalChapter, CorpusFile, Document, Question
from app.modules.identity.dependencies import (
    require_csrf_session,
    require_current_session,
)
from app.modules.identity.session import AuthenticatedSession
from app.modules.practice.models import (
    PracticeAnswer,
    PracticeSession,
    PracticeSessionQuestion,
    StudyTimerRecord,
)

router = APIRouter(prefix="/app/practice", tags=["用户模拟考试"])


class CreatePracticeSessionRequest(BaseModel):
    document_id: str
    mode: Literal["mock_exam", "practice"] = "mock_exam"
    question_count: int = Field(20, ge=1, le=100)
    duration_seconds: int = Field(7200, ge=60, le=21600)


class SavePracticeAnswerRequest(BaseModel):
    answer: str = Field("", max_length=20000)
    time_spent_seconds: int = Field(0, ge=0, le=21600)
    expected_version: int = Field(0, ge=0)


class RequestPracticeHintRequest(BaseModel):
    level: Literal["direction", "concept", "method"]
    expected_version: int = Field(0, ge=0)


class StartTimerRequest(BaseModel):
    phase: Literal["focus", "rest"]
    planned_seconds: int = Field(..., ge=60, le=7200)
    context: Optional[dict] = None


class CompleteTimerRequest(BaseModel):
    actual_seconds: int = Field(..., ge=0, le=21600)


def _visible_document(user_id: object):
    return and_(
        or_(CorpusFile.owner_user_id.is_(None), CorpusFile.owner_user_id == user_id),
        CorpusFile.deleted_at.is_(None),
        CorpusFile.retrieval_enabled.is_(True),
    )


def _normalize_answer(value: str) -> str:
    compact = re.sub(r"\s+", "", value or "").strip().upper()
    if re.fullmatch(r"[A-Z][.、:：]?.*", compact):
        return compact[:1]
    aliases = {"正确": "TRUE", "对": "TRUE", "错误": "FALSE", "错": "FALSE"}
    return aliases.get(compact, compact)


def _assert_answer_version(
    answer: PracticeAnswer | None, expected_version: int
) -> None:
    current_version = answer.version if answer is not None else 0
    if current_version != expected_version:
        raise HTTPException(
            status_code=409,
            detail="答案已在其他设备更新，请选择使用服务器答案或覆盖保存",
        )


def _practice_hint(snapshot: dict, level: str) -> str:
    if level == "direction":
        return "先标出题目的已知条件、求解目标和容易忽略的限制，再决定使用哪类方法。"
    if level == "concept":
        terms = [
            str(item).strip()
            for item in snapshot.get("topic_terms") or []
            if str(item).strip()
        ]
        if terms:
            return f"优先回忆这些核心概念：{'、'.join(terms[:4])}。"
        return "回忆这道题所属章节的核心定义、适用条件和常见反例。"
    question_type = str(snapshot.get("type") or "")
    if question_type in {"single_choice", "multiple_choice", "choice", "judge"}:
        return "逐项检验选项是否满足全部条件；先排除违反定义或边界条件的项。"
    return "先写出解题步骤和每一步依据，再代入条件检查结论是否完整。"


async def _owned_session(
    db: AsyncSession, session_id: str, user_id: object, *, lock: bool = False
) -> PracticeSession:
    query = select(PracticeSession).where(
        PracticeSession.id == session_id, PracticeSession.user_id == user_id
    )
    if lock:
        query = query.with_for_update()
    session = await db.scalar(query)
    if not session:
        raise HTTPException(status_code=404, detail="练习记录不存在")
    return session


async def _submit(db: AsyncSession, session: PracticeSession) -> None:
    if session.status == "submitted":
        return
    rows = (
        await db.execute(
            select(PracticeSessionQuestion, Question, PracticeAnswer)
            .join(Question, Question.id == PracticeSessionQuestion.question_id)
            .outerjoin(
                PracticeAnswer,
                and_(
                    PracticeAnswer.session_id == PracticeSessionQuestion.session_id,
                    PracticeAnswer.question_id == PracticeSessionQuestion.question_id,
                ),
            )
            .where(PracticeSessionQuestion.session_id == session.id)
        )
    ).all()
    awarded_total = 0
    for link, question, answer in rows:
        if answer is None:
            answer = PracticeAnswer(
                session_id=session.id,
                question_id=question.id,
                user_answer="",
                time_spent_seconds=0,
            )
            db.add(answer)
        standard_answer = str((link.snapshot_json or {}).get("answer") or "")
        is_correct = bool(_normalize_answer(answer.user_answer)) and _normalize_answer(
            answer.user_answer
        ) == _normalize_answer(standard_answer)
        answer.is_correct = is_correct
        answer.awarded_score = link.max_score if is_correct else 0
        awarded_total += answer.awarded_score
    session.status = "submitted"
    session.awarded_score = awarded_total
    session.submitted_at = datetime.utcnow()


async def _session_payload(db: AsyncSession, session: PracticeSession) -> dict:
    rows = (
        await db.execute(
            select(PracticeSessionQuestion, Question, PracticeAnswer)
            .join(Question, Question.id == PracticeSessionQuestion.question_id)
            .outerjoin(
                PracticeAnswer,
                and_(
                    PracticeAnswer.session_id == PracticeSessionQuestion.session_id,
                    PracticeAnswer.question_id == PracticeSessionQuestion.question_id,
                ),
            )
            .where(PracticeSessionQuestion.session_id == session.id)
            .order_by(PracticeSessionQuestion.order_no)
        )
    ).all()
    submitted = session.status == "submitted"
    now = datetime.utcnow()
    elapsed = int(((session.submitted_at or now) - session.started_at).total_seconds())
    return {
        "id": session.id,
        "title": session.title,
        "mode": session.mode,
        "status": session.status,
        "duration_seconds": session.duration_seconds,
        "elapsed_seconds": max(0, elapsed),
        "remaining_seconds": (
            max(0, session.duration_seconds - elapsed) if not submitted else 0
        ),
        "question_count": session.question_count,
        "total_score": session.total_score,
        "awarded_score": session.awarded_score,
        "started_at": session.started_at.isoformat(),
        "submitted_at": (
            session.submitted_at.isoformat() if session.submitted_at else None
        ),
        "questions": [
            {
                "id": question.id,
                "order_no": link.order_no,
                "type": (link.snapshot_json or {}).get("type") or question.type,
                "content": (link.snapshot_json or {}).get("content")
                or question.content,
                "options": (link.snapshot_json or {}).get("options") or [],
                "max_score": link.max_score,
                "source": (link.snapshot_json or {}).get("source"),
                "question_no": (link.snapshot_json or {}).get("question_no"),
                "chapter_id": (link.snapshot_json or {}).get("chapter_id"),
                "user_answer": answer.user_answer if answer else "",
                "version": answer.version if answer else 0,
                "hint_levels_used": answer.hint_levels_used_json if answer else [],
                "time_spent_seconds": answer.time_spent_seconds if answer else 0,
                "is_correct": answer.is_correct if submitted and answer else None,
                "awarded_score": answer.awarded_score if submitted and answer else None,
                "standard_answer": (
                    (link.snapshot_json or {}).get("answer") if submitted else None
                ),
                "explanation": (
                    (link.snapshot_json or {}).get("explanation") if submitted else None
                ),
            }
            for link, question, answer in rows
        ],
    }


@router.get("/papers", response_model=ApiResponse)
async def list_practice_papers(
    current: AuthenticatedSession = Depends(require_current_session),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(
                Document, CorpusFile, func.count(Question.id).label("question_count")
            )
            .join(CorpusFile, CorpusFile.id == Document.corpus_file_id)
            .join(Question, Question.source_document_id == Document.id)
            .where(
                _visible_document(current.user.id),
                Document.doc_type.in_(["past_exam", "mock_exam"]),
                Question.status == "active",
            )
            .group_by(Document.id, CorpusFile.id)
            .order_by(Document.exam_year.desc(), Document.created_at.desc())
        )
    ).all()
    return ApiResponse(
        data={
            "items": [
                {
                    "document_id": document.id,
                    "title": document.paper_name
                    or document.title
                    or corpus_file.file_name,
                    "year": document.exam_year,
                    "scope": document.exam_scope,
                    "question_count": count,
                    "origin": "personal" if corpus_file.owner_user_id else "platform",
                }
                for document, corpus_file, count in rows
            ]
        }
    )


@router.post(
    "/sessions/{session_id}/answers/{question_id}/hints",
    response_model=ApiResponse,
)
async def request_practice_hint(
    session_id: str,
    question_id: str,
    payload: RequestPracticeHintRequest,
    current: AuthenticatedSession = Depends(require_csrf_session),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(db, session_id, current.user.id, lock=True)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="试卷已经交卷")
    if session.mode != "practice":
        raise HTTPException(status_code=409, detail="模拟考不提供提示")
    link = await db.scalar(
        select(PracticeSessionQuestion).where(
            PracticeSessionQuestion.session_id == session.id,
            PracticeSessionQuestion.question_id == question_id,
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="题目不属于当前试卷")
    answer = await db.scalar(
        select(PracticeAnswer).where(
            PracticeAnswer.session_id == session.id,
            PracticeAnswer.question_id == question_id,
        )
    )
    _assert_answer_version(answer, payload.expected_version)
    if answer is None:
        answer = PracticeAnswer(
            session_id=session.id,
            question_id=question_id,
            version=1,
            hint_levels_used_json=[payload.level],
        )
        db.add(answer)
    else:
        used = list(answer.hint_levels_used_json or [])
        if payload.level not in used:
            used.append(payload.level)
        answer.hint_levels_used_json = used
        answer.version += 1
    await db.commit()
    return ApiResponse(
        data={
            "level": payload.level,
            "hint": _practice_hint(link.snapshot_json or {}, payload.level),
            "version": answer.version,
            "hint_levels_used": answer.hint_levels_used_json or [],
        }
    )


@router.post("/sessions", response_model=ApiResponse)
async def create_practice_session(
    payload: CreatePracticeSessionRequest,
    current: AuthenticatedSession = Depends(require_csrf_session),
    db: AsyncSession = Depends(get_db),
):
    document_row = (
        await db.execute(
            select(Document, CorpusFile)
            .join(CorpusFile, CorpusFile.id == Document.corpus_file_id)
            .where(
                Document.id == payload.document_id, _visible_document(current.user.id)
            )
        )
    ).one_or_none()
    if not document_row:
        raise HTTPException(status_code=404, detail="真题资料不存在或无权访问")
    document, corpus_file = document_row
    questions = list(
        (
            await db.scalars(
                select(Question)
                .where(
                    Question.source_document_id == document.id,
                    Question.status == "active",
                )
                .order_by(Question.question_no, Question.created_at)
                .limit(payload.question_count)
            )
        ).all()
    )
    if not questions:
        raise HTTPException(status_code=409, detail="这份资料还没有完成题目抽取")
    session = PracticeSession(
        id=uuid.uuid4().hex,
        user_id=current.user.id,
        source_document_id=document.id,
        mode=payload.mode,
        title=document.paper_name or document.title or corpus_file.file_name,
        duration_seconds=payload.duration_seconds,
        question_count=len(questions),
        total_score=len(questions),
    )
    db.add(session)
    for index, question in enumerate(questions, 1):
        db.add(
            PracticeSessionQuestion(
                session_id=session.id,
                question_id=question.id,
                order_no=index,
                max_score=1,
                snapshot_json={
                    "type": question.type,
                    "content": question.content,
                    "options": question.options or [],
                    "answer": question.answer,
                    "explanation": question.explanation,
                    "source": question.source,
                    "question_no": question.question_no,
                    "chapter_id": question.primary_chapter_id or question.chapter_id,
                    "answer_source": question.answer_source,
                    "explanation_source": question.explanation_source,
                    "topic_terms": question.topic_terms or [],
                    "tags": question.tags or [],
                    "knowledge_point_ids": question.knowledge_point_ids or [],
                },
            )
        )
    await db.commit()
    return ApiResponse(message="模拟考已开始", data=await _session_payload(db, session))


@router.get("/sessions/{session_id}", response_model=ApiResponse)
async def get_practice_session(
    session_id: str,
    current: AuthenticatedSession = Depends(require_current_session),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(db, session_id, current.user.id, lock=True)
    if (
        session.status == "active"
        and (datetime.utcnow() - session.started_at).total_seconds()
        >= session.duration_seconds
    ):
        await _submit(db, session)
        await db.commit()
    return ApiResponse(data=await _session_payload(db, session))


@router.put("/sessions/{session_id}/answers/{question_id}", response_model=ApiResponse)
async def save_practice_answer(
    session_id: str,
    question_id: str,
    payload: SavePracticeAnswerRequest,
    current: AuthenticatedSession = Depends(require_csrf_session),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(db, session_id, current.user.id, lock=True)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="试卷已经交卷，不能继续修改")
    if (
        datetime.utcnow() - session.started_at
    ).total_seconds() >= session.duration_seconds:
        await _submit(db, session)
        await db.commit()
        raise HTTPException(status_code=409, detail="考试时间已到，系统已经自动交卷")
    allowed = await db.scalar(
        select(PracticeSessionQuestion.id).where(
            PracticeSessionQuestion.session_id == session.id,
            PracticeSessionQuestion.question_id == question_id,
        )
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="题目不属于当前试卷")
    answer = await db.scalar(
        select(PracticeAnswer).where(
            PracticeAnswer.session_id == session.id,
            PracticeAnswer.question_id == question_id,
        )
    )
    _assert_answer_version(answer, payload.expected_version)
    if answer is None:
        answer = PracticeAnswer(
            session_id=session.id,
            question_id=question_id,
            version=1,
        )
        db.add(answer)
    else:
        answer.version += 1
    answer.user_answer = payload.answer
    answer.time_spent_seconds = payload.time_spent_seconds
    answer.saved_at = datetime.utcnow()
    await db.commit()
    return ApiResponse(
        message="答案已保存",
        data={"saved_at": answer.saved_at.isoformat(), "version": answer.version},
    )


@router.post("/sessions/{session_id}/submit", response_model=ApiResponse)
async def submit_practice_session(
    session_id: str,
    current: AuthenticatedSession = Depends(require_csrf_session),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(db, session_id, current.user.id, lock=True)
    await _submit(db, session)
    await db.commit()
    return ApiResponse(message="交卷完成", data=await _session_payload(db, session))


@router.get("/history", response_model=ApiResponse)
async def list_practice_history(
    limit: int = Query(20, ge=1, le=100),
    current: AuthenticatedSession = Depends(require_current_session),
    db: AsyncSession = Depends(get_db),
):
    sessions = list(
        (
            await db.scalars(
                select(PracticeSession)
                .where(PracticeSession.user_id == current.user.id)
                .order_by(PracticeSession.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    auto_submitted = False
    for session in sessions:
        if (
            session.status == "active"
            and (datetime.utcnow() - session.started_at).total_seconds()
            >= session.duration_seconds
        ):
            await _submit(db, session)
            auto_submitted = True
    if auto_submitted:
        await db.commit()
    return ApiResponse(
        data={
            "items": [
                {
                    "id": item.id,
                    "title": item.title,
                    "status": item.status,
                    "question_count": item.question_count,
                    "total_score": item.total_score,
                    "awarded_score": item.awarded_score,
                    "started_at": item.started_at.isoformat(),
                    "submitted_at": (
                        item.submitted_at.isoformat() if item.submitted_at else None
                    ),
                }
                for item in sessions
            ]
        }
    )


@router.get("/stats", response_model=ApiResponse)
async def get_practice_stats(
    current: AuthenticatedSession = Depends(require_current_session),
    db: AsyncSession = Depends(get_db),
):
    answered, correct, covered = (
        await db.execute(
            select(
                func.count(PracticeAnswer.id),
                func.sum(case((PracticeAnswer.is_correct.is_(True), 1), else_=0)),
                func.count(distinct(Question.primary_chapter_id)),
            )
            .join(PracticeSession, PracticeSession.id == PracticeAnswer.session_id)
            .join(Question, Question.id == PracticeAnswer.question_id)
            .where(
                PracticeSession.user_id == current.user.id,
                PracticeSession.status == "submitted",
            )
        )
    ).one()
    total_chapters = (
        await db.scalar(
            select(func.count(CanonicalChapter.id)).where(
                CanonicalChapter.status == "active"
            )
        )
        or 0
    )
    return ApiResponse(
        data={
            "answered_count": int(answered or 0),
            "correct_count": int(correct or 0),
            "covered_chapters": int(covered or 0),
            "total_chapters": int(total_chapters),
            "coverage_rate": (
                round((covered or 0) / total_chapters * 100, 1) if total_chapters else 0
            ),
        }
    )


@router.post("/timers", response_model=ApiResponse)
async def start_study_timer(
    payload: StartTimerRequest,
    current: AuthenticatedSession = Depends(require_csrf_session),
    db: AsyncSession = Depends(get_db),
):
    record = StudyTimerRecord(
        id=uuid.uuid4().hex,
        user_id=current.user.id,
        phase=payload.phase,
        planned_seconds=payload.planned_seconds,
        context_json=payload.context,
    )
    db.add(record)
    await db.commit()
    return ApiResponse(
        data={
            "id": record.id,
            "phase": record.phase,
            "started_at": record.started_at.isoformat(),
            "planned_seconds": record.planned_seconds,
        }
    )


@router.post("/timers/{timer_id}/complete", response_model=ApiResponse)
async def complete_study_timer(
    timer_id: str,
    payload: CompleteTimerRequest,
    current: AuthenticatedSession = Depends(require_csrf_session),
    db: AsyncSession = Depends(get_db),
):
    record = await db.scalar(
        select(StudyTimerRecord)
        .where(
            StudyTimerRecord.id == timer_id, StudyTimerRecord.user_id == current.user.id
        )
        .with_for_update()
    )
    if not record:
        raise HTTPException(status_code=404, detail="计时记录不存在")
    if record.status != "completed":
        record.status = "completed"
        record.actual_seconds = payload.actual_seconds
        record.completed_at = datetime.utcnow()
        await db.commit()
    return ApiResponse(
        message="计时已记录",
        data={
            "id": record.id,
            "status": record.status,
            "actual_seconds": record.actual_seconds,
        },
    )
