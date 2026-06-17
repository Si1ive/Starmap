"""
大纲（考试大纲 / 知识体系大纲）导入服务

支持的输入格式：
1. JSON：直接结构化的章节树
2. 纯文本：按编号或缩进识别层级（1. / 1.1 / 1.1.1 / 一、 / (一) / 第X章）
3. （扩展）从已解析的 PDF document_sections 转换 — 见 import_from_document

入库流程：
- 创建 exam_outlines 元信息
- 创建 canonical_chapters 树（继承 outline_id）
- 后续抽取知识点/题目时，可以传 outline_id 限定使用该大纲匹配章节
"""

import json
import re
import uuid
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    ExamOutline, CanonicalChapter, Subject, DocumentSection,
)

logger = get_logger(__name__)


def _gen_id() -> str:
    return uuid.uuid4().hex[:32]


# 编号匹配（带层级权重）
NUMBER_PATTERNS: List[Tuple[re.Pattern, int]] = [
    # 第X章/第X部分（最高级）
    (re.compile(r'^\s*第\s*[一二三四五六七八九十百千万零\d]+\s*[章部篇]'), 1),
    # 中文一、二、三
    (re.compile(r'^\s*[一二三四五六七八九十]+\s*[、.]'), 1),
    # 1.1.1 类阿拉伯数字编号
    (re.compile(r'^\s*\d+(?:\.\d+){2,}'), 3),
    (re.compile(r'^\s*\d+\.\d+'), 2),
    (re.compile(r'^\s*\d+[.、]'), 1),
    # (一) (1)
    (re.compile(r'^\s*[（(]\s*[一二三四五六七八九十]+\s*[）)]'), 2),
    (re.compile(r'^\s*[（(]\s*\d+\s*[）)]'), 3),
    # ① ② 等圆圈数字
    (re.compile(r'^\s*[①②③④⑤⑥⑦⑧⑨⑩]'), 3),
]

# 编号清理（去除编号留下纯名称）
NUMBER_STRIP_RE = re.compile(
    r'^\s*(?:'
    r'第\s*[一二三四五六七八九十百千万零\d]+\s*[章部篇]\s*[:：、.]?'
    r'|[一二三四五六七八九十]+\s*[、.]'
    r'|\d+(?:\.\d+)*\s*[、.]?'
    r'|[（(]\s*[一二三四五六七八九十\d]+\s*[）)]'
    r'|[①②③④⑤⑥⑦⑧⑨⑩]'
    r')\s*'
)


def _detect_level(line: str) -> int:
    """根据行首编号或缩进推测层级（1=一级，越大越深）"""
    stripped = line.lstrip()
    indent = len(line) - len(stripped)

    for pattern, level_hint in NUMBER_PATTERNS:
        if pattern.match(stripped):
            # 阿拉伯数字层数 = 点数 + 1
            m = re.match(r'^\s*(\d+(?:\.\d+)*)', stripped)
            if m:
                dots = m.group(1).count(".")
                return max(1, dots + 1)
            return level_hint

    # 没有编号：用缩进推（每 2 空格为一级）
    if indent >= 4:
        return 3
    if indent >= 2:
        return 2
    return 1


def _extract_outline_code(line: str) -> Optional[str]:
    """从行首抽出大纲编号（1.1.1, 一、, (一), 第一章）"""
    m = re.match(r'^\s*(\d+(?:\.\d+)*)', line)
    if m:
        return m.group(1)
    m = re.match(r'^\s*(第\s*[一二三四五六七八九十百千万零\d]+\s*[章部篇])', line)
    if m:
        return m.group(1).replace(" ", "")
    m = re.match(r'^\s*([一二三四五六七八九十]+)\s*[、.]', line)
    if m:
        return m.group(1)
    m = re.match(r'^\s*[（(]\s*([一二三四五六七八九十\d]+)\s*[）)]', line)
    if m:
        return f"({m.group(1)})"
    return None


def _strip_number(line: str) -> str:
    """剥离行首编号"""
    return NUMBER_STRIP_RE.sub("", line.strip()).strip()


def parse_outline_text(text: str) -> List[Dict[str, Any]]:
    """
    解析纯文本大纲。

    返回 chapters 树（init_chapters 接受的格式）：
    [{"name": "...", "code": "...", "children": [{...}, ...]}]
    """
    if not text or not text.strip():
        return []

    chapters_tree: List[Dict[str, Any]] = []
    # 用栈维护当前父链（栈深 = 当前层级）
    stack: List[Tuple[int, List[Dict[str, Any]]]] = [(0, chapters_tree)]

    sort_order = 0
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        if raw_line.strip().startswith("#"):  # 允许注释
            continue

        level = _detect_level(raw_line)
        outline_code = _extract_outline_code(raw_line)
        name = _strip_number(raw_line)
        if not name:
            continue

        chapter = {
            "name": name[:200],
            "outline_code": outline_code,
            "sort_order": sort_order,
            "children": [],
        }
        sort_order += 1

        # 弹出栈直到找到父层级
        while stack and stack[-1][0] >= level:
            stack.pop()

        parent_children = stack[-1][1] if stack else chapters_tree
        parent_children.append(chapter)
        stack.append((level, chapter["children"]))

    return chapters_tree


def parse_outline_json(text: str) -> List[Dict[str, Any]]:
    """JSON 格式的大纲；接受根级数组或 {"chapters": [...]}"""
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("chapters") or []
    raise ValueError("无效的 JSON 大纲格式")


def detect_format(filename: str, content: str) -> str:
    """根据文件扩展名 + 内容启发式探测格式"""
    name_lower = (filename or "").lower()
    if name_lower.endswith(".json"):
        return "json"
    if name_lower.endswith((".txt", ".md")):
        return "text"
    # 启发：以 { 或 [ 开头当 JSON
    head = content.lstrip()[:1]
    if head in "[{":
        return "json"
    return "text"


class OutlineImportService:
    """大纲导入服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def preview(self, content: str, filename: str = "") -> Dict[str, Any]:
        """解析大纲文本并返回预览（不入库）"""
        fmt = detect_format(filename, content)
        if fmt == "json":
            chapters = parse_outline_json(content)
        else:
            chapters = parse_outline_text(content)

        # 统计
        total = self._count_tree(chapters)
        max_depth = self._max_depth(chapters)

        return {
            "format": fmt,
            "total_chapters": total,
            "max_depth": max_depth,
            "chapters": chapters,
        }

    async def import_outline(
        self,
        subject_id: str,
        name: str,
        year: int,
        content: str,
        filename: str = "",
        version: str = "v1.0",
        description: Optional[str] = None,
        set_default: bool = False,
    ) -> Dict[str, Any]:
        """完整导入流程：解析 + 创建大纲 + 创建章节树"""
        subject = await self.db.get(Subject, subject_id)
        if not subject:
            raise ValueError(f"学科不存在: {subject_id}")

        preview = await self.preview(content, filename=filename)
        chapters = preview["chapters"]
        if not chapters:
            raise ValueError("解析后未发现任何章节，请检查文件格式")

        # 1) 创建大纲（按 year+version 唯一，存在则复用）
        existing_outline = (await self.db.execute(
            select(ExamOutline).where(
                ExamOutline.year == year,
                ExamOutline.version == version,
            )
        )).scalar_one_or_none()
        if existing_outline:
            outline = existing_outline
            # 更新基础信息
            outline.name = name
            outline.description = description or outline.description
            outline.status = "active"
        else:
            outline = ExamOutline(
                id=_gen_id(),
                name=name,
                year=year,
                version=version,
                description=description,
                release_date=date.today(),
                effective_date=date.today(),
                status="active",
                is_default=set_default,
            )
            self.db.add(outline)
            await self.db.flush()

        if set_default:
            # 把其他大纲的 is_default 关掉
            others = (await self.db.execute(
                select(ExamOutline).where(ExamOutline.id != outline.id, ExamOutline.is_default == True)
            )).scalars().all()
            for o in others:
                o.is_default = False
            outline.is_default = True

        # 2) 创建/更新章节树
        created, updated = await self._upsert_chapters(
            subject_id=subject_id,
            outline_id=outline.id,
            chapters=chapters,
            parent_id=None,
            level=1,
        )

        await self.db.commit()

        return {
            "outline_id": outline.id,
            "outline_name": outline.name,
            "year": outline.year,
            "version": outline.version,
            "created_chapters": created,
            "updated_chapters": updated,
            "total_chapters": preview["total_chapters"],
        }

    async def _upsert_chapters(
        self,
        subject_id: str,
        outline_id: str,
        chapters: List[Dict[str, Any]],
        parent_id: Optional[str],
        level: int,
    ) -> Tuple[int, int]:
        created = 0
        updated = 0
        for idx, data in enumerate(chapters):
            from sqlalchemy import and_, or_

            existing_q = select(CanonicalChapter).where(and_(
                CanonicalChapter.subject_id == subject_id,
                CanonicalChapter.outline_id == outline_id,
                CanonicalChapter.name == data["name"],
                CanonicalChapter.level == level,
            ))
            if parent_id:
                existing_q = existing_q.where(CanonicalChapter.parent_id == parent_id)
            else:
                existing_q = existing_q.where(CanonicalChapter.parent_id.is_(None))

            chapter = (await self.db.execute(existing_q)).scalar_one_or_none()
            if chapter:
                chapter.outline_code = data.get("outline_code") or chapter.outline_code
                chapter.code = data.get("code") or chapter.code
                chapter.aliases = data.get("aliases") or chapter.aliases
                chapter.description = data.get("description") or chapter.description
                chapter.sort_order = data.get("sort_order", idx)
                chapter.status = "active"
                updated += 1
            else:
                chapter = CanonicalChapter(
                    id=_gen_id(),
                    subject_id=subject_id,
                    outline_id=outline_id,
                    parent_id=parent_id,
                    level=level,
                    name=data["name"],
                    code=data.get("code"),
                    outline_code=data.get("outline_code"),
                    aliases=data.get("aliases"),
                    description=data.get("description"),
                    sort_order=data.get("sort_order", idx),
                    status="active",
                )
                self.db.add(chapter)
                created += 1
                await self.db.flush()

            children = data.get("children") or []
            if children:
                c, u = await self._upsert_chapters(
                    subject_id=subject_id,
                    outline_id=outline_id,
                    chapters=children,
                    parent_id=chapter.id,
                    level=level + 1,
                )
                created += c
                updated += u
        return created, updated

    async def import_from_document_sections(
        self,
        subject_id: str,
        document_id: str,
        outline_name: str,
        year: int,
        version: str = "v1.0",
        set_default: bool = False,
    ) -> Dict[str, Any]:
        """
        从已解析文档的标题树（document_sections）转换为大纲入库。
        适合用户上传 PDF 大纲文件 → 解析器跑标题树 → 一键转大纲场景。
        """
        sections = (await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start, DocumentSection.level, DocumentSection.id)
        )).scalars().all()
        if not sections:
            raise ValueError("文档没有可用的标题树，请先执行『提取标题树』")

        # 把扁平 sections 转成树
        chapters_tree: List[Dict[str, Any]] = []
        # 用栈维护父链：(level, children_list)
        stack: List[Tuple[int, List[Dict[str, Any]]]] = [(0, chapters_tree)]
        sort_order = 0
        for sec in sections:
            level = max(1, int(sec.level or 1))
            chapter = {
                "name": (sec.title or "").strip()[:200],
                "outline_code": _extract_outline_code(sec.title or ""),
                "sort_order": sort_order,
                "children": [],
            }
            sort_order += 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            (stack[-1][1] if stack else chapters_tree).append(chapter)
            stack.append((level, chapter["children"]))

        if not chapters_tree:
            raise ValueError("标题树解析后为空")

        # 转成 import_outline 同样的入库流程
        existing_outline = (await self.db.execute(
            select(ExamOutline).where(
                ExamOutline.year == year, ExamOutline.version == version
            )
        )).scalar_one_or_none()

        if existing_outline:
            outline = existing_outline
            outline.name = outline_name
            outline.status = "active"
        else:
            outline = ExamOutline(
                id=_gen_id(),
                name=outline_name,
                year=year,
                version=version,
                description=f"从文档 {document_id} 自动转换",
                release_date=date.today(),
                effective_date=date.today(),
                status="active",
                is_default=set_default,
            )
            self.db.add(outline)
            await self.db.flush()

        if set_default:
            others = (await self.db.execute(
                select(ExamOutline).where(ExamOutline.id != outline.id, ExamOutline.is_default == True)
            )).scalars().all()
            for o in others:
                o.is_default = False
            outline.is_default = True

        created, updated = await self._upsert_chapters(
            subject_id=subject_id,
            outline_id=outline.id,
            chapters=chapters_tree,
            parent_id=None,
            level=1,
        )
        await self.db.commit()

        return {
            "outline_id": outline.id,
            "created_chapters": created,
            "updated_chapters": updated,
            "total_chapters": self._count_tree(chapters_tree),
            "source_document_id": document_id,
        }

    @staticmethod
    def _count_tree(chapters: List[Dict[str, Any]]) -> int:
        n = 0
        for c in chapters:
            n += 1
            n += OutlineImportService._count_tree(c.get("children") or [])
        return n

    @staticmethod
    def _max_depth(chapters: List[Dict[str, Any]], current: int = 1) -> int:
        if not chapters:
            return 0
        return max(
            OutlineImportService._max_depth(c.get("children") or [], current + 1) or current
            for c in chapters
        )


async def list_outlines(session: AsyncSession) -> List[Dict[str, Any]]:
    rows = (await session.execute(
        select(ExamOutline).order_by(ExamOutline.year.desc(), ExamOutline.version)
    )).scalars().all()
    return [
        {
            "id": o.id,
            "name": o.name,
            "year": o.year,
            "version": o.version,
            "description": o.description,
            "status": o.status,
            "is_default": bool(o.is_default),
            "release_date": o.release_date.isoformat() if o.release_date else None,
            "effective_date": o.effective_date.isoformat() if o.effective_date else None,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in rows
    ]


async def get_outline_chapters(session: AsyncSession, outline_id: str) -> List[Dict[str, Any]]:
    """以树结构返回大纲下所有章节"""
    rows = (await session.execute(
        select(CanonicalChapter)
        .where(CanonicalChapter.outline_id == outline_id)
        .order_by(CanonicalChapter.level, CanonicalChapter.sort_order)
    )).scalars().all()

    by_id = {r.id: {
        "id": r.id,
        "name": r.name,
        "code": r.code,
        "outline_code": r.outline_code,
        "level": r.level,
        "parent_id": r.parent_id,
        "sort_order": r.sort_order,
        "children": [],
    } for r in rows}

    roots: List[Dict[str, Any]] = []
    for node in by_id.values():
        if node["parent_id"] and node["parent_id"] in by_id:
            by_id[node["parent_id"]]["children"].append(node)
        else:
            roots.append(node)
    return roots
