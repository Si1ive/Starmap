"""Document parsing orchestration for the corpus module.

Parse PDF/DOCX/PPTX files through the normalized parser adapters, persist
pages/blocks/assets, and track parse run state.
"""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    CorpusFile,
    ParseRun,
)
from app.modules.corpus.document_store import (
    ParsedDocumentStore,
    generate_id,
)
from app.modules.corpus.entity_persistence import cleanup_document_entities
from app.modules.corpus.parser_runtime import choose_parser
from app.modules.corpus.parser_types import ParserUnavailableError
from app.modules.corpus.parse_progress import (
    MinerUProgressHandler,
    attach_mineru_progress_handler,
    detach_mineru_progress_handler,
)
from app.modules.operations.settings_service import SystemSettingsService

logger = get_logger(__name__)


class DocumentParseService:
    """文档解析服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.store = ParsedDocumentStore(db)

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

        if corpus_file.status == "parsing":
            raise ValueError("该语料正在解析中，请稍后刷新状态")

        if not corpus_file.local_path or not Path(corpus_file.local_path).exists():
            raise ValueError(f"文件不存在于磁盘: {corpus_file.local_path}")

        if corpus_file.status == "parsed" and parse_mode in {"primary", "fallback"}:
            existing_document = await self.store.get_document_by_corpus_file_id(
                corpus_file_id
            )
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
            document = await self.store.get_or_create_document(
                corpus_file,
                parse_run.id,
            )

            # 5. 落库 pages、blocks、assets（assets 必须在 blocks 后，因为会读取 figure/table/formula block 二次注册）
            await self.store.persist_pages(document.id, parse_result.pages)
            await self.store.persist_blocks(document.id, parse_result.blocks)
            await self.store.persist_assets(document.id, parse_result.assets)

            # 5.5 清理旧的抽取实体：blocks/assets 已重建，旧知识点/题目基于旧版面已失效，
            # 与版面在同一事务清掉，避免新版面配旧实体（坐标桥与来源引用错位）。
            removed = await cleanup_document_entities(self.db, document.id)
            if removed.get("knowledge_point") or removed.get("question"):
                logger.info(
                    "重解析清理旧抽取实体",
                    document_id=document.id,
                    removed_knowledge=removed.get("knowledge_point", 0),
                    removed_questions=removed.get("question", 0),
                )

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
            document.document_json = self.store.serialize_parse_result(
                parse_result
            )
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
            # - HTTP 服务模式（local / remote）：轮询 parser_service 的 /progress 端点
            progress_handler = None
            is_http_service = hasattr(parser, "fetch_progress") and hasattr(parser, "endpoint")

            if parser.name.lower() == "mineru" and not is_http_service:
                # embedded 模式：挂载日志拦截器
                try:
                    loop = asyncio.get_running_loop()
                    progress_handler = attach_mineru_progress_handler(
                        run_id,
                        self.db,
                        loop,
                    )
                    logger.info("MinerU 日志拦截器已挂载(embedded)", run_id=run_id)
                except Exception as e:
                    logger.warning(f"无法挂载 MinerU 进度拦截器: {e}")

            # 把解析放到后台线程，主协程并发轮询进度
            parse_future = asyncio.ensure_future(
                asyncio.to_thread(parser.parse, corpus_file.local_path, task_id=run_id)
                if is_http_service
                else asyncio.to_thread(parser.parse, corpus_file.local_path)
            )

            try:
                while not parse_future.done():
                    await asyncio.sleep(2)
                    # HTTP 服务模式：轮询 parser_service /progress
                    if is_http_service:
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
                        detach_mineru_progress_handler(progress_handler)
                    except Exception as e:
                        logger.warning(f"卸载 MinerU 进度拦截器失败: {e}")

            # 更新进度：解析完成，开始入库
            parse_run.total_pages = parse_result.page_count
            parse_run.current_page = parse_result.page_count
            parse_run.stage_detail = f"解析完成，共 {parse_result.page_count} 页，正在入库..."
            await self.db.commit()

            # 4. 创建/更新 Document
            document = await self.store.get_or_create_document(
                corpus_file,
                parse_run.id,
            )

            # 5. 落库 pages、blocks、assets
            await self.store.persist_pages(document.id, parse_result.pages)
            await self.store.persist_blocks(document.id, parse_result.blocks)
            await self.store.persist_assets(document.id, parse_result.assets)

            # 5.5 清理旧的抽取实体：与主链路同理，重解析重建版面后旧实体已失效。
            removed = await cleanup_document_entities(self.db, document.id)
            if removed.get("knowledge_point") or removed.get("question"):
                logger.info(
                    "重解析清理旧抽取实体",
                    document_id=document.id,
                    removed_knowledge=removed.get("knowledge_point", 0),
                    removed_questions=removed.get("question", 0),
                )

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
            document.document_json = self.store.serialize_parse_result(
                parse_result
            )
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
        return await self.store.get_document_detail(document_id)
