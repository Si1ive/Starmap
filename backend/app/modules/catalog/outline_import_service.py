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

from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import Subject
from app.modules.catalog.outline_document_sections import (
    load_outline_tree_from_document_sections,
)
from app.modules.catalog.outline_parser import (
    detect_outline_format,
    parse_outline_json,
    parse_outline_text,
)
from app.modules.catalog.outline_persistence import (
    OutlinePersistence,
)
from app.modules.catalog.outline_tree import (
    count_outline_nodes,
    max_outline_depth,
)


class OutlineImportService:
    """大纲导入服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.persistence = OutlinePersistence(db)

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

        outline = await self.persistence.upsert_outline_meta(
            name=name,
            year=year,
            version=version,
            description=description,
            set_default=set_default,
        )

        # 2) 创建/更新章节树
        created, updated = await self.persistence.upsert_chapters(
            subject_id=subject_id,
            outline_id=outline.id,
            chapters=chapters,
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

        outline = await self.persistence.upsert_outline_meta(
            name=outline_name,
            year=year,
            version=version,
            description=f"从文档 {document_id} 自动转换",
            set_default=set_default,
            update_description=False,
        )

        created, updated = await self.persistence.upsert_chapters(
            subject_id=subject_id,
            outline_id=outline.id,
            chapters=chapters_tree,
        )
        await self.db.commit()

        return {
            "outline_id": outline.id,
            "created_chapters": created,
            "updated_chapters": updated,
            "total_chapters": count_outline_nodes(chapters_tree),
            "source_document_id": document_id,
        }
