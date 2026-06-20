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
    ExamOutline, CanonicalChapter, Subject, DocumentSection, ExamOutlineSubject,
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
                chapter.enhanced_description = data.get("enhanced_description") or chapter.enhanced_description
                chapter.keywords = data.get("keywords") or chapter.keywords
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
                    enhanced_description=data.get("enhanced_description"),
                    keywords=data.get("keywords"),
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

    async def _load_document_sections_tree(self, document_id: str) -> List[Dict[str, Any]]:
        """
        读取文档标题树（document_sections）并转成 chapters 树。

        大纲走的是「标题树」这条路（document_section_service 的规则提取），
        与题目抽取的「题干/选项分离 + LLM 兜底」机制完全不同。
        """
        sections = (await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start, DocumentSection.level, DocumentSection.id)
        )).scalars().all()
        if not sections:
            raise ValueError("文档没有可用的标题树，请先执行『提取标题树』")

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
        return chapters_tree

    async def preview_from_document_sections(self, document_id: str) -> Dict[str, Any]:
        """预览文档标题树转成的大纲章节树（不入库）。"""
        chapters_tree = await self._load_document_sections_tree(document_id)
        return {
            "format": "document_sections",
            "total_chapters": self._count_tree(chapters_tree),
            "max_depth": self._max_depth(chapters_tree),
            "chapters": chapters_tree,
        }

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
        chapters_tree = await self._load_document_sections_tree(document_id)

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

    async def _upsert_outline_meta(
        self, name: str, year: int, version: str,
        description: Optional[str], set_default: bool,
    ) -> ExamOutline:
        """按 year+version upsert 大纲元信息，处理 is_default 互斥。"""
        outline = (await self.db.execute(
            select(ExamOutline).where(
                ExamOutline.year == year, ExamOutline.version == version
            )
        )).scalar_one_or_none()
        if outline:
            outline.name = name
            outline.description = description or outline.description
            outline.status = "active"
        else:
            outline = ExamOutline(
                id=_gen_id(), name=name, year=year, version=version,
                description=description,
                release_date=date.today(), effective_date=date.today(),
                status="active", is_default=set_default,
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
        return outline

    async def import_from_llm_result(
        self,
        llm_result: Dict[str, Any],
        name: str,
        year: int,
        version: str = "v1.0",
        description: Optional[str] = None,
        set_default: bool = False,
    ) -> Dict[str, Any]:
        """
        把 OutlineLLMService.split_outline 的多门课结果整体入库。

        llm_result: {"subjects": [{subject_id, subject_name, exam_objective,
                                    chapters: [...], error?: str}]}
        - upsert ExamOutline
        - 每门课 upsert 一条 exam_outline_subjects（存考察目标）
        - 每门课章节树挂到对应 subject_id + outline_id（description 一并入库）

        重要改进：
        - 如果某个科目有 error 字段或 chapters 为空，跳过该科目但不影响其他科目
        - 部分成功时仍然入库，返回 partial=True 标识
        """
        subjects = llm_result.get("subjects") or []
        if not subjects:
            raise ValueError("LLM 拆分结果为空，无法入库")

        # 过滤出有效科目（有 chapters 且无 error）
        valid_subjects = [s for s in subjects if s.get("chapters") and not s.get("error")]
        failed_subjects = [s for s in subjects if s.get("error") or not s.get("chapters")]

        if not valid_subjects:
            # 全部科目都失败
            error_summary = "; ".join([f"{s.get('subject_name')}: {s.get('error', '章节为空')}" for s in failed_subjects])
            raise ValueError(f"所有科目拆分均失败，无法入库。错误: {error_summary}")

        outline = await self._upsert_outline_meta(name, year, version, description, set_default)

        total_created = 0
        total_updated = 0
        subject_summaries: List[Dict[str, Any]] = []

        # 处理成功的科目
        for subj in valid_subjects:
            subject_id = subj.get("subject_id")
            chapters = subj.get("chapters") or []
            if not subject_id or not chapters:
                continue

            try:
                # upsert 考察目标关联
                link = (await self.db.execute(
                    select(ExamOutlineSubject).where(
                        ExamOutlineSubject.outline_id == outline.id,
                        ExamOutlineSubject.subject_id == subject_id,
                    )
                )).scalar_one_or_none()
                chapter_count = self._count_tree(chapters)
                if link:
                    link.exam_objective = subj.get("exam_objective") or link.exam_objective
                    link.chapter_count = chapter_count
                    link.guidance_status = "pending"
                else:
                    link = ExamOutlineSubject(
                        id=_gen_id(),
                        outline_id=outline.id,
                        subject_id=subject_id,
                        exam_objective=subj.get("exam_objective"),
                        chapter_count=chapter_count,
                        guidance_status="pending",
                    )
                    self.db.add(link)
                    await self.db.flush()

                created, updated = await self._upsert_chapters(
                    subject_id=subject_id,
                    outline_id=outline.id,
                    chapters=chapters,
                    parent_id=None,
                    level=1,
                )
                total_created += created
                total_updated += updated
                subject_summaries.append({
                    "subject_id": subject_id,
                    "subject_name": subj.get("subject_name"),
                    "chapter_count": chapter_count,
                    "created": created,
                    "updated": updated,
                    "status": "success",
                })
            except Exception as e:
                logger.error("入库某科目章节树时失败", subject_id=subject_id, error=str(e))
                subject_summaries.append({
                    "subject_id": subject_id,
                    "subject_name": subj.get("subject_name"),
                    "status": "failed",
                    "error": str(e),
                })

        # 记录失败的科目
        for subj in failed_subjects:
            subject_summaries.append({
                "subject_id": subj.get("subject_id"),
                "subject_name": subj.get("subject_name"),
                "status": "failed",
                "error": subj.get("error", "章节为空"),
            })

        await self.db.commit()

        return {
            "outline_id": outline.id,
            "outline_name": outline.name,
            "year": outline.year,
            "version": outline.version,
            "created_chapters": total_created,
            "updated_chapters": total_updated,
            "subjects": subject_summaries,
            "partial": len(failed_subjects) > 0,  # 标识是否部分成功
            "total_subjects": len(subjects),
            "successful_subjects": len([s for s in subject_summaries if s.get("status") == "success"]),
            "failed_subjects": len(failed_subjects),
        }

    async def generate_guidance_for_subject(
        self, outline_id: str, subject_id: str, batch_size: int = 15,
    ) -> Dict[str, Any]:
        """
        为某门课的所有章节批量生成复习指导（exam_guidance）。

        结合该门课的考察目标，按 batch_size 分组调 LLM，逐节点写回 CanonicalChapter。
        单组失败不影响其他组；全部失败才标记 failed。
        """
        from app.services.outline_llm_service import OutlineLLMService

        link = (await self.db.execute(
            select(ExamOutlineSubject).where(
                ExamOutlineSubject.outline_id == outline_id,
                ExamOutlineSubject.subject_id == subject_id,
            )
        )).scalar_one_or_none()
        if not link:
            raise ValueError("该大纲下不存在此科目的考察目标记录")

        chapters = (await self.db.execute(
            select(CanonicalChapter).where(
                CanonicalChapter.outline_id == outline_id,
                CanonicalChapter.subject_id == subject_id,
            ).order_by(CanonicalChapter.level, CanonicalChapter.sort_order)
        )).scalars().all()
        if not chapters:
            raise ValueError("该科目下没有章节，无法生成复习指导")

        llm_service = OutlineLLMService(self.db)
        client = await llm_service._get_client()
        if not client.is_available:
            raise ValueError("大纲拆分 LLM 未启用或缺少配置，请在系统设置 -> outline_llm 配置后重试")

        link.guidance_status = "generating"
        await self.db.commit()

        objective = link.exam_objective or ""
        by_id = {c.id: c for c in chapters}
        updated = 0
        any_success = False
        any_fail = False

        for i in range(0, len(chapters), batch_size):
            batch = chapters[i:i + batch_size]
            items = [
                {"id": c.id, "code": c.outline_code or "", "name": c.name,
                 "points": (c.description or "")[:500]}
                for c in batch
            ]
            prompt = self._build_guidance_prompt(objective, items)
            try:
                from app.services.outline_llm_service import _extract_json
                text = await client.chat(prompt, purpose="大纲章节复习指导生成")
                data = _extract_json(text)
                guidance_map = data.get("guidance") if isinstance(data, dict) else data
                if isinstance(guidance_map, list):
                    guidance_map = {g.get("id"): g.get("guidance") for g in guidance_map if isinstance(g, dict)}
                if not isinstance(guidance_map, dict):
                    raise ValueError("复习指导返回格式不正确")
                for cid, guidance in guidance_map.items():
                    chapter = by_id.get(cid)
                    if chapter and guidance:
                        chapter.exam_guidance = str(guidance).strip()
                        updated += 1
                any_success = True
                await self.db.commit()
            except Exception as e:
                any_fail = True
                logger.warning("复习指导某批生成失败", outline_id=outline_id,
                               subject_id=subject_id, batch_start=i, error=str(e))

        link.guidance_status = "done" if any_success and not any_fail else ("failed" if not any_success else "done")
        await self.db.commit()

        return {
            "outline_id": outline_id,
            "subject_id": subject_id,
            "guidance_status": link.guidance_status,
            "updated_chapters": updated,
            "total_chapters": len(chapters),
        }

    @staticmethod
    def _build_guidance_prompt(objective: str, items: List[Dict[str, Any]]) -> str:
        chapters_json = json.dumps(items, ensure_ascii=False, indent=2)
        return (
            "你是408考研复习规划专家。下面是一门课的考察目标，以及若干章节（含原文考点）。\n"
            "请结合考察目标，为每个章节生成简洁的『复习指导』（重点内容 + 复习方向，2-4 句），"
            "帮助考生抓住该章重点。\n\n"
            f"考察目标：\n{objective or '（未提供，按通用408要求）'}\n\n"
            f"章节列表（JSON，id 是章节标识）：\n{chapters_json}\n\n"
            "只输出 JSON，格式：{\"guidance\": {\"<章节id>\": \"复习指导文本\", ...}}，不要任何解释。"
        )

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


async def get_outline_chapters(
    session: AsyncSession, outline_id: str, subject_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """以树结构返回大纲下所有章节（可按 subject_id 过滤）。含原文考点 description + 增强字段 + 复习指导 exam_guidance。"""
    query = (
        select(CanonicalChapter)
        .where(CanonicalChapter.outline_id == outline_id)
        .order_by(CanonicalChapter.level, CanonicalChapter.sort_order)
    )
    if subject_id:
        query = query.where(CanonicalChapter.subject_id == subject_id)
    rows = (await session.execute(query)).scalars().all()

    by_id = {r.id: {
        "id": r.id,
        "name": r.name,
        "code": r.code,
        "outline_code": r.outline_code,
        "level": r.level,
        "parent_id": r.parent_id,
        "subject_id": r.subject_id,
        "sort_order": r.sort_order,
        "description": r.description,
        "enhanced_description": r.enhanced_description,
        "keywords": r.keywords,
        "exam_guidance": r.exam_guidance,
        "children": [],
    } for r in rows}

    roots: List[Dict[str, Any]] = []
    for node in by_id.values():
        if node["parent_id"] and node["parent_id"] in by_id:
            by_id[node["parent_id"]]["children"].append(node)
        else:
            roots.append(node)
    return roots


async def get_outline_subjects(session: AsyncSession, outline_id: str) -> List[Dict[str, Any]]:
    """返回某大纲下各门课的考察目标 + 指导生成状态。"""
    rows = (await session.execute(
        select(ExamOutlineSubject, Subject)
        .join(Subject, Subject.id == ExamOutlineSubject.subject_id)
        .where(ExamOutlineSubject.outline_id == outline_id)
        .order_by(Subject.sort_order)
    )).all()
    return [
        {
            "subject_id": link.subject_id,
            "subject_name": subject.name,
            "subject_code": subject.code,
            "exam_objective": link.exam_objective,
            "guidance_status": link.guidance_status,
            "chapter_count": link.chapter_count,
        }
        for link, subject in rows
    ]
