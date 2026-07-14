"""考试大纲章节复习指导生成服务。"""

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.infrastructure.ai.llm_client import OutlineLLMClient
from app.models.mysql_models import CanonicalChapter, ExamOutlineSubject
from app.modules.catalog.outline_llm_parser import extract_outline_llm_json
from app.modules.catalog.outline_llm_runtime import load_outline_llm_client
from app.modules.catalog.outline_prompts import build_outline_guidance_prompt

logger = get_logger(__name__)


class OutlineGuidanceService:
    """结合考察目标，批量生成并持久化章节复习指导。"""

    def __init__(
        self,
        db: AsyncSession,
        client: Optional[OutlineLLMClient] = None,
    ):
        self.db = db
        self._client = client

    async def _get_client(self) -> OutlineLLMClient:
        if self._client is None:
            self._client = await load_outline_llm_client(self.db)
        return self._client

    async def generate_for_subject(
        self,
        outline_id: str,
        subject_id: str,
        batch_size: int = 15,
    ) -> Dict[str, Any]:
        """
        为某门课的所有章节批量生成复习指导。

        单批失败不影响其他批次；至少一批成功时保留已生成结果，全部失败才标记 failed。
        """
        link = (
            await self.db.execute(
                select(ExamOutlineSubject).where(
                    ExamOutlineSubject.outline_id == outline_id,
                    ExamOutlineSubject.subject_id == subject_id,
                )
            )
        ).scalar_one_or_none()
        if not link:
            raise ValueError("该大纲下不存在此科目的考察目标记录")

        chapters = (
            await self.db.execute(
                select(CanonicalChapter)
                .where(
                    CanonicalChapter.outline_id == outline_id,
                    CanonicalChapter.subject_id == subject_id,
                )
                .order_by(CanonicalChapter.level, CanonicalChapter.sort_order)
            )
        ).scalars().all()
        if not chapters:
            raise ValueError("该科目下没有章节，无法生成复习指导")

        client = await self._get_client()
        if not client.is_available:
            raise ValueError(
                "大纲拆分 LLM 未启用或缺少配置，请在系统设置 -> outline_llm 配置后重试"
            )

        link.guidance_status = "generating"
        await self.db.commit()

        objective = link.exam_objective or ""
        chapters_by_id = {chapter.id: chapter for chapter in chapters}
        updated = 0
        any_success = False

        for start in range(0, len(chapters), batch_size):
            batch = chapters[start:start + batch_size]
            items = [
                {
                    "id": chapter.id,
                    "code": chapter.outline_code or "",
                    "name": chapter.name,
                    "points": (chapter.description or "")[:500],
                }
                for chapter in batch
            ]
            prompt = build_outline_guidance_prompt(objective, items)
            try:
                text = await client.chat(
                    prompt,
                    purpose="大纲章节复习指导生成",
                )
                data = extract_outline_llm_json(text)
                guidance_map = data.get("guidance") if isinstance(data, dict) else data
                if isinstance(guidance_map, list):
                    guidance_map = {
                        item.get("id"): item.get("guidance")
                        for item in guidance_map
                        if isinstance(item, dict)
                    }
                if not isinstance(guidance_map, dict):
                    raise ValueError("复习指导返回格式不正确")

                for chapter_id, guidance in guidance_map.items():
                    chapter = chapters_by_id.get(chapter_id)
                    if chapter and guidance:
                        chapter.exam_guidance = str(guidance).strip()
                        updated += 1
                any_success = True
                await self.db.commit()
            except Exception as exc:
                logger.warning(
                    "复习指导某批生成失败",
                    outline_id=outline_id,
                    subject_id=subject_id,
                    batch_start=start,
                    error=str(exc),
                )

        link.guidance_status = "done" if any_success else "failed"
        await self.db.commit()

        return {
            "outline_id": outline_id,
            "subject_id": subject_id,
            "guidance_status": link.guidance_status,
            "updated_chapters": updated,
            "total_chapters": len(chapters),
        }
