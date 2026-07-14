"""LLM 大纲拆分结果入库服务。"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import ExamOutlineSubject, OutlineIngestionRun
from app.modules.catalog.outline_persistence import (
    OutlinePersistence,
    generate_outline_id,
)
from app.modules.catalog.outline_tree import count_outline_nodes

logger = get_logger(__name__)


class _AllSubjectsFailed(Exception):
    """触发整批大纲变更保存点回滚。"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OutlineLLMImportService:
    """把 LLM 拆分出的多科目大纲结果可靠地写入目录域。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.persistence = OutlinePersistence(db)

    async def import_result(
        self,
        llm_result: Dict[str, Any],
        name: str,
        year: int,
        version: str = "v1.0",
        description: Optional[str] = None,
        set_default: bool = False,
    ) -> Dict[str, Any]:
        subjects = llm_result.get("subjects") or []
        if not subjects:
            raise ValueError("LLM 拆分结果为空，无法入库")

        run = OutlineIngestionRun(
            id=generate_outline_id(),
            outline_name=name,
            year=year,
            version=version,
            total_subjects=len(subjects),
            status="processing",
            current_stage="importing",
            stage_detail="正在写入大纲和章节树",
            started_at=_utc_now(),
        )
        self.db.add(run)
        await self.db.flush()

        valid_subjects = [
            subject
            for subject in subjects
            if subject.get("chapters") and not subject.get("error")
        ]
        rejected_subjects = [
            subject
            for subject in subjects
            if subject.get("error") or not subject.get("chapters")
        ]
        rejected_summaries = [
            self._failed_summary(
                subject,
                subject.get("error") or "章节为空",
            )
            for subject in rejected_subjects
        ]

        if not valid_subjects:
            error_detail = self._format_failure_detail(rejected_summaries)
            self._finish_run(
                run,
                status="failed",
                summaries=rejected_summaries,
                created=0,
                updated=0,
                error_detail=f"所有科目拆分均失败。{error_detail}",
            )
            await self.db.commit()
            raise ValueError(f"所有科目拆分均失败，无法入库。{error_detail}")

        outline = None
        total_created = 0
        total_updated = 0
        successful_count = 0
        subject_summaries: List[Dict[str, Any]] = []

        try:
            async with self.db.begin_nested():
                outline = await self.persistence.upsert_outline_meta(
                    name=name,
                    year=year,
                    version=version,
                    description=description,
                    set_default=set_default,
                )
                run.outline_id = outline.id

                for index, subject in enumerate(valid_subjects, start=1):
                    subject_name = subject.get("subject_name")
                    run.current_subject_name = subject_name
                    run.stage_detail = (
                        f"正在写入《{subject_name or '未命名科目'}》"
                        f"（{index}/{len(valid_subjects)}）"
                    )
                    await self.db.flush()

                    try:
                        async with self.db.begin_nested():
                            summary = await self._import_subject(
                                outline.id,
                                subject,
                            )
                    except Exception as exc:
                        logger.error(
                            "入库某科目章节树时失败",
                            subject_id=subject.get("subject_id"),
                            error=str(exc),
                        )
                        summary = self._failed_summary(subject, str(exc))
                    else:
                        total_created += summary["created"]
                        total_updated += summary["updated"]
                        successful_count += 1

                    subject_summaries.append(summary)
                    run.processed_subjects = len(rejected_subjects) + index
                    run.successful_subjects = successful_count
                    await self.db.flush()

                if successful_count == 0:
                    raise _AllSubjectsFailed()
        except _AllSubjectsFailed:
            outline = None
            run.outline_id = None
            total_created = 0
            total_updated = 0
        except Exception as exc:
            run.outline_id = None
            failure_summaries = [
                (
                    self._failed_summary(
                        summary,
                        f"整批事务已回滚：{exc}",
                    )
                    if summary.get("status") == "success"
                    else summary
                )
                for summary in subject_summaries
            ]
            failure_summaries.extend(rejected_summaries)
            self._finish_run(
                run,
                status="failed",
                summaries=failure_summaries,
                created=0,
                updated=0,
                error_detail=f"大纲入库失败：{exc}",
            )
            await self.db.commit()
            raise

        subject_summaries.extend(rejected_summaries)
        failed_count = len(
            [
                summary
                for summary in subject_summaries
                if summary.get("status") == "failed"
            ]
        )

        if successful_count == 0:
            error_detail = self._format_failure_detail(subject_summaries)
            self._finish_run(
                run,
                status="failed",
                summaries=subject_summaries,
                created=0,
                updated=0,
                error_detail=f"所有科目入库均失败。{error_detail}",
            )
            await self.db.commit()
            raise ValueError(f"所有科目入库均失败。{error_detail}")

        status = "partial" if failed_count else "done"
        self._finish_run(
            run,
            status=status,
            summaries=subject_summaries,
            created=total_created,
            updated=total_updated,
            error_detail=(
                self._format_failure_detail(subject_summaries)
                if failed_count
                else None
            ),
        )
        await self.db.commit()

        await self._build_outline_segments(outline.id)

        return {
            "outline_id": outline.id,
            "outline_name": outline.name,
            "year": outline.year,
            "version": outline.version,
            "created_chapters": total_created,
            "updated_chapters": total_updated,
            "subjects": subject_summaries,
            "partial": failed_count > 0,
            "total_subjects": len(subjects),
            "successful_subjects": successful_count,
            "failed_subjects": failed_count,
            "run_id": run.id,
        }

    async def _import_subject(
        self,
        outline_id: str,
        subject: Dict[str, Any],
    ) -> Dict[str, Any]:
        subject_id = subject.get("subject_id")
        chapters = subject.get("chapters") or []
        if not subject_id or not chapters:
            raise ValueError("科目 ID 或章节树为空")

        link = (
            await self.db.execute(
                select(ExamOutlineSubject).where(
                    ExamOutlineSubject.outline_id == outline_id,
                    ExamOutlineSubject.subject_id == subject_id,
                )
            )
        ).scalar_one_or_none()
        chapter_count = count_outline_nodes(chapters)
        if link:
            link.exam_objective = (
                subject.get("exam_objective") or link.exam_objective
            )
            link.chapter_count = chapter_count
            link.guidance_status = "pending"
        else:
            link = ExamOutlineSubject(
                id=generate_outline_id(),
                outline_id=outline_id,
                subject_id=subject_id,
                exam_objective=subject.get("exam_objective"),
                chapter_count=chapter_count,
                guidance_status="pending",
            )
            self.db.add(link)
            await self.db.flush()

        created, updated = await self.persistence.upsert_chapters(
            subject_id=subject_id,
            outline_id=outline_id,
            chapters=chapters,
        )
        return {
            "subject_id": subject_id,
            "subject_name": subject.get("subject_name"),
            "chapter_count": chapter_count,
            "created": created,
            "updated": updated,
            "status": "success",
        }

    async def _build_outline_segments(self, outline_id: str) -> None:
        try:
            from app.modules.retrieval.segment_service import SegmentService

            result = await SegmentService(
                self.db
            ).build_canonical_chapter_segments(
                outline_id=outline_id,
                rebuild=False,
            )
            logger.info(
                "大纲章节 segment 构建完成",
                outline_id=outline_id,
                count=result.get("segments_count", 0),
            )
        except Exception as exc:
            logger.warning(
                "大纲章节 segment 构建失败（不影响大纲入库）",
                outline_id=outline_id,
                error=str(exc),
            )

    @staticmethod
    def _failed_summary(
        subject: Dict[str, Any],
        error: str,
    ) -> Dict[str, Any]:
        return {
            "subject_id": subject.get("subject_id"),
            "subject_name": subject.get("subject_name"),
            "status": "failed",
            "error": error,
        }

    @staticmethod
    def _format_failure_detail(
        summaries: List[Dict[str, Any]],
    ) -> str:
        failures = [
            summary
            for summary in summaries
            if summary.get("status") == "failed"
        ]
        return "; ".join(
            (
                f"{summary.get('subject_name') or '未命名科目'}: "
                f"{summary.get('error') or '未知错误'}"
            )
            for summary in failures
        )

    @staticmethod
    def _finish_run(
        run: OutlineIngestionRun,
        *,
        status: str,
        summaries: List[Dict[str, Any]],
        created: int,
        updated: int,
        error_detail: Optional[str],
    ) -> None:
        successful = len(
            [
                summary
                for summary in summaries
                if summary.get("status") == "success"
            ]
        )
        run.status = status
        run.current_stage = "failed" if status == "failed" else "completed"
        run.stage_detail = (
            f"入库完成，成功 {successful}/{run.total_subjects} 个科目"
            if status != "failed"
            else f"入库失败，成功 {successful}/{run.total_subjects} 个科目"
        )
        run.current_subject_name = None
        run.processed_subjects = run.total_subjects
        run.successful_subjects = successful
        run.created_chapters = created
        run.updated_chapters = updated
        run.error_detail = error_detail
        run.result_summary = {"subjects": summaries}
        run.completed_at = _utc_now()
