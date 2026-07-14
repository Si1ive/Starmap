"""将文档原生标题树转换为考试大纲章节树。"""

from typing import Any, Dict, List, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import DocumentSection
from app.modules.catalog.outline_parser import extract_outline_code


def build_outline_tree_from_sections(
    sections: Sequence[DocumentSection],
) -> List[Dict[str, Any]]:
    """按标题出现顺序和层级构建大纲章节树。"""
    chapters_tree: List[Dict[str, Any]] = []
    stack: List[Tuple[int, List[Dict[str, Any]]]] = [(0, chapters_tree)]

    for sort_order, section in enumerate(sections):
        level = max(1, int(section.level or 1))
        title = section.title or ""
        chapter = {
            "name": title.strip()[:200],
            "outline_code": extract_outline_code(title),
            "sort_order": sort_order,
            "children": [],
        }

        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_children = stack[-1][1] if stack else chapters_tree
        parent_children.append(chapter)
        stack.append((level, chapter["children"]))

    return chapters_tree


async def load_outline_tree_from_document_sections(
    session: AsyncSession,
    document_id: str,
) -> List[Dict[str, Any]]:
    """加载文档标题并转换为大纲章节树。"""
    sections = (
        await session.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(
                DocumentSection.page_start,
                DocumentSection.level,
                DocumentSection.id,
            )
        )
    ).scalars().all()
    if not sections:
        raise ValueError("文档没有可用的标题树，请先执行『提取标题树』")

    chapters_tree = build_outline_tree_from_sections(sections)
    if not chapters_tree:
        raise ValueError("标题树解析后为空")
    return chapters_tree
