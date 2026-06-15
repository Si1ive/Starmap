#!/usr/bin/env python3
"""
初始化测试数据：知识点和题目
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mysql import mysql_client
from app.models.mysql_models import Subject, Chapter, KnowledgePoint, Question
from sqlalchemy import select
import uuid


async def init_knowledge_points(db):
    """初始化知识点测试数据"""

    # 获取所有学科和章节
    subjects = (await db.execute(select(Subject).where(Subject.status == "active"))).scalars().all()

    if not subjects:
        print("⚠️  没有找到学科数据，请先初始化学科")
        return 0

    count = 0
    for subject in subjects[:2]:  # 只为前两个学科添加数据
        chapters = (await db.execute(
            select(Chapter).where(
                Chapter.subject_id == subject.id,
                Chapter.status == "active"
            ).limit(3)
        )).scalars().all()

        for chapter in chapters:
            # 为每个章节创建 2-3 个知识点
            for i in range(2):
                kp = KnowledgePoint(
                    id=f"kp_{uuid.uuid4().hex[:12]}",
                    subject_id=subject.id,
                    chapter_id=chapter.id,
                    title=f"{chapter.name} - 知识点 {i+1}",
                    content=f"""
## {chapter.name} - 知识点 {i+1}

### 基本概念
这是关于{chapter.name}的第{i+1}个知识点的详细说明。

### 核心要点
1. 要点一：理解基本原理
2. 要点二：掌握应用场景
3. 要点三：注意常见问题

### 重点内容
- 定义和特性
- 使用方法
- 常见误区

### 考试要求
- 理解基本概念
- 能够应用到实际问题
- 掌握相关算法

### 示例
```
示例代码或图示
```
                    """.strip(),
                    difficulty=["easy", "medium", "hard"][i % 3],
                    exam_frequency=["low", "medium", "high"][i % 3],
                    tags=[subject.name, chapter.name, "核心知识点"],
                    key_points=[
                        "理解基本概念",
                        "掌握应用场景",
                        "注意常见错误"
                    ],
                    source=f"《{subject.name}考研复习指南》",
                    source_page=f"第{10 + i*5}页",
                    status="active"
                )
                db.add(kp)
                count += 1

    await db.commit()
    print(f"✓ 创建了 {count} 个知识点")
    return count


async def init_questions(db):
    """初始化题目测试数据"""

    # 获取所有学科和章节
    subjects = (await db.execute(select(Subject).where(Subject.status == "active"))).scalars().all()

    if not subjects:
        print("⚠️  没有找到学科数据，请先初始化学科")
        return 0

    # 获取知识点
    kps = (await db.execute(select(KnowledgePoint).limit(10))).scalars().all()
    kp_ids = [kp.id for kp in kps] if kps else []

    count = 0
    question_types = [
        ("choice", "选择题"),
        ("fill", "填空题"),
        ("judge", "判断题"),
        ("short_answer", "简答题"),
    ]

    for subject in subjects[:2]:  # 只为前两个学科添加数据
        chapters = (await db.execute(
            select(Chapter).where(
                Chapter.subject_id == subject.id,
                Chapter.status == "active"
            ).limit(3)
        )).scalars().all()

        for chapter in chapters:
            # 为每个章节创建不同类型的题目
            for q_idx, (qtype, type_name) in enumerate(question_types):

                if qtype == "choice":
                    # 选择题
                    question = Question(
                        id=f"q_{uuid.uuid4().hex[:12]}",
                        subject_id=subject.id,
                        chapter_id=chapter.id,
                        type=qtype,
                        content=f"关于{chapter.name}，下列说法正确的是（）",
                        options=[
                            {"key": "A", "text": "选项 A 的内容"},
                            {"key": "B", "text": "选项 B 的内容"},
                            {"key": "C", "text": "选项 C 的内容"},
                            {"key": "D", "text": "选项 D 的内容"},
                        ],
                        answer="B",
                        explanation=f"正确答案是 B。{chapter.name}的核心特点是...",
                        difficulty=["easy", "medium", "hard"][q_idx % 3],
                        source="历年真题",
                        exam_year=2020 + q_idx,
                        knowledge_point_ids=kp_ids[:2] if kp_ids else [],
                        tags=[subject.name, chapter.name, type_name],
                        status="active"
                    )

                elif qtype == "fill":
                    # 填空题
                    question = Question(
                        id=f"q_{uuid.uuid4().hex[:12]}",
                        subject_id=subject.id,
                        chapter_id=chapter.id,
                        type=qtype,
                        content=f"{chapter.name}的基本定义是______，其主要特点包括______。",
                        options=None,
                        answer="定义内容；特点1、特点2",
                        explanation=f"本题考查{chapter.name}的基本概念...",
                        difficulty=["easy", "medium", "hard"][q_idx % 3],
                        source="模拟题",
                        exam_year=2021 + q_idx,
                        knowledge_point_ids=kp_ids[:1] if kp_ids else [],
                        tags=[subject.name, chapter.name, type_name],
                        status="active"
                    )

                elif qtype == "judge":
                    # 判断题
                    question = Question(
                        id=f"q_{uuid.uuid4().hex[:12]}",
                        subject_id=subject.id,
                        chapter_id=chapter.id,
                        type=qtype,
                        content=f"{chapter.name}具有某某特性。（）",
                        options=None,
                        answer="正确",
                        explanation=f"该说法正确。{chapter.name}确实具有这个特性...",
                        difficulty=["easy", "medium", "hard"][q_idx % 3],
                        source="练习题",
                        exam_year=None,
                        knowledge_point_ids=kp_ids[:1] if kp_ids else [],
                        tags=[subject.name, chapter.name, type_name],
                        status="active"
                    )

                else:
                    # 简答题
                    question = Question(
                        id=f"q_{uuid.uuid4().hex[:12]}",
                        subject_id=subject.id,
                        chapter_id=chapter.id,
                        type=qtype,
                        content=f"请简述{chapter.name}的基本原理及其应用场景。",
                        options=None,
                        answer=f"""
1. 基本原理：{chapter.name}是指...
2. 主要特点：包括...
3. 应用场景：适用于...
4. 注意事项：需要注意...
                        """.strip(),
                        explanation=f"本题考查{chapter.name}的综合理解能力...",
                        difficulty=["easy", "medium", "hard"][q_idx % 3],
                        source="历年真题",
                        exam_year=2022,
                        knowledge_point_ids=kp_ids[:3] if kp_ids else [],
                        tags=[subject.name, chapter.name, type_name],
                        status="active"
                    )

                db.add(question)
                count += 1

    await db.commit()
    print(f"✓ 创建了 {count} 个题目")
    return count


async def main():
    """主函数"""
    print("=" * 60)
    print("初始化 408 考研平台测试数据")
    print("=" * 60)

    async with mysql_client.session() as db:
        # 检查现有数据
        subject_count = await db.scalar(
            select(Subject).where(Subject.status == "active")
        )
        if not subject_count:
            print("⚠️  请先运行 init_408_data.py 初始化学科和章节数据")
            return

        # 初始化知识点
        print("\n1. 初始化知识点...")
        kp_count = await init_knowledge_points(db)

        # 初始化题目
        print("\n2. 初始化题目...")
        q_count = await init_questions(db)

        print("\n" + "=" * 60)
        print("✅ 测试数据初始化完成")
        print(f"   - 知识点：{kp_count} 个")
        print(f"   - 题目：{q_count} 个")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
