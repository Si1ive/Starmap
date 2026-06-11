"""
文档原生标题树提取服务

从解析后的 document_blocks 中提取标题层级，生成 document_sections 记录。
"""

import re
import uuid
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import Document, DocumentBlock, DocumentSection

logger = get_logger(__name__)

# 常见标题模式
HEADING_PATTERNS = [
    # 第X章 / 第X节 / 第X部分
    re.compile(r'^第[一二三四五六七八九十百千\d]+[章节目部]'),
    # 数字编号：1. / 1.1 / 1.1.1
    re.compile(r'^\d+(\.\d+)*\.?\s'),
    # 罗马数字：I. / II. / III.
    re.compile(r'^[IVXLC]+\.?\s'),
    # 中文数字：一、 / 二、 / （一）
    re.compile(r'^[一二三四五六七八九十]+[、.．]'),
    re.compile(r'^[（(][一二三四五六七八九十]+[）)]'),
    # 章节关键词
    re.compile(r'^(Chapter|Section|Part)\s+\d+', re.IGNORECASE),
]

# 标题层级关键词
LEVEL_KEYWORDS = {
    1: ['章', 'chapter', 'part', '部分'],
    2: ['节', 'section', '模块'],
    3: ['点', '小节', 'subsection'],
}


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


def _detect_heading_level(text: str, block_type: str) -> Optional[int]:
    """
    检测标题层级

    Returns:
        层级数 (1, 2, 3...) 或 None 表示不是标题
    """
    text = text.strip()
    if not text:
        return None

    # 如果 block_type 已经是 title/heading，优先使用
    if block_type in ('title', 'heading'):
        # 根据内容判断层级
        # 第X章 -> level 1
        if re.match(r'^第[一二三四五六七八九十百千\d]+章', text):
            return 1
        # 第X节 -> level 2
        if re.match(r'^第[一二三四五六七八九十百千\d]+节', text):
            return 2
        # 数字编号：1. -> level 1, 1.1 -> level 2, 1.1.1 -> level 3
        match = re.match(r'^(\d+(?:\.\d+)*)\.?\s', text)
        if match:
            parts = match.group(1).split('.')
            return len(parts)
        # 罗马数字 -> level 1
        if re.match(r'^[IVXLC]+\.?\s', text):
            return 1
        # 中文数字：一、 -> level 1
        if re.match(r'^[一二三四五六七八九十]+[、.．]', text):
            return 1
        # 中文数字：（一） -> level 2
        if re.match(r'^[（(][一二三四五六七八九十]+[）)]', text):
            return 2
        # 默认为 level 1
        return 1

    # 对于 paragraph 类型，检查是否包含标题模式
    if block_type == 'paragraph':
        for pattern in HEADING_PATTERNS:
            if pattern.match(text):
                # 根据模式判断层级
                if re.match(r'^第[一二三四五六七八九十百千\d]+章', text):
                    return 1
                if re.match(r'^第[一二三四五六七八九十百千\d]+节', text):
                    return 2
                match = re.match(r'^(\d+(?:\.\d+)*)\.?\s', text)
                if match:
                    parts = match.group(1).split('.')
                    return len(parts)
                return 1
        # 检查是否是短文本且包含章节关键词（可能是标题但未被正确标记）
        if len(text) < 100:
            for level, keywords in LEVEL_KEYWORDS.items():
                for kw in keywords:
                    if kw in text.lower():
                        return level

    return None


def _build_section_path(sections: List[Dict[str, Any]], current_level: int, current_title: str) -> str:
    """
    构建 section_path

    例如：第1章 > 1.1 > 1.1.1
    """
    path_parts = []

    # 找到父级
    for i in range(len(sections) - 1, -1, -1):
        if sections[i]['level'] < current_level:
            path_parts.insert(0, sections[i]['title'])
            current_level = sections[i]['level']
            if current_level == 1:
                break

    path_parts.append(current_title)
    return ' > '.join(path_parts)


class DocumentSectionService:
    """文档原生标题树提取服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def extract_sections(self, document_id: str) -> Dict[str, Any]:
        """
        从文档的 blocks 中提取标题树

        Args:
            document_id: 文档ID

        Returns:
            提取结果统计
        """
        # 1. 获取文档信息
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        # 2. 获取所有 blocks，按页码和顺序排列
        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = blocks_result.scalars().all()

        if not blocks:
            logger.warning("文档没有 blocks", document_id=document_id)
            return {"sections_count": 0, "message": "文档没有 blocks"}

        # 3. 删除旧的 sections
        await self.db.execute(
            delete(DocumentSection).where(DocumentSection.document_id == document_id)
        )

        # 4. 提取标题并构建树
        sections_data: List[Dict[str, Any]] = []
        pending_sections: List[Dict[str, Any]] = []  # 用于构建层级关系

        for block in blocks:
            text = block.content_text or block.content_md or ""
            level = _detect_heading_level(text, block.block_type)

            if level is not None:
                section_id = generate_id()
                section_path = _build_section_path(pending_sections, level, text.strip())

                section_data = {
                    'id': section_id,
                    'document_id': document_id,
                    'level': level,
                    'title': text.strip()[:500],  # 限制长度
                    'section_path': section_path[:1000],
                    'page_start': block.page_no,
                    'block_start_id': block.id,
                    'parent_id': None,
                }

                # 找到父节点
                for i in range(len(pending_sections) - 1, -1, -1):
                    if pending_sections[i]['level'] < level:
                        section_data['parent_id'] = pending_sections[i]['id']
                        break

                # 更新 pending_sections
                # 移除同级和更深层级的节点
                while pending_sections and pending_sections[-1]['level'] >= level:
                    # 设置 page_end 和 block_end_id
                    popped = pending_sections.pop()
                    popped['page_end'] = block.page_no
                    popped['block_end_id'] = block.id

                pending_sections.append(section_data)
                sections_data.append(section_data)

        # 5. 设置最后的 section 的 page_end
        if pending_sections and blocks:
            last_block = blocks[-1]
            for section in pending_sections:
                if section.get('page_end') is None:
                    section['page_end'] = last_block.page_no
                    section['block_end_id'] = last_block.id

        # 6. 持久化 sections
        for section_data in sections_data:
            section = DocumentSection(
                id=section_data['id'],
                document_id=section_data['document_id'],
                parent_id=section_data.get('parent_id'),
                level=section_data['level'],
                title=section_data['title'],
                section_path=section_data['section_path'],
                page_start=section_data.get('page_start'),
                page_end=section_data.get('page_end'),
                block_start_id=section_data.get('block_start_id'),
                block_end_id=section_data.get('block_end_id'),
            )
            self.db.add(section)

        await self.db.commit()

        logger.info(
            "文档标题树提取完成",
            document_id=document_id,
            sections_count=len(sections_data),
        )

        return {
            "document_id": document_id,
            "sections_count": len(sections_data),
            "sections": [
                {
                    "id": s['id'],
                    "level": s['level'],
                    "title": s['title'],
                    "section_path": s['section_path'],
                    "page_start": s.get('page_start'),
                    "page_end": s.get('page_end'),
                    "parent_id": s.get('parent_id'),
                }
                for s in sections_data
            ],
        }

    async def get_section_tree(self, document_id: str) -> List[Dict[str, Any]]:
        """
        获取文档的 section 树形结构

        Returns:
            树形结构的 section 列表
        """
        result = await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start, DocumentSection.id)
        )
        sections = result.scalars().all()

        if not sections:
            return []

        # 构建树形结构
        section_map = {s.id: self._section_to_dict(s) for s in sections}
        root_sections = []

        for section in sections:
            node = section_map[section.id]
            if section.parent_id and section.parent_id in section_map:
                parent = section_map[section.parent_id]
                if 'children' not in parent:
                    parent['children'] = []
                parent['children'].append(node)
            else:
                root_sections.append(node)

        return root_sections

    async def get_sections_flat(self, document_id: str) -> List[Dict[str, Any]]:
        """
        获取文档的 section 平面列表

        Returns:
            平面结构的 section 列表
        """
        result = await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start, DocumentSection.id)
        )
        sections = result.scalars().all()

        return [self._section_to_dict(s) for s in sections]

    def _section_to_dict(self, section: DocumentSection) -> Dict[str, Any]:
        return {
            "id": section.id,
            "document_id": section.document_id,
            "parent_id": section.parent_id,
            "level": section.level,
            "title": section.title,
            "section_path": section.section_path,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "block_start_id": section.block_start_id,
            "block_end_id": section.block_end_id,
            "confidence": float(section.confidence) if section.confidence else None,
            "created_at": section.created_at.isoformat() if section.created_at else None,
        }
