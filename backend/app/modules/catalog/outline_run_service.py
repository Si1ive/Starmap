"""大纲解析与入库任务的查询和维护服务。"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import OutlineIngestionRun


def _progress(run: OutlineIngestionRun) -> float:
    if run.total_subjects > 0:
        return round(
            run.processed_subjects / run.total_subjects * 100,
            1,
        )
    return 0


def _isoformat(value: Any) -> Optional[str]:
    return value.isoformat() if value else None


def serialize_outline_run(
    run: OutlineIngestionRun,
    *,
    include_result_summary: bool,
) -> Dict[str, Any]:
    """按管理端任务契约序列化一条执行记录。"""
    data = {
        "id": run.id,
        "document_id": run.document_id,
        "outline_id": run.outline_id,
        "outline_name": run.outline_name,
        "year": run.year,
        "version": run.version,
        "status": run.status,
        "current_stage": run.current_stage,
        "stage_detail": run.stage_detail,
        "progress": _progress(run),
        "total_subjects": run.total_subjects,
        "processed_subjects": run.processed_subjects,
        "successful_subjects": run.successful_subjects,
        "current_subject_name": run.current_subject_name,
        "created_chapters": run.created_chapters,
        "updated_chapters": run.updated_chapters,
        "error_detail": run.error_detail,
        "started_at": _isoformat(run.started_at),
        "completed_at": _isoformat(run.completed_at),
        "created_at": _isoformat(run.created_at),
    }
    if include_result_summary:
        data["result_summary"] = run.result_summary
    else:
        data["file_name"] = (
            (run.result_summary or {}).get("file_name")
            if isinstance(run.result_summary, dict)
            else None
        )
    return data


class OutlineRunService:
    """管理大纲解析和入库任务记录。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_detail(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = await self.db.get(OutlineIngestionRun, run_id)
        if not run:
            return None
        return serialize_outline_run(
            run,
            include_result_summary=True,
        )

    async def list_runs(
        self,
        *,
        document_id: Optional[str],
        status: Optional[str],
        limit: int,
    ) -> Dict[str, List[Dict[str, Any]]]:
        query = (
            select(OutlineIngestionRun)
            .order_by(OutlineIngestionRun.created_at.desc())
            .limit(limit)
        )
        if document_id:
            query = query.where(
                OutlineIngestionRun.document_id == document_id
            )
        if status:
            query = query.where(OutlineIngestionRun.status == status)

        runs = (await self.db.execute(query)).scalars().all()
        return {
            "items": [
                serialize_outline_run(
                    run,
                    include_result_summary=False,
                )
                for run in runs
            ]
        }

    async def delete_run(self, run_id: str) -> bool:
        run = await self.db.get(OutlineIngestionRun, run_id)
        if not run:
            return False
        await self.db.delete(run)
        await self.db.commit()
        return True

    async def batch_delete(self, run_ids: List[str]) -> Dict[str, int]:
        requested_count = len(set(run_ids))
        if not run_ids:
            return {
                "deleted_count": 0,
                "requested_count": 0,
            }

        runs = (
            await self.db.execute(
                select(OutlineIngestionRun).where(
                    OutlineIngestionRun.id.in_(run_ids)
                )
            )
        ).scalars().all()
        for run in runs:
            await self.db.delete(run)
        await self.db.commit()
        return {
            "deleted_count": len(runs),
            "requested_count": requested_count,
        }
