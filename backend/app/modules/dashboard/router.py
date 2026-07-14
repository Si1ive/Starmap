"""后台数据看板路由。"""

from datetime import datetime, time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import (
    Chapter,
    ChatSession,
    KnowledgePoint,
    Question,
    Subject,
)

router = APIRouter(prefix="/admin", tags=["后台管理"])


@router.get("/dashboard/stats", response_model=ApiResponse)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """获取 408 学习平台的核心数量统计。"""
    subject_count = (
        await db.scalar(
            select(func.count())
            .select_from(Subject)
            .where(Subject.status == "active")
        )
        or 0
    )
    chapter_count = (
        await db.scalar(
            select(func.count())
            .select_from(Chapter)
            .where(Chapter.status == "active")
        )
        or 0
    )
    knowledge_point_count = (
        await db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.status != "deleted")
        )
        or 0
    )
    question_count = (
        await db.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.status != "deleted")
        )
        or 0
    )
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    today_chat_count = (
        await db.scalar(
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.created_at >= today_start)
        )
        or 0
    )

    return ApiResponse(
        code=200,
        message="success",
        data={
            "subject_count": subject_count,
            "chapter_count": chapter_count,
            "knowledge_point_count": knowledge_point_count,
            "question_count": question_count,
            "today_chat_count": today_chat_count,
        },
    )


@router.get("/dashboard/charts", response_model=ApiResponse)
async def get_dashboard_charts(db: AsyncSession = Depends(get_db)):
    """获取学科、难度和题型分布。"""
    subject_rows = await db.execute(
        select(Subject.name, func.count(KnowledgePoint.id))
        .outerjoin(KnowledgePoint, Subject.id == KnowledgePoint.subject_id)
        .where(Subject.status == "active")
        .group_by(Subject.id, Subject.name)
        .order_by(Subject.sort_order)
    )
    subject_distribution = [
        {"name": row[0], "value": row[1] or 0} for row in subject_rows
    ]

    difficulty_rows = await db.execute(
        select(KnowledgePoint.difficulty, func.count())
        .where(KnowledgePoint.status != "deleted")
        .group_by(KnowledgePoint.difficulty)
    )
    difficulty_name_map = {"easy": "简单", "medium": "中等", "hard": "困难"}
    difficulty_distribution = [
        {"name": difficulty_name_map.get(difficulty, difficulty), "value": count}
        for difficulty, count in difficulty_rows
    ]

    type_rows = await db.execute(
        select(Question.type, func.count())
        .where(Question.status != "deleted")
        .group_by(Question.type)
    )
    type_name_map = {
        "choice": "选择题",
        "fill": "填空题",
        "judge": "判断题",
        "short_answer": "简答题",
        "design": "设计题",
        "analysis": "分析题",
    }
    question_type_distribution = [
        {"name": type_name_map.get(question_type, question_type), "value": count}
        for question_type, count in type_rows
    ]

    return ApiResponse(
        code=200,
        message="success",
        data={
            "subject_distribution": subject_distribution,
            "difficulty_distribution": difficulty_distribution,
            "question_type_distribution": question_type_distribution,
        },
    )
