"""
目录模块的语料 ↔ 大纲章节关联服务

为当前可用的知识点/题目建立与大纲章节的关联。

匹配策略（4层）:
1. 直接读取: entity.primary_chapter_id（已有关联）
2. 文档映射: DocumentSectionMapping（规则匹配）
3. 向量检索: canonical_chapter segments（语义匹配）
4. LLM 推理: 低分候选让 LLM 选择（可选）
"""

from typing import Dict, Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.catalog.chapter_matcher import (
    HIGH_CONFIDENCE_KEYWORD_THRESHOLD,
    SUBJECT_FALLBACK_MARGIN,
    VECTOR_MATCH_THRESHOLD,
    ChapterMatcher,
)
from app.modules.catalog.chapter_compat import resolve_legacy_chapter_id
from app.modules.catalog.chapter_link_store import ChapterLinkStore
from app.modules.catalog.document_chapter_resolver import (
    DocumentSectionChapterResolver,
)
from app.models.mysql_models import (
    CanonicalChapter,
    KnowledgePoint,
    Question,
)

logger = get_logger(__name__)


class ChapterLinkService:
    """语料 ↔ 大纲章节关联服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.matcher = ChapterMatcher(db)
        self.link_store = ChapterLinkStore(db)
        self.document_resolver = DocumentSectionChapterResolver(db)

    # ========== 公共接口 ==========

    async def link_knowledge_point_to_chapters(self, kp_id: str) -> Dict[str, Any]:
        """
        为知识点匹配大纲章节

        返回:
        {
            "linked_count": N,
            "primary_chapter": {...},
            "related_chapters": [...],
            "strategy_used": "existing / document_mapping / vector_search"
        }
        """
        kp = await self.db.get(KnowledgePoint, kp_id)
        if not kp:
            raise ValueError(f"知识点不存在: {kp_id}")

        return await self._link_entity_to_chapters(kp, "knowledge_point")

    async def link_question_to_chapters(self, question_id: str) -> Dict[str, Any]:
        """为题目匹配大纲章节"""
        question = await self.db.get(Question, question_id)
        if not question:
            raise ValueError(f"题目不存在: {question_id}")

        return await self._link_entity_to_chapters(question, "question")

    async def batch_link_document(self, document_id: str) -> Dict[str, Any]:
        """
        批量处理一个文档下的所有可用实体

        返回:
        {
            "knowledge_points": {"linked": N, "failed": M},
            "questions": {"linked": N, "failed": M}
        }
        """
        # 查询该文档下的所有可用知识点
        kps = (await self.db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.source_document_id == document_id,
                KnowledgePoint.status == "active"
            )
        )).scalars().all()

        # 查询该文档下的所有可用题目
        questions = (await self.db.execute(
            select(Question).where(
                Question.source_document_id == document_id,
                Question.status == "active"
            )
        )).scalars().all()

        kp_linked = 0
        kp_failed = 0
        for kp in kps:
            try:
                result = await self.link_knowledge_point_to_chapters(kp.id)
                if result["linked_count"] > 0:
                    kp_linked += 1
                else:
                    kp_failed += 1
            except Exception as e:
                logger.error("批量关联知识点失败", kp_id=kp.id, error=str(e))
                kp_failed += 1

        q_linked = 0
        q_failed = 0
        for q in questions:
            try:
                result = await self.link_question_to_chapters(q.id)
                if result["linked_count"] > 0:
                    q_linked += 1
                else:
                    q_failed += 1
            except Exception as e:
                logger.error("批量关联题目失败", question_id=q.id, error=str(e))
                q_failed += 1

        return {
            "knowledge_points": {"linked": kp_linked, "failed": kp_failed},
            "questions": {"linked": q_linked, "failed": q_failed}
        }

    async def backfill_question_chapters(
        self,
        review_status: str = "pending",
        status: str = "active",
        subject_id: Optional[str] = None,
        limit: int = 500,
        force: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        批量回填题目的章节归属。

        用于新章节解析策略上线后修正历史题目：
        - 默认只处理待审核题目
        - force=False 时跳过已有 primary_chapter_id 的题目
        - force=True 时重新解析并覆盖 subject_id / primary_chapter_id / chapter_id
        """
        query = select(Question).where(Question.status != "deleted")
        if review_status:
            query = query.where(Question.review_status == review_status)
        if status:
            query = query.where(Question.status == status)
        if subject_id:
            query = query.where(Question.subject_id == subject_id)
        query = query.order_by(Question.created_at.desc(), Question.id.desc()).limit(limit)

        questions = (await self.db.execute(query)).scalars().all()
        result: Dict[str, Any] = {
            "scanned": len(questions),
            "updated": 0,
            "unchanged": 0,
            "skipped_existing": 0,
            "missed": 0,
            "failed": 0,
            "dry_run": dry_run,
            "items": [],
        }

        for q in questions:
            if q.primary_chapter_id and not force:
                result["skipped_existing"] += 1
                continue

            try:
                resolved = await self.resolve_chapter_for_entity(
                    title=(q.content or "")[:200],
                    content=q.content or "",
                    subject_id=q.subject_id,
                    topic_terms=q.topic_terms or [],
                    entity_type="question",
                    options=q.options or [],
                )
            except Exception as e:
                result["failed"] += 1
                result["items"].append({
                    "id": q.id,
                    "status": "failed",
                    "error": str(e)[:300],
                })
                continue

            if not resolved:
                result["missed"] += 1
                result["items"].append({
                    "id": q.id,
                    "status": "missed",
                    "old_primary_chapter_id": q.primary_chapter_id,
                })
                continue

            new_primary_chapter_id = resolved["chapter_id"]
            new_subject_id = resolved.get("subject_id") or q.subject_id
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=new_primary_chapter_id,
                subject_id=new_subject_id,
            )

            changed = (
                q.primary_chapter_id != new_primary_chapter_id
                or q.subject_id != new_subject_id
                or (legacy_chapter_id and q.chapter_id != legacy_chapter_id)
            )

            item = {
                "id": q.id,
                "status": "updated" if changed else "unchanged",
                "old_subject_id": q.subject_id,
                "new_subject_id": new_subject_id,
                "old_primary_chapter_id": q.primary_chapter_id,
                "new_primary_chapter_id": new_primary_chapter_id,
                "old_chapter_id": q.chapter_id,
                "new_chapter_id": legacy_chapter_id,
                "source": resolved.get("source"),
                "confidence": resolved.get("confidence"),
            }
            result["items"].append(item)

            if changed:
                result["updated"] += 1
                if not dry_run:
                    q.subject_id = new_subject_id
                    q.primary_chapter_id = new_primary_chapter_id
                    if legacy_chapter_id:
                        q.chapter_id = legacy_chapter_id
            else:
                result["unchanged"] += 1

        if not dry_run:
            await self.db.commit()

        return result

    # ========== 核心匹配逻辑 ==========

    async def _link_entity_to_chapters(
        self, entity, entity_type: str
    ) -> Dict[str, Any]:
        """
        综合 3 层策略匹配章节

        策略优先级:
        1. existing: 直接读取 primary_chapter_id
        2. document_mapping: 通过文档section映射
        3. vector_search: 向量检索

        返回格式见 link_knowledge_point_to_chapters 文档
        """
        results = []
        strategy_used = None

        # 策略 1: 直接读取
        if entity.primary_chapter_id:
            # 检查该章节是否仍然存在
            chapter = await self.db.get(CanonicalChapter, entity.primary_chapter_id)
            if chapter and chapter.status == "active":
                results = [{
                    "chapter_id": entity.primary_chapter_id,
                    "relevance": 1.0,
                    "source": "existing",
                    "is_primary": True
                }]
                strategy_used = "existing"
                logger.info("使用已有关联", entity_id=entity.id, entity_type=entity_type)

        # 策略 2: 文档映射
        if not results and entity.source_document_id:
            mapping_result = await self.document_resolver.resolve(
                entity,
                entity_type,
            )
            if mapping_result:
                results = [mapping_result]
                strategy_used = "document_mapping"
                logger.info("文档映射匹配成功", entity_id=entity.id,
                           chapter_id=mapping_result["chapter_id"])

        # 策略 3: 向量检索
        if not results:
            vector_results = await self._match_by_vector_search(entity, entity_type)
            if vector_results:
                results = vector_results
                strategy_used = "vector_search"
                logger.info("向量检索匹配成功", entity_id=entity.id,
                           count=len(vector_results))

        # 没有任何匹配
        if not results:
            logger.warning("无法匹配章节", entity_id=entity.id, entity_type=entity_type)
            return {
                "linked_count": 0,
                "primary_chapter": None,
                "related_chapters": [],
                "strategy_used": "none"
            }

        # 写入关联表
        return await self.link_store.save_links(
            entity,
            entity_type,
            results,
            strategy_used,
        )

    # ========== 抽取阶段直接解析章节（无 section mapping 时使用） ==========

    async def resolve_chapter_for_entity(
        self,
        title: str,
        content: str,
        subject_id: Optional[str],
        topic_terms: Optional[List[str]] = None,
        entity_type: str = "knowledge_point",
        options: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        抽取时直接为 KP/Question 解析 primary_chapter_id，不依赖 section mapping。

        用于试卷类文档（无 DocumentSection）或教材 section 未映射到大纲的情况。
        两路策略：
        1. 高置信关键词匹配 CanonicalChapter.keywords / aliases / name（精确命中才快速返回）
        2. 向量召回 canonical_chapter segments（题干问法与考点术语不重合时的主力）

        Returns: {"chapter_id", "subject_id", "confidence", "source"} 或 None
        """
        # 路 1: 高置信关键词命中才直接采信。题目正文/选项容易包含干扰术语，跳过内容频次匹配。
        kw_hit = None
        if entity_type != "question" or topic_terms:
            kw_hit = await self._match_by_keyword(
                title=title,
                content=content,
                subject_id=subject_id,
                topic_terms=topic_terms or [],
                include_content=entity_type != "question",
            )
        if kw_hit and kw_hit["confidence"] >= HIGH_CONFIDENCE_KEYWORD_THRESHOLD:
            return kw_hit

        # 路 2: 向量（用一个临时 entity-like 对象复用现有 _match_by_vector_search 逻辑）
        class _EntityProxy:
            def __init__(
                self,
                title: str,
                content: str,
                subject_id: Optional[str],
                options: Optional[List[Dict[str, Any]]] = None,
            ):
                self.title = title
                self.content = content
                self.subject_id = subject_id
                self.options = options or []

        proxy = _EntityProxy(title=title, content=content, subject_id=subject_id, options=options)
        try:
            vec_results = await self._match_by_vector_search(proxy, entity_type)
        except Exception as e:
            logger.warning("抽取阶段向量召回失败", error=str(e))
            return None

        if not vec_results:
            return None

        top = vec_results[0]
        return {
            "chapter_id": top["chapter_id"],
            "subject_id": top.get("subject_id") or subject_id,
            "confidence": top["relevance"],
            "source": "vector_search",
        }

    async def _match_by_keyword(
        self,
        title: str,
        content: str,
        subject_id: Optional[str],
        topic_terms: List[str],
        include_content: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Compatibility delegate for keyword chapter matching."""
        return await self.matcher.match_by_keyword(
            title=title,
            content=content,
            subject_id=subject_id,
            topic_terms=topic_terms,
            include_content=include_content,
        )

    # ========== 策略 3: 向量检索 ==========

    async def _match_by_vector_search(
        self, entity, entity_type: str
    ) -> List[Dict[str, Any]]:
        """Compatibility delegate for vector chapter matching."""
        return await self.matcher.match_by_vector_search(
            entity,
            entity_type,
            search_core=self._vector_search_core,
        )

    async def _vector_search_core(
        self, entity, entity_type: str
    ) -> List[Dict[str, Any]]:
        """Compatibility delegate for the vector search core."""
        return await self.matcher.vector_search_core(entity, entity_type)
