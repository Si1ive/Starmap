"""
语料 ↔ 大纲章节关联服务

当知识点/题目审核通过后，自动建立与大纲章节的关联。

匹配策略（4层）:
1. 直接读取: entity.primary_chapter_id（已有关联）
2. 文档映射: DocumentSectionMapping（规则匹配）
3. 向量检索: canonical_chapter segments（语义匹配）
4. LLM 推理: 低分候选让 LLM 选择（可选）
"""

import uuid
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    KnowledgePoint, Question, CanonicalChapter,
    KnowledgePointChapterLink, QuestionChapterLink,
    EntitySourceLink, DocumentBlock, DocumentSection, DocumentSectionMapping
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id

logger = get_logger(__name__)

HIGH_CONFIDENCE_KEYWORD_THRESHOLD = 0.85
VECTOR_MATCH_THRESHOLD = 0.55
SUBJECT_FALLBACK_MARGIN = 0.05


def _gen_id() -> str:
    return uuid.uuid4().hex[:32]


class ChapterLinkService:
    """语料 ↔ 大纲章节关联服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

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
        批量处理一个文档下的所有已审核实体

        返回:
        {
            "knowledge_points": {"linked": N, "failed": M},
            "questions": {"linked": N, "failed": M}
        }
        """
        # 查询该文档下的所有已审核知识点
        kps = (await self.db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.source_document_id == document_id,
                KnowledgePoint.review_status == "approved"
            )
        )).scalars().all()

        # 查询该文档下的所有已审核题目
        questions = (await self.db.execute(
            select(Question).where(
                Question.source_document_id == document_id,
                Question.review_status == "approved"
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
        status: str = "pending",
        subject_id: Optional[str] = None,
        limit: int = 500,
        force: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        批量回填题目的章节归属。

        用于新章节解析策略上线后修正历史 pending 题目：
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
            mapping_result = await self._match_by_document_mapping(entity, entity_type)
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
        return await self._save_links(entity, entity_type, results, strategy_used)

    # ========== 策略 2: 文档映射 ==========

    async def _match_by_document_mapping(
        self, entity, entity_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        通过文档section映射查找章节

        流程:
        1. entity → EntitySourceLink → 第一个 block
        2. block.page_no → DocumentSection (该页所在的section)
        3. DocumentSection → DocumentSectionMapping (approved)
        4. 返回 canonical_chapter_id
        """
        # 1. 查询实体的第一个来源 block
        source_link_query = select(EntitySourceLink).where(
            EntitySourceLink.entity_type == entity_type,
            EntitySourceLink.entity_id == entity.id
        ).order_by(EntitySourceLink.id).limit(1)

        source_link = (await self.db.execute(source_link_query)).scalar_one_or_none()
        if not source_link or not source_link.block_ids:
            return None

        first_block_id = source_link.block_ids[0]
        block = await self.db.get(DocumentBlock, first_block_id)
        if not block:
            return None

        # 2. 查询该页所在的 DocumentSection（取最深层级的）
        section_query = select(DocumentSection).where(
            DocumentSection.document_id == entity.source_document_id,
            DocumentSection.page_start <= block.page_no,
            DocumentSection.page_end >= block.page_no
        ).order_by(DocumentSection.level.desc())  # 优先取最深层级

        section = (await self.db.execute(section_query)).scalar_one_or_none()
        if not section:
            return None

        # 3. 查询该 section 的 approved 映射
        mapping_query = select(DocumentSectionMapping).where(
            DocumentSectionMapping.document_section_id == section.id,
            DocumentSectionMapping.review_status == "approved"
        ).order_by(DocumentSectionMapping.confidence.desc())

        mapping = (await self.db.execute(mapping_query)).scalar_one_or_none()
        if not mapping:
            return None

        return {
            "chapter_id": mapping.canonical_chapter_id,
            "relevance": float(mapping.confidence),
            "source": "document_mapping",
            "is_primary": True,
            "mapping_type": mapping.mapping_type
        }

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
        """
        在 CanonicalChapter 表里按 name / aliases / keywords / outline_code 做关键词匹配。

        打分（取最高）：
          - 标题或 topic_term 精确等于 chapter.name → 1.0
          - 等于某个 alias → 0.9
          - 等于某个 keyword → 0.88
          - 标题/topic_term 包含 keyword 或反之 → 0.78
          - 标题包含 chapter.name 或反之 → 0.75

        返回 confidence ≥ 0.75 的最佳匹配，否则 None。
        """
        if not (title or content or topic_terms):
            return None

        query = select(CanonicalChapter).where(CanonicalChapter.status == "active")
        if subject_id:
            query = query.where(CanonicalChapter.subject_id == subject_id)
        chapters = (await self.db.execute(query)).scalars().all()
        if not chapters:
            return None

        title_norm = (title or "").strip().lower()
        terms_norm = [t.strip().lower() for t in (topic_terms or []) if t and t.strip()]
        # 待匹配的"短文本"候选：标题 + topic_terms，用来对齐 chapter name/alias/keyword（路径 A）
        probes = [p for p in [title_norm, *terms_norm] if p]
        # 题干/正文全文，用于关键词频次匹配（路径 B）。题目调用会关闭，避免选项术语误挂。
        content_l = (content or "").strip().lower() if include_content else ""
        if not probes and not content_l:
            return None

        best: Optional[Tuple[float, CanonicalChapter]] = None
        for ch in chapters:
            name_l = (ch.name or "").strip().lower()
            aliases_l = [(a or "").strip().lower() for a in (ch.aliases or []) if a]
            keywords_l = [(k or "").strip().lower() for k in (ch.keywords or []) if k]

            score = 0.0

            # 路径 A：干净 probe（KP 标题 / topic_terms）做精确匹配。
            # 只用相等，不做"长文本包含短词"——否则长题干会把任意短 keyword 吞成子串。
            for p in probes:
                if len(p) < 2:
                    continue
                if name_l and p == name_l:
                    score = max(score, 1.0)
                elif p in aliases_l:
                    score = max(score, 0.9)
                elif p in keywords_l:
                    score = max(score, 0.88)
                # probe 是 name 的子串（probe 更短，如别名片段），方向受限：只允许 probe⊆name
                elif name_l and len(p) >= 3 and p in name_l:
                    score = max(score, 0.8)

            # 路径 B：题干内容做关键词频次匹配（题目无干净标题时的主力）。
            # 只数长度 ≥3 的 specific 关键词，排除"图/序/锁"这类通用短词，避免噪声。
            specific_kw = {k for k in keywords_l if len(k) >= 3}
            if name_l and len(name_l) >= 4:
                specific_kw.add(name_l)
            for a in aliases_l:
                if len(a) >= 3:
                    specific_kw.add(a)
            hits = {k for k in specific_kw if k in content_l}
            if hits:
                strong_hits = {k for k in hits if len(k) >= 4}
                if len(hits) >= 2:
                    score = max(score, min(0.78 + 0.04 * len(hits), 0.9))
                elif strong_hits:
                    # 单个长度 ≥4 的强特征词（如 RISC / SPOOLing / 段页式）
                    score = max(score, 0.78)

            if best is None or score > best[0]:
                best = (score, ch)

        if not best or best[0] < 0.75:
            return None

        score, ch = best
        return {
            "chapter_id": ch.id,
            "subject_id": ch.subject_id,
            "confidence": round(score, 4),
            "source": "keyword_match",
        }

    # ========== 策略 3: 向量检索 ==========

    async def _match_by_vector_search(
        self, entity, entity_type: str
    ) -> List[Dict[str, Any]]:
        """用实体内容在 canonical_chapter segments 中检索，返回最多 top-3 相关章节。

        包装层：负责向量召回日志记录（side-effect，失败不影响召回）。
        核心检索逻辑在 _vector_search_core。
        """
        from app.services.vector_recall_recorder import VectorRecallRecorder

        # 构造入参文本（与 core 内一致的口径，用于日志展示）
        if entity_type == "knowledge_point":
            query_text = f"{getattr(entity, 'title', '') or ''}\n{(getattr(entity, 'content', '') or '')[:500]}"
        else:
            query_text = (getattr(entity, "content", "") or "")[:300]

        rec = VectorRecallRecorder(
            called_by=entity_type,
            purpose="章节归属向量召回",
            query_text=query_text,
            query_entity_id=getattr(entity, "id", None),
            subject_id=getattr(entity, "subject_id", None),
        ).start()

        try:
            candidates = await self._vector_search_core(entity, entity_type)
        except Exception as e:
            rec.record_error(e)
            await rec.persist()
            raise

        # 补充 chapter 名称，便于日志可读
        name_map: Dict[str, str] = {}
        try:
            for c in candidates:
                cid = c.get("chapter_id")
                if cid and cid not in name_map:
                    ch = await self.db.get(CanonicalChapter, cid)
                    if ch:
                        name_map[cid] = ch.name
        except Exception:
            name_map = {}

        rec.record_results(candidates, threshold=VECTOR_MATCH_THRESHOLD, chapter_name_map=name_map)
        await rec.persist()
        return candidates

    async def _vector_search_core(
        self, entity, entity_type: str
    ) -> List[Dict[str, Any]]:
        """
        用实体内容在 canonical_chapter segments 中检索

        返回: 最多 top-3 相关章节
        """
        from app.services.embedding_service import get_embedding_service_from_settings
        from app.db.qdrant import qdrant_manager
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        # 1. 构造查询文本
        if entity_type == "knowledge_point":
            query_texts = [f"{entity.title}\n{(entity.content or '')[:500]}"]
        else:  # question
            options_text = "\n".join([
                f"{opt.get('key', '')}. {opt.get('text', '')}"
                for opt in (entity.options or [])[:4]
            ])
            stem_text = entity.content[:300]
            query_texts = [stem_text]
            if options_text.strip():
                query_texts.append(f"{stem_text}\n{options_text[:200]}")

        query_texts = [text for text in query_texts if text.strip()]
        if not query_texts:
            return []

        # 2. 生成 embedding
        try:
            embedding_service = await get_embedding_service_from_settings(self.db)
            if len(query_texts) == 1:
                query_vectors = [await embedding_service.embed_text(query_texts[0])]
            else:
                query_vectors = await embedding_service.embed_batch(query_texts)
        except Exception as e:
            logger.error("生成 embedding 失败", error=str(e))
            return []

        def _build_filter(subject_id: Optional[str] = None) -> Filter:
            must = [
                FieldCondition(key="entity_type", match=MatchValue(value="canonical_chapter")),
            ]
            if subject_id:
                must.append(FieldCondition(key="subject_id", match=MatchValue(value=subject_id)))
            return Filter(must=must)

        def _aggregate(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            chapter_scores: Dict[str, Dict[str, Any]] = {}
            for hit in results:
                payload = hit.get("payload") or {}
                chapter_id = payload.get("entity_id")
                if not chapter_id:
                    continue
                score = hit.get("score", 0)
                current = chapter_scores.get(chapter_id)
                if not current or score > current["score"]:
                    chapter_scores[chapter_id] = {
                        "score": score,
                        "subject_id": payload.get("subject_id"),
                    }

            candidates = []
            for i, (cid, data) in enumerate(
                sorted(chapter_scores.items(), key=lambda x: -x[1]["score"])
            ):
                score = data["score"]
                if score < VECTOR_MATCH_THRESHOLD:
                    continue
                candidates.append({
                    "chapter_id": cid,
                    "subject_id": data.get("subject_id"),
                    "relevance": score,
                    "source": "vector_search",
                    "is_primary": i == 0,
                })
            return candidates[:3]

        def _search_with_filter(query_filter: Filter) -> List[Dict[str, Any]]:
            results: List[Dict[str, Any]] = []
            for query_vector in query_vectors:
                results.extend(qdrant_manager.search(
                    collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=10,
                ))
            return results

        # 3. Qdrant 检索：同时看当前 subject 与全学科。
        # 当全学科 top 明显更高时，认为抽取阶段 subject_id 可能错误，允许纠正。
        try:
            if getattr(entity, "subject_id", None):
                subject_candidates = _aggregate(
                    _search_with_filter(_build_filter(getattr(entity, "subject_id", None)))
                )
                all_candidates = _aggregate(_search_with_filter(_build_filter()))
                if not subject_candidates:
                    return all_candidates
                if (
                    all_candidates
                    and all_candidates[0]["chapter_id"] != subject_candidates[0]["chapter_id"]
                    and all_candidates[0]["relevance"] >= subject_candidates[0]["relevance"] + SUBJECT_FALLBACK_MARGIN
                ):
                    return all_candidates
                return subject_candidates

            return _aggregate(_search_with_filter(_build_filter()))
        except Exception as e:
            logger.error("Qdrant 检索失败", error=str(e))
            return []

        return []

    # ========== 保存关联 ==========

    async def _save_links(
        self, entity, entity_type: str, results: List[Dict[str, Any]], strategy_used: str
    ) -> Dict[str, Any]:
        """
        写入关联表并返回结果

        处理去重: 如果关联已存在，更新 relevance/source
        """
        primary = None
        related = []

        for res in results:
            chapter_id = res["chapter_id"]

            # 检查章节是否存在
            chapter = await self.db.get(CanonicalChapter, chapter_id)
            if not chapter or chapter.status != "active":
                continue

            # 检查是否已有关联
            if entity_type == "knowledge_point":
                existing_link = (await self.db.execute(
                    select(KnowledgePointChapterLink).where(
                        KnowledgePointChapterLink.knowledge_point_id == entity.id,
                        KnowledgePointChapterLink.canonical_chapter_id == chapter_id
                    )
                )).scalar_one_or_none()

                if existing_link:
                    # 更新已有关联
                    existing_link.relevance = res["relevance"]
                    existing_link.source = res["source"]
                    existing_link.is_primary = res.get("is_primary", False)
                else:
                    # 创建新关联
                    link = KnowledgePointChapterLink(
                        knowledge_point_id=entity.id,
                        canonical_chapter_id=chapter_id,
                        is_primary=res.get("is_primary", False),
                        relevance=res["relevance"],
                        source=res["source"],
                        created_by="system"
                    )
                    self.db.add(link)
            else:  # question
                existing_link = (await self.db.execute(
                    select(QuestionChapterLink).where(
                        QuestionChapterLink.question_id == entity.id,
                        QuestionChapterLink.canonical_chapter_id == chapter_id
                    )
                )).scalar_one_or_none()

                if existing_link:
                    existing_link.relevance = res["relevance"]
                    existing_link.source = res["source"]
                    existing_link.is_primary = res.get("is_primary", False)
                else:
                    link = QuestionChapterLink(
                        question_id=entity.id,
                        canonical_chapter_id=chapter_id,
                        is_primary=res.get("is_primary", False),
                        relevance=res["relevance"],
                        source=res["source"],
                        created_by="system"
                    )
                    self.db.add(link)

            # 构造返回信息
            chapter_info = {
                "id": chapter.id,
                "name": chapter.name,
                "outline_code": chapter.outline_code,
                "level": chapter.level,
                "relevance": res["relevance"],
                "source": res["source"]
            }

            if res.get("is_primary"):
                primary = chapter_info
            else:
                related.append(chapter_info)

        await self.db.commit()

        return {
            "linked_count": len(results),
            "primary_chapter": primary,
            "related_chapters": related,
            "strategy_used": strategy_used
        }
