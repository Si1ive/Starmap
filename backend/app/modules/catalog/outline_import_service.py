"""
目录大纲（考试大纲 / 知识体系大纲）导入服务

支持的输入格式：
1. JSON：直接结构化的章节树
2. 纯文本：按编号或缩进识别层级（1. / 1.1 / 1.1.1 / 一、 / (一) / 第X章）
3. （扩展）从已解析的 PDF document_sections 转换 — 见 import_from_document

入库流程：
- 创建 exam_outlines 元信息
- 创建 canonical_chapters 树（继承 outline_id）
- 后续抽取知识点/题目时，可以传 outline_id 限定使用该大纲匹配章节
"""

import uuid
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    ExamOutline, CanonicalChapter, Subject, ExamOutlineSubject,
)
from app.modules.catalog.outline_document_sections import (
    load_outline_tree_from_document_sections,
)
from app.modules.catalog.outline_parser import (
    detect_outline_format,
    parse_outline_json,
    parse_outline_text,
)
from app.modules.catalog.outline_tree import (
    count_outline_nodes,
    max_outline_depth,
)
from app.modules.retrieval.chapter_relation_retrieval import (
    validate_cross_references,
)

logger = get_logger(__name__)


def _gen_id() -> str:
    return uuid.uuid4().hex[:32]


class OutlineImportService:
    """大纲导入服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def preview(self, content: str, filename: str = "") -> Dict[str, Any]:
        """解析大纲文本并返回预览（不入库）"""
        fmt = detect_outline_format(filename, content)
        if fmt == "json":
            chapters = parse_outline_json(content)
        else:
            chapters = parse_outline_text(content)

        # 统计
        total = count_outline_nodes(chapters)
        max_depth = max_outline_depth(chapters)

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
                if data.get("cross_references"):
                    validated = await validate_cross_references(self.db, data["cross_references"])
                    chapter.cross_references = validated
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
                    cross_references=data.get("cross_references") if data.get("cross_references") else None,
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

    async def preview_from_document_sections(self, document_id: str) -> Dict[str, Any]:
        """预览文档标题树转成的大纲章节树（不入库）。"""
        chapters_tree = await load_outline_tree_from_document_sections(
            self.db,
            document_id,
        )
        return {
            "format": "document_sections",
            "total_chapters": count_outline_nodes(chapters_tree),
            "max_depth": max_outline_depth(chapters_tree),
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
        chapters_tree = await load_outline_tree_from_document_sections(
            self.db,
            document_id,
        )

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
            "total_chapters": count_outline_nodes(chapters_tree),
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
        - 创建 OutlineIngestionRun 记录任务进度
        """
        from app.models.mysql_models import OutlineIngestionRun

        subjects = llm_result.get("subjects") or []
        if not subjects:
            raise ValueError("LLM 拆分结果为空，无法入库")

        # 创建任务记录（status 用 "processing"，与 DB ENUM 一致）
        run = OutlineIngestionRun(
            id=_gen_id(),
            outline_name=name,
            year=year,
            version=version,
            total_subjects=len(subjects),
            status="processing",
        )
        self.db.add(run)
        await self.db.flush()

        # 过滤出有效科目（有 chapters 且无 error）
        valid_subjects = [s for s in subjects if s.get("chapters") and not s.get("error")]
        failed_subjects = [s for s in subjects if s.get("error") or not s.get("chapters")]

        if not valid_subjects:
            # 全部科目都失败
            error_summary = "; ".join([f"{s.get('subject_name')}: {s.get('error', '章节为空')}" for s in failed_subjects])
            run.status = "failed"
            run.error_detail = f"所有科目拆分均失败。错误: {error_summary}"
            run.completed_at = datetime.utcnow()
            await self.db.commit()
            raise ValueError(f"所有科目拆分均失败，无法入库。错误: {error_summary}")

        outline = await self._upsert_outline_meta(name, year, version, description, set_default)
        run.outline_id = outline.id

        total_created = 0
        total_updated = 0
        subject_summaries: List[Dict[str, Any]] = []
        processed_count = 0

        # 处理成功的科目
        for subj in valid_subjects:
            subject_id = subj.get("subject_id")
            subject_name = subj.get("subject_name")
            chapters = subj.get("chapters") or []
            if not subject_id or not chapters:
                continue

            # 更新当前处理科目
            run.current_subject_name = subject_name
            await self.db.flush()

            try:
                # upsert 考察目标关联
                link = (await self.db.execute(
                    select(ExamOutlineSubject).where(
                        ExamOutlineSubject.outline_id == outline.id,
                        ExamOutlineSubject.subject_id == subject_id,
                    )
                )).scalar_one_or_none()
                chapter_count = count_outline_nodes(chapters)
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
                processed_count += 1

                # 更新进度
                run.processed_subjects = processed_count
                await self.db.flush()

                subject_summaries.append({
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "chapter_count": chapter_count,
                    "created": created,
                    "updated": updated,
                    "status": "success",
                })
            except Exception as e:
                logger.error("入库某科目章节树时失败", subject_id=subject_id, error=str(e))
                subject_summaries.append({
                    "subject_id": subject_id,
                    "subject_name": subject_name,
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

        # 更新任务状态
        run.processed_subjects = len(valid_subjects)
        if len(failed_subjects) > 0:
            run.status = "partial_success"
        else:
            run.status = "done"
        run.completed_at = datetime.utcnow()

        await self.db.commit()

        # 大纲入库完成后，自动构建考点 segment 写入 Qdrant
        try:
            from app.modules.retrieval.segment_service import SegmentService
            seg_service = SegmentService(self.db)
            seg_result = await seg_service.build_canonical_chapter_segments(
                outline_id=outline.id,
                rebuild=False,
            )
            logger.info("大纲章节 segment 构建完成", outline_id=outline.id, count=seg_result.get("segments_count", 0))
        except Exception as e:
            logger.warning("大纲章节 segment 构建失败（不影响大纲入库）", outline_id=outline.id, error=str(e))

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
            "run_id": run.id,  # 返回任务 ID
        }
