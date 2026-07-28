"""Corpus file registration, deduplication, and query service."""

import hashlib
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CorpusFile, Document

logger = get_logger(__name__)

# 默认支持的文件类型
SUPPORTED_EXTENSIONS = {"pdf", "docx", "pptx"}

# 本地 downloads 目录（兼容容器路径 → 本地路径映射）
BACKEND_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_DOWNLOADS = str(BACKEND_ROOT / "downloads")


def _resolve_download_path(file_path: str) -> Path:
    """将容器路径 /app/downloads/... 翻译为本地实际路径"""
    p = Path(file_path)
    if p.exists():
        return p
    # 容器路径前缀翻译
    if file_path.startswith("/app/downloads/"):
        local = Path(_LOCAL_DOWNLOADS) / file_path[len("/app/downloads/"):]
        if local.exists():
            return local
    return p

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


class CorpusFileService:
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
        registered_items: List[Dict[str, str]] = []

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
                registered_items.append(
                    {
                        "id": corpus_file.id,
                        "file_name": corpus_file.file_name,
                        "status": corpus_file.status,
                    }
                )

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
            "registered_count": registered,
            "skipped_count": skipped,
            "failed_count": len(errors),
            "items": registered_items,
            "registered": registered,
            "skipped": skipped,
            "errors": errors,
            "batch_label": batch,
        }

    async def register_single_file(
        self,
        file_path: str,
        batch_label: Optional[str] = None,
        file_name: Optional[str] = None,
        owner_user_id: object | None = None,
    ) -> Dict[str, Any]:
        """
        注册单个文件到 corpus_files

        如果文件已存在（SHA256 匹配），返回已有的 corpus_file 信息。

        Args:
            file_path: 文件的绝对路径
            batch_label: 批次标签
            file_name: 可选展示文件名；上传存储名包含唯一前缀时使用

        Returns:
            {"corpus_file_id": str, "status": str, "is_new": bool}
        """
        p = _resolve_download_path(file_path)
        if not p.exists() or not p.is_file():
            raise ValueError(f"文件不存在: {file_path}")

        ext = p.suffix.lstrip(".").lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: {ext}，支持: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

        sha256 = compute_sha256(str(p))

        # 去重检查
        owner_condition = (
            CorpusFile.owner_user_id.is_(None)
            if owner_user_id is None
            else CorpusFile.owner_user_id == owner_user_id
        )
        existing = await self.db.execute(
            select(CorpusFile).where(
                CorpusFile.sha256 == sha256,
                owner_condition,
            )
        )
        existing_file = existing.scalar_one_or_none()
        if existing_file:
            logger.debug("文件已存在，返回已有记录", file=str(p), sha256=sha256[:16])
            return {
                "corpus_file_id": existing_file.id,
                "status": existing_file.status,
                "is_new": False,
            }

        stat = p.stat()
        batch = batch_label or f"single-{generate_id()[:8]}"
        corpus_file = CorpusFile(
            id=generate_id(),
            owner_user_id=owner_user_id,
            source_type="upload",
            source_ref=batch,
            file_name=file_name or p.name,
            file_ext=ext,
            local_path=str(p),
            sha256=sha256,
            file_size=stat.st_size,
            mime_type=MIME_MAP.get(ext),
            status="pending",
        )
        self.db.add(corpus_file)
        await self.db.commit()

        logger.info("单文件注册成功", file=str(p), corpus_file_id=corpus_file.id)
        return {
            "corpus_file_id": corpus_file.id,
            "status": "pending",
            "is_new": True,
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
        query = (
            select(CorpusFile, Document.id.label("document_id"))
            .outerjoin(Document, Document.corpus_file_id == CorpusFile.id)
        )
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
        rows = result.all()

        return {
            "items": [self._to_dict(f, document_id=document_id) for f, document_id in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        }

    async def get_corpus_file_detail(self, file_id: str) -> Optional[Dict[str, Any]]:
        """获取语料文件详情"""
        result = await self.db.execute(
            select(CorpusFile, Document.id.label("document_id"))
            .outerjoin(Document, Document.corpus_file_id == CorpusFile.id)
            .where(CorpusFile.id == file_id)
        )
        row = result.one_or_none()
        if not row:
            return None
        corpus_file, document_id = row
        return self._to_dict(corpus_file, document_id=document_id)

    def _to_dict(self, f: CorpusFile, document_id: Optional[str] = None) -> Dict[str, Any]:
        return {
            "id": f.id,
            "owner_user_id": str(f.owner_user_id) if f.owner_user_id else None,
            "source_type": f.source_type,
            "source_ref": f.source_ref,
            "batch_label": f.source_ref,
            "file_name": f.file_name,
            "file_path": f.local_path,
            "file_type": f.file_ext,
            "file_ext": f.file_ext,
            "local_path": f.local_path,
            "sha256": f.sha256,
            "file_size": f.file_size,
            "mime_type": f.mime_type,
            "doc_type": f.doc_type,
            "version": f.version,
            "status": f.status,
            "error_detail": f.error_detail,
            "document_id": document_id,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        }
