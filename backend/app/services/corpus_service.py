"""
语料文件注册服务

扫描本地目录，将文件注册到 corpus_files 表，支持去重和状态追踪。
"""

import hashlib
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CorpusFile

logger = get_logger(__name__)

# 默认支持的文件类型
SUPPORTED_EXTENSIONS = {"pdf", "docx", "pptx"}

# MIME 类型映射
MIME_MAP = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def compute_sha256(file_path: str) -> str:
    """计算文件 SHA256 哈希"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_id() -> str:
    """生成 32 位唯一 ID"""
    return uuid.uuid4().hex[:32]


class CorpusService:
    """语料文件注册服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def scan_and_register(
        self,
        root_path: str,
        file_types: Optional[List[str]] = None,
        batch_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        扫描目录并将文件注册到 corpus_files

        Args:
            root_path: 扫描根目录
            file_types: 要扫描的文件扩展名列表，默认 pdf/docx/pptx
            batch_label: 批次标签，写入 source_ref

        Returns:
            {"total_scanned": int, "registered": int, "skipped": int, "errors": list}
        """
        root = Path(root_path).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"目录不存在: {root_path}")

        extensions = set(file_types) if file_types else SUPPORTED_EXTENSIONS
        batch = batch_label or f"scan-{generate_id()[:8]}"

        total_scanned = 0
        registered = 0
        skipped = 0
        errors: List[Dict[str, str]] = []

        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lstrip(".").lower()
            if ext not in extensions:
                continue

            total_scanned += 1

            try:
                sha256 = compute_sha256(str(file_path))

                # 去重检查
                existing = await self.db.execute(
                    select(CorpusFile).where(CorpusFile.sha256 == sha256)
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    logger.debug("文件已存在，跳过", file=str(file_path), sha256=sha256[:16])
                    continue

                stat = file_path.stat()
                corpus_file = CorpusFile(
                    id=generate_id(),
                    source_type="crawler",
                    source_ref=batch,
                    file_name=file_path.name,
                    file_ext=ext,
                    local_path=str(file_path),
                    sha256=sha256,
                    file_size=stat.st_size,
                    mime_type=MIME_MAP.get(ext),
                    status="pending",
                )
                self.db.add(corpus_file)
                registered += 1

            except Exception as e:
                errors.append({"file": str(file_path), "error": str(e)})
                logger.warning("文件注册失败", file=str(file_path), error=str(e))

        await self.db.commit()

        logger.info(
            "目录扫描完成",
            root=str(root),
            total_scanned=total_scanned,
            registered=registered,
            skipped=skipped,
            errors=len(errors),
        )

        return {
            "total_scanned": total_scanned,
            "registered": registered,
            "skipped": skipped,
            "errors": errors,
            "batch_label": batch,
        }

    async def get_corpus_files(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        file_ext: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分页查询语料文件"""
        query = select(CorpusFile)
        count_query = select(func.count()).select_from(CorpusFile)

        conditions = []
        if status:
            conditions.append(CorpusFile.status == status)
        if source_type:
            conditions.append(CorpusFile.source_type == source_type)
        if file_ext:
            conditions.append(CorpusFile.file_ext == file_ext)
        if keyword:
            kw = f"%{keyword}%"
            conditions.append(
                CorpusFile.file_name.ilike(kw) | CorpusFile.local_path.ilike(kw)
            )

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = await self.db.scalar(count_query) or 0

        query = query.order_by(CorpusFile.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        items = result.scalars().all()

        return {
            "items": [self._to_dict(f) for f in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_corpus_file_detail(self, file_id: str) -> Optional[Dict[str, Any]]:
        """获取语料文件详情"""
        result = await self.db.execute(
            select(CorpusFile).where(CorpusFile.id == file_id)
        )
        f = result.scalar_one_or_none()
        if not f:
            return None
        return self._to_dict(f)

    def _to_dict(self, f: CorpusFile) -> Dict[str, Any]:
        return {
            "id": f.id,
            "source_type": f.source_type,
            "source_ref": f.source_ref,
            "file_name": f.file_name,
            "file_ext": f.file_ext,
            "local_path": f.local_path,
            "sha256": f.sha256,
            "file_size": f.file_size,
            "mime_type": f.mime_type,
            "doc_type": f.doc_type,
            "version": f.version,
            "status": f.status,
            "error_detail": f.error_detail,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        }
