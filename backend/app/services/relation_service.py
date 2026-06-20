"""
知识点关系构建服务

构建知识点之间的关系边，支持：
- prerequisite: 先修关系
- contrast_with: 对比关系
- common_confusion: 易混淆关系
- contains: 包含关系
- part_of: 属于关系
- used_in: 应用于关系
- similar_to: 相似关系
"""

import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    KnowledgePoint, KnowledgeRelation, EntitySourceLink
)

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


# 关系类型优先级
RELATION_PRIORITY = {
    "common_confusion": 1,
    "contrast_with": 2,
    "prerequisite": 3,
    "contains": 4,
    "part_of": 5,
    "used_in": 6,
    "similar_to": 7,
}


class RelationService:
    """知识点关系构建服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_relations(
        self,
        subject_id: Optional[str] = None,
        knowledge_point_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        构建知识点关系

        首版实现：基于术语相似度和规则
        后续可扩展为 LLM 抽取

        Args:
            subject_id: 学科ID（可选）
            knowledge_point_ids: 知识点ID列表（可选）

        Returns:
            构建结果统计
        """
        # 1. 获取知识点
        query = select(KnowledgePoint)
        if subject_id:
            query = query.where(KnowledgePoint.subject_id == subject_id)
        if knowledge_point_ids:
            query = query.where(KnowledgePoint.id.in_(knowledge_point_ids))

        result = await self.db.execute(query)
        knowledge_points = result.scalars().all()

        if len(knowledge_points) < 2:
            return {"relations_count": 0, "message": "知识点数量不足，无法构建关系"}

        # 2. 删除旧的关系（如果指定知识点）
        if knowledge_point_ids:
            from sqlalchemy import delete
            await self.db.execute(
                delete(KnowledgeRelation).where(
                    or_(
                        KnowledgeRelation.source_knowledge_id.in_(knowledge_point_ids),
                        KnowledgeRelation.target_knowledge_id.in_(knowledge_point_ids),
                    )
                )
            )

        # 3. 构建关系
        relations_count = 0
        kp_list = list(knowledge_points)

        for i in range(len(kp_list)):
            for j in range(i + 1, len(kp_list)):
                kp1 = kp_list[i]
                kp2 = kp_list[j]

                # 检测关系
                relations = self._detect_relations(kp1, kp2)

                for relation_type, confidence, evidence, direction in relations:
                    # 检查关系是否已存在
                    existing = await self._check_relation_exists(
                        kp1.id, kp2.id, relation_type
                    )
                    if existing:
                        continue

                    # 创建关系
                    if direction == "forward":
                        source_id, target_id = kp1.id, kp2.id
                    elif direction == "backward":
                        source_id, target_id = kp2.id, kp1.id
                    else:
                        source_id, target_id = kp1.id, kp2.id

                    relation = KnowledgeRelation(
                        id=generate_id(),
                        source_knowledge_id=source_id,
                        target_knowledge_id=target_id,
                        relation_type=relation_type,
                        directionality="directed" if direction != "both" else "undirected",
                        evidence_text=evidence,
                        confidence=confidence,
                        source_type="term_similarity",
                        review_status="pending",
                    )
                    self.db.add(relation)
                    relations_count += 1

        # 3.5 语义相似度边：用知识点 summary/title 的 embedding 算余弦，
        # 超阈值且尚无关系的配对补 similar_to（source_type="embedding"）。
        try:
            semantic_count = await self._build_semantic_edges(kp_list)
            relations_count += semantic_count
        except Exception as e:
            semantic_count = 0
            logger.warning("语义相似度关系构建失败，跳过", error=str(e))

        await self.db.commit()

        logger.info(
            "关系构建完成",
            subject_id=subject_id,
            relations_count=relations_count,
            semantic_count=semantic_count,
        )

        return {
            "relations_count": relations_count,
            "knowledge_points_count": len(knowledge_points),
        }

    # 语义相似度阈值（cosine）：超过则建 similar_to 边
    SEMANTIC_SIM_THRESHOLD = 0.82
    # 每个知识点最多补的语义边数，避免稠密爆炸
    SEMANTIC_TOP_N = 3

    async def _build_semantic_edges(self, kp_list: List[KnowledgePoint]) -> int:
        """
        语义相似度边：对每个知识点取 summary/title 的 embedding，
        两两算 cosine，超阈值且尚无关系的配对补 similar_to（source_type="embedding"）。
        """
        if len(kp_list) < 2:
            return 0

        from app.services.embedding_service import get_embedding_service_from_settings

        embedding = await get_embedding_service_from_settings(self.db)
        # 富化后优先用 summary，没有则退回 title + topic_terms
        texts: List[str] = []
        for kp in kp_list:
            base = (getattr(kp, "summary", None) or kp.title or "").strip()
            if kp.topic_terms:
                base = f"{base} {' '.join(kp.topic_terms)}"
            texts.append(base or kp.title or "")
        vectors = await embedding.embed_batch(texts)

        def _cosine(a: List[float], b: List[float]) -> float:
            import math
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            if na == 0 or nb == 0:
                return 0.0
            return dot / (na * nb)

        count = 0
        n = len(kp_list)
        for i in range(n):
            # 收集 i 与其它点的相似度，取 top-N 超阈值
            sims: List[Tuple[int, float]] = []
            for j in range(n):
                if i == j:
                    continue
                sim = _cosine(vectors[i], vectors[j])
                if sim >= self.SEMANTIC_SIM_THRESHOLD:
                    sims.append((j, sim))
            sims.sort(key=lambda x: x[1], reverse=True)
            for j, sim in sims[: self.SEMANTIC_TOP_N]:
                kp1, kp2 = kp_list[i], kp_list[j]
                # 无向去重：只在 i<j 方向落库
                if i >= j:
                    continue
                if await self._check_relation_exists(kp1.id, kp2.id, "similar_to"):
                    continue
                self.db.add(KnowledgeRelation(
                    id=generate_id(),
                    source_knowledge_id=kp1.id,
                    target_knowledge_id=kp2.id,
                    relation_type="similar_to",
                    directionality="undirected",
                    evidence_text=f"语义相似度 {sim:.2f}",
                    confidence=round(float(sim), 4),
                    source_type="embedding",
                    review_status="pending",
                ))
                count += 1
        return count

    def _detect_relations(
        self,
        kp1: KnowledgePoint,
        kp2: KnowledgePoint,
    ) -> List[Tuple[str, float, Optional[str], str]]:
        """
        检测两个知识点之间的关系

        Returns:
            List of (relation_type, confidence, evidence, direction)
        """
        relations = []

        # 获取术语集合
        terms1 = set(kp1.topic_terms or []) | {kp1.title}
        terms2 = set(kp2.topic_terms or []) | {kp2.title}

        # 计算术语相似度
        common_terms = terms1 & terms2
        if not common_terms:
            # 没有共同术语，检查是否在同一章节
            if kp1.primary_chapter_id and kp1.primary_chapter_id == kp2.primary_chapter_id:
                # 同一章节，可能是相似或对比关系
                relations.append(("similar_to", 0.5, "同一章节", "both"))
            return relations

        # 有共同术语
        term_similarity = len(common_terms) / max(len(terms1), len(terms2), 1)

        # 检查是否是易混淆关系
        # 策略：标题相似但内容不同
        title_sim = self._string_similarity(kp1.title, kp2.title)
        if title_sim > 0.6 and title_sim < 0.95:
            evidence = f"标题相似度 {title_sim:.2f}，共同术语: {', '.join(list(common_terms)[:3])}"
            relations.append(("common_confusion", 0.7, evidence, "both"))

        # 检查是否是对比关系
        # 策略：包含对比关键词
        contrast_keywords = ['vs', '对比', '比较', '区别', '差异', '不同', '相反']
        content1 = (kp1.content or "").lower()
        content2 = (kp2.content or "").lower()
        for kw in contrast_keywords:
            if kw in content1 or kw in content2:
                evidence = f"包含对比关键词: {kw}"
                relations.append(("contrast_with", 0.6, evidence, "both"))
                break

        # 检查是否是先修关系
        # 策略：一个知识点的内容提到另一个是前置知识
        prerequisite_keywords = ['前置', '先修', '基础', '预备', '需要先了解', '首先']
        for kw in prerequisite_keywords:
            if kw in content1 and kp2.title in content1:
                evidence = f"内容提到需要先了解: {kp2.title}"
                relations.append(("prerequisite", 0.7, evidence, "backward"))
                break
            if kw in content2 and kp1.title in content2:
                evidence = f"内容提到需要先了解: {kp1.title}"
                relations.append(("prerequisite", 0.7, evidence, "forward"))
                break

        # 如果没有检测到特定关系，但有共同术语，标记为相似
        if not relations and term_similarity > 0.3:
            evidence = f"共同术语: {', '.join(list(common_terms)[:3])}"
            relations.append(("similar_to", 0.5 + term_similarity * 0.3, evidence, "both"))

        return relations

    def _string_similarity(self, s1: str, s2: str) -> float:
        """计算两个字符串的相似度（简单实现）"""
        if not s1 or not s2:
            return 0.0

        s1 = s1.lower().strip()
        s2 = s2.lower().strip()

        if s1 == s2:
            return 1.0

        # 使用字符级别的 Jaccard 相似度
        set1 = set(s1)
        set2 = set(s2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    async def _check_relation_exists(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
    ) -> bool:
        """检查关系是否已存在"""
        result = await self.db.execute(
            select(KnowledgeRelation).where(
                or_(
                    and_(
                        KnowledgeRelation.source_knowledge_id == source_id,
                        KnowledgeRelation.target_knowledge_id == target_id,
                        KnowledgeRelation.relation_type == relation_type,
                    ),
                    and_(
                        KnowledgeRelation.source_knowledge_id == target_id,
                        KnowledgeRelation.target_knowledge_id == source_id,
                        KnowledgeRelation.relation_type == relation_type,
                    ),
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_relations(
        self,
        knowledge_point_id: str,
        relation_type: Optional[str] = None,
        review_status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取知识点的关系列表"""
        query = (
            select(KnowledgeRelation, KnowledgePoint)
            .join(
                KnowledgePoint,
                or_(
                    and_(
                        KnowledgeRelation.target_knowledge_id == KnowledgePoint.id,
                        KnowledgeRelation.source_knowledge_id == knowledge_point_id,
                    ),
                    and_(
                        KnowledgeRelation.source_knowledge_id == KnowledgePoint.id,
                        KnowledgeRelation.target_knowledge_id == knowledge_point_id,
                    ),
                )
            )
            .where(
                or_(
                    KnowledgeRelation.source_knowledge_id == knowledge_point_id,
                    KnowledgeRelation.target_knowledge_id == knowledge_point_id,
                )
            )
        )

        if relation_type:
            query = query.where(KnowledgeRelation.relation_type == relation_type)
        if review_status:
            query = query.where(KnowledgeRelation.review_status == review_status)

        result = await self.db.execute(query)
        rows = result.all()

        relations = []
        for relation, kp in rows:
            # 确定是源还是目标
            if relation.source_knowledge_id == knowledge_point_id:
                related_kp_id = relation.target_knowledge_id
                direction = "outgoing"
            else:
                related_kp_id = relation.source_knowledge_id
                direction = "incoming"

            relations.append({
                "relation_id": relation.id,
                "relation_type": relation.relation_type,
                "directionality": relation.directionality,
                "direction": direction,
                "related_knowledge_id": related_kp_id,
                "related_knowledge_title": kp.title,
                "evidence_text": relation.evidence_text,
                "confidence": float(relation.confidence) if relation.confidence else None,
                "source_type": relation.source_type,
                "review_status": relation.review_status,
            })

        return relations

    async def get_relation_types(self) -> List[Dict[str, Any]]:
        """获取所有关系类型及其描述"""
        return [
            {"type": "prerequisite", "name": "先修关系", "description": "学习当前知识点前需要先掌握的知识点"},
            {"type": "contrast_with", "name": "对比关系", "description": "与当前知识点形成对比的知识点"},
            {"type": "common_confusion", "name": "易混淆", "description": "容易与当前知识点混淆的知识点"},
            {"type": "contains", "name": "包含", "description": "当前知识点包含的子知识点"},
            {"type": "part_of", "name": "属于", "description": "当前知识点所属的父知识点"},
            {"type": "used_in", "name": "应用于", "description": "当前知识点应用于哪些场景"},
            {"type": "similar_to", "name": "相似", "description": "与当前知识点相似的知识点"},
        ]

    async def review_relation(
        self,
        relation_id: str,
        review_status: str,
        relation_type: Optional[str] = None,
        directionality: Optional[str] = None,
        review_notes: Optional[str] = None,
        reviewed_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """审核关系"""
        result = await self.db.execute(
            select(KnowledgeRelation).where(KnowledgeRelation.id == relation_id)
        )
        relation = result.scalar_one_or_none()

        if not relation:
            raise ValueError(f"关系不存在: {relation_id}")

        # 更新关系类型
        if relation_type:
            relation.relation_type = relation_type
        if directionality:
            relation.directionality = directionality

        relation.review_status = review_status
        relation.review_notes = review_notes
        relation.reviewed_by = reviewed_by
        relation.reviewed_at = datetime.utcnow()

        await self.db.commit()

        logger.info(
            "关系审核完成",
            relation_id=relation_id,
            review_status=review_status,
        )

        return {
            "relation_id": relation_id,
            "review_status": review_status,
            "relation_type": relation.relation_type,
        }

    async def get_pending_review_count(
        self,
        subject_id: Optional[str] = None,
        relation_type: Optional[str] = None,
    ) -> int:
        """获取待审核关系数量"""
        query = select(KnowledgeRelation).where(
            KnowledgeRelation.review_status == "pending"
        )

        if subject_id:
            query = (
                select(KnowledgeRelation)
                .join(KnowledgePoint, KnowledgeRelation.source_knowledge_id == KnowledgePoint.id)
                .where(
                    and_(
                        KnowledgeRelation.review_status == "pending",
                        KnowledgePoint.subject_id == subject_id,
                    )
                )
            )

        if relation_type:
            query = query.where(KnowledgeRelation.relation_type == relation_type)

        result = await self.db.execute(query)
        return len(result.scalars().all())
