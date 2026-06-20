"""
语料富化增强服务

审核通过后用 LLM 富化题目/知识点，并建立题↔知识点关联：

题目富化 enrich_question：
- 若 answer_source=="extracted"（PDF 答案区已回连）不覆盖答案，只补解析；
  否则 LLM 生成 answer+explanation，标 answer_source/explanation_source="llm"。
- LLM 同时输出"考点标签列表"，用向量检索+规则把标签回连到已有知识点实体：
  连上的写 QuestionKnowledgeLink + 回填 knowledge_point_ids；没连上的暂存 tags（候选新知识点）。

知识点富化 enrich_knowledge_point：LLM 输出 summary/aliases/key_points 写回。

批量入口 enrich_document：按批富化，单个失败不阻塞其他，更新 enrich_status。

enrich_llm 未配置时优雅降级：PDF 抽取的答案仍保留，LLM 部分跳过并标 enrich_status=failed。
"""

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    Question, KnowledgePoint, QuestionKnowledgeLink,
)
from app.services.llm_client import EnrichLLMClient, extract_json_block
from app.services.system_settings_service import SystemSettingsService

logger = get_logger(__name__)

# 标签回连知识点的相似度阈值（向量检索 score）
KP_LINK_SCORE_THRESHOLD = 0.78
# 每个考点标签最多回连的知识点数
KP_LINK_TOP_N = 2


def _gen_id() -> str:
    return uuid.uuid4().hex[:32]


_QUESTION_PROMPT = """下面是一道408考研题目。请富化它，只输出 JSON：
{{"answer": "参考答案（选择题给选项字母如 B / ABCD；主观题给要点式答案）",
 "explanation": "解析（解题思路、考点说明，3-6 句）",
 "knowledge_tags": ["该题所考的知识点，2-5 个，用规范术语，如 二叉树遍历 / 进程调度"],
 "difficulty": "easy|medium|hard"}}

要求：
1. answer 必须给出；若题目本身已含答案信息，忠实整理。
2. knowledge_tags 是这道题考查的核心知识点名词，便于关联到知识库。
3. 只输出 JSON，不要解释文字。

题目：
{question_text}"""

_KNOWLEDGE_PROMPT = """下面是一个408考研知识点。请富化它，只输出 JSON：
{{"summary": "一句话摘要（用于检索召回，30-60 字）",
 "aliases": ["该知识点的常见别名/同义说法，0-4 个"],
 "key_points": ["核心要点，2-5 条"]}}

只输出 JSON，不要解释文字。

知识点标题：{title}
知识点内容：
{content}"""


class EnrichmentService:
    """语料富化增强服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._client: Optional[EnrichLLMClient] = None
        self._retrieval = None  # 延迟加载，避免循环依赖

    async def _get_client(self) -> EnrichLLMClient:
        if self._client is None:
            runtime_settings = await SystemSettingsService(self.db).load()
            cfg = runtime_settings.get("enrich_llm", {})
            self._client = EnrichLLMClient(cfg if isinstance(cfg, dict) else {})
        return self._client

    async def _get_retrieval(self):
        if self._retrieval is None:
            from app.services.retrieval_service import RetrievalService
            self._retrieval = RetrievalService(self.db)
        return self._retrieval

    # ========== 题目富化 ==========

    async def enrich_question(self, question_id: str) -> Dict[str, Any]:
        """富化单道题目：答案/解析 + 考点标签回连知识点。"""
        q = await self.db.get(Question, question_id)
        if not q:
            raise ValueError(f"题目不存在: {question_id}")

        client = await self._get_client()
        if not client.is_available:
            q.enrich_status = "failed"
            await self.db.flush()
            logger.warning("enrich_llm 未配置，题目富化跳过", question_id=question_id)
            return {"question_id": question_id, "enrich_status": "failed", "reason": "enrich_llm_unavailable"}

        q.enrich_status = "enriching"
        await self.db.flush()

        # 拼题目文本（题干 + 选项）
        parts = [q.content or ""]
        if q.options:
            for opt in q.options:
                if isinstance(opt, dict):
                    label = opt.get("key") or opt.get("label") or opt.get("option_label") or ""
                    parts.append(f"{label}. {opt.get('text', '')}")
        question_text = "\n".join(p for p in parts if p)

        try:
            raw = await client.chat(_QUESTION_PROMPT.format(question_text=question_text[:6000]))
            data = extract_json_block(raw)
        except Exception as e:
            q.enrich_status = "failed"
            await self.db.flush()
            logger.warning("题目富化 LLM 失败", question_id=question_id, error=str(e))
            return {"question_id": question_id, "enrich_status": "failed", "reason": str(e)[:200]}

        # 答案：extracted 优先，不覆盖；否则写 LLM 答案
        if q.answer_source != "extracted":
            if data.get("answer"):
                q.answer = str(data["answer"])
                q.answer_source = "llm"
        # 解析：为空才写 LLM 解析（不覆盖已有）
        if not (q.explanation or "").strip() and data.get("explanation"):
            q.explanation = str(data["explanation"])
            q.explanation_source = "llm"
        # 难度：仅在 LLM 给出合法值时更新
        if data.get("difficulty") in ("easy", "medium", "hard"):
            q.difficulty = data["difficulty"]

        # 考点标签回连知识点
        tags = [str(t).strip() for t in (data.get("knowledge_tags") or []) if str(t).strip()]
        linked_kp_ids, unmatched = await self._link_tags_to_knowledge(
            tags, subject_id=q.subject_id, question_id=q.id
        )
        if linked_kp_ids:
            q.knowledge_point_ids = linked_kp_ids
        # 没连上的标签并入 tags（候选新知识点）
        existing_tags = list(q.tags or [])
        for t in unmatched:
            if t not in existing_tags:
                existing_tags.append(t)
        if existing_tags:
            q.tags = existing_tags

        q.enrich_status = "done"
        await self.db.flush()
        logger.info("题目富化完成", question_id=question_id,
                    answer_source=q.answer_source, linked_kp=len(linked_kp_ids), unmatched=len(unmatched))
        return {
            "question_id": question_id,
            "enrich_status": "done",
            "answer_source": q.answer_source,
            "explanation_source": q.explanation_source,
            "linked_knowledge_point_ids": linked_kp_ids,
            "unmatched_tags": unmatched,
        }

    async def _link_tags_to_knowledge(
        self, tags: List[str], subject_id: Optional[str], question_id: str
    ) -> tuple[List[str], List[str]]:
        """把考点标签回连到已有知识点。返回 (已连知识点ID去重列表, 未匹配标签列表)。"""
        if not tags:
            return [], []
        retrieval = await self._get_retrieval()
        # 先清掉该题旧的 link（重富化场景）
        await self.db.execute(
            delete(QuestionKnowledgeLink).where(QuestionKnowledgeLink.question_id == question_id)
        )
        linked_ids: List[str] = []
        unmatched: List[str] = []
        seen: set = set()
        for tag in tags:
            matched = False
            try:
                results = await retrieval.search(
                    query=tag, subject_id=subject_id,
                    entity_type="knowledge_point", mode="hybrid", limit=KP_LINK_TOP_N,
                )
            except Exception as e:
                logger.warning("标签向量回连检索失败", tag=tag, error=str(e))
                results = []
            for r in results:
                if r.score < KP_LINK_SCORE_THRESHOLD:
                    continue
                kp_id = r.entity_id
                if kp_id in seen:
                    matched = True
                    continue
                seen.add(kp_id)
                self.db.add(QuestionKnowledgeLink(
                    id=_gen_id(),
                    question_id=question_id,
                    knowledge_point_id=kp_id,
                    relevance=round(float(r.score), 4),
                    source="vector",
                ))
                linked_ids.append(kp_id)
                matched = True
            if not matched:
                unmatched.append(tag)
        return linked_ids, unmatched

    # ========== 知识点富化 ==========

    async def enrich_knowledge_point(self, kp_id: str) -> Dict[str, Any]:
        """富化单个知识点：summary/aliases/key_points。"""
        kp = await self.db.get(KnowledgePoint, kp_id)
        if not kp:
            raise ValueError(f"知识点不存在: {kp_id}")

        client = await self._get_client()
        if not client.is_available:
            kp.enrich_status = "failed"
            await self.db.flush()
            return {"knowledge_point_id": kp_id, "enrich_status": "failed", "reason": "enrich_llm_unavailable"}

        kp.enrich_status = "enriching"
        await self.db.flush()

        try:
            raw = await client.chat(_KNOWLEDGE_PROMPT.format(
                title=kp.title or "", content=(kp.content or "")[:6000]
            ))
            data = extract_json_block(raw)
        except Exception as e:
            kp.enrich_status = "failed"
            await self.db.flush()
            logger.warning("知识点富化 LLM 失败", kp_id=kp_id, error=str(e))
            return {"knowledge_point_id": kp_id, "enrich_status": "failed", "reason": str(e)[:200]}

        if data.get("summary"):
            kp.summary = str(data["summary"])[:1000]
        aliases = [str(a).strip() for a in (data.get("aliases") or []) if str(a).strip()]
        if aliases:
            merged = list(kp.aliases or [])
            for a in aliases:
                if a not in merged:
                    merged.append(a)
            kp.aliases = merged
        key_points = [str(k).strip() for k in (data.get("key_points") or []) if str(k).strip()]
        if key_points:
            kp.key_points = key_points

        kp.enrich_status = "done"
        await self.db.flush()
        logger.info("知识点富化完成", kp_id=kp_id)
        return {"knowledge_point_id": kp_id, "enrich_status": "done"}

    # ========== 批量入口 ==========

    async def enrich_document(self, document_id: str, batch_size: int = 15) -> Dict[str, Any]:
        """批量富化某文档下所有已审核的题目和知识点。单个失败不阻塞其他。"""
        q_rows = (await self.db.execute(
            select(Question.id).where(
                Question.source_document_id == document_id,
                Question.review_status == "approved",
            )
        )).scalars().all()
        kp_rows = (await self.db.execute(
            select(KnowledgePoint.id).where(
                KnowledgePoint.source_document_id == document_id,
                KnowledgePoint.review_status == "approved",
            )
        )).scalars().all()

        q_done = q_failed = kp_done = kp_failed = 0
        for qid in q_rows:
            try:
                r = await self.enrich_question(qid)
                if r.get("enrich_status") == "done":
                    q_done += 1
                else:
                    q_failed += 1
            except Exception as e:
                q_failed += 1
                logger.warning("题目富化异常，跳过", question_id=qid, error=str(e))
        for kid in kp_rows:
            try:
                r = await self.enrich_knowledge_point(kid)
                if r.get("enrich_status") == "done":
                    kp_done += 1
                else:
                    kp_failed += 1
            except Exception as e:
                kp_failed += 1
                logger.warning("知识点富化异常，跳过", kp_id=kid, error=str(e))

        await self.db.commit()
        logger.info("文档富化完成", document_id=document_id,
                    q_done=q_done, q_failed=q_failed, kp_done=kp_done, kp_failed=kp_failed)
        return {
            "document_id": document_id,
            "questions": {"done": q_done, "failed": q_failed, "total": len(q_rows)},
            "knowledge_points": {"done": kp_done, "failed": kp_failed, "total": len(kp_rows)},
        }
