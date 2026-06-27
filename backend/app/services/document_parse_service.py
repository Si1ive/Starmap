"""
文档解析服务

通过标准化适配层解析 PDF/DOCX/PPTX，输出统一的 pages/blocks/assets 并落库。
当前支持 Docling / MinerU 双解析器，可手动切换单一活动解析器。
"""

import asyncio
import base64
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    CorpusFile, ParseRun, Document,
    DocumentPage, DocumentBlock, DocumentAsset,
    KnowledgePoint, Question, CanonicalChapter,
)
from app.services.document_parsers import (
    ParserUnavailableError,
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
    choose_parser,
)
from app.services.system_settings_service import SystemSettingsService
from app.services.text_cleaning import clean_block_text

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


class MinerUProgressHandler(logging.Handler):
    """
    拦截 MinerU 日志，提取逐页进度并更新 ParseRun（embedded 模式用）。

    真实 MinerU 日志关键行（loguru INFO）：
    - "Pipeline processing window batch 2/11: 2/11 pages, batch_pages=1, ..."
    - "... multi-file run. doc_count=1, total_pages=11, window_size=1, total_batches=11"
    """

    def __init__(self, run_id: str, db_session: AsyncSession, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.run_id = run_id
        self.db = db_session
        self.loop = loop
        self.last_update_time = 0
        self.update_interval = 2.0  # 最多每 2 秒更新一次 DB，避免过于频繁
        self.total_pages: Optional[int] = None

        self.patterns = [
            re.compile(r'batch\s+(\d+)\s*/\s*(\d+)', re.IGNORECASE),   # "batch 2/11" —— 最可靠
            re.compile(r'(\d+)\s*/\s*(\d+)\s*pages', re.IGNORECASE),   # "2/11 pages"
            re.compile(r'page[^\d]{0,6}(\d+)\s*/\s*(\d+)', re.IGNORECASE),
        ]
        self.total_pages_pattern = re.compile(r'total_pages[=:\s]+(\d+)', re.IGNORECASE)

    def emit(self, record):
        """处理日志记录，提取页码并更新进度"""
        try:
            message = record.getMessage()
            lower = message.lower()
            if "page" not in lower and "batch" not in lower:
                return

            # 先抓总页数
            tm = self.total_pages_pattern.search(message)
            if tm:
                self.total_pages = int(tm.group(1))

            current_page = None
            total_pages = self.total_pages
            for pattern in self.patterns:
                match = pattern.search(message)
                if match:
                    current_page = int(match.group(1))
                    if len(match.groups()) > 1:
                        total_pages = int(match.group(2))
                    break

            if current_page is None:
                return

            # 限流：避免过于频繁的 DB 写入
            now = time.time()
            if now - self.last_update_time < self.update_interval:
                return
            self.last_update_time = now

            asyncio.run_coroutine_threadsafe(
                self._update_progress(current_page, total_pages),
                self.loop
            )
        except Exception as e:
            logger.warning(f"MinerU progress handler error: {e}")

    async def _update_progress(self, current_page: int, total_pages: Optional[int]):
        """异步更新 ParseRun 的进度字段"""
        try:
            run = await self.db.get(ParseRun, self.run_id)
            if run:
                run.current_page = current_page
                if total_pages:
                    run.total_pages = total_pages
                    run.stage_detail = f"正在解析第 {current_page}/{total_pages} 页..."
                else:
                    run.stage_detail = f"正在解析第 {current_page} 页..."
                await self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to update parse progress: {e}")


class DocumentParseService:
    """文档解析服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _generate_id(self) -> str:
        """生成唯一 ID"""
        return generate_id()

    async def _get_parser(self, parser_name: Optional[str] = None):
        """获取解析器实例（供 API 层提前检查用）"""
        runtime_config = await SystemSettingsService(self.db).get_pdf_parser_runtime_config()
        return choose_parser(requested_parser=parser_name, runtime_config=runtime_config)

    async def parse_document(
        self,
        corpus_file_id: str,
        parser_name: Optional[str] = None,
        parse_mode: str = "primary",
    ) -> Dict[str, Any]:
        """
        解析单个文档

        1. 读取 corpus_file 记录
        2. 创建 parse_run 记录
        3. 选择解析器并输出标准化结构
        4. 创建/更新 Document 记录
        5. 落库 pages、blocks、assets
        6. 更新 parse_run 状态和指标
        """
        # 1. 获取文件记录
        result = await self.db.execute(
            select(CorpusFile).where(CorpusFile.id == corpus_file_id)
        )
        corpus_file = result.scalar_one_or_none()
        if not corpus_file:
            raise ValueError(f"语料文件不存在: {corpus_file_id}")

        if not corpus_file.local_path or not Path(corpus_file.local_path).exists():
            raise ValueError(f"文件不存在于磁盘: {corpus_file.local_path}")

        if corpus_file.status == "parsing":
            raise ValueError("该语料正在解析中，请稍后刷新状态")

        if corpus_file.status == "parsed" and parse_mode in {"primary", "fallback"}:
            existing_document = await self._get_document_by_corpus_file_id(corpus_file_id)
            raise ValueError(
                "该语料已成功解析，无需重复执行；如需重跑请使用 retry 或 manual_fix 模式"
                if existing_document
                else "该语料已标记为解析成功，无需重复执行；如需重跑请使用 retry 或 manual_fix 模式"
            )

        runtime_config = await SystemSettingsService(self.db).get_pdf_parser_runtime_config()
        parser = choose_parser(
            requested_parser=parser_name,
            runtime_config=runtime_config,
        )

        # 2. 创建 parse_run
        parse_run = ParseRun(
            id=generate_id(),
            corpus_file_id=corpus_file_id,
            parser_name=parser.name,
            parser_version=parser.version,
            parse_mode=parse_mode,
            status="running",
        )
        self.db.add(parse_run)

        # 更新文件状态
        corpus_file.status = "parsing"
        corpus_file.error_detail = None
        await self.db.commit()

        start_time = time.time()

        try:
            # 3. 调用解析器并标准化
            # 解析器本身是同步 CPU/IO 重任务，放到线程池执行，避免阻塞事件循环，
            # 否则解析过程中管理端的列表查询会一起超时。
            parse_result = await asyncio.to_thread(parser.parse, corpus_file.local_path)

            # 4. 创建/更新 Document
            document = await self._get_or_create_document(
                corpus_file, parse_run.id, parse_result
            )

            # 5. 落库 pages、blocks、assets（assets 必须在 blocks 后，因为会读取 figure/table/formula block 二次注册）
            await self._persist_pages(document.id, parse_result.pages)
            await self._persist_blocks(document.id, parse_result.blocks)
            await self._persist_assets(document.id, parse_result.assets)

            elapsed = time.time() - start_time

            # 6. 更新 parse_run
            parse_run.status = "success"
            parse_run.parser_name = parse_result.parser_name
            parse_run.parser_version = parse_result.parser_version
            parse_run.parse_mode = parse_mode
            parse_run.page_count = parse_result.page_count
            parse_run.block_count = parse_result.block_count
            parse_run.asset_count = parse_result.asset_count
            parse_run.confidence = parse_result.confidence
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parse_result.parser_name,
                "parser_version": parse_result.parser_version,
                "parse_mode": parse_mode,
                "metadata": parse_result.metadata or {},
            }

            # 更新文件状态
            corpus_file.status = "parsed"
            corpus_file.error_detail = None

            # 更新文档
            document.page_count = parse_result.page_count
            document.document_markdown = parse_result.document_markdown or ""
            document.document_json = self._serialize_parse_result(parse_result)
            document.raw_parser_output = parse_result.raw_output
            document.status = "pending"

            await self.db.commit()

            # 刷新对象以避免访问detached对象
            await self.db.refresh(parse_run)
            await self.db.refresh(document)
            await self.db.refresh(corpus_file)

            logger.info(
                "文档解析成功并落库",
                corpus_file_id=corpus_file_id,
                document_id=document.id,
                parser=parse_result.parser_name,
                parse_mode=parse_mode,
                pages=parse_result.page_count,
                blocks=parse_result.block_count,
                assets=parse_result.asset_count,
                elapsed=f"{elapsed:.2f}s",
            )

            return {
                "parse_run_id": parse_run.id,
                "document_id": document.id,
                "status": "success",
                "parser_name": parse_result.parser_name,
                "parser_version": parse_result.parser_version,
                "parse_mode": parse_mode,
                "page_count": parse_result.page_count,
                "block_count": parse_result.block_count,
                "asset_count": parse_result.asset_count,
                "elapsed_seconds": round(elapsed, 2),
            }

        except ParserUnavailableError as e:
            elapsed = time.time() - start_time
            error_msg = (
                f"当前激活解析器 {parser.name} 不可用：{str(e)}。"
                " 请在系统设置 -> PDF解析器完成停旧启新后重试。"
            )[:500]
            parse_run.status = "failed"
            parse_run.error_detail = error_msg
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parser.name,
                "parser_version": parser.version,
                "parse_mode": parse_mode,
            }
            corpus_file.status = "failed"
            corpus_file.error_detail = error_msg
            await self.db.commit()
            logger.error(
                "文档解析器不可用",
                corpus_file_id=corpus_file_id,
                parser=parser.name,
                error=error_msg,
            )
            raise ParserUnavailableError(parser.name, error_msg) from e

        except RuntimeError as e:
            elapsed = time.time() - start_time
            error_msg = str(e)[:500]
            parse_run.status = "failed"
            parse_run.error_detail = error_msg
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parser.name,
                "parser_version": parser.version,
                "parse_mode": parse_mode,
            }
            corpus_file.status = "failed"
            corpus_file.error_detail = error_msg
            await self.db.commit()
            logger.error(
                "文档解析运行时失败",
                corpus_file_id=corpus_file_id,
                parser=parser.name,
                error=error_msg,
            )
            raise

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e)[:500]
            parse_run.status = "failed"
            parse_run.error_detail = error_msg
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parser.name,
                "parser_version": parser.version,
                "parse_mode": parse_mode,
            }

            corpus_file.status = "failed"
            corpus_file.error_detail = error_msg

            await self.db.commit()
            logger.error(
                "文档解析失败",
                corpus_file_id=corpus_file_id,
                parser=parser.name,
                error=error_msg,
            )
            raise

    async def parse_document_with_run_id(
        self,
        run_id: str,
        corpus_file_id: str,
        parser_name: Optional[str] = None,
        parse_mode: Optional[str] = "primary",
    ) -> Dict[str, Any]:
        """
        解析单个文档（接收已创建的 run_id，用于异步派发场景）

        与 parse_document 的区别：
        1. 不创建 ParseRun，而是查询已存在的 run
        2. 在解析过程中更新 run 的进度字段 (current_page, total_pages, stage_detail)
        3. 用于后台任务，不抛异常给调用方（错误写到 run.error_detail）
        """
        start_time = time.time()

        # 查询已创建的 run
        parse_run = await self.db.get(ParseRun, run_id)
        if not parse_run:
            logger.error("ParseRun 不存在", run_id=run_id)
            return {"status": "failed", "error": "ParseRun 不存在"}

        try:
            # 1. 获取文件记录
            corpus_file = await self.db.get(CorpusFile, corpus_file_id)
            if not corpus_file:
                raise ValueError(f"语料文件不存在: {corpus_file_id}")

            if not corpus_file.local_path or not Path(corpus_file.local_path).exists():
                raise ValueError(f"文件不存在于磁盘: {corpus_file.local_path}")

            # 更新文件状态
            corpus_file.status = "parsing"
            corpus_file.error_detail = None
            await self.db.commit()

            # 2. 选择解析器
            runtime_config = await SystemSettingsService(self.db).get_pdf_parser_runtime_config()
            parser = choose_parser(requested_parser=parser_name, runtime_config=runtime_config)

            # 更新进度：开始解析
            parse_run.current_stage = "parsing"
            parse_run.stage_detail = f"正在使用 {parser.name} 解析文档..."
            await self.db.commit()

            # 3. 调用解析器（同步 IO 重任务放线程池），并发追踪逐页进度
            # - embedded 模式：MinerU 在本进程内，用 logging.Handler 拦截日志
            # - local 模式：MinerU 在独立 parser_service 进程，轮询其 /progress 端点
            progress_handler = None
            is_local_service = hasattr(parser, "fetch_progress") and hasattr(parser, "endpoint")

            if parser.name.lower() == "mineru" and not is_local_service:
                # embedded 模式：挂载日志拦截器
                try:
                    loop = asyncio.get_running_loop()
                    progress_handler = MinerUProgressHandler(run_id, self.db, loop)
                    progress_handler.setLevel(logging.DEBUG)
                    # 兼容新旧 MinerU：同时挂到 root / mineru / magic_pdf
                    for logger_name in ("", "mineru", "magic_pdf"):
                        logging.getLogger(logger_name).addHandler(progress_handler)
                    logger.info("MinerU 日志拦截器已挂载(embedded)", run_id=run_id)
                except Exception as e:
                    logger.warning(f"无法挂载 MinerU 进度拦截器: {e}")

            # 把解析放到后台线程，主协程并发轮询进度
            parse_future = asyncio.ensure_future(
                asyncio.to_thread(parser.parse, corpus_file.local_path, task_id=run_id)
                if is_local_service
                else asyncio.to_thread(parser.parse, corpus_file.local_path)
            )

            try:
                while not parse_future.done():
                    await asyncio.sleep(2)
                    # local 模式：轮询 parser_service /progress
                    if is_local_service:
                        prog = await asyncio.to_thread(parser.fetch_progress, run_id)
                        if prog and prog.get("total_pages"):
                            cur = prog.get("current_page") or 0
                            total = prog.get("total_pages")
                            parse_run.current_page = cur
                            parse_run.total_pages = total
                            parse_run.stage_detail = f"正在解析第 {cur}/{total} 页..."
                            await self.db.commit()
                parse_result = await parse_future
            finally:
                # 卸载 embedded 日志拦截器
                if progress_handler:
                    try:
                        for logger_name in ("", "mineru", "magic_pdf"):
                            logging.getLogger(logger_name).removeHandler(progress_handler)
                    except Exception as e:
                        logger.warning(f"卸载 MinerU 进度拦截器失败: {e}")

            # 更新进度：解析完成，开始入库
            parse_run.total_pages = parse_result.page_count
            parse_run.current_page = parse_result.page_count
            parse_run.stage_detail = f"解析完成，共 {parse_result.page_count} 页，正在入库..."
            await self.db.commit()

            # 4. 创建/更新 Document
            document = await self._get_or_create_document(corpus_file, parse_run.id, parse_result)

            # 5. 落库 pages、blocks、assets
            await self._persist_pages(document.id, parse_result.pages)
            await self._persist_blocks(document.id, parse_result.blocks)
            await self._persist_assets(document.id, parse_result.assets)

            elapsed = time.time() - start_time

            # 6. 更新 parse_run 为成功
            parse_run.status = "success"
            parse_run.current_stage = "completed"
            parse_run.page_count = parse_result.page_count
            parse_run.block_count = parse_result.block_count
            parse_run.asset_count = parse_result.asset_count
            parse_run.confidence = parse_result.confidence
            parse_run.completed_at = datetime.utcnow()
            parse_run.stage_detail = f"完成：{parse_result.page_count} 页 / {parse_result.block_count} 块 / {parse_result.asset_count} 资产"
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parse_result.parser_name,
                "parser_version": parse_result.parser_version,
                "parse_mode": parse_mode or "primary",
                "metadata": parse_result.metadata or {},
            }

            # 更新文件状态
            corpus_file.status = "parsed"
            corpus_file.error_detail = None

            # 更新文档
            document.page_count = parse_result.page_count
            document.document_markdown = parse_result.document_markdown or ""
            document.document_json = self._serialize_parse_result(parse_result)
            document.raw_parser_output = parse_result.raw_output
            document.status = "pending"

            await self.db.commit()

            logger.info(
                "后台解析任务完成",
                run_id=run_id,
                document_id=document.id,
                pages=parse_result.page_count,
                elapsed=f"{elapsed:.2f}s",
            )

            return {
                "status": "success",
                "run_id": run_id,
                "document_id": document.id,
                "page_count": parse_result.page_count,
            }

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e)[:500]

            parse_run.status = "failed"
            parse_run.current_stage = "failed"
            parse_run.error_detail = error_msg
            parse_run.completed_at = datetime.utcnow()
            parse_run.stage_detail = f"失败：{error_msg[:100]}"
            parse_run.metrics_json = {"elapsed_seconds": round(elapsed, 2)}

            corpus_file = await self.db.get(CorpusFile, corpus_file_id)
            if corpus_file:
                corpus_file.status = "failed"
                corpus_file.error_detail = error_msg

            await self.db.commit()

            logger.error("后台解析任务失败", run_id=run_id, error=error_msg)
            return {"status": "failed", "run_id": run_id, "error": error_msg}

    async def _get_document_by_corpus_file_id(self, corpus_file_id: str) -> Optional[Document]:
        result = await self.db.execute(
            select(Document).where(Document.corpus_file_id == corpus_file_id)
        )
        return result.scalar_one_or_none()

    async def _get_or_create_document(
        self,
        corpus_file: CorpusFile,
        parse_run_id: str,
        parse_result: ParsedDocumentResult,
    ) -> Document:
        """Get existing or create new Document for a corpus file."""
        result = await self.db.execute(
            select(Document).where(Document.corpus_file_id == corpus_file.id)
        )
        document = result.scalar_one_or_none()

        if not document:
            document = Document(
                id=generate_id(),
                corpus_file_id=corpus_file.id,
                title=corpus_file.file_name,
                doc_type=corpus_file.doc_type,
                language=corpus_file.language,
                status="pending",
            )
            self.db.add(document)

        document.latest_parse_run_id = parse_run_id
        await self.db.flush()
        return document

    def _serialize_parse_result(self, parse_result: ParsedDocumentResult) -> Dict[str, Any]:
        return {
            "parser_name": parse_result.parser_name,
            "parser_version": parse_result.parser_version,
            "confidence": parse_result.confidence,
            "metadata": parse_result.metadata or {},
            "page_count": parse_result.page_count,
            "block_count": parse_result.block_count,
            "asset_count": parse_result.asset_count,
            "pages": [
                {
                    "page_no": page.page_no,
                    "width": page.width,
                    "height": page.height,
                }
                for page in parse_result.pages
            ],
            "blocks": [
                {
                    "page_no": block.page_no,
                    "block_type": block.block_type,
                    "order_no": block.order_no,
                    "content_text": block.content_text,
                    "content_md": block.content_md,
                    "bbox": block.bbox,
                    "html_table": block.html_table,
                    "latex": block.latex,
                }
                for block in parse_result.blocks
            ],
            "assets": [
                {
                    "page_no": asset.page_no,
                    "asset_type": asset.asset_type,
                    "caption_text": asset.caption_text,
                    "bbox": asset.bbox,
                    "file_path": asset.file_path,
                }
                for asset in parse_result.assets
            ],
        }

    async def _persist_pages(self, document_id: str, pages: List[ParsedPage]) -> None:
        """Persist page records."""
        # Remove old pages for re-parse
        old = await self.db.execute(
            select(DocumentPage).where(DocumentPage.document_id == document_id)
        )
        for p in old.scalars().all():
            await self.db.delete(p)

        for page_data in pages:
            page = DocumentPage(
                id=generate_id(),
                document_id=document_id,
                page_no=page_data.page_no,
                width=page_data.width,
                height=page_data.height,
            )
            self.db.add(page)

        await self.db.flush()

    @staticmethod
    def _bbox_x1(bbox: Optional[dict]) -> Optional[float]:
        """取 bbox 的 x1 作为同页同类型 block/asset 的位置判别键。"""
        if not bbox:
            return None
        x1 = bbox.get("x1")
        try:
            return round(float(x1), 2) if x1 is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _write_asset_image(document_id: str, asset_data: ParsedAsset) -> Optional[str]:
        """
        把内联的 base64 图片字节解码落盘到 uploads/assets/<document_id>/，返回 host 绝对路径。

        嵌入模式与服务模式都把图片字节以 base64 内联回传（见 ParsedAsset.image_base64），
        由主 backend 在此统一写盘，确保 file_path 始终是主 backend 可读的 host 路径。
        无 base64 时返回 None（如 block 提升的 asset、或读取失败的图片）。
        """
        b64 = getattr(asset_data, "image_base64", None)
        if not b64:
            return None

        ext = getattr(asset_data, "image_ext", None) or ".png"
        # backend 根目录：本文件在 app/services/ 下，向上三层到 backend
        dest_dir = Path(__file__).parent.parent.parent / "uploads" / "assets" / document_id
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{generate_id()}{ext}"
            dest.write_bytes(base64.b64decode(b64))
            return str(dest)
        except Exception as e:
            logger.warning("资产图片落盘失败", document_id=document_id, error=str(e))
            return None

    @staticmethod
    def _bbox_x1(bbox: Optional[dict]):
        """取 bbox 的 x1 作为同页内的位置键（MinerU 同一图/表的 block 与 asset 共享 bbox）。"""
        if not bbox:
            return None
        x1 = bbox.get("x1")
        try:
            return round(float(x1), 1) if x1 is not None else None
        except (TypeError, ValueError):
            return None

    async def _persist_assets(self, document_id: str, assets: List[ParsedAsset]) -> None:
        """
        落库资产记录，并回填 DocumentBlock.asset_id 建立 block→asset 精确桥。

        MinerU 对同一个 figure/table 会同时产出 block 和 asset 且共享 bbox，提升来的
        asset 本就源自 block。这里按 (page, type, bbox.x1) 把每个 asset 对回它的 block，
        写入 block.asset_id —— 下游按实体的 block_ids 即可精确绑定资产（不再按页笛卡尔积）。
        """
        from app.models.mysql_models import DocumentBlock as _Block

        # Remove old assets for re-parse
        old = await self.db.execute(
            select(DocumentAsset).where(DocumentAsset.document_id == document_id)
        )
        for a in old.scalars().all():
            await self.db.delete(a)

        # 该文档的 figure/table/formula block：用于回填 asset_id + 提升为 asset
        media_blocks = (await self.db.execute(
            select(_Block).where(
                _Block.document_id == document_id,
                _Block.block_type.in_(["figure", "table", "formula"]),
            )
        )).scalars().all()
        for b in media_blocks:
            b.asset_id = None  # 重新解析时重建桥

        # (page_no, type, x1) → block，把 MinerU content_list 产出的 asset 对回它的 block
        block_by_key: Dict[Any, Any] = {}
        for b in media_blocks:
            block_by_key.setdefault((b.page_no, b.block_type, self._bbox_x1(b.bbox)), b)

        explicit_keys = set()
        for asset_data in assets:
            # 图片字节以 base64 内联回传（嵌入/服务两种模式统一），在此解码落盘到
            # uploads/assets/<document_id>/，file_path 由主 backend 生成、确保 host 可读。
            persisted_path = self._write_asset_image(document_id, asset_data)
            asset_type = asset_data.asset_type or "figure"
            asset = DocumentAsset(
                id=generate_id(),
                document_id=document_id,
                page_no=asset_data.page_no,
                asset_type=asset_type,
                file_path=persisted_path or (asset_data.file_path or None),
                caption_text=asset_data.caption_text,
                bbox=asset_data.bbox,
                metadata_json=getattr(asset_data, "metadata", None),
            )
            self.db.add(asset)
            key = (asset_data.page_no, asset_type, self._bbox_x1(asset_data.bbox))
            explicit_keys.add(key)
            matched = block_by_key.get(key)
            if matched is not None:
                matched.asset_id = asset.id  # 回填 block→asset 桥

        # 把未被显式 asset 覆盖的 figure/table/formula block 提升为 asset，并回填 asset_id
        for b in media_blocks:
            key = (b.page_no, b.block_type, self._bbox_x1(b.bbox))
            if key in explicit_keys or b.asset_id:
                continue  # 已有同位置 asset 或已回填
            metadata = {}
            if b.block_type == "table" and b.html_table:
                metadata["html"] = b.html_table
            if b.block_type == "formula" and b.latex:
                metadata["latex"] = b.latex
            if b.content_text:
                metadata.setdefault("text", b.content_text)
            promoted = DocumentAsset(
                id=generate_id(),
                document_id=document_id,
                page_no=b.page_no,
                asset_type=b.block_type,
                file_path=None,
                caption_text=b.content_text[:500] if b.content_text else None,
                bbox=b.bbox,
                metadata_json=metadata or None,
            )
            self.db.add(promoted)
            b.asset_id = promoted.id

        await self.db.flush()

    async def _persist_blocks(self, document_id: str, blocks: List[ParsedBlock]) -> None:
        """Persist block records."""
        # Remove old blocks for re-parse
        old = await self.db.execute(
            select(DocumentBlock).where(DocumentBlock.document_id == document_id)
        )
        for b in old.scalars().all():
            await self.db.delete(b)

        for block_data in blocks:
            content_text = clean_block_text(block_data.content_text)
            content_md = clean_block_text(block_data.content_md)
            if content_md and content_md == content_text:
                content_md = None
            block = DocumentBlock(
                id=generate_id(),
                document_id=document_id,
                page_no=block_data.page_no,
                block_type=block_data.block_type,
                order_no=block_data.order_no,
                content_text=content_text,
                content_md=content_md,
                bbox=block_data.bbox,
                html_table=block_data.html_table,
                latex=block_data.latex,
            )
            self.db.add(block)

        await self.db.flush()

    async def get_parse_runs(self, corpus_file_id: str) -> List[Dict[str, Any]]:
        """获取文件的所有解析记录"""
        result = await self.db.execute(
            select(ParseRun)
            .where(ParseRun.corpus_file_id == corpus_file_id)
            .order_by(ParseRun.created_at.desc())
        )
        runs = result.scalars().all()
        return [
            {
                "id": r.id,
                "parser_name": r.parser_name,
                "parser_version": r.parser_version,
                "parse_mode": r.parse_mode,
                "status": r.status,
                "page_count": r.page_count,
                "block_count": r.block_count,
                "asset_count": r.asset_count,
                "confidence": float(r.confidence) if r.confidence else None,
                "error_detail": r.error_detail,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in runs
        ]

    async def get_document_detail(self, document_id: str) -> Optional[Dict[str, Any]]:
        """获取文档详情（含 pages 和 blocks）"""
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            return None

        # pages
        pages_result = await self.db.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_no)
        )
        pages = [
            {
                "id": p.id,
                "page_no": p.page_no,
                "width": p.width,
                "height": p.height,
            }
            for p in pages_result.scalars().all()
        ]

        # blocks
        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = [
            {
                "id": b.id,
                "page_no": b.page_no,
                "block_type": b.block_type,
                "order_no": b.order_no,
                "content_text": b.content_text,
                "content_md": b.content_md,
                "html_table": b.html_table,
                "latex": b.latex,
                "bbox": b.bbox,
                "review_status": b.review_status,
            }
            for b in blocks_result.scalars().all()
        ]

        # assets
        assets_result = await self.db.execute(
            select(DocumentAsset)
            .where(DocumentAsset.document_id == document_id)
            .order_by(DocumentAsset.page_no)
        )
        assets = [
            {
                "id": a.id,
                "page_no": a.page_no,
                "asset_type": a.asset_type,
                "caption_text": a.caption_text,
                "file_path": a.file_path,
            }
            for a in assets_result.scalars().all()
        ]

        return {
            "id": document.id,
            "corpus_file_id": document.corpus_file_id,
            "title": document.title,
            "doc_type": document.doc_type,
            "subject_id": document.subject_id,
            "source_label": document.source_label,
            "page_count": document.page_count,
            "latest_parse_run_id": document.latest_parse_run_id,
            "document_markdown": document.document_markdown,
            "document_json": document.document_json,
            "raw_parser_output": document.raw_parser_output,
            "status": document.status,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
            "pages": pages,
            "blocks": blocks,
            "assets": assets,
        }

    async def get_content_overview(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        文档内容总览：知识点按所属大纲考点分组，题目按题号排列。

        替代原"原生标题映射 + 归属诊断"的展示——直接把解析出的结构化内容
        清晰列出，让人能看出每章有哪些知识点、考点关键词是什么，题目有哪些。
        """
        document = (await self.db.execute(
            select(Document).where(Document.id == document_id)
        )).scalar_one_or_none()
        if not document:
            return None

        # 知识点（排除已删除）
        kps = (await self.db.execute(
            select(KnowledgePoint)
            .where(
                KnowledgePoint.source_document_id == document_id,
                KnowledgePoint.status != "deleted",
            )
            .order_by(KnowledgePoint.created_at, KnowledgePoint.id)
        )).scalars().all()

        # 题目（排除已删除）
        questions = (await self.db.execute(
            select(Question)
            .where(
                Question.source_document_id == document_id,
                Question.status != "deleted",
            )
        )).scalars().all()

        # 收集涉及的考点，批量加载章节信息
        chapter_ids = {kp.primary_chapter_id for kp in kps if kp.primary_chapter_id}
        chapter_ids |= {q.primary_chapter_id for q in questions if q.primary_chapter_id}
        chapter_map: Dict[str, CanonicalChapter] = {}
        if chapter_ids:
            chapters = (await self.db.execute(
                select(CanonicalChapter).where(CanonicalChapter.id.in_(list(chapter_ids)))
            )).scalars().all()
            chapter_map = {ch.id: ch for ch in chapters}

        # 知识点按 primary_chapter 分组；无章节的归入 ungrouped
        groups: Dict[str, Dict[str, Any]] = {}
        ungrouped_kps: List[Dict[str, Any]] = []
        for kp in kps:
            kp_brief = {
                "id": kp.id,
                "title": kp.title,
                "summary": kp.summary,
                "content_preview": (kp.content or "")[:300],
                "topic_terms": kp.topic_terms or [],
                "review_status": kp.review_status,
                "status": kp.status,
                "source_section_path": kp.source_section_path,
            }
            cid = kp.primary_chapter_id
            if cid and cid in chapter_map:
                if cid not in groups:
                    ch = chapter_map[cid]
                    groups[cid] = {
                        "chapter_id": cid,
                        "chapter_name": ch.name,
                        "outline_code": ch.outline_code,
                        "keywords": ch.keywords or [],
                        "description": ch.description,
                        "exam_guidance": ch.exam_guidance,
                        "knowledge_points": [],
                    }
                groups[cid]["knowledge_points"].append(kp_brief)
            else:
                ungrouped_kps.append(kp_brief)

        # 题目按题号排序（题号可能是 "16"/"44" 等字符串，按数值优先、回退字典序）
        def _q_sort_key(q: Question):
            no = (q.question_no or "").strip()
            digits = "".join(c for c in no if c.isdigit())
            return (0, int(digits)) if digits else (1, no)

        questions_sorted = sorted(questions, key=_q_sort_key)
        question_items = [
            {
                "id": q.id,
                "question_no": q.question_no,
                "type": q.type,
                "content_preview": (q.content or "")[:300],
                "options": q.options or [],
                "exam_year": q.exam_year,
                "review_status": q.review_status,
                "status": q.status,
                "primary_chapter_id": q.primary_chapter_id,
                "primary_chapter_name": (
                    chapter_map[q.primary_chapter_id].name
                    if q.primary_chapter_id and q.primary_chapter_id in chapter_map else None
                ),
                "source_section_path": q.source_section_path,
            }
            for q in questions_sorted
        ]

        return {
            "document_id": document.id,
            "title": document.title,
            "doc_type": document.doc_type,
            "knowledge_chapters": list(groups.values()),
            "ungrouped_knowledge_points": ungrouped_kps,
            "questions": question_items,
            "summary": {
                "knowledge_count": len(kps),
                "question_count": len(questions),
                "chapter_count": len(groups),
                "ungrouped_count": len(ungrouped_kps),
            },
        }
