"""
实体抽取服务

从文档的 blocks 中抽取知识点和题目，生成 knowledge_points 和 questions 记录。
"""

import re
import uuid
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    Document, DocumentBlock, DocumentSection, DocumentSectionMapping,
    KnowledgePoint, Question, KnowledgePointChapterLink, QuestionChapterLink,
    EntitySourceLink, CanonicalChapter, RetrievalSegment
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


def clean_punctuation_subscript(text: str) -> str:
    """
    清理解析器误识别的标点符号
    将 <sub>．</sub>、<sub>，</sub> 等错误格式替换为正确的标点
    """
    if not text:
        return text

    patterns = [
        (r'<sub>\s*[．。]\s*</sub>', '。'),
        (r'<sub>\s*[，,]\s*</sub>', '，'),
        (r'<sub>\s*[；;]\s*</sub>', '；'),
        (r'<sub>\s*[：:]\s*</sub>', '：'),
        (r'<sub>\s*[！!]\s*</sub>', '！'),
        (r'<sub>\s*[？?]\s*</sub>', '？'),
        (r'<sub>\s*[、]\s*</sub>', '、'),
    ]

    cleaned = text
    for pattern, replacement in patterns:
        cleaned = re.sub(pattern, replacement, cleaned)

    return cleaned


def clean_blocks_punctuation(blocks: List[DocumentBlock]) -> List[DocumentBlock]:
    """
    清理所有blocks中的标点错误
    修改blocks的content_text和content_md字段
    """
    for block in blocks:
        if block.content_text:
            block.content_text = clean_punctuation_subscript(block.content_text)
        if block.content_md:
            block.content_md = clean_punctuation_subscript(block.content_md)

    return blocks


class OptionIntegrityChecker:
    """选择题选项完整性检查器"""

    EXPECTED_OPTIONS = {
        'single_choice': ['A', 'B', 'C', 'D'],
        'multiple_choice': ['A', 'B', 'C', 'D'],
    }

    def check(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """
        检查选项是否完整

        Args:
            question: 题目字典，包含question_type和options字段

        Returns:
            {
                'is_complete': bool,
                'missing_options': ['C', 'D'],
                'issue_type': 'missing_end' | 'missing_middle' | 'missing_start' | 'too_few' | 'complete'
            }
        """
        question_type = question.get('question_type') or question.get('type')
        if question_type not in ['single_choice', 'multiple_choice', 'choice']:
            return {'is_complete': True, 'issue_type': 'not_choice', 'missing_options': []}

        options = question.get('options', [])
        if not options:
            return {
                'is_complete': False,
                'missing_options': ['A', 'B', 'C', 'D'],
                'issue_type': 'missing_all'
            }

        # 提取选项标签
        option_labels = sorted([opt.get('label', opt.get('option_label', '')) for opt in options if opt.get('label') or opt.get('option_label')])

        if not option_labels:
            return {
                'is_complete': False,
                'missing_options': ['A', 'B', 'C', 'D'],
                'issue_type': 'missing_all'
            }

        # 期望的选项（从第一个到最后一个应该连续）
        first_label = option_labels[0]
        last_label = option_labels[-1]
        expected_labels = [chr(ord(first_label) + i)
                          for i in range(ord(last_label) - ord(first_label) + 1)]

        missing = set(expected_labels) - set(option_labels)

        if not missing:
            # 检查是否至少有4个选项（单选题标准）
            if len(option_labels) < 4:
                missing_count = 4 - len(option_labels)
                return {
                    'is_complete': False,
                    'missing_options': [chr(ord(last_label) + i + 1) for i in range(missing_count)],
                    'issue_type': 'too_few'
                }
            return {'is_complete': True, 'issue_type': 'complete', 'missing_options': []}

        # 判断缺失位置
        missing_list = sorted(list(missing))
        expected_end = expected_labels[-len(missing_list):]
        expected_start = expected_labels[:len(missing_list)]

        if set(missing_list) == set(expected_end):
            issue_type = 'missing_end'  # 缺尾部：有AB缺CD
        elif set(missing_list) == set(expected_start):
            issue_type = 'missing_start'  # 缺头部：有CD缺AB（罕见）
        else:
            issue_type = 'missing_middle'  # 缺中间：有AC缺B

        return {
            'is_complete': False,
            'missing_options': missing_list,
            'issue_type': issue_type
        }


class QuestionNumberChecker:
    """题目编号连续性检查器"""

    # 题号正则模式（按优先级）
    NUMBER_PATTERNS = [
        (r'^(\d+)[.、．]\s*', 'arabic'),      # 1. 2. 3.
        (r'^[（(](\d+)[）)]\s*', 'paren'),    # (1) (2) (3)
        (r'^\[(\d+)\]\s*', 'bracket'),        # [1] [2] [3]
        (r'^例(\d+)', 'example'),              # 例1 例2
        (r'^第(\d+)题', 'diti'),               # 第1题 第2题
    ]

    def extract_question_numbers(self, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        提取所有题目的编号

        Returns:
            [{'index': 0, 'number': 1, 'pattern': 'arabic', 'text': '1.', 'question': {...}}, ...]
        """
        results = []
        for i, q in enumerate(questions):
            # 优先从题干或content开头提取
            text = (q.get('stem') or q.get('content') or q.get('raw_text', '')).strip()

            number_info = None
            for pattern, pattern_type in self.NUMBER_PATTERNS:
                match = re.match(pattern, text)
                if match:
                    number_info = {
                        'index': i,
                        'number': int(match.group(1)),
                        'pattern': pattern_type,
                        'text': match.group(0),
                        'question': q
                    }
                    break

            if number_info:
                results.append(number_info)
            else:
                # 没有识别到编号
                results.append({
                    'index': i,
                    'number': None,
                    'pattern': 'none',
                    'text': '',
                    'question': q
                })

        return results

    def detect_continuity_issues(self, number_infos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        检测编号连续性问题

        Returns:
            {
                'segments': [  # 分段统计
                    {
                        'start_index': 0,
                        'end_index': 10,
                        'number_range': (1, 11),
                        'pattern': 'arabic',
                        'issues': [...]
                    }
                ],
                'global_issues': {
                    'total_questions': 50,
                    'numbered_questions': 45,
                    'unnumbered_questions': 5,
                    'unnumbered_indices': [3, 7, 12]
                }
            }
        """
        # Step 1: 分段（遇到编号重新从1开始，或pattern变化，认为是新段）
        segments = self._segment_by_pattern(number_infos)

        # Step 2: 对每段检查连续性
        for seg in segments:
            seg['issues'] = self._check_segment_continuity(seg)

        # Step 3: 全局统计
        global_issues = self._compute_global_stats(number_infos)

        return {
            'segments': segments,
            'global_issues': global_issues
        }

    def _segment_by_pattern(self, number_infos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        按编号模式和重置点分段
        例如：1,2,3,4,1,2,3 → 两段：[1-4] 和 [1-3]
        """
        segments = []
        current_segment = {
            'start_index': 0,
            'numbers': [],
            'pattern': None,
            'infos': []
        }

        for i, info in enumerate(number_infos):
            number = info['number']
            pattern = info['pattern']

            if pattern == 'none':
                continue  # 跳过无编号的题目

            # 判断是否开始新段
            should_start_new_segment = (
                # pattern变化
                (current_segment['pattern'] and pattern != current_segment['pattern']) or
                # 编号重新从1开始（且不是第一题）
                (number == 1 and current_segment['numbers'] and current_segment['numbers'][-1] != 0)
            )

            if should_start_new_segment:
                # 保存当前段
                current_segment['end_index'] = i - 1
                if current_segment['numbers']:
                    current_segment['number_range'] = (
                        min(current_segment['numbers']),
                        max(current_segment['numbers'])
                    )
                    segments.append(current_segment)
                # 开始新段
                current_segment = {
                    'start_index': i,
                    'numbers': [number],
                    'pattern': pattern,
                    'infos': [info]
                }
            else:
                # 继续当前段
                current_segment['numbers'].append(number)
                current_segment.setdefault('infos', []).append(info)
                current_segment['pattern'] = pattern

        # 添加最后一段
        if current_segment['numbers']:
            current_segment['end_index'] = len(number_infos) - 1
            current_segment['number_range'] = (
                min(current_segment['numbers']),
                max(current_segment['numbers'])
            )
            segments.append(current_segment)

        return segments

    def _check_segment_continuity(self, segment: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        检查单个段的连续性

        Returns:
            问题列表：[
                {'type': 'missing', 'missing_number': 3, 'after_index': 5, 'severity': 'high'},
                {'type': 'duplicate', 'number': 5, 'indices': [7, 8], 'severity': 'medium'},
                {'type': 'jump', 'from_number': 10, 'to_number': 15, 'gap': 4, 'at_index': 12, 'severity': 'high'}
            ]
        """
        issues = []
        numbers = segment['numbers']
        infos = segment['infos']

        if not numbers:
            return issues

        # 期望的连续序列
        expected_start = numbers[0]
        expected_end = expected_start + len(numbers) - 1
        expected_numbers = list(range(expected_start, expected_end + 1))
        actual_numbers = numbers

        # 检查缺失
        missing = set(expected_numbers) - set(actual_numbers)
        if missing:
            for miss_num in sorted(missing):
                # 找到缺失编号应该出现的位置
                before_index = None
                for i, num in enumerate(actual_numbers):
                    if num < miss_num:
                        before_index = infos[i]['index']

                issues.append({
                    'type': 'missing',
                    'missing_number': miss_num,
                    'after_index': before_index,
                    'severity': 'high'
                })

        # 检查重复
        from collections import Counter
        duplicates = [num for num, count in Counter(actual_numbers).items() if count > 1]
        for dup_num in duplicates:
            dup_indices = [info['index'] for info in infos if info['number'] == dup_num]
            issues.append({
                'type': 'duplicate',
                'number': dup_num,
                'indices': dup_indices,
                'severity': 'medium'
            })

        # 检查跳跃（相邻编号差值>1）
        for i in range(len(actual_numbers) - 1):
            diff = actual_numbers[i + 1] - actual_numbers[i]
            if diff > 1:
                issues.append({
                    'type': 'jump',
                    'from_number': actual_numbers[i],
                    'to_number': actual_numbers[i + 1],
                    'gap': diff - 1,
                    'at_index': infos[i + 1]['index'],
                    'severity': 'high'
                })
            elif diff < 0:
                issues.append({
                    'type': 'reverse',
                    'from_number': actual_numbers[i],
                    'to_number': actual_numbers[i + 1],
                    'at_index': infos[i + 1]['index'],
                    'severity': 'high'
                })

        return issues

    def _compute_global_stats(self, number_infos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算全局统计"""
        total = len(number_infos)
        numbered = sum(1 for info in number_infos if info['number'] is not None)
        unnumbered_indices = [info['index'] for info in number_infos if info['number'] is None]

        return {
            'total_questions': total,
            'numbered_questions': numbered,
            'unnumbered_questions': total - numbered,
            'unnumbered_indices': unnumbered_indices
        }


class EntityExtractionService:
    """实体抽取服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def extract_entities(
        self,
        document_id: str,
        extract_knowledge: bool = True,
        extract_questions: bool = True,
    ) -> Dict[str, Any]:
        """
        从文档中抽取实体

        学科归属从章节映射反推（canonical_chapter.subject_id），
        不依赖 document.subject_id，因此同一文档的不同 section 可以属于不同学科。

        Args:
            document_id: 文档ID
            extract_knowledge: 是否抽取知识点
            extract_questions: 是否抽取题目

        Returns:
            抽取结果统计
        """
        # 1. 获取文档信息
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        # document.subject_id 仅作为 fallback
        fallback_subject_id = document.subject_id

        # 2. 获取 blocks
        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = blocks_result.scalars().all()

        if not blocks:
            return {"knowledge_count": 0, "question_count": 0, "message": "文档没有 blocks"}

        # 3. 获取 section 映射，用于确定章节和学科归属
        # page -> {chapter_id, subject_id}
        section_mappings = await self._get_section_mappings(document_id)

        knowledge_count = 0
        question_count = 0

        # 4. 抽取知识点
        if extract_knowledge:
            await self._cleanup_existing_entities(document_id, "knowledge_point")
            knowledge_count = await self._extract_knowledge_points(
                document_id, fallback_subject_id, blocks, section_mappings
            )

        # 5. 抽取题目
        if extract_questions:
            await self._cleanup_existing_entities(document_id, "question")
            question_count = await self._extract_questions(
                document_id, fallback_subject_id, blocks, section_mappings
            )

        await self.db.commit()

        logger.info(
            "实体抽取完成",
            document_id=document_id,
            knowledge_count=knowledge_count,
            question_count=question_count,
        )

        return {
            "document_id": document_id,
            "knowledge_count": knowledge_count,
            "question_count": question_count,
        }

    async def _get_section_mappings(self, document_id: str) -> Dict[int, Dict[str, Optional[str]]]:
        """获取 section 到标准章节的映射关系，同时获取章节对应的学科"""
        result = await self.db.execute(
            select(DocumentSection, DocumentSectionMapping, CanonicalChapter)
            .join(DocumentSectionMapping, DocumentSection.id == DocumentSectionMapping.document_section_id)
            .join(CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id)
            .where(
                and_(
                    DocumentSection.document_id == document_id,
                    DocumentSectionMapping.review_status.in_(["approved", "pending"])
                )
            )
        )
        rows = result.all()

        # 构建 page -> {chapter_id, subject_id} 的映射
        page_chapter_map: Dict[int, Dict[str, Optional[str]]] = {}
        legacy_chapter_cache: Dict[str, Optional[str]] = {}
        for section, mapping, chapter in rows:
            if section.page_start:
                if chapter.id not in legacy_chapter_cache:
                    legacy_chapter_cache[chapter.id] = await resolve_legacy_chapter_id(
                        self.db,
                        canonical_chapter_id=chapter.id,
                        subject_id=chapter.subject_id,
                    )
                info = {
                    "chapter_id": mapping.canonical_chapter_id,
                    "subject_id": chapter.subject_id,
                    "legacy_chapter_id": legacy_chapter_cache[chapter.id],
                }
                for page in range(section.page_start, (section.page_end or section.page_start) + 1):
                    page_chapter_map[page] = info

        return page_chapter_map

    async def _cleanup_existing_entities(self, document_id: str, entity_type: str) -> None:
        """清理同一文档已抽取的实体，避免重复入库。"""
        model = KnowledgePoint if entity_type == "knowledge_point" else Question
        result = await self.db.execute(
            select(model.id).where(model.source_document_id == document_id)
        )
        entity_ids = [row[0] for row in result.all()]
        if not entity_ids:
            return

        await self.db.execute(
            delete(EntitySourceLink).where(
                and_(
                    EntitySourceLink.entity_type == entity_type,
                    EntitySourceLink.entity_id.in_(entity_ids),
                )
            )
        )
        await self.db.execute(
            delete(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == entity_type,
                    RetrievalSegment.entity_id.in_(entity_ids),
                )
            )
        )
        await self.db.execute(
            delete(model).where(model.id.in_(entity_ids))
        )

    async def _extract_knowledge_points(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> int:
        """抽取知识点"""
        knowledge_count = 0

        # 简单策略：将连续的 paragraph + title blocks 组合为知识点
        current_title = None
        current_content_blocks = []

        for block in blocks:
            # 如果是标题类型，保存前一个知识点并开始新的
            if block.block_type in ('title', 'heading'):
                # 保存前一个知识点
                if current_title and current_content_blocks:
                    created = await self._save_knowledge_point(
                        document_id, fallback_subject_id, current_title,
                        current_content_blocks, section_mappings
                    )
                    if created:
                        knowledge_count += 1
                    current_content_blocks = []

                current_title = block
            elif block.block_type in ('paragraph', 'list'):
                current_content_blocks.append(block)

        # 保存最后一个知识点
        if current_title and current_content_blocks:
            created = await self._save_knowledge_point(
                document_id, fallback_subject_id, current_title,
                current_content_blocks, section_mappings
            )
            if created:
                knowledge_count += 1

        return knowledge_count

    async def _save_knowledge_point(
        self,
        document_id: str,
        fallback_subject_id: str,
        title_block: DocumentBlock,
        content_blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> bool:
        """保存单个知识点"""
        # 从章节映射推断学科和章节（同一文档不同块可属于不同学科）
        mapping_info = section_mappings.get(title_block.page_no)
        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = mapping_info["subject_id"] if mapping_info else fallback_subject_id
        legacy_chapter_id = mapping_info["legacy_chapter_id"] if mapping_info else None
        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(self.db, subject_id=subject_id)

        # 组合内容
        content_parts = []
        for block in content_blocks:
            text = block.content_md or block.content_text or ""
            if text.strip():
                content_parts.append(text.strip())
        content = "\n\n".join(content_parts)

        if not content:
            return False
        if not subject_id or not legacy_chapter_id:
            logger.warning(
                "知识点缺少有效章节归属，跳过入库",
                document_id=document_id,
                block_id=title_block.id,
            )
            return False

        # 生成 topic_terms（简单实现：从标题和内容中提取关键词）
        topic_terms = self._extract_topic_terms(title_block.content_text or "", content)

        # 创建知识点
        kp_id = generate_id()
        knowledge_point = KnowledgePoint(
            id=kp_id,
            chapter_id=legacy_chapter_id,
            subject_id=subject_id,
            primary_chapter_id=primary_chapter_id,
            source_document_id=document_id,
            title=title_block.content_text or "未命名知识点",
            canonical_title=title_block.content_text,
            content=content,
            topic_terms=topic_terms,
            review_status="pending",
        )
        self.db.add(knowledge_point)

        # 创建章节关联
        if primary_chapter_id:
            link = KnowledgePointChapterLink(
                knowledge_point_id=kp_id,
                canonical_chapter_id=primary_chapter_id,
                is_primary=True,
            )
            self.db.add(link)

        # 创建来源引用
        source_link = EntitySourceLink(
            entity_type="knowledge_point",
            entity_id=kp_id,
            document_id=document_id,
            page_start=title_block.page_no,
            page_end=content_blocks[-1].page_no if content_blocks else title_block.page_no,
            block_ids=[title_block.id] + [b.id for b in content_blocks],
            excerpt_text=content[:500] if content else None,
        )
        self.db.add(source_link)

        await self.db.flush()
        return True

    async def _extract_questions(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> int:
        """抽取题目"""
        # Step 1: 清洗blocks中的标点错误
        blocks = clean_blocks_punctuation(blocks)
        logger.info(f"清洗标点完成，处理 {len(blocks)} 个blocks")

        question_count = 0

        # 简单策略：查找包含题目标记的 blocks
        # 题目通常以 "第X题"、"X."、"（X）" 等开头
        question_markers = ['第', '题', '（', '(', 'A.', 'B.', 'C.', 'D.']

        current_question_blocks = []
        in_question = False

        for block in blocks:
            text = (block.content_text or "").strip()

            # 检测题目开始
            is_question_start = False
            if block.block_type in ('paragraph', 'heading'):
                # 检查是否是题号
                for marker in question_markers:
                    if text.startswith(marker):
                        is_question_start = True
                        break

            if is_question_start:
                # 保存前一个题目
                if in_question and current_question_blocks:
                    created = await self._save_question(
                        document_id, fallback_subject_id, current_question_blocks, section_mappings
                    )
                    if created:
                        question_count += 1
                    current_question_blocks = []

                in_question = True
                current_question_blocks.append(block)
            elif in_question:
                # 如果遇到新的标题，结束当前题目
                if block.block_type in ('title', 'heading'):
                    if current_question_blocks:
                        created = await self._save_question(
                            document_id, fallback_subject_id, current_question_blocks, section_mappings
                        )
                        if created:
                            question_count += 1
                        current_question_blocks = []
                    in_question = False
                else:
                    current_question_blocks.append(block)

        # 保存最后一个题目
        if in_question and current_question_blocks:
            created = await self._save_question(
                document_id, fallback_subject_id, current_question_blocks, section_mappings
            )
            if created:
                question_count += 1

        return question_count

    async def _save_question(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> bool:
        """保存单个题目"""
        if not blocks:
            return False

        first_block = blocks[0]
        mapping_info = section_mappings.get(first_block.page_no)
        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = mapping_info["subject_id"] if mapping_info else fallback_subject_id
        legacy_chapter_id = mapping_info["legacy_chapter_id"] if mapping_info else None
        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(self.db, subject_id=subject_id)

        # 组合题目内容
        content_parts = []
        for block in blocks:
            text = block.content_md or block.content_text or ""
            if text.strip():
                content_parts.append(text.strip())
        content = "\n".join(content_parts)

        if not content:
            return False
        if not subject_id or not legacy_chapter_id:
            logger.warning(
                "题目缺少有效章节归属，跳过入库",
                document_id=document_id,
                block_id=first_block.id,
            )
            return False

        # 简单判断题型
        question_type = "short_answer"  # 默认简答
        if any(kw in content for kw in ['A.', 'B.', 'C.', 'D.', 'A、', 'B、', 'C、', 'D、']):
            question_type = "choice"
        elif '判断' in content[:50]:
            question_type = "judge"
        elif '填空' in content[:50]:
            question_type = "fill"

        # 创建题目
        q_id = generate_id()
        question = Question(
            id=q_id,
            subject_id=subject_id,
            chapter_id=legacy_chapter_id,
            primary_chapter_id=primary_chapter_id,
            source_document_id=document_id,
            type=question_type,
            content=content,
            answer="",  # 需要后续从 blocks 中提取或人工补充
            review_status="pending",
        )
        self.db.add(question)

        # 创建章节关联
        if primary_chapter_id:
            link = QuestionChapterLink(
                question_id=q_id,
                canonical_chapter_id=primary_chapter_id,
                is_primary=True,
            )
            self.db.add(link)

        # 创建来源引用
        source_link = EntitySourceLink(
            entity_type="question",
            entity_id=q_id,
            document_id=document_id,
            page_start=first_block.page_no,
            page_end=blocks[-1].page_no,
            block_ids=[b.id for b in blocks],
            excerpt_text=content[:500],
        )
        self.db.add(source_link)

        await self.db.flush()
        return True

    def _extract_topic_terms(self, title: str, content: str) -> List[str]:
        """提取主题术语（简单实现）"""
        terms = set()

        # 从标题提取
        if title:
            # 去除常见前缀
            clean_title = title.strip()
            for prefix in ['第', '章', '节', '、', '。', '：', ':', ' ']:
                clean_title = clean_title.replace(prefix, ' ')
            words = clean_title.split()
            for word in words:
                if len(word) >= 2:
                    terms.add(word)

        # 从内容提取高频词（简单实现）
        # 实际应该使用 NLP 工具提取关键词
        if content:
            # 提取引号中的术语
            import re
            quoted = re.findall(r'[「「""]([^」」""]+)[」」""]', content)
            for q in quoted:
                if 2 <= len(q) <= 20:
                    terms.add(q)

        return list(terms)[:20]  # 限制数量

    async def get_entity_source_links(
        self,
        entity_type: str,
        entity_id: str
    ) -> List[Dict[str, Any]]:
        """获取实体的来源引用"""
        result = await self.db.execute(
            select(EntitySourceLink)
            .where(
                and_(
                    EntitySourceLink.entity_type == entity_type,
                    EntitySourceLink.entity_id == entity_id,
                )
            )
        )
        links = result.scalars().all()

        return [
            {
                "id": link.id,
                "entity_type": link.entity_type,
                "entity_id": link.entity_id,
                "document_id": link.document_id,
                "page_start": link.page_start,
                "page_end": link.page_end,
                "block_ids": link.block_ids,
                "excerpt_text": link.excerpt_text,
                "created_at": link.created_at.isoformat() if link.created_at else None,
            }
            for link in links
        ]
