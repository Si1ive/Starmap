"""
实体抽取服务

从文档的 blocks 中抽取知识点和题目，生成 knowledge_points 和 questions 记录。
"""

import re
import uuid
import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.mysql_models import (
    Document, DocumentBlock, DocumentSection, DocumentSectionMapping,
    KnowledgePoint, Question, KnowledgePointChapterLink, QuestionChapterLink,
    EntitySourceLink, CanonicalChapter, RetrievalSegment, EntityExtractionRun
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id
from app.services.system_settings_service import SystemSettingsService
from app.services.text_cleaning import clean_block_text, normalize_whitespace
from app.services.llm_call_recorder import LLMCallRecorder
from app.services.llm_client import PDFStructureLLMClient

logger = get_logger(__name__)


async def cleanup_document_entities(
    db: AsyncSession,
    document_id: str,
    entity_type: Optional[str] = None,
) -> Dict[str, int]:
    """清理某文档已抽取的实体及其级联数据（来源链/资产链/检索段/关联）。

    entity_type=None 时同时清理知识点与题目；否则只清理指定类型。
    重解析会重建 blocks/assets，旧实体基于旧版面已失效，必须一并清掉，
    否则新版面配旧实体，坐标桥与来源引用全部错位。
    """
    types = ["knowledge_point", "question"] if entity_type is None else [entity_type]
    removed: Dict[str, int] = {}
    for etype in types:
        model = KnowledgePoint if etype == "knowledge_point" else Question
        rows = await db.execute(
            select(model.id).where(model.source_document_id == document_id)
        )
        entity_ids = [row[0] for row in rows.all()]
        removed[etype] = len(entity_ids)
        if not entity_ids:
            continue

        await db.execute(
            delete(EntitySourceLink).where(
                and_(
                    EntitySourceLink.entity_type == etype,
                    EntitySourceLink.entity_id.in_(entity_ids),
                )
            )
        )
        try:
            from app.services.entity_asset_service import cleanup_entity_links
            await cleanup_entity_links(db, entity_type=etype, entity_ids=entity_ids)
        except Exception:
            pass
        await db.execute(
            delete(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == etype,
                    RetrievalSegment.entity_id.in_(entity_ids),
                )
            )
        )
        await db.execute(delete(model).where(model.id.in_(entity_ids)))
    return removed


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


# 题干年份/真题标记探测：匹配【2019】(2019)（2019）[2019] 2019年 等
STEM_YEAR_RE = re.compile(r'[\[【(（]?\s*((?:19|20)\d{2})\s*(?:年)?\s*[\]】)）]?')
STEM_REAL_EXAM_RE = re.compile(r'真题|考研真题|历年|统考')


def _detect_stem_year(text: str) -> Optional[int]:
    """从题干前部探测年份（仅扫前 30 字，避免命中题目正文里的年份数字）。"""
    head = (text or "")[:30]
    m = STEM_YEAR_RE.search(head)
    if m:
        year = int(m.group(1))
        if 1990 <= year <= 2099:
            return year
    return None


def _build_question_tags(
    question_type: str, exam_year: Optional[int], is_real: bool
) -> List[str]:
    """结构化标签：题型 + 真题/课后习题 + 年份。"""
    type_label = {
        "choice": "选择题", "fill": "填空题", "judge": "判断题",
        "short_answer": "简答题", "design": "设计题", "analysis": "分析题",
    }.get(question_type, "")
    tags: List[str] = []
    if type_label:
        tags.append(type_label)
    tags.append("真题" if is_real else "课后习题")
    if exam_year:
        tags.append(str(exam_year))
    return tags



OPTION_SEPARATOR_RE = re.compile(
    r'(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)(?=\S)'
)
# 选项标记限定 A-D：408 单选恒为四选项，放宽到 A-H 会把题干里的
# 数学符号（图 G、访问位 R、修改位 M 等）误当选项标记切分。
OPTION_MARKER_RE = re.compile(r'([A-D])(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)(?=\S)')
OPTION_BLOCK_RE = re.compile(r'^\s*([A-D])(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)(?=\S)')
CHOICE_BLANK_RE = re.compile(r'[（(]\s*(?:\)|）|_|　|\.{2,}|…{1,2})?\s*[）)]')
QUESTION_NUMERIC_RE = re.compile(r'^\s*(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)')
EMBEDDED_QUESTION_NUMERIC_RE = re.compile(r'(?<!\d)(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)')
QUESTION_TITLE_RE = re.compile(r'^\s*第\s*([一二三四五六七八九十百千\d]+)\s*题')
QUESTION_PAREN_RE = re.compile(r'^\s*[（(]\s*(\d{1,3})\s*[）)]\s*\S+')
QUESTION_EXAMPLE_RE = re.compile(r'^\s*例\s*\d+')
QUESTION_CUE_RE = re.compile(
    r'[?？]|下列|以下|关于|若|设|已知|正确|错误|不是|可以|能够|应|属于|采用|'
    r'给出|求|计算|证明|说明|分析|为什么|多少|哪个|哪些|如果|判断'
)


def _get_option_label(option: Dict[str, Any]) -> str:
    """兼容 key/label/option_label 三种选项标识字段。"""
    value = option.get("key") or option.get("label") or option.get("option_label") or ""
    return str(value).strip().upper()[:1]




def clean_punctuation_subscript(text: str) -> str:
    """兼容入口：转发到 text_cleaning.clean_block_text"""
    return clean_block_text(text) or ""


def clean_blocks_punctuation(blocks):
    """清理 blocks 的 content_text/content_md 字段"""
    for block in blocks:
        if block.content_text:
            block.content_text = clean_block_text(block.content_text)
        if block.content_md:
            block.content_md = clean_block_text(block.content_md)
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
        option_labels = sorted([label for label in (_get_option_label(opt) for opt in options) if label])

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
        (r'^(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)', 'arabic'),  # 1. / 1、 / 1 若
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


class RuleBasedFixer:
    """基于规则的问题修复器"""

    def __init__(self):
        self.option_checker = OptionIntegrityChecker()

    def fix_option_issues(
        self,
        questions: List[Dict[str, Any]],
        option_issues: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        修复选项不完整的问题
        策略：向后查找（换页/换列后的block）中缺失的选项
        """
        fixed_questions = questions.copy()

        for issue in option_issues:
            idx = issue['question_index']
            missing = issue['missing_options']

            if issue['issue_type'] == 'missing_end':
                # 缺尾部选项，向后查找
                found_options = self._search_options_forward(
                    questions,
                    idx,
                    missing,
                    max_distance=3  # 最多向后看3个题目
                )

                if found_options:
                    # 合并选项
                    if 'options' not in fixed_questions[idx]:
                        fixed_questions[idx]['options'] = []
                    fixed_questions[idx]['options'].extend(found_options['options'])
                    # 标记为已修复
                    fixed_questions[idx]['fixed_by_rule'] = 'option_append'
                    fixed_questions[idx]['fixed_source_index'] = found_options['source_index']
                    logger.info(f"Fixed question {idx}: appended options {missing}")

        return fixed_questions

    def fix_number_issues(
        self,
        questions: List[Dict[str, Any]],
        continuity_report: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        修复编号相关问题
        """
        fixed_questions = questions.copy()

        for segment in continuity_report['segments']:
            for issue in segment['issues']:

                if issue['type'] == 'missing':
                    # 编号缺失：可能是题目被拆分了
                    fixed = self._fix_missing_number(
                        fixed_questions,
                        issue['missing_number'],
                        issue['after_index']
                    )
                    if fixed:
                        fixed_questions = fixed

                elif issue['type'] == 'duplicate':
                    # 编号重复：可能是一道题被错误拆成两道
                    fixed = self._fix_duplicate_number(
                        fixed_questions,
                        issue['number'],
                        issue['indices']
                    )
                    if fixed:
                        fixed_questions = fixed

        return fixed_questions

    def _search_options_forward(
        self,
        questions: List[Dict[str, Any]],
        start_idx: int,
        missing_labels: List[str],
        max_distance: int
    ) -> Optional[Dict[str, Any]]:
        """
        向后搜索缺失的选项
        """
        current_q = questions[start_idx]
        current_page = current_q.get('page_no', 0)

        for offset in range(1, max_distance + 1):
            if start_idx + offset >= len(questions):
                break

            next_q = questions[start_idx + offset]
            next_page = next_q.get('page_no', 0)

            # 只在相邻页或同页查找
            if abs(next_page - current_page) > 1:
                break

            # 检查next_q是否包含缺失的选项
            next_options = next_q.get('options', [])
            next_labels = [_get_option_label(opt) for opt in next_options]

            # 如果next_q只包含缺失的选项（说明是被拆分的部分）
            if set(next_labels) == set(missing_labels):
                return {
                    'source_index': start_idx + offset,
                    'options': next_options
                }

            # 如果next_q包含部分缺失选项
            found_labels = set(next_labels) & set(missing_labels)
            if found_labels:
                found_options = [opt for opt in next_options if _get_option_label(opt) in found_labels]
                return {
                    'source_index': start_idx + offset,
                    'options': found_options,
                    'partial': True
                }

        return None

    def _fix_missing_number(
        self,
        questions: List[Dict[str, Any]],
        missing_num: int,
        after_index: Optional[int]
    ) -> Optional[List[Dict[str, Any]]]:
        """
        修复缺失的编号
        场景：编号应该是1,2,3，但实际只有1,3（缺2）
        可能原因：题2被拆成了两部分，分别附在题1和题3上
        """
        if after_index is None:
            return None

        # 查找after_index之后的题目，看是否有无编号的题目
        for offset in range(1, 4):
            if after_index + offset >= len(questions):
                break

            candidate = questions[after_index + offset]
            candidate_num = self._extract_number(candidate)

            # 如果找到无编号的题目，且它的内容看起来像独立题目
            if candidate_num is None and self._looks_like_complete_question(candidate):
                # 给它赋予缺失的编号
                candidate['inferred_number'] = missing_num
                candidate['fixed_by_rule'] = 'number_infer'
                logger.info(f"Inferred missing number {missing_num} for question at index {after_index + offset}")
                return questions

        return None

    def _fix_duplicate_number(
        self,
        questions: List[Dict[str, Any]],
        dup_num: int,
        dup_indices: List[int]
    ) -> Optional[List[Dict[str, Any]]]:
        """
        修复重复的编号
        场景：两道题都标记为"3"
        可能原因：一道题被错误拆成两道
        """
        if len(dup_indices) != 2:
            return None  # 暂时只处理2个重复的情况

        idx1, idx2 = dup_indices
        q1, q2 = questions[idx1], questions[idx2]

        # 判断是否应该合并
        if self._should_merge_duplicates(q1, q2):
            # 合并两道题
            merged = self._merge_questions(q1, q2)
            merged['fixed_by_rule'] = 'duplicate_merge'

            # 替换idx1，删除idx2
            new_questions = questions[:idx1] + [merged] + questions[idx1+1:idx2] + questions[idx2+1:]
            logger.info(f"Merged duplicate number {dup_num} at indices {idx1}, {idx2}")
            return new_questions

        return None

    def _extract_number(self, question: Dict[str, Any]) -> Optional[int]:
        """从题目中提取编号"""
        text = (question.get('stem') or question.get('content') or question.get('raw_text', '')).strip()
        for pattern, _ in QuestionNumberChecker.NUMBER_PATTERNS:
            match = re.match(pattern, text)
            if match:
                return int(match.group(1))
        return None

    def _looks_like_complete_question(self, question: Dict[str, Any]) -> bool:
        """判断是否看起来像完整的题目"""
        # 有足够长的题干
        stem_length = len(question.get('stem', '') or question.get('content', ''))
        # 选择题有选项
        has_options = len(question.get('options', [])) > 0
        return stem_length > 20 and has_options

    def _should_merge_duplicates(self, q1: Dict[str, Any], q2: Dict[str, Any]) -> bool:
        """判断两个重复编号的题目是否应该合并"""
        # 检查页码相邻
        page1 = q1.get('page_no', 0)
        page2 = q2.get('page_no', 0)
        if abs(page2 - page1) > 1:
            return False

        # 检查q1缺选项，q2只有选项
        q1_result = self.option_checker.check(q1)

        return (
            not q1_result['is_complete'] and
            q1_result['issue_type'] == 'missing_end' and
            len(q2.get('stem', '') or q2.get('content', '')) < 20 and  # q2题干很短
            len(q2.get('options', [])) > 0     # q2有选项
        )

    def _merge_questions(self, q1: Dict[str, Any], q2: Dict[str, Any]) -> Dict[str, Any]:
        """合并两道题目"""
        merged = q1.copy()
        stem1 = q1.get('stem', '') or q1.get('content', '')
        stem2 = q2.get('stem', '') or q2.get('content', '')
        merged['stem'] = (stem1 + ' ' + stem2).strip()
        if 'content' in merged:
            merged['content'] = merged['stem']
        merged['options'] = q1.get('options', []) + q2.get('options', [])
        merged['page_range'] = f"{q1.get('page_no')}-{q2.get('page_no')}"
        return merged


class LLMFallbackFixer:
    """LLM兜底修复器"""

    def __init__(self, llm_client):
        self.llm_client = llm_client

    async def fix_remaining_issues(
        self,
        questions: List[Dict[str, Any]],
        validation_report: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        对规则无法修复的问题，使用LLM进行二次判断

        Args:
            questions: 题目列表
            validation_report: 校验报告，包含critical_issues

        Returns:
            修复后的题目列表
        """
        critical_issues = validation_report.get('summary', {}).get('critical_issues', [])

        # 只处理规则未修复的
        unfixed_issues = []
        for issue in critical_issues:
            idx = issue.get("question_index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(questions):
                logger.warning("LLM fallback skipped invalid issue index", issue=issue)
                continue
            if not questions[idx].get('fixed_by_rule'):
                self._remember_original_issue(questions[idx], issue)
                unfixed_issues.append(issue)

        if not unfixed_issues:
            return questions

        logger.info(f"LLM fallback for {len(unfixed_issues)} unfixed issues")

        for issue in sorted(unfixed_issues, key=lambda item: item.get("question_index", 0), reverse=True):
            idx = issue['question_index']
            if idx < 0 or idx >= len(questions):
                logger.warning("LLM fallback skipped stale issue index", issue=issue)
                continue

            # 异常只会波及相邻题：前一题 + 目标题 + 后一题。
            context_start = max(0, idx - 1)
            context_end = min(len(questions), idx + 2)
            context_questions = questions[context_start:context_end]

            # 调用LLM
            prompt = self._build_fix_prompt(
                context_questions,
                target_idx=idx - context_start,
                issue=issue
            )

            try:
                llm_response = await self.llm_client.chat(
                    prompt,
                    purpose="题目结构修复",
                )

                # 应用LLM建议
                fix_action = self._parse_llm_fix_result(llm_response)
                if fix_action and fix_action.get("action") != "none":
                    fix_action["issue"] = issue
                    questions = self._apply_llm_fix(questions, idx, context_start, fix_action)
                    logger.info(f"LLM fixed question {idx}")
            except Exception as e:
                logger.error(f"LLM fix failed for question {idx}: {e}")

        return questions

    @staticmethod
    def _remember_original_issue(question: Dict[str, Any], issue: Dict[str, Any]) -> None:
        """保留修复前诊断，避免最终重算质量元数据时抹掉原问题。"""
        meta = dict(question.get("extraction_meta") or {})
        original_issues = list(meta.get("original_issues") or [])
        issue_snapshot = {
            key: issue.get(key)
            for key in (
                "question_number",
                "page_no",
                "issue_type",
                "missing_options",
                "missing_number",
                "from_number",
                "to_number",
                "gap",
            )
            if key in issue
        }
        identity = (
            issue_snapshot.get("issue_type"),
            tuple(issue_snapshot.get("missing_options") or []),
            issue_snapshot.get("missing_number"),
        )
        existing_identities = {
            (
                item.get("issue_type"),
                tuple(item.get("missing_options") or []),
                item.get("missing_number"),
            )
            for item in original_issues
            if isinstance(item, dict)
        }
        if identity not in existing_identities:
            original_issues.append(issue_snapshot)
        meta["original_issues"] = original_issues
        question["extraction_meta"] = meta

    def _build_fix_prompt(
        self,
        context: List[Dict[str, Any]],
        target_idx: int,
        issue: Dict[str, Any]
    ) -> str:
        """构造 LLM 判断/修复 prompt。"""
        # 将题目列表格式化为文本
        formatted = []
        for i, q in enumerate(context):
            marker = " ← 【目标】" if i == target_idx else ""
            stem = q.get('stem') or q.get('content', '')
            raw_text = q.get("raw_text") or q.get("content") or stem
            options = q.get('options', [])
            options_text = ', '.join(
                f"{_get_option_label(o)}. {o.get('text', '')[:80]}"
                for o in options
            )

            formatted.append(f"""
题目{i+1}{marker}:
页码: {q.get('page_no', '?')}
题干: {stem[:500]}
原始提取文本: {raw_text[:1200]}
选项: {options_text}
---
""")

        issue_desc = f"""
问题类型: {issue.get('issue_type', 'unknown')}
缺失选项: {issue.get('missing_options', [])}
"""

        return f"""
你是一个教材题目结构分析专家。以下是从PDF中提取的目标题及其相邻题，共最多三题。

{chr(10).join(formatted)}

【当前问题】
{issue_desc}

【任务】分析标记为【目标】的题目，并选择一种动作：
1. repair_options：目标题独立，但选项缺失或选项粘在题干中。
   - 优先从“原始提取文本”和相邻题原文中逐字恢复缺失选项。
   - 原文确实不存在时，允许生成合理选项。
   - 每个补充选项必须标 source：原文恢复为 extracted，AI 生成则为 ai_generated。
   - 返回完整题干和 A-D 选项；不要改写已有选项。
2. merge：目标题被错误拆开，需要与前题或后题合并。
3. none：无需修改或无法可靠修复。

merge_indices 使用上方上下文题目列表的 0 基索引，例如第一道题是 0，第二道题是 1。

【输出格式】JSON:
{{
  "action": "repair_options" / "merge" / "none",
  "is_complete": true/false,
  "should_merge": true/false,
  "merge_with": "previous" / "next" / "none",
  "merge_indices": [0, 1],
  "repaired_question": {{
    "stem": "修复后的题干",
    "options": [
      {{"key": "A", "text": "...", "source": "extracted"}},
      {{"key": "B", "text": "...", "source": "ai_generated"}}
    ]
  }},
  "merged_question": {{
    "stem": "合并后的题干",
    "options": [{{"label": "A", "text": "..."}}, ...]
  }},
  "reason": "简短说明"
}}
"""

    def _parse_llm_fix_result(self, llm_response: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的修复指令。"""
        try:
            # 尝试提取JSON
            import json
            # 查找JSON块
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                action = str(result.get("action") or "").strip().lower()
                repaired_question = (
                    result.get("repaired_question")
                    or result.get("fixed_question")
                )
                if action not in {"repair_options", "merge", "none"}:
                    if result.get("should_merge"):
                        action = "merge"
                    elif isinstance(repaired_question, dict):
                        action = "repair_options"
                    else:
                        action = "none"
                return {
                    'action': action,
                    'should_merge': result.get('should_merge', False),
                    'merge_with': result.get('merge_with', 'none'),
                    'merge_indices': result.get('merge_indices', []),
                    'merged_question': result.get('merged_question'),
                    'repaired_question': repaired_question,
                    'reason': result.get('reason'),
                }
        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")

        # LLM返回格式错误，保守处理：不合并
        return {'action': 'none', 'should_merge': False}

    def _apply_llm_fix(
        self,
        questions: List[Dict[str, Any]],
        idx: int,
        context_start: int,
        fix_action: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """应用LLM的修复建议"""
        if fix_action.get("action") == "repair_options":
            return self._apply_option_repair(questions, idx, fix_action)
        if fix_action.get("action") != "merge" and not fix_action.get("should_merge"):
            return questions

        merged_question = fix_action.get('merged_question')
        if not merged_question:
            return questions

        merge_indices = fix_action.get('merge_indices', [])
        global_indices: List[int] = []
        if isinstance(merge_indices, list):
            for rel_idx in merge_indices:
                if isinstance(rel_idx, int):
                    global_idx = context_start + rel_idx
                    if 0 <= global_idx < len(questions):
                        global_indices.append(global_idx)

        if not global_indices:
            merge_with = fix_action.get('merge_with')
            if merge_with == 'previous' and idx > 0:
                global_indices = [idx - 1, idx]
            elif merge_with == 'next' and idx + 1 < len(questions):
                global_indices = [idx, idx + 1]
            else:
                global_indices = [idx]

        if idx not in global_indices:
            global_indices.append(idx)

        global_indices = sorted(set(global_indices))
        keep_idx = global_indices[0]
        merged_blocks = []
        merged_block_ids = []
        page_numbers = []
        for global_idx in global_indices:
            q = questions[global_idx]
            merged_blocks.extend(q.get('blocks') or [])
            merged_block_ids.extend(q.get('block_ids') or [])
            if q.get('page_no') is not None:
                page_numbers.append(q['page_no'])

        merged_meta = dict(questions[keep_idx].get("extraction_meta") or {})
        original_issues = list(merged_meta.get("original_issues") or [])
        for global_idx in global_indices:
            source_meta = questions[global_idx].get("extraction_meta") or {}
            for original_issue in source_meta.get("original_issues") or []:
                if original_issue not in original_issues:
                    original_issues.append(original_issue)

        # 替换保留题目，保留原始归属与来源信息
        questions[keep_idx].update(merged_question)
        if 'stem' in merged_question and 'content' not in merged_question:
            questions[keep_idx]['content'] = merged_question['stem']
        if 'content' in merged_question and 'stem' not in merged_question:
            questions[keep_idx]['stem'] = merged_question['content']
        if merged_blocks:
            questions[keep_idx]['blocks'] = merged_blocks
        if merged_block_ids:
            questions[keep_idx]['block_ids'] = merged_block_ids
        if page_numbers:
            questions[keep_idx]['page_no'] = min(page_numbers)
            questions[keep_idx]['page_range'] = f"{min(page_numbers)}-{max(page_numbers)}"
        questions[keep_idx]['fixed_by_llm'] = True
        merged_meta["original_issues"] = original_issues
        self._append_llm_fix_action(
            questions[keep_idx],
            merged_meta,
            action={
                "action": "merge",
                "merged_question_indices": global_indices,
                "reason": fix_action.get("reason"),
            },
        )

        # 如果需要删除其他题目（合并的情况）
        for remove_idx in sorted([i for i in global_indices if i != keep_idx], reverse=True):
            del questions[remove_idx]

        return questions

    def _apply_option_repair(
        self,
        questions: List[Dict[str, Any]],
        idx: int,
        fix_action: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """只补缺失标签，已有选项保持原文；自动核验补充选项来源。"""
        if idx < 0 or idx >= len(questions):
            return questions
        repaired = fix_action.get("repaired_question")
        if not isinstance(repaired, dict):
            return questions

        target = questions[idx]
        existing_options = list(target.get("options") or [])
        existing_labels = {
            _get_option_label(option)
            for option in existing_options
            if _get_option_label(option)
        }
        issue = fix_action.get("issue") or {}
        missing_labels = {
            str(label).strip().upper()[:1]
            for label in issue.get("missing_options") or []
            if str(label).strip().upper()[:1] in {"A", "B", "C", "D"}
        }
        if not missing_labels:
            missing_labels = {"A", "B", "C", "D"} - existing_labels

        source_text = self._collect_source_text(questions, idx)
        added_options: List[Dict[str, Any]] = []
        for option in repaired.get("options") or []:
            if not isinstance(option, dict):
                continue
            label = _get_option_label(option)
            text = str(option.get("text") or option.get("content") or "").strip()
            if (
                label not in {"A", "B", "C", "D"}
                or label in existing_labels
                or label not in missing_labels
                or not text
            ):
                continue
            source = (
                "extracted"
                if self._text_exists_in_source(text, source_text)
                else "ai_generated"
            )
            added_options.append({
                "key": label,
                "label": label,
                "option_label": label,
                "text": text,
                "source": source,
            })
            existing_labels.add(label)

        if not added_options:
            return questions

        target["options"] = sorted(
            [*existing_options, *added_options],
            key=lambda option: _get_option_label(option),
        )

        current_stem = target.get("stem") or target.get("content") or ""
        repaired_stem = str(repaired.get("stem") or repaired.get("content") or "").strip()
        if self._is_safe_repaired_stem(current_stem, repaired_stem):
            target["stem"] = repaired_stem
            target["content"] = repaired_stem

        meta = dict(target.get("extraction_meta") or {})
        self._append_llm_fix_action(
            target,
            meta,
            action={
                "action": "repair_options",
                "issue_type": issue.get("issue_type"),
                "added_options": [
                    {"key": option["key"], "source": option["source"]}
                    for option in added_options
                ],
                "reason": fix_action.get("reason"),
            },
        )
        return questions

    @staticmethod
    def _collect_source_text(questions: List[Dict[str, Any]], idx: int) -> str:
        """收集目标题及相邻题原文，作为 extracted/ai_generated 的事实依据。"""
        parts: List[str] = []
        for question in questions[max(0, idx - 1):min(len(questions), idx + 2)]:
            for key in ("raw_text", "stem", "content"):
                value = question.get(key)
                if value:
                    parts.append(str(value))
            for option in question.get("options") or []:
                text = option.get("text") if isinstance(option, dict) else None
                if text:
                    parts.append(str(text))
            for block in question.get("blocks") or []:
                if isinstance(block, dict):
                    text = block.get("content_text") or block.get("content_md") or ""
                else:
                    text = (
                        getattr(block, "content_text", None)
                        or getattr(block, "content_md", None)
                        or ""
                    )
                if text:
                    parts.append(str(text))
        return "\n".join(parts)

    @staticmethod
    def _normalize_source_text(text: str) -> str:
        return re.sub(r"[\s　]+", "", text or "")

    @classmethod
    def _text_exists_in_source(cls, text: str, source_text: str) -> bool:
        normalized = cls._normalize_source_text(text)
        return bool(normalized and normalized in cls._normalize_source_text(source_text))

    @classmethod
    def _is_safe_repaired_stem(cls, current_stem: str, repaired_stem: str) -> bool:
        if not repaired_stem:
            return False
        current_normalized = cls._normalize_source_text(current_stem)
        repaired_normalized = cls._normalize_source_text(repaired_stem)
        return bool(
            repaired_normalized
            and current_normalized
            and repaired_normalized in current_normalized
        )

    @staticmethod
    def _append_llm_fix_action(
        question: Dict[str, Any],
        meta: Dict[str, Any],
        action: Dict[str, Any],
    ) -> None:
        actions = list(meta.get("llm_fix_actions") or [])
        actions.append(action)
        meta["llm_fix_actions"] = actions
        meta["fixed_by_llm"] = True
        question["fixed_by_llm"] = True
        question["llm_fix_actions"] = actions
        question["extraction_meta"] = meta


def comprehensive_validation(questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    综合校验，生成完整的问题报告

    Returns:
        {
            'option_issues': [...],
            'number_continuity': {...},
            'quantity_check': {...},
            'summary': {
                'total_issues': int,
                'critical_issues': [...]
            }
        }
    """
    option_checker = OptionIntegrityChecker()
    number_checker = QuestionNumberChecker()

    # 1. 选项完整性
    option_issues = []
    for i, q in enumerate(questions):
        result = option_checker.check(q)
        if not result['is_complete']:
            option_issues.append({
                'question_index': i,
                'question_number': _extract_question_number_simple(q),
                'page_no': q.get('page_no'),
                **result
            })

    # 2. 编号连续性
    number_infos = number_checker.extract_question_numbers(questions)
    continuity_report = number_checker.detect_continuity_issues(number_infos)

    # 3. 数量一致性
    max_number = max([info['number'] for info in number_infos if info['number']], default=0)
    quantity_check = {
        'total_extracted': len(questions),
        'max_number_found': max_number,
        'is_consistent': len(questions) == continuity_report['global_issues']['numbered_questions']
    }

    # 4. 收集critical issues
    critical_issues = []
    # 选项问题都是critical
    critical_issues.extend(option_issues)
    # 编号问题中的high severity
    for seg in continuity_report['segments']:
        for iss in seg['issues']:
            if iss['severity'] == 'high':
                critical_issues.append({
                    'question_index': iss.get('after_index', iss.get('at_index', 0)),
                    'issue_type': iss['type'],
                    **iss
                })

    return {
        'option_issues': option_issues,
        'number_continuity': continuity_report,
        'quantity_check': quantity_check,
        'summary': {
            'total_issues': len(option_issues) + sum(len(seg['issues']) for seg in continuity_report['segments']),
            'critical_issues': critical_issues
        }
    }


def _extract_question_number_simple(question: Dict[str, Any]) -> Optional[int]:
    """简单提取题号"""
    text = (question.get('stem') or question.get('content') or '').strip()
    for pattern, _ in QuestionNumberChecker.NUMBER_PATTERNS:
        match = re.match(pattern, text)
        if match:
            return int(match.group(1))
    return None


# ===== QuestionLayoutGrouper: 基于 bbox 坐标的题目分组器 =====

# 阈值常量
LEFT_EDGE_MARGIN = 30       # 0-1000 坐标系，约 3% 页宽
GAP_RATIO_NEW_QUESTION = 3.0
GAP_RATIO_PAREN_Q = 1.5
GAP_RATIO_CONTINUATION = 1.5
# 分栏检测（0-1000 坐标系）：双栏页的左右栏 x0 分布会出现两个聚集带，
# 中间有明显空隙。COLUMN_GAP_MIN 为两带间的最小空隙，低于此视为单栏。
COLUMN_GAP_MIN = 120        # 左右栏 x0 聚集带之间的最小间隔
COLUMN_MIN_BLOCKS_PER_COL = 3   # 每栏至少的文本块数，避免个别偏移块误判成栏


def _strip_option_marker_simple(text: str) -> str:
    """去掉选项文本开头可能残留的选项标记，如 '. ' 或 '. Ⅰ' 等。"""
    t = (text or "").strip()
    t = re.sub(r'^\s*[.．、:：。]\s*', '', t)
    return t.strip()


@dataclass
class PageStats:
    page_no: int
    left_edge: float
    median_gap: float
    is_dense: bool
    # 分栏：column_boundary 为 None 表示单栏；非 None 时为左右栏分界 x 坐标。
    # left_edge_by_col 记录每栏各自的左边缘（0=左栏,1=右栏），双栏时右栏题号
    # 需按右栏左边缘判断 at_left_edge，否则右栏题目永远无法被识别为新题起点。
    column_boundary: Optional[float] = None
    left_edge_by_col: Optional[Dict[int, float]] = None


@dataclass
class BlockTag:
    block: Any
    at_left_edge: bool
    has_q_number: bool
    has_option: bool
    has_paren_q: bool
    is_media: bool
    is_noise: bool
    gap_ratio: float


@dataclass
class QuestionGroup:
    blocks: List[Any]
    page_no: int


class QuestionLayoutGrouper:
    """基于 bbox 坐标的题目分组器"""

    def __init__(self, blocks: List[Any]):
        self.blocks = blocks
        self.page_stats: Dict[int, PageStats] = {}

    # ---- Phase 1: 页面统计 ----

    def _compute_page_stats(self, page_no: int, page_blocks: List[Any]) -> PageStats:
        gaps: List[float] = []

        # 只对 text 类 block 计算左边缘和行距，排除 figure/table 等媒体块
        text_blocks = [
            b for b in page_blocks
            if (getattr(b, "block_type", "") or "").lower()
            not in (
                "figure", "table", "formula", "image", "chart",
                "header", "footer", "page_number", "aside_text", "page_footnote",
            )
        ]

        left_edges = [
            x0 for b in text_blocks
            if (x0 := self._bbox_x0(getattr(b, "bbox", None) or {})) is not None
        ]

        for i in range(1, len(text_blocks)):
            prev_bbox = getattr(text_blocks[i - 1], "bbox", None) or {}
            cur_bbox = getattr(text_blocks[i], "bbox", None) or {}
            prev_y1 = self._bbox_y1(prev_bbox)
            cur_y0 = self._bbox_y0(cur_bbox)
            if prev_y1 is not None and cur_y0 is not None:
                gap = cur_y0 - prev_y1
                if gap >= 0:
                    gaps.append(gap)

        page_left_edge = min(left_edges) if left_edges else 50.0
        median_gap = self._median(gaps) if gaps else 10.0
        is_dense = self._check_dense_layout(text_blocks)

        # 分栏检测：按 x0 分布找左右栏分界，双栏时每栏各算左边缘
        column_boundary, left_edge_by_col = self._detect_columns(text_blocks)

        return PageStats(
            page_no=page_no,
            left_edge=page_left_edge,
            median_gap=max(median_gap, 1.0),
            is_dense=is_dense,
            column_boundary=column_boundary,
            left_edge_by_col=left_edge_by_col,
        )

    def _detect_columns(
        self, text_blocks: List[Any]
    ) -> Tuple[Optional[float], Optional[Dict[int, float]]]:
        """检测页面是否双栏排版，返回 (分界x坐标, 每栏左边缘)。

        判据：block 的 x0 分布若明显聚成两簇（簇间存在宽间隙），即为双栏。
        单栏或样本不足返回 (None, None)。分界取两簇之间的中点。
        """
        x0s = sorted(
            x0 for b in text_blocks
            if (x0 := self._bbox_x0(getattr(b, "bbox", None) or {})) is not None
        )
        if len(x0s) < 6:
            return None, None

        # 找相邻 x0 的最大间隙，作为候选栏边界
        max_gap = 0.0
        gap_at = None
        for a, b in zip(x0s, x0s[1:]):
            if b - a > max_gap:
                max_gap = b - a
                gap_at = (a + b) / 2
        # 最大间隙需足够宽，且左右两侧都有足够 block，才认定为双栏
        if gap_at is None or max_gap < COLUMN_GAP_MIN:
            return None, None

        left = [x for x in x0s if x < gap_at]
        right = [x for x in x0s if x >= gap_at]
        if len(left) < COLUMN_MIN_BLOCKS_PER_COL or len(right) < COLUMN_MIN_BLOCKS_PER_COL:
            return None, None

        return gap_at, {0: min(left), 1: min(right)}

    def _column_of(self, block: Any, stats: PageStats) -> int:
        """返回 block 所在栏（0=左,1=右）；单栏恒为 0。"""
        if stats.column_boundary is None:
            return 0
        x0 = self._bbox_x0(getattr(block, "bbox", None) or {})
        if x0 is None:
            return 0
        return 1 if x0 >= stats.column_boundary else 0

    def _order_page_blocks(self, page_blocks: List[Any], stats: PageStats) -> List[Any]:
        """按阅读顺序重排一页内的 block。

        单栏：保持原 order_no（MinerU 输出顺序）。
        双栏：左栏整列（按 y 升序）→ 右栏整列（按 y 升序），修正 MinerU 跨栏交错。
        媒体/噪声块按其 y 坐标归入所在栏，保持与文本的相对位置。
        """
        if stats.column_boundary is None:
            return list(page_blocks)

        left_col: List[Any] = []
        right_col: List[Any] = []
        for b in page_blocks:
            col = self._column_of(b, stats)
            (left_col if col == 0 else right_col).append(b)

        def _y0(b: Any) -> float:
            v = self._bbox_y0(getattr(b, "bbox", None) or {})
            return v if v is not None else 0.0

        left_col.sort(key=_y0)
        right_col.sort(key=_y0)
        return left_col + right_col

    def _check_dense_layout(self, page_blocks: List[Any]) -> bool:
        """统计同 y 坐标的 block 数量，判断是否多栏排版"""
        y_buckets: Dict[int, int] = {}
        for b in page_blocks:
            bbox = getattr(b, "bbox", None) or {}
            y0 = self._bbox_y0(bbox)
            if y0 is None:
                continue
            bucket = int(y0 // 20)
            y_buckets[bucket] = y_buckets.get(bucket, 0) + 1
        total = sum(1 for v in y_buckets.values())
        if total == 0:
            return False
        multi = sum(1 for v in y_buckets.values() if v > 2)
        return (multi / total) > 0.3

    # ---- Phase 2: 逐 block 打标 ----

    @staticmethod
    def _col_left_edge(stats: PageStats, x0: Optional[float]) -> float:
        """取 block 所属栏的左边缘。单栏或无坐标时回退到全页左边缘。"""
        if x0 is None or stats.column_boundary is None or not stats.left_edge_by_col:
            return stats.left_edge
        col = 0 if x0 < stats.column_boundary else 1
        return stats.left_edge_by_col.get(col, stats.left_edge)

    def _tag_block(self, block: Any, stats: PageStats, prev_block: Optional[Any]) -> BlockTag:
        bbox = getattr(block, "bbox", None) or {}
        text = getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
        block_type = getattr(block, "block_type", "") or ""

        x0 = self._bbox_x0(bbox)
        at_left_edge = False
        if x0 is not None:
            # 双栏时用所属栏的左边缘，右栏题号（x0≈右栏起点）才能被判为贴边
            col_edge = self._col_left_edge(stats, x0)
            at_left_edge = (x0 - col_edge) < LEFT_EDGE_MARGIN

        has_q_number = bool(QUESTION_NUMERIC_RE.match(text.strip()))
        has_option = bool(OPTION_BLOCK_RE.match(text.strip()))
        has_paren_q = bool(QUESTION_PAREN_RE.match(text.strip()))
        is_media = block_type.lower() in ("figure", "table", "formula", "image", "chart")
        is_noise = block_type.lower() in ("header", "footer", "page_number", "aside_text", "page_footnote")

        gap_ratio = 0.0
        if prev_block is not None:
            prev_bbox = getattr(prev_block, "bbox", None) or {}
            prev_y1 = self._bbox_y1(prev_bbox)
            cur_y0 = self._bbox_y0(bbox)
            if prev_y1 is not None and cur_y0 is not None and stats.median_gap > 0:
                gap = cur_y0 - prev_y1
                gap_ratio = gap / stats.median_gap

        return BlockTag(
            block=block,
            at_left_edge=at_left_edge,
            has_q_number=has_q_number,
            has_option=has_option,
            has_paren_q=has_paren_q,
            is_media=is_media,
            is_noise=is_noise,
            gap_ratio=gap_ratio,
        )

    # ---- Phase 3: 题目边界判定 ----

    def group_into_questions(self) -> List[QuestionGroup]:
        """主入口：将 blocks 分组为题目列表"""
        if not self.blocks:
            return []

        # 按页组合 blocks
        pages: Dict[int, List[Any]] = {}
        for b in self.blocks:
            page_no = getattr(b, "page_no", None) or 1
            pages.setdefault(page_no, []).append(b)

        # 为每页计算 PageStats
        for page_no, page_blocks in pages.items():
            self.page_stats[page_no] = self._compute_page_stats(page_no, page_blocks)
            if self.page_stats[page_no].is_dense:
                logger.warning("检测到疑似多栏/密排页面，当前版本仅记录告警", page_no=page_no)

        groups: List[QuestionGroup] = []
        current_group_blocks: List[Any] = []
        prev_block: Optional[Any] = None

        all_blocks_ordered: List[Any] = []
        for page_no in sorted(pages.keys()):
            all_blocks_ordered.extend(
                self._order_page_blocks(pages[page_no], self.page_stats.get(page_no))
            )

        for i, block in enumerate(all_blocks_ordered):
            page_no = getattr(block, "page_no", None) or 1
            stats = self.page_stats.get(page_no)
            if stats is None:
                stats = PageStats(page_no=page_no, left_edge=50.0, median_gap=10.0, is_dense=False)
                self.page_stats[page_no] = stats

            prev = all_blocks_ordered[i - 1] if i > 0 else None
            tag = self._tag_block(block, stats, prev)

            if tag.is_noise:
                continue

            is_new_question = self._is_new_question_start(tag, prev_block)

            if is_new_question:
                if current_group_blocks:
                    groups.append(QuestionGroup(
                        blocks=current_group_blocks,
                        page_no=getattr(current_group_blocks[0], "page_no", None) or 1,
                    ))
                current_group_blocks = [block]
            else:
                current_group_blocks.append(block)

            prev_block = block

        if current_group_blocks:
            groups.append(QuestionGroup(
                blocks=current_group_blocks,
                page_no=getattr(current_group_blocks[0], "page_no", None) or 1,
            ))

        # Phase 5: 跨页合并
        groups = self._merge_cross_page_groups(groups)

        return groups

    def _is_new_question_start(self, tag: BlockTag, prev_block: Optional[Any]) -> bool:
        """判断是否为新题目起点"""
        if prev_block is None:
            return True

        # 选项/噪声块绝不可能是新题起点
        if tag.has_option or tag.is_noise:
            return False

        # 媒体块（图/表）通常不是新题起点，但 MinerU 有时把"题号+题干+数据表"
        # 整块识别成 table（如第47题），此时题号就在 media 块里。若 media 块
        # 左边缘且带阿拉伯数字题号，视为新题起点，避免整道题被并入前一题；
        # 否则（纯图表、无题号）仍归属当前题。
        if tag.is_media:
            return bool(tag.at_left_edge and tag.has_q_number)

        # 检查当前 block 是否有有效的 bbox（x0 和 y0 都能取到）
        bbox = getattr(tag.block, "bbox", None) or {}
        has_bbox = (
            self._bbox_x0(bbox) is not None
            and self._bbox_y0(bbox) is not None
        )

        if has_bbox:
            # ---- 有 bbox：题号锚定 ----
            # 一道题的边界由"题号"锚定，而非 block 间距。408 简答题常有
            # "题干 + 图/表 + 追问 + (1)(2) 小问"结构，中间的表格/图/续体
            # 没有题号，必须归属当前题，不能因大间距被误判成新题——否则一道题
            # 会被表格从中间切断（如第46题）。

            # A. 左边缘 + 阿拉伯数字题号 → 新题（最高置信度，覆盖选择题与大题）
            if tag.at_left_edge and tag.has_q_number:
                return True

            # 括号号 (1)(2) 是题内小问，绝不是新题起点；有它就明确归属当前题。
            if tag.has_paren_q:
                return False

            # 其余无题号块（续体、表格后的追问、跨栏延续）一律归属当前题。
            # 去掉原"大间距 + 长文本 → 新题"的规则 C：表格/图会撑大间距，
            # 是题目被切断的元凶，间距不再作为新题依据。
            return False

        # ---- 无 bbox：只认强题号（与有 bbox 分支一致）。
        # 括号号 (1)(2) 是题内小问，不作为新题起点，避免把简答题的小问拆成独立题。
        if tag.has_q_number:
            return True

        return False

    # ---- Phase 4: 组内处理 ----

    @staticmethod
    def _has_inline_options(text: str) -> bool:
        """判断文本内是否内联了选项序列（题干与选项同一 block）。

        要求含选项 A 且至少 2 个不同选项标记，避免把题干中孤立的 "A。" 误判为选项。
        """
        labels = {m.group(1).upper() for m in OPTION_MARKER_RE.finditer(text or "")}
        return "A" in labels and len(labels) >= 2

    @staticmethod
    def _find_inline_option_start(text: str) -> int:
        """返回选项 A 标记在文本中的起始下标；找不到返回 -1。"""
        for m in OPTION_MARKER_RE.finditer(text or ""):
            if m.group(1).upper() == "A":
                return m.start()
        return -1

    def _extract_stem(self, group: QuestionGroup) -> str:
        parts: List[str] = []
        in_options = False
        recoverable_inline = self._find_recoverable_inline_option(group)
        for block_idx, block in enumerate(group.blocks):
            text = getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
            text = text.strip()
            if not text:
                continue
            if OPTION_BLOCK_RE.match(text):
                in_options = True
            if in_options:
                continue
            block_type = getattr(block, "block_type", "") or ""
            if block_type.lower() in ("figure", "table", "formula", "image", "chart"):
                # media 块通常是纯图表，内容不混进题干。但 MinerU 常把"题干文字+数据表"
                # 混成一个 table 块（如第47题），块内带题号的文字正是题干，需纳入；
                # 纯图表（无题号文字）仍跳过。
                if QUESTION_NUMERIC_RE.match(text):
                    parts.append(text)
                continue
            if recoverable_inline and block_idx == recoverable_inline[0]:
                stem_part = text[:recoverable_inline[1]].strip()
                if stem_part:
                    parts.append(stem_part)
                in_options = True
                continue
            # 题干+选项同块：只保留选项标记之前的题干，选项部分留给 _extract_options 处理
            if self._has_inline_options(text):
                opt_start = self._find_inline_option_start(text)
                if opt_start > 0:
                    stem_part = text[:opt_start].strip()
                    if stem_part:
                        parts.append(stem_part)
                    in_options = True
                    continue
            parts.append(text)
        # 用空格而非换行拼接 stem
        return " ".join(parts)

    def _extract_options(self, group: QuestionGroup) -> List[Dict[str, str]]:
        """从组内提取选项（含跨 block 合并）"""
        option_blocks: List[Dict[str, Any]] = []
        non_option_after: List[Any] = []
        last_option_block: Optional[Any] = None

        option_phase = False
        recoverable_inline = self._find_recoverable_inline_option(group)
        for block_idx, block in enumerate(group.blocks):
            text = getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
            text = text.strip()
            block_type = getattr(block, "block_type", "") or ""

            if recoverable_inline and block_idx == recoverable_inline[0]:
                option_phase = True
                option_blocks.append({
                    "text": text[recoverable_inline[1]:],
                    "block": block,
                    "is_option": True,
                })
                last_option_block = block
            elif OPTION_BLOCK_RE.match(text):
                option_phase = True
                option_blocks.append({"text": text, "block": block, "is_option": True})
                last_option_block = block
            elif not option_phase and self._has_inline_options(text):
                # 题干+选项同块：切出选项标记之后的部分作为选项文本
                opt_start = self._find_inline_option_start(text)
                if opt_start >= 0:
                    option_phase = True
                    option_blocks.append({"text": text[opt_start:], "block": block, "is_option": True})
                    last_option_block = block
            elif option_phase:
                # 媒体块不应作为选项尾部文字合并
                if (
                    block_type.lower() not in ("figure", "table", "formula", "image", "chart")
                    and last_option_block is not None
                    and self._should_append_to_last_option(last_option_block, block)
                ):
                    non_option_after.append(block)

        if not option_blocks:
            return []

        # 从选项块中解析出各个选项
        all_option_text = " ".join(ob["text"] for ob in option_blocks)

        options = self._parse_options_from_text(all_option_text)

        # 处理跨 block 的选项尾部文字
        if non_option_after and options:
            trailing_text = " ".join(
                getattr(b, "content_text", None) or getattr(b, "content_md", None) or ""
                for b in non_option_after
            ).strip()
            if trailing_text and not QUESTION_NUMERIC_RE.match(trailing_text):
                options[-1]["text"] = options[-1]["text"] + " " + trailing_text

        return options

    @staticmethod
    def _find_recoverable_inline_option(group: QuestionGroup) -> Optional[Tuple[int, int]]:
        """识别“A 粘在题干末尾、后续 B/C/D 分块”的 MinerU 常见输出。"""
        first_option_block_idx: Optional[int] = None
        first_option_label = ""
        for block_idx, block in enumerate(group.blocks):
            text = (
                getattr(block, "content_text", None)
                or getattr(block, "content_md", None)
                or ""
            ).strip()
            match = OPTION_BLOCK_RE.match(text)
            if match:
                first_option_block_idx = block_idx
                first_option_label = match.group(1).upper()
                break

        if first_option_block_idx is None or first_option_label != "B":
            return None

        for block_idx in range(first_option_block_idx - 1, -1, -1):
            block = group.blocks[block_idx]
            text = (
                getattr(block, "content_text", None)
                or getattr(block, "content_md", None)
                or ""
            ).strip()
            matches = [
                match
                for match in OPTION_MARKER_RE.finditer(text)
                if match.group(1).upper() == "A"
            ]
            if matches:
                start = matches[-1].start(1)
                if start > 0 and text[matches[-1].end():].strip():
                    return block_idx, start
            if QUESTION_NUMERIC_RE.match(text):
                break
        return None

    def _should_append_to_last_option(self, option_block: Any, continuation_block: Any) -> bool:
        text = (
            getattr(continuation_block, "content_text", None)
            or getattr(continuation_block, "content_md", None)
            or ""
        ).strip()
        if not text:
            return False
        if QUESTION_NUMERIC_RE.match(text) or QUESTION_PAREN_RE.match(text) or OPTION_BLOCK_RE.match(text):
            return False

        option_bbox = getattr(option_block, "bbox", None) or {}
        cont_bbox = getattr(continuation_block, "bbox", None) or {}
        option_y1 = self._bbox_y1(option_bbox)
        cont_y0 = self._bbox_y0(cont_bbox)
        option_x0 = self._bbox_x0(option_bbox)
        option_x1 = self._bbox_x1(option_bbox)
        cont_x0 = self._bbox_x0(cont_bbox)

        if option_y1 is not None and cont_y0 is not None and cont_y0 < option_y1:
            return False

        page_no = getattr(option_block, "page_no", None) or getattr(continuation_block, "page_no", None) or 1
        stats = self.page_stats.get(page_no)
        if stats and option_y1 is not None and cont_y0 is not None:
            gap = max(0.0, cont_y0 - option_y1)
            gap_ratio = gap / max(stats.median_gap, 1.0)
            if gap_ratio >= GAP_RATIO_CONTINUATION:
                return False

        if option_x0 is not None and option_x1 is not None and cont_x0 is not None:
            if cont_x0 > option_x1 + LEFT_EDGE_MARGIN:
                return False

        return True

    def _parse_options_from_text(self, text: str) -> List[Dict[str, str]]:
        """从选项文本中提取各个选项"""
        if not text:
            return []
        matches = list(OPTION_MARKER_RE.finditer(text))
        if not matches:
            return []

        # 选项标记必然严格升序 A<B<C<D。遇到非升序标记（MinerU 常把右栏末题的
        # 末选项重复输出成残块，或选项文本尾部粘连下一标记字母）即视为选项区结束，
        # 用它的位置作为最后一个有效选项的截断点，丢弃其后的重复残块。
        valid: List[Any] = []
        last_ord = ord("A") - 1
        cutoff = len(text)
        for m in matches:
            if ord(m.group(1).upper()) > last_ord:
                valid.append(m)
                last_ord = ord(m.group(1).upper())
            else:
                cutoff = m.start(1)
                break

        options: List[Dict[str, str]] = []
        for idx, match in enumerate(valid):
            label = match.group(1).upper()
            text_start = match.end()
            text_end = valid[idx + 1].start(1) if idx + 1 < len(valid) else cutoff
            option_text = text[text_start:text_end].strip()
            # 去掉选项文本开头可能残留的选项标记
            option_text = _strip_option_marker_simple(option_text)
            if not option_text:
                continue
            options.append({
                "key": label,
                "label": label,
                "option_label": label,
                "text": option_text,
            })

        return options if len(options) >= 2 else []

    def _extract_figures(self, group: QuestionGroup) -> List[str]:
        figure_ids: List[str] = []
        for block in group.blocks:
            block_type = getattr(block, "block_type", "") or ""
            if block_type.lower() in ("figure", "table", "formula", "image", "chart"):
                block_id = getattr(block, "id", None)
                if block_id:
                    figure_ids.append(block_id)
        return figure_ids

    def _extract_question_no(self, group: QuestionGroup) -> Optional[int]:
        for block in group.blocks:
            text = getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
            text = text.strip()
            m = QUESTION_NUMERIC_RE.match(text)
            if m:
                return int(m.group(1))
            m = QUESTION_PAREN_RE.match(text)
            if m:
                return int(m.group(1))
            m = QUESTION_TITLE_RE.match(text)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
        return None

    def classify_group(
        self, group: QuestionGroup, options: List[Dict[str, str]], question_no: Optional[int]
    ) -> Tuple[str, str]:
        """判断一个组是题目还是知识点候选。

        返回 (label, reason)，label ∈ {"question", "knowledge_candidate", "uncertain"}。
        组题已经把拆散的选项/跨页内容合并好，所以"有选项"是题目的强信号。
        判定顺序按置信度从高到低：
          1. 有 ≥2 个选项 → 题目（最强，选择题）
          2. 有题号(1./（1）/第一题) → 题目
          3. 有明确疑问特征(下列/正确的是/？等) → 题目（大题/简答）
          4. 都没有 → 知识点候选(uncertain，交给上层决定或 LLM)
        """
        if options and len(options) >= 2:
            return "question", "has_options"
        if question_no is not None:
            return "question", "has_question_no"

        # 疑问特征：合并组内全部文本再判，避免题干被拆到多个 block 时漏判
        joined = " ".join(
            (getattr(b, "content_text", None) or getattr(b, "content_md", None) or "")
            for b in group.blocks
        )
        if QUESTION_CUE_RE.search(joined):
            return "question", "has_cue"

        return "uncertain", "no_signal"

    # ---- Phase 5: 跨页处理 ----

    def _merge_cross_page_groups(self, groups: List[QuestionGroup]) -> List[QuestionGroup]:
        """合并跨页的题目"""
        if len(groups) < 2:
            return groups

        merged: List[QuestionGroup] = []
        i = 0
        while i < len(groups):
            current = groups[i]
            next_group = groups[i + 1] if i + 1 < len(groups) else None

            if next_group and self._should_merge_groups(current, next_group):
                combined = QuestionGroup(
                    blocks=current.blocks + next_group.blocks,
                    page_no=current.page_no,
                )
                merged.append(combined)
                i += 2
            else:
                merged.append(current)
                i += 1

        return merged

    def _should_merge_groups(self, current: QuestionGroup, next_group: QuestionGroup) -> bool:
        cur_has_options = any(
            OPTION_BLOCK_RE.match(
                (getattr(b, "content_text", None) or getattr(b, "content_md", None) or "").strip()
            )
            for b in current.blocks
        )
        if cur_has_options:
            return False

        # 当前组只有题干没有选项，且下组开头是选项
        next_blocks = next_group.blocks
        if not next_blocks:
            return False
        first_text = (
            getattr(next_blocks[0], "content_text", None) or
            getattr(next_blocks[0], "content_md", None) or ""
        ).strip()
        if OPTION_BLOCK_RE.match(first_text) and not QUESTION_NUMERIC_RE.match(first_text):
            return True

        return False

    # ---- 坐标辅助方法 ----

    @staticmethod
    def _bbox_x0(bbox: Optional[dict]) -> Optional[float]:
        """左边缘。MinerU 归一化存储 {x1: left, y1: top, x2: right, y2: bottom}"""
        if not bbox:
            return None
        val = bbox.get("x1")  # MinerU normalized: x1 = left
        if val is None:
            val = bbox.get("x0") or bbox.get("l")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bbox_y0(bbox: Optional[dict]) -> Optional[float]:
        """上边缘。MinerU 归一化存储 {x1: left, y1: top, x2: right, y2: bottom}"""
        if not bbox:
            return None
        val = bbox.get("y1")  # MinerU normalized: y1 = top
        if val is None:
            val = bbox.get("y0") or bbox.get("t")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bbox_x1(bbox: Optional[dict]) -> Optional[float]:
        """右边缘。MinerU 归一化存储 {x1: left, y1: top, x2: right, y2: bottom}"""
        if not bbox:
            return None
        val = bbox.get("x2")  # MinerU normalized: x2 = right
        if val is None:
            val = bbox.get("x1") or bbox.get("r")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bbox_y1(bbox: Optional[dict]) -> Optional[float]:
        """下边缘。MinerU 归一化存储 {x1: left, y1: top, x2: right, y2: bottom}"""
        if not bbox:
            return None
        val = bbox.get("y2")  # MinerU normalized: y2 = bottom
        if val is None:
            val = bbox.get("y1") or bbox.get("b")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _median(values: List[float]) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n % 2 == 1:
            return sorted_vals[n // 2]
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0


class EntityExtractionService:
    """实体抽取服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def extract_entities_with_run_id(self, run_id: str) -> Dict[str, Any]:
        """执行已创建的抽取任务，并将最终状态持久化到运行记录。"""
        run = await self.db.get(EntityExtractionRun, run_id)
        if not run:
            raise ValueError(f"抽取任务不存在: {run_id}")

        try:
            result = await self.extract_entities(
                document_id=run.document_id,
                extract_knowledge=run.extract_knowledge,
                extract_questions=run.extract_questions,
                fallback_subject_id=run.subject_id,
            )
            run.status = "success"
            run.knowledge_count = int(result.get("knowledge_count") or 0)
            run.question_count = int(result.get("question_count") or 0)
            run.result_json = json.loads(
                json.dumps(result, ensure_ascii=False, default=str)
            )
            run.error_detail = None
            run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self.db.commit()
            return result
        except Exception as exc:
            await self.db.rollback()
            failed_run = await self.db.get(EntityExtractionRun, run_id)
            if failed_run:
                failed_run.status = "failed"
                failed_run.error_detail = str(exc)[:4000]
                failed_run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await self.db.commit()
            raise

    async def extract_entities(
        self,
        document_id: str,
        extract_knowledge: bool = True,
        extract_questions: bool = True,
        fallback_subject_id: Optional[str] = None,
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

        # document.subject_id 仅作为 fallback；前端可在试卷类文档中显式传入学科。
        fallback_subject_id = fallback_subject_id or document.subject_id

        # 1.5 提取文档级来源元信息（年份/真题/机构/试卷名），广播到题目
        from app.services.document_meta_service import DocumentMetaService
        try:
            self._doc_meta = await DocumentMetaService(self.db).extract_and_store_meta(document_id)
        except Exception as e:
            logger.warning("文档元信息提取失败，题目来源将留空", document_id=document_id, error=str(e))
            self._doc_meta = {}
        self._doc_type = document.doc_type or "other"

        # 2. 获取 blocks
        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = blocks_result.scalars().all()

        if not blocks:
            return {
                "knowledge_count": 0,
                "question_count": 0,
                "question_diagnostic": None,
                "message": "文档没有 blocks",
            }

        # 2.5 清洗 <sub>/<sup> 标签和多余空白，知识点和题目两条路径共用
        blocks = clean_blocks_punctuation(blocks)

        # 2.6 混排识别：把每个 block 标记为 knowledge / question_stem / question_option / answer 等
        from app.services.block_classifier import BlockClassifier
        classifier_llm = await self._get_pdf_structure_llm_client()
        classifier = BlockClassifier(llm_client=classifier_llm)
        classifications = await classifier.classify(blocks, use_llm=bool(classifier_llm and classifier_llm.is_available))
        block_label_by_id = {c.block_id: c.label for c in classifications if c.block_id}
        classification_stats = BlockClassifier.stats(classifications)
        logger.info("Block 类型分类完成", stats=classification_stats)

        # 3. 获取 section 映射，用于确定章节和学科归属
        # page -> {chapter_id, subject_id}
        section_mappings = await self._get_section_mappings(document_id)

        knowledge_count = 0
        question_count = 0
        question_diagnostic: Optional[Dict[str, Any]] = None
        question_unassigned: List[Dict[str, Any]] = []
        answer_linked = 0

        # 架构：先组题再判类型。题目路径吃全部文本 block（不再按分类器预过滤，
        # 避免题目 block 被误判成 knowledge 而在组题前就被滤掉）。组题后由
        # QuestionLayoutGrouper.classify_group 按"有选项/题号/疑问特征"判定是否题目，
        # 非题目组不落为题目、其 block 留给知识点路径。
        # block_label_by_id 仅用于诊断展示，不再决定分流。
        consumed_block_ids: set = set()

        # 4. 抽取题目 — 吃全部 block，组题后判类型
        if extract_questions:
            await self._cleanup_existing_entities(document_id, "question")
            question_result = await self._extract_questions(
                document_id, fallback_subject_id, list(blocks), section_mappings
            )
            question_count = question_result["saved_count"]
            question_diagnostic = question_result["diagnostic"]
            question_unassigned = question_result.get("unassigned", [])
            consumed_block_ids = set(question_result.get("consumed_block_ids") or [])
            # 4.1 PDF 自带答案区回连：扫描"参考答案"段，按题号写回 answer（标 extracted）
            try:
                answer_linked = await self._extract_and_link_answers(document_id, blocks)
            except Exception as e:
                logger.warning("PDF 答案区回连失败，跳过", document_id=document_id, error=str(e))
                answer_linked = 0

        # 5. 抽取知识点 — 用剩余 block（排除已被题目消费的），保留标题/段落结构
        if extract_knowledge:
            await self._cleanup_existing_entities(document_id, "knowledge_point")
            knowledge_blocks = [
                b for b in blocks
                if getattr(b, "id", None) not in consumed_block_ids
                and block_label_by_id.get(getattr(b, "id", ""), "") in ("knowledge", "heading", "table", "figure", "formula")
            ] or [b for b in blocks if getattr(b, "id", None) not in consumed_block_ids]
            knowledge_count = await self._extract_knowledge_points(
                document_id, fallback_subject_id, knowledge_blocks, section_mappings
            )

        # 跨页归属加固：找出未被任何 section 覆盖的页码（标题漏检/映射失败的信号）
        all_pages = sorted({b.page_no for b in blocks if b.page_no is not None})
        covered_pages = set(section_mappings.keys())
        uncovered_pages = [p for p in all_pages if p not in covered_pages]
        if uncovered_pages:
            logger.warning(
                "存在未被章节映射覆盖的页码，题目/知识点将依赖前后回退归属",
                document_id=document_id,
                uncovered_pages=uncovered_pages,
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
            "question_diagnostic": question_diagnostic,
            "block_classification": classification_stats,
            "doc_meta": getattr(self, "_doc_meta", {}) or {},
            "unassigned_questions": question_unassigned,
            "uncovered_pages": uncovered_pages,
            "answer_linked": answer_linked,
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
                    DocumentSectionMapping.review_status == "approved"
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
                    "source_section_path": section.section_path[:500] if section.section_path else None,
                }
                for page in range(section.page_start, (section.page_end or section.page_start) + 1):
                    page_chapter_map[page] = info

        return page_chapter_map

    def _resolve_mapping_for_page(
        self,
        page_no: Optional[int],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> Optional[Dict[str, Optional[str]]]:
        """按页码获取章节映射，缺精确页时回退到最近的前序映射，再回退到最近后序映射。"""
        if page_no is None or not section_mappings:
            return None
        if page_no in section_mappings:
            return section_mappings[page_no]

        previous_pages = [page for page in section_mappings.keys() if page <= page_no]
        if previous_pages:
            return section_mappings[max(previous_pages)]
        next_pages = [page for page in section_mappings.keys() if page > page_no]
        if next_pages:
            return section_mappings[min(next_pages)]
        return None

    async def _cleanup_existing_entities(self, document_id: str, entity_type: str) -> None:
        """清理同一文档已抽取的实体，避免重复入库。"""
        await cleanup_document_entities(self.db, document_id, entity_type)

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
        mapping_info = self._resolve_mapping_for_page(title_block.page_no, section_mappings)
        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = mapping_info["subject_id"] if mapping_info else fallback_subject_id
        legacy_chapter_id = mapping_info["legacy_chapter_id"] if mapping_info else None
        source_section_path = mapping_info.get("source_section_path") if mapping_info else None
        resolved_source: Optional[str] = None

        # 组合内容
        content_parts = []
        for block in content_blocks:
            text = block.content_md or block.content_text or ""
            if text.strip():
                content_parts.append(text.strip())
        content = "\n\n".join(content_parts)

        if not content:
            return False

        title_text = title_block.content_text or ""

        # 回退：section 映射拿不到章节时，直接用 title/content 匹配大纲
        if not primary_chapter_id:
            from app.services.chapter_link_service import ChapterLinkService
            topic_terms_preview = self._extract_topic_terms(title_text, content)
            resolved = await ChapterLinkService(self.db).resolve_chapter_for_entity(
                title=title_text,
                content=content[:1000],
                subject_id=subject_id,
                topic_terms=topic_terms_preview,
                entity_type="knowledge_point",
            )
            if resolved:
                primary_chapter_id = resolved["chapter_id"]
                subject_id = resolved.get("subject_id") or subject_id
                resolved_source = resolved.get("source", "keyword_match")
                logger.info(
                    "知识点章节直接解析成功",
                    document_id=document_id,
                    chapter_id=primary_chapter_id,
                    source=resolved_source,
                    confidence=resolved.get("confidence"),
                )

        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=subject_id,
            )
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
            source_section_path=source_section_path,
            title=title_block.content_text or "未命名知识点",
            canonical_title=title_block.content_text,
            content=content,
            topic_terms=topic_terms,
            review_status="pending",
            status="active",
        )
        self.db.add(knowledge_point)

        # 创建章节关联
        if primary_chapter_id:
            link = KnowledgePointChapterLink(
                knowledge_point_id=kp_id,
                canonical_chapter_id=primary_chapter_id,
                is_primary=True,
                source=resolved_source or ("document_mapping" if mapping_info else "manual"),
                created_by="system",
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

        # 关联资产：按实体覆盖的 block 精确绑定（只绑这些 block 上挂着的图/表/公式）
        try:
            from app.services.entity_asset_service import link_entity_assets_by_blocks
            block_ids = [title_block.id] + [b.id for b in content_blocks]
            await link_entity_assets_by_blocks(
                self.db,
                entity_type="knowledge_point",
                entity_id=kp_id,
                block_ids=block_ids,
            )
        except Exception as e:
            logger.warning("知识点资产关联失败", knowledge_point_id=kp_id, error=str(e))

        return True

    async def _extract_questions(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> Dict[str, Any]:
        """
        抽取题目（带校验和修复）

        完整流程：
        1. 标点清洗（入口已完成）
        2. 基于 bbox 坐标分组提取题目
        3. 综合校验
        4. 规则修复
        5. 重新校验
        6. LLM兜底（可选）
        7. 保存题目和诊断报告
        """
        # Step 1: 标点 / 空白清洗已在 extract_entities 入口完成

        # Step 2: 基于 bbox 坐标分组提取题目
        raw_questions = await self._extract_questions_v2(
            document_id, fallback_subject_id, blocks, section_mappings
        )
        logger.info(f"初步提取 (bbox): {len(raw_questions)} 道题目")

        if not raw_questions:
            diagnostic = self._build_question_extraction_diagnostic(
                raw_questions=[],
                final_questions=[],
                validation_report={},
                final_report={},
                saved_results=[],
            )
            return {"saved_count": 0, "diagnostic": diagnostic, "unassigned": [], "consumed_block_ids": set()}

        # Step 3: 综合校验
        validation_report = comprehensive_validation(raw_questions)
        logger.info(f"校验发现 {validation_report['summary']['total_issues']} 个问题")

        # Step 4: 规则修复
        fixer = RuleBasedFixer()

        # 4.1 修复选项问题
        questions = fixer.fix_option_issues(raw_questions, validation_report['option_issues'])

        rule_fixed_count = sum(1 for q in questions if q.get('fixed_by_rule'))
        logger.info(f"规则修复: {rule_fixed_count} 道题目")

        # Step 5: 重新校验
        validation_report_v2 = comprehensive_validation(questions)

        # Step 6: LLM兜底（可选，由配置中心的 pdf_structure_llm 独立控制）
        if validation_report_v2['summary']['critical_issues']:
            llm_client = await self._get_pdf_structure_llm_client()
            if llm_client and llm_client.is_available:
                llm_fixer = LLMFallbackFixer(llm_client)
                questions = await llm_fixer.fix_remaining_issues(questions, validation_report_v2)
            elif llm_client and llm_client.enabled:
                logger.warning(
                    "PDF结构解析LLM已启用但配置不完整，跳过LLM兜底",
                    provider=llm_client.provider,
                    model=llm_client.model,
                    has_api_key=bool(llm_client.api_key),
                )

        # Step 7: 最终验证
        final_report = comprehensive_validation(questions)
        logger.info(f"最终: {len(questions)} 道题目, {final_report['summary']['total_issues']} 个剩余问题")

        # Step 7.5: 基于修复后的最终 options 重算 extraction_meta。
        # meta 首次在组题阶段(Step 2)生成，但 Step 4 规则修复会补齐跨 block 的选项
        # （如第3题的 D 选项单独成块后被合并），若不重算，few_options/option_count
        # 等诊断仍是修复前的快照，导致"选项已补全却标选项不足"的误标。
        for q in questions:
            prev_meta = q.get('extraction_meta') or {}
            new_meta = self._build_extraction_meta(
                blocks=q.get('blocks') or [],
                options=q.get('options') or [],
                question_type=q.get('question_type') or q.get('type') or "short_answer",
                question_no=q.get('question_no'),
                has_figures=bool(q.get('figures')),
                group_label_reason=prev_meta.get('group_label_reason'),
            )
            q['extraction_meta'] = {**prev_meta, **new_meta}

        # Step 8: 保存诊断报告（存储到document的metadata中）
        diagnostic_report = {
            'initial_report': validation_report,
            'after_rule_fix': validation_report_v2,
            'final_report': final_report,
            'fix_history': self._extract_fix_history(questions)
        }
        await self._save_diagnostic_report(document_id, diagnostic_report)

        # Step 9: 保存题目到数据库
        saved_results = []
        for question_dict in questions:
            saved, reason = await self._save_question_from_dict(question_dict)
            saved_results.append({
                "question_id": question_dict.get("id"),
                "question_no": _extract_question_number_simple(question_dict),
                "page_no": question_dict.get("page_no"),
                "saved": saved,
                "reason": reason,
                "subject_id": question_dict.get("subject_id"),
                "chapter_id": question_dict.get("chapter_id"),
                "primary_chapter_id": question_dict.get("primary_chapter_id"),
                "text_excerpt": self._question_text_excerpt(question_dict),
            })

        question_count = sum(1 for item in saved_results if item["saved"])
        # 未归属（缺学科/章节）题目现在也入库（reason=saved_unassigned），
        # 聚合页码 + 摘要冒泡到结果，供前端人工指认章节。
        unassigned = [
            {
                "page_no": item.get("page_no"),
                "question_no": item.get("question_no"),
                "reason": item.get("reason"),
                "text_excerpt": item.get("text_excerpt"),
            }
            for item in saved_results
            if item.get("reason") == "saved_unassigned"
        ]
        diagnostic = self._build_question_extraction_diagnostic(
            raw_questions=raw_questions,
            final_questions=questions,
            validation_report=validation_report,
            final_report=final_report,
            saved_results=saved_results,
        )

        # 收集被题目消费的 block_ids：知识点路径据此排除，避免同一 block 既成题又成知识点
        saved_ids = {item["question_id"] for item in saved_results if item["saved"]}
        consumed_block_ids: set = set()
        for q in questions:
            if q.get("id") in saved_ids:
                consumed_block_ids.update(q.get("block_ids") or [])

        return {
            "saved_count": question_count,
            "diagnostic": diagnostic,
            "unassigned": unassigned,
            "consumed_block_ids": consumed_block_ids,
        }

    async def _get_pdf_structure_llm_client(self) -> Optional[PDFStructureLLMClient]:
        """读取 PDF 结构解析专用 LLM 配置。"""
        try:
            runtime_settings = await SystemSettingsService(self.db).load()
            llm_config = runtime_settings.get("pdf_structure_llm", {})
            return PDFStructureLLMClient(llm_config if isinstance(llm_config, dict) else {})
        except Exception as e:
            logger.warning("读取PDF结构解析LLM配置失败，跳过LLM兜底", error=str(e))
            return None

    @staticmethod
    def _detect_merged_question_nos(text: str, base_no: Optional[int]) -> List[int]:
        """检测一段文本里是否粘连了后继题目的题号。

        MinerU 偶尔把相邻两题输出进同一 block（如第8题的题号"8。"粘在第7题
        选项之后）。这里在 base_no 之后找 base_no+1..base_no+3 的题号标记，
        命中说明本组疑似多题粘连，返回粘进来的题号列表。
        base_no 为空时无法判断后继，返回空。
        """
        if base_no is None or not text:
            return []
        found: List[int] = []
        # 题号标记：文本中的"<数字>。/、"，只认 base_no 之后的连续后继题号
        for m in re.finditer(r'(?<!\d)(\d{1,3})\s*[.、．。]\s*(?=\S)', text):
            n = int(m.group(1))
            if base_no < n <= base_no + 3 and n not in found:
                found.append(n)
        return found

    async def _llm_split_merged_questions(
        self,
        llm_client: "PDFStructureLLMClient",
        raw_text: str,
        base_no: int,
        successor_nos: List[int],
    ) -> Optional[List[Dict[str, Any]]]:
        """用 LLM 把粘在一起的多道题切开。

        只做切分（信息都在 raw_text 里），不补选项、不改写内容。
        返回 [{question_no, stem, options:[{key,text}]}, ...]；失败返回 None。
        """
        import json
        nos = ", ".join(str(n) for n in [base_no, *successor_nos])
        prompt = f"""下面这段文本是从试卷 PDF 中提取的，疑似把多道题（题号 {nos}）粘连在了一起。
请按题号把它们切分成独立题目。严格要求：
1. 只做切分，不要补全、改写、编造任何内容——所有文字都必须来自原文。
2. 每道题输出题号、题干、选项（如果是选择题）。选项格式 {{"key":"A","text":"..."}}。
3. 若某题没有选项（简答/大题），options 为空数组。

原始文本：
{raw_text}

只输出 JSON 数组，格式：
[{{"question_no": {base_no}, "stem": "...", "options": [{{"key":"A","text":"..."}}]}}, ...]"""
        try:
            resp = await llm_client.chat(prompt, purpose="题目粘连切分")
            start = resp.find("[")
            end = resp.rfind("]")
            if start < 0 or end <= start:
                logger.warning("LLM 切分返回无有效 JSON 数组", base_no=base_no)
                return None
            parsed = json.loads(resp[start:end + 1])
            if not isinstance(parsed, list) or len(parsed) < 2:
                return None
            out: List[Dict[str, Any]] = []
            for item in parsed:
                if not isinstance(item, dict) or not (item.get("stem") or "").strip():
                    continue
                opts = []
                for o in item.get("options") or []:
                    if isinstance(o, dict) and o.get("text"):
                        key = str(o.get("key") or o.get("label") or "").strip().upper()[:1]
                        opts.append({"key": key, "label": key, "option_label": key, "text": o["text"].strip()})
                out.append({
                    "question_no": item.get("question_no"),
                    "stem": item["stem"].strip(),
                    "options": opts,
                })
            return out if len(out) >= 2 else None
        except Exception as e:
            logger.warning("LLM 切分失败，保留原组", base_no=base_no, error=str(e))
            return None

    async def _extract_questions_v2(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> List[Dict[str, Any]]:
        """
        基于 bbox 坐标的题目分组提取（新方案）。

        流程：
        1. QuestionLayoutGrouper.group_into_questions() → List[QuestionGroup]
        2. 对每个 QuestionGroup 调用组内处理 → List[question_dict]
        """
        grouper = QuestionLayoutGrouper(list(blocks))
        groups = grouper.group_into_questions()

        # LLM 切分兜底：只在组文本粘连了后继题号时触发（预筛确定性、成本可控）。
        # client 取一次；不可用则整个切分能力静默跳过，不影响主流程。
        split_llm = await self._get_pdf_structure_llm_client()
        split_enabled = bool(split_llm and split_llm.is_available)

        questions: List[Dict[str, Any]] = []
        for group in groups:
            q_dict = await self._question_group_to_dict(
                document_id, fallback_subject_id, group, section_mappings, grouper
            )
            if not q_dict:
                continue

            base_no = _extract_question_number_simple(q_dict)
            successors = self._detect_merged_question_nos(q_dict.get("raw_text") or "", base_no)
            if split_enabled and successors:
                parts = await self._llm_split_merged_questions(
                    split_llm, q_dict.get("raw_text") or "", base_no, successors
                )
                if parts:
                    logger.info("LLM 切分多题粘连", base_no=base_no, successors=successors, into=len(parts))
                    for part in parts:
                        questions.append(await self._build_split_question(
                            document_id, fallback_subject_id, q_dict, part, section_mappings
                        ))
                    continue

            questions.append(q_dict)

        return questions

    async def _build_split_question(
        self,
        document_id: str,
        fallback_subject_id: str,
        base: Dict[str, Any],
        part: Dict[str, Any],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> Dict[str, Any]:
        """由 LLM 切分结果 + 原组基底构造一道独立题目。

        复用原组的页码/来源/block 归属，但题干/选项/题号用切分结果，
        并按切出的题干重新解析章节归属；标 fixed_by_llm 可追溯。
        """
        q = dict(base)  # 浅拷贝原组的页码/source/exam_year/blocks 等
        stem = part.get("stem") or ""
        options = part.get("options") or []
        q_no = part.get("question_no")
        question_type = "choice" if options else base.get("question_type") or "short_answer"

        q["id"] = generate_id()
        q["stem"] = stem
        q["content"] = stem
        q["raw_text"] = stem
        q["options"] = options
        q["question_no"] = str(q_no) if q_no is not None else None
        q["question_type"] = question_type
        q["type"] = question_type

        # 切出的题各自重新解析章节（可能分属不同考点）
        primary_chapter_id = base.get("primary_chapter_id")
        subject_id = base.get("subject_id")
        resolved_source = base.get("chapter_link_source")
        try:
            from app.services.chapter_link_service import ChapterLinkService
            resolved = await ChapterLinkService(self.db).resolve_chapter_for_entity(
                title=stem[:200], content=stem, subject_id=subject_id,
                entity_type="question", options=options,
            )
            if resolved:
                primary_chapter_id = resolved["chapter_id"]
                subject_id = resolved["subject_id"] or subject_id
                resolved_source = resolved.get("source", "vector_search")
        except Exception as e:
            logger.warning("切分题章节解析失败，沿用原组归属", error=str(e))
        q["primary_chapter_id"] = primary_chapter_id
        q["subject_id"] = subject_id
        q["chapter_link_source"] = resolved_source

        meta = dict(base.get("extraction_meta") or {})
        meta["fixed_by_llm"] = "split"
        meta["option_count"] = len(options)
        meta["few_options"] = question_type == "choice" and 0 < len(options) < 4
        q["extraction_meta"] = meta
        return q

    async def _question_group_to_dict(
        self,
        document_id: str,
        fallback_subject_id: str,
        group: QuestionGroup,
        section_mappings: Dict[int, Dict[str, Optional[str]]],
        grouper: QuestionLayoutGrouper,
    ) -> Optional[Dict[str, Any]]:
        """将 QuestionGroup 转换为题目字典"""
        blocks = group.blocks
        if not blocks:
            return None

        first_block = blocks[0]
        mapping_info = self._resolve_mapping_for_page(
            getattr(first_block, "page_no", None), section_mappings
        )

        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = mapping_info["subject_id"] if mapping_info else fallback_subject_id
        legacy_chapter_id = mapping_info["legacy_chapter_id"] if mapping_info else None
        source_section_path = mapping_info.get("source_section_path") if mapping_info else None
        resolved_source: Optional[str] = None

        # 使用 bbox 分组器提取 stem / options / figures
        stem = grouper._extract_stem(group)
        options = grouper._extract_options(group)
        figures = grouper._extract_figures(group)
        question_no = grouper._extract_question_no(group)

        # 组内类型判定：组题已把拆散的选项/跨页合并好，此时判"是不是题目"最准。
        # 非题目组（无选项/无题号/无疑问特征）直接跳过，不落为题目——避免把知识点
        # 段落误抽成题目。这些组的 block 会留给知识点路径处理。
        group_label, group_label_reason = grouper.classify_group(group, options, question_no)
        if group_label != "question":
            return None

        # 组合内容
        content_parts = []
        for block in blocks:
            text = getattr(block, "content_md", None) or getattr(block, "content_text", None) or ""
            if text.strip():
                content_parts.append(text.strip())
        content = "\n".join(content_parts)

        if not content:
            return None

        # section_mapping 缺失时用题干内容直接匹配大纲考点
        if not primary_chapter_id:
            from app.services.chapter_link_service import ChapterLinkService
            try:
                resolved = await ChapterLinkService(self.db).resolve_chapter_for_entity(
                    title=stem[:200],
                    content=content,
                    subject_id=subject_id,
                    entity_type="question",
                    options=options,
                )
                if resolved:
                    primary_chapter_id = resolved["chapter_id"]
                    subject_id = resolved["subject_id"] or subject_id
                    resolved_source = resolved.get("source", "vector_search")
                    logger.info(
                        "题目章节解析（bbox v2）",
                        chapter_id=primary_chapter_id,
                        confidence=resolved.get("confidence"),
                        source=resolved.get("source"),
                    )
            except Exception as e:
                logger.warning("题目章节解析失败，跳过", error=str(e))

        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=subject_id,
            )

        # 判断题型
        question_type = "short_answer"
        if options:
            question_type = "choice"
        elif '判断' in content[:50]:
            question_type = "judge"
        elif '填空' in content[:50]:
            question_type = "fill"

        # 题目级来源/年份
        doc_meta = getattr(self, "_doc_meta", {}) or {}
        doc_type = getattr(self, "_doc_type", "other")
        stem_year = _detect_stem_year(content)
        if stem_year:
            exam_year = stem_year
            source = f"{stem_year}年真题"
            paper_name = doc_meta.get("source_label") or None
        elif doc_meta.get("exam_year"):
            exam_year = doc_meta.get("exam_year")
            source = doc_meta.get("source_label") or None
            paper_name = doc_meta.get("paper_name") or doc_meta.get("source_label") or None
        else:
            exam_year = 0
            inst = doc_meta.get("institution")
            if doc_type == "textbook":
                source = f"课后习题（{inst}）" if inst else "课后习题"
            else:
                source = doc_meta.get("source_label") or (inst or None)
            paper_name = doc_meta.get("paper_name") or doc_meta.get("source_label") or None

        tags = _build_question_tags(question_type, exam_year, bool(stem_year))

        extraction_meta = self._build_extraction_meta(
            blocks=blocks,
            options=options,
            question_type=question_type,
            question_no=question_no,
            has_figures=bool(figures),
            group_label_reason=group_label_reason,
        )

        return {
            'id': generate_id(),
            'document_id': document_id,
            'source_section_path': source_section_path,
            'subject_id': subject_id,
            'chapter_id': legacy_chapter_id,
            'primary_chapter_id': primary_chapter_id,
            'chapter_link_source': resolved_source or ("document_mapping" if mapping_info else None),
            'question_type': question_type,
            'type': question_type,
            'content': stem if options else content,
            'stem': stem if options else content,
            'options': options,
            'page_no': getattr(first_block, "page_no", None),
            'block_ids': [getattr(b, "id", None) for b in blocks if getattr(b, "id", None)],
            'blocks': blocks,
            'raw_text': content,
            'source': source,
            'exam_year': int(exam_year or 0),
            'exam_scope': doc_meta.get("exam_scope"),
            'paper_name': paper_name,
            'tags': tags,
            'question_no': question_no,
            'figures': figures,
            'extraction_meta': extraction_meta,
        }

    @staticmethod
    def _build_extraction_meta(
        blocks: List[Any],
        options: List[Dict[str, str]],
        question_type: str,
        question_no: Optional[str],
        has_figures: bool,
        group_label_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构建题目抽取质量诊断，供前端区分组题问题与 block 噪音。

        - group_source: single_block（一块成题）/ merged（多块合并）
        - block_count: 组题用了几个 block
        - option_count: 提取到的选项数
        - suspected_truncated_options: 选项文本疑似被截断（过短或无中文/字母数字实体）
        - missing_question_no: 未识别出题号
        """
        block_count = len(blocks)
        option_count = len(options)

        suspected_truncated = False
        if question_type == "choice" and options:
            # 选择题选项文本过短（<2 字符）视为疑似截断
            short_opts = sum(1 for o in options if len((o.get("text") or "").strip()) < 2)
            if short_opts > 0:
                suspected_truncated = True

        # 选择题却选项不足 4 个：疑似漏选项（D 常见丢失）
        few_options = question_type == "choice" and 0 < option_count < 4

        return {
            "group_source": "single_block" if block_count == 1 else "merged",
            "block_count": block_count,
            "option_count": option_count,
            "has_figures": has_figures,
            "missing_question_no": not question_no,
            "suspected_truncated_options": suspected_truncated,
            "few_options": few_options,
            "group_label_reason": group_label_reason,
        }

    def _strip_leading_option_marker(self, text: str, expected_label: Optional[str] = None) -> str:
        """清理选项文本中重复出现的选项标记。"""
        cleaned = (text or "").strip()
        if expected_label:
            cleaned = re.sub(
                rf'^\s*{re.escape(expected_label.upper())}\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*',
                '',
                cleaned,
            ).strip()
        malformed_sub = re.match(r'^\s*<sub>\s*[.．、:：。]\s*', cleaned)
        if malformed_sub:
            cleaned = cleaned[malformed_sub.end():]
            cleaned = re.sub(r'^([^<]{0,60})</sub>', r'\1', cleaned, count=1).strip()
        return re.sub(r'^\s*[.．、:：。]\s*', '', cleaned).strip()

    def _normalize_options(self, options: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """统一选择题选项结构，兼容前端 key/text 和校验器 label/text。"""
        normalized: List[Dict[str, Any]] = []
        seen_labels = set()
        for option in options or []:
            label = _get_option_label(option)
            text = str(option.get("text") or option.get("content") or "").strip()
            text = self._strip_leading_option_marker(text, expected_label=label)
            if not label or not text or label in seen_labels:
                continue
            normalized_option = {
                "key": label,
                "label": label,
                "option_label": label,
                "text": text,
            }
            if option.get("source") in {"extracted", "ai_generated"}:
                normalized_option["source"] = option["source"]
            normalized.append(normalized_option)
            seen_labels.add(label)
        return normalized

    async def _save_question_from_dict(self, question_dict: Dict[str, Any]) -> Tuple[bool, str]:
        """从字典保存题目到数据库"""
        subject_id = question_dict.get('subject_id')
        legacy_chapter_id = question_dict.get('chapter_id')
        primary_chapter_id = question_dict.get('primary_chapter_id')

        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=subject_id,
            )
            question_dict['chapter_id'] = legacy_chapter_id

        # 归属缺失不再丢弃：组题成功的题目一律入库，缺归属者标记待指认，
        # 让前端能区分"组题失败"（题目根本没出现）与"归属失败"（题目在但未挂章节）。
        unassigned = not subject_id or not legacy_chapter_id
        if unassigned:
            logger.info(
                "题目归属缺失，以待指认状态入库",
                document_id=question_dict.get('document_id'),
                question_id=question_dict.get('id'),
                page_no=question_dict.get('page_no'),
                subject_id=subject_id,
                chapter_id=legacy_chapter_id,
            )

        try:
            async with self.db.begin_nested():
                options = self._normalize_options(question_dict.get('options'))
                question_content = (question_dict.get('stem') or question_dict.get('content') or "").strip()

                # 关键词标签：题型/真题/年份结构化标签 + 主题术语
                tags = question_dict.get('tags') or None
                topic_terms = self._extract_topic_terms(question_content, question_content) or None

                # 创建题目记录
                question = Question(
                    id=question_dict['id'],
                    subject_id=subject_id,
                    chapter_id=legacy_chapter_id,
                    primary_chapter_id=primary_chapter_id,
                    source_document_id=question_dict['document_id'],
                    source_section_path=(question_dict.get('source_section_path') or None),
                    type=question_dict['question_type'],
                    content=question_content,
                    options=options or None,
                    answer="",
                    source=(question_dict.get('source') or None),
                    exam_year=int(question_dict.get('exam_year') or 0),
                    exam_scope=(question_dict.get('exam_scope') or None),
                    paper_name=(question_dict.get('paper_name') or None),
                    tags=tags,
                    topic_terms=topic_terms,
                    question_no=str(_extract_question_number_simple(question_dict) or "") or None,
                    review_status="pending",
                    status="active",
                    # 归属状态只记在 extraction_meta.unassigned，供前端区分与指认；
                    # 是否可用与人工审核状态独立。
                    extraction_meta={
                        **(question_dict.get('extraction_meta') or {}),
                        "unassigned": unassigned,
                    },
                )
                self.db.add(question)

                # 创建章节关联
                if primary_chapter_id:
                    link = QuestionChapterLink(
                        question_id=question_dict['id'],
                        canonical_chapter_id=primary_chapter_id,
                        is_primary=True,
                        source=question_dict.get('chapter_link_source') or "manual",
                        created_by="system",
                    )
                    self.db.add(link)

                # 创建来源引用
                blocks = question_dict.get('blocks', [])
                if blocks:
                    source_link = EntitySourceLink(
                        entity_type="question",
                        entity_id=question_dict['id'],
                        document_id=question_dict['document_id'],
                        page_start=blocks[0].page_no,
                        page_end=blocks[-1].page_no,
                        block_ids=question_dict.get('block_ids', []),
                        excerpt_text=question_dict['content'][:500],
                    )
                    self.db.add(source_link)

                await self.db.flush()

                # 关联资产：按 block 精确绑定，只绑题目真正包含的图/表/公式
                block_ids = question_dict.get('block_ids') or [b.id for b in blocks]
                if block_ids:
                    try:
                        from app.services.entity_asset_service import link_entity_assets_by_blocks
                        await link_entity_assets_by_blocks(
                            self.db,
                            entity_type="question",
                            entity_id=question_dict['id'],
                            block_ids=block_ids,
                        )
                    except Exception as e:
                        logger.warning("题目资产关联失败", question_id=question_dict['id'], error=str(e))
            return True, ("saved_unassigned" if unassigned else "saved")
        except Exception as e:
            logger.error(f"保存题目失败: {e}")
            return False, "save_failed"

    def _build_question_extraction_diagnostic(
        self,
        raw_questions: List[Dict[str, Any]],
        final_questions: List[Dict[str, Any]],
        validation_report: Dict[str, Any],
        final_report: Dict[str, Any],
        saved_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """构建可直接返回给前端的题目抽取诊断摘要。"""
        save_reasons = Counter(item.get("reason") or "unknown" for item in saved_results)
        raw_by_page = Counter(q.get("page_no") for q in raw_questions if q.get("page_no") is not None)
        final_by_page = Counter(q.get("page_no") for q in final_questions if q.get("page_no") is not None)
        saved_by_page = Counter(
            item.get("page_no")
            for item in saved_results
            if item.get("saved") and item.get("page_no") is not None
        )
        skipped_by_page = Counter(
            item.get("page_no")
            for item in saved_results
            if not item.get("saved") and item.get("page_no") is not None
        )
        page_numbers = sorted(set(raw_by_page) | set(final_by_page) | set(saved_by_page) | set(skipped_by_page))

        return {
            "raw_question_count": len(raw_questions),
            "final_question_count": len(final_questions),
            "saved_question_count": save_reasons.get("saved", 0),
            "skipped_question_count": len(saved_results) - save_reasons.get("saved", 0),
            "save_reasons": dict(save_reasons),
            "by_page": [
                {
                    "page_no": page_no,
                    "raw_question_count": raw_by_page.get(page_no, 0),
                    "final_question_count": final_by_page.get(page_no, 0),
                    "saved_question_count": saved_by_page.get(page_no, 0),
                    "skipped_question_count": skipped_by_page.get(page_no, 0),
                }
                for page_no in page_numbers
            ],
            "numbering": self._question_numbering_summary(final_questions, final_report),
            "validation": {
                "initial_issue_count": validation_report.get("summary", {}).get("total_issues", 0),
                "final_issue_count": final_report.get("summary", {}).get("total_issues", 0),
                "initial_critical_issue_count": len(
                    validation_report.get("summary", {}).get("critical_issues", [])
                ),
                "final_critical_issue_count": len(
                    final_report.get("summary", {}).get("critical_issues", [])
                ),
            },
            "unsaved_samples": [
                item for item in saved_results
                if not item.get("saved")
            ][:20],
        }

    def _question_numbering_summary(
        self,
        questions: List[Dict[str, Any]],
        final_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        numbers = [
            number for number in (_extract_question_number_simple(question) for question in questions)
            if number is not None
        ]
        duplicate_numbers = [
            number for number, count in Counter(numbers).items()
            if count > 1
        ]
        max_number = max(numbers, default=0)
        number_set = set(numbers)
        missing_numbers = (
            [number for number in range(min(numbers), max_number + 1) if number not in number_set]
            if numbers
            else []
        )

        continuity = final_report.get("number_continuity", {})
        return {
            "numbered_question_count": len(numbers),
            "unnumbered_question_count": len(questions) - len(numbers),
            "min_number": min(numbers) if numbers else None,
            "max_number": max_number or None,
            "missing_numbers": missing_numbers,
            "duplicate_numbers": sorted(duplicate_numbers),
            "segment_count": len(continuity.get("segments", [])),
        }

    def _question_text_excerpt(self, question_dict: Dict[str, Any], limit: int = 120) -> str:
        text = " ".join(
            (question_dict.get("stem") or question_dict.get("content") or question_dict.get("raw_text") or "")
            .split()
        )
        return text if len(text) <= limit else f"{text[:limit]}..."

    async def _extract_and_link_answers(
        self, document_id: str, blocks: List[DocumentBlock]
    ) -> int:
        """
        PDF 自带答案区回连：扫描"参考答案/答案"段，按题号把答案写回已入库题目。

        策略：
        1. 定位答案区起点——出现"参考答案/答案/答案与解析/答案速查"等标题的 block 之后的内容。
        2. 在答案区文本里用正则抓 `题号 + 答案` 形式：
           - 客观题：`1. B` / `1、B` / `1．BCD` / `(1) B`
           - 兼容一行多题：`1.B 2.C 3.D`
        3. 按 question_no 匹配本文档已入库的 Question，写 answer + answer_source="extracted"。
           已有 extracted 答案的不覆盖；LLM 答案此处也不覆盖（extracted 优先级最高，仅在为空时写）。

        返回成功回连的题目数。
        """
        # 收集本文档题目：question_no -> Question
        rows = (await self.db.execute(
            select(Question).where(Question.source_document_id == document_id)
        )).scalars().all()
        by_no: Dict[str, Question] = {}
        for q in rows:
            if q.question_no:
                by_no[str(q.question_no).strip()] = q
        if not by_no:
            return 0

        # 定位答案区：找到含答案标题的 block，从其后开始拼接文本
        answer_header_re = re.compile(r'(参考答案|答案与解析|答案速查|答案及解析|^\s*答案\s*$)')
        text_parts: List[str] = []
        in_answer_zone = False
        for b in blocks:
            t = (b.content_text or b.content_md or "").strip()
            if not t:
                continue
            if not in_answer_zone and answer_header_re.search(t):
                in_answer_zone = True
                # 标题行后面可能紧跟答案，去掉标题词本身
                tail = answer_header_re.sub(" ", t).strip()
                if tail:
                    text_parts.append(tail)
                continue
            if in_answer_zone:
                text_parts.append(t)
        if not in_answer_zone:
            return 0

        answer_text = "\n".join(text_parts)
        # 抓 `题号<分隔> 答案`，答案为 A-D 字母（含多选 ABCD）或"对/错/√/×/正确/错误"
        pair_re = re.compile(
            r'(?<!\d)(\d{1,3})\s*[.．、:：)）]\s*'
            r'([A-Da-d]{1,4}|对|错|正确|错误|√|×|T|F|是|否)'
        )
        linked = 0
        for m in pair_re.finditer(answer_text):
            no = m.group(1).strip()
            ans = m.group(2).strip().upper()
            q = by_no.get(no)
            if not q:
                continue
            # extracted 永不被覆盖；仅当当前答案为空时写入
            if (q.answer or "").strip():
                continue
            q.answer = ans
            q.answer_source = "extracted"
            linked += 1

        if linked:
            await self.db.flush()
            logger.info("PDF 答案区回连完成", document_id=document_id, linked=linked)
        return linked

    def _extract_fix_history(self, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """提取修复历史"""
        history = []
        for i, q in enumerate(questions):
            if q.get('fixed_by_rule'):
                history.append({
                    'question_index': i,
                    'question_id': q.get('id'),
                    'fix_type': 'rule',
                    'fix_action': q.get('fixed_by_rule'),
                    'details': {
                        'source_index': q.get('fixed_source_index'),
                        'inferred_number': q.get('inferred_number'),
                    }
                })
            if q.get('fixed_by_llm'):
                llm_actions = (
                    (q.get("extraction_meta") or {}).get("llm_fix_actions")
                    or q.get("llm_fix_actions")
                    or []
                )
                history.append({
                    'question_index': i,
                    'question_id': q.get('id'),
                    'fix_type': 'llm',
                    'fix_action': (
                        llm_actions[-1].get("action")
                        if llm_actions and isinstance(llm_actions[-1], dict)
                        else 'llm_fix'
                    ),
                    'details': llm_actions,
                })
        return history

    async def _save_diagnostic_report(self, document_id: str, report: Dict[str, Any]) -> None:
        """保存诊断报告到document的metadata"""
        try:
            result = await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            if document:
                # 将报告存储到document的某个字段（如果有JSON字段）
                # 或者创建独立的诊断报告表
                # 这里暂时只记录日志
                logger.info(f"诊断报告: document={document_id}, "
                          f"initial_issues={report['initial_report']['summary']['total_issues']}, "
                          f"final_issues={report['final_report']['summary']['total_issues']}, "
                          f"fixes={len(report['fix_history'])}")
        except Exception as e:
            logger.error(f"保存诊断报告失败: {e}")

    async def _extract_questions_legacy(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> int:
        """
        旧版题目提取逻辑（保留备用）
        直接保存到数据库，不经过校验和修复
        """
        question_count = 0

        # 简单策略：查找包含题目标记的 blocks
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
                    created = await self._save_question_legacy(
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
                        created = await self._save_question_legacy(
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
            created = await self._save_question_legacy(
                document_id, fallback_subject_id, current_question_blocks, section_mappings
            )
            if created:
                question_count += 1

        return question_count

    async def _save_question_legacy(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> bool:
        """保存单个题目（旧版逻辑）"""
        if not blocks:
            return False

        first_block = blocks[0]
        mapping_info = self._resolve_mapping_for_page(first_block.page_no, section_mappings)
        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = mapping_info["subject_id"] if mapping_info else fallback_subject_id
        legacy_chapter_id = mapping_info["legacy_chapter_id"] if mapping_info else None
        source_section_path = mapping_info.get("source_section_path") if mapping_info else None
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
            source_section_path=source_section_path,
            type=question_type,
            content=content,
            answer="",  # 需要后续从 blocks 中提取或人工补充
            review_status="pending",
            status="active",
        )
        self.db.add(question)

        # 创建章节关联
        if primary_chapter_id:
            link = QuestionChapterLink(
                question_id=q_id,
                canonical_chapter_id=primary_chapter_id,
                is_primary=True,
                source="document_mapping" if mapping_info else "manual",
                created_by="system",
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
