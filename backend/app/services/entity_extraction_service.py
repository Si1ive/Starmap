"""
实体抽取服务

从文档的 blocks 中抽取知识点和题目，生成 knowledge_points 和 questions 记录。
"""

import re
import uuid
import asyncio
from collections import Counter
from types import SimpleNamespace
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.mysql_models import (
    Document, DocumentBlock, DocumentSection, DocumentSectionMapping,
    KnowledgePoint, Question, KnowledgePointChapterLink, QuestionChapterLink,
    EntitySourceLink, CanonicalChapter, RetrievalSegment
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id
from app.services.system_settings_service import SystemSettingsService
from app.services.text_cleaning import clean_block_text, normalize_whitespace
from app.services.llm_call_recorder import LLMCallRecorder

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


OPTION_SEPARATOR_RE = re.compile(
    r'(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)(?=\S)'
)
OPTION_MARKER_RE = re.compile(r'([A-H])(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)(?=\S)')
OPTION_BLOCK_RE = re.compile(r'^\s*([A-H])(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)(?=\S)')
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


class PDFStructureLLMClient:
    """PDF 结构解析专用 OpenAI 兼容客户端。"""

    def __init__(self, config: Dict[str, Any]):
        self.enabled = bool(config.get("enabled"))
        self.provider = str(config.get("provider") or "openai_compatible")
        self.base_url = str(config.get("base_url") or "").strip()
        self.api_key = str(config.get("api_key") or settings.OPENAI_API_KEY or "").strip()
        self.model = str(config.get("model") or settings.OPENAI_MODEL).strip()
        self.temperature = float(config.get("temperature", 0.1))
        self.max_tokens = int(config.get("max_tokens", 2000))
        self.timeout_seconds = int(config.get("timeout_seconds", 60))
        self.system_prompt = str(
            config.get("system_prompt")
            or "你是一个PDF题目结构分析专家，负责判断跨页、跨列导致的题目拆分和选项缺失问题。"
        ).strip()

    @property
    def is_available(self) -> bool:
        return self.enabled and self.provider == "openai_compatible" and bool(self.api_key and self.model)

    async def chat(self, prompt: str) -> str:
        if not self.is_available:
            raise RuntimeError("PDF structure LLM is not enabled or missing api_key/model")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        params = {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout_seconds": self.timeout_seconds,
        }

        async with LLMCallRecorder(
            model=self.model,
            called_by="pdf_structure_llm",
            purpose="题目结构 LLM 兜底修复",
            base_url=self.base_url or None,
            request_messages=messages,
            request_params=params,
        ) as rec:
            response_obj, text = await asyncio.to_thread(self._chat_sync, messages)
            rec.record_response(response_text=text, response_obj=response_obj)
            return text

    def _chat_sync(self, messages):
        import openai

        previous_api_key = getattr(openai, "api_key", None)
        previous_api_base = getattr(openai, "api_base", None)
        openai.api_key = self.api_key
        if self.base_url:
            openai.api_base = self.base_url.rstrip("/")

        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                request_timeout=self.timeout_seconds,
            )
            text = response.choices[0].message.content.strip()
            return response, text
        finally:
            openai.api_key = previous_api_key
            openai.api_base = previous_api_base


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
                unfixed_issues.append(issue)

        if not unfixed_issues:
            return questions

        logger.info(f"LLM fallback for {len(unfixed_issues)} unfixed issues")

        for issue in sorted(unfixed_issues, key=lambda item: item.get("question_index", 0), reverse=True):
            idx = issue['question_index']
            if idx < 0 or idx >= len(questions):
                logger.warning("LLM fallback skipped stale issue index", issue=issue)
                continue

            # 构造上下文
            context_start = max(0, idx - 2)
            context_end = min(len(questions), idx + 3)
            context_questions = questions[context_start:context_end]

            # 调用LLM
            prompt = self._build_fix_prompt(
                context_questions,
                target_idx=idx - context_start,
                issue=issue
            )

            try:
                llm_response = await self.llm_client.chat(prompt)

                # 应用LLM建议
                fix_action = self._parse_llm_fix_result(llm_response)
                if fix_action and fix_action.get('should_merge'):
                    questions = self._apply_llm_fix(questions, idx, context_start, fix_action)
                    logger.info(f"LLM fixed question {idx}")
            except Exception as e:
                logger.error(f"LLM fix failed for question {idx}: {e}")

        return questions

    def _build_fix_prompt(
        self,
        context: List[Dict[str, Any]],
        target_idx: int,
        issue: Dict[str, Any]
    ) -> str:
        """构造LLM判断prompt"""
        # 将题目列表格式化为文本
        formatted = []
        for i, q in enumerate(context):
            marker = " ← 【目标】" if i == target_idx else ""
            stem = q.get('stem') or q.get('content', '')
            options = q.get('options', [])
            options_text = ', '.join([f"{_get_option_label(o)}. {o.get('text', '')[:20]}" for o in options])

            formatted.append(f"""
题目{i+1}{marker}:
页码: {q.get('page_no', '?')}
题干: {stem[:200]}...
选项: {options_text}
---
""")

        issue_desc = f"""
问题类型: {issue.get('issue_type', 'unknown')}
缺失选项: {issue.get('missing_options', [])}
"""

        return f"""
你是一个教材题目结构分析专家。以下是从PDF中提取的题目片段，可能存在跨页/跨列导致的分离问题。

{chr(10).join(formatted)}

【当前问题】
{issue_desc}

【任务】分析标记为【目标】的题目，判断：
1. 它是否是一道完整的独立题目？
2. 如果不完整，它应该与前面哪个题目合并？还是与后面的合并？
3. 如果需要合并，请给出合并后的完整题目结构（题干+选项）

merge_indices 使用上方上下文题目列表的 0 基索引，例如第一道题是 0，第二道题是 1。

【输出格式】JSON:
{{
  "is_complete": true/false,
  "should_merge": true/false,
  "merge_with": "previous" / "next" / "none",
  "merge_indices": [0, 1],
  "merged_question": {{
    "stem": "合并后的题干",
    "options": [{{"label": "A", "text": "..."}}, ...]
  }}
}}
"""

    def _parse_llm_fix_result(self, llm_response: str) -> Optional[Dict[str, Any]]:
        """解析LLM返回的合并指令"""
        try:
            # 尝试提取JSON
            import json
            # 查找JSON块
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                return {
                    'should_merge': result.get('should_merge', False),
                    'merge_with': result.get('merge_with', 'none'),
                    'merge_indices': result.get('merge_indices', []),
                    'merged_question': result.get('merged_question')
                }
        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")

        # LLM返回格式错误，保守处理：不合并
        return {'should_merge': False}

    def _apply_llm_fix(
        self,
        questions: List[Dict[str, Any]],
        idx: int,
        context_start: int,
        fix_action: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """应用LLM的修复建议"""
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

        # 如果需要删除其他题目（合并的情况）
        for remove_idx in sorted([i for i in global_indices if i != keep_idx], reverse=True):
            del questions[remove_idx]

        return questions


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


class EntityExtractionService:
    """实体抽取服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

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

        # 4. 抽取知识点 — 只用被分类为 knowledge / heading 的 block
        if extract_knowledge:
            await self._cleanup_existing_entities(document_id, "knowledge_point")
            knowledge_blocks = [
                b for b in blocks
                if block_label_by_id.get(getattr(b, "id", ""), "") in ("knowledge", "heading", "table", "figure", "formula")
            ] or blocks  # 完全识别不出时退化为全量
            knowledge_count = await self._extract_knowledge_points(
                document_id, fallback_subject_id, knowledge_blocks, section_mappings
            )

        # 5. 抽取题目 — 只用被分类为题目相关的 block
        if extract_questions:
            await self._cleanup_existing_entities(document_id, "question")
            question_blocks = [
                b for b in blocks
                if block_label_by_id.get(getattr(b, "id", ""), "") in
                   ("question_stem", "question_option", "answer", "heading", "unknown")
            ] or blocks
            question_result = await self._extract_questions(
                document_id, fallback_subject_id, question_blocks, section_mappings
            )
            question_count = question_result["saved_count"]
            question_diagnostic = question_result["diagnostic"]

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
        mapping_info = self._resolve_mapping_for_page(title_block.page_no, section_mappings)
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
    ) -> Dict[str, Any]:
        """
        抽取题目（带校验和修复）

        完整流程：
        1. 标点清洗
        2. 初步提取题目
        3. 综合校验
        4. 规则修复
        5. 重新校验
        6. LLM兜底（可选）
        7. 保存题目和诊断报告
        """
        # Step 1: 标点 / 空白清洗已在 extract_entities 入口完成
        blocks = self._expand_blocks_with_embedded_question_starts(blocks)
        logger.info(f"展开内嵌题号完成，处理 {len(blocks)} 个blocks")

        # Step 2: 初步提取题目（转换为字典格式，不直接入库）
        raw_questions = await self._extract_questions_to_dict(
            document_id, fallback_subject_id, blocks, section_mappings
        )
        logger.info(f"初步提取: {len(raw_questions)} 道题目")

        if not raw_questions:
            diagnostic = self._build_question_extraction_diagnostic(
                raw_questions=[],
                final_questions=[],
                validation_report={},
                final_report={},
                saved_results=[],
            )
            return {"saved_count": 0, "diagnostic": diagnostic}

        # Step 3: 综合校验
        validation_report = comprehensive_validation(raw_questions)
        logger.info(f"校验发现 {validation_report['summary']['total_issues']} 个问题")

        # Step 4: 规则修复
        fixer = RuleBasedFixer()

        # 4.1 修复选项问题
        questions = fixer.fix_option_issues(raw_questions, validation_report['option_issues'])

        # 4.2 修复编号问题
        questions = fixer.fix_number_issues(questions, validation_report['number_continuity'])

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
        diagnostic = self._build_question_extraction_diagnostic(
            raw_questions=raw_questions,
            final_questions=questions,
            validation_report=validation_report,
            final_report=final_report,
            saved_results=saved_results,
        )

        return {"saved_count": question_count, "diagnostic": diagnostic}

    async def _get_pdf_structure_llm_client(self) -> Optional[PDFStructureLLMClient]:
        """读取 PDF 结构解析专用 LLM 配置。"""
        try:
            runtime_settings = await SystemSettingsService(self.db).load()
            llm_config = runtime_settings.get("pdf_structure_llm", {})
            return PDFStructureLLMClient(llm_config if isinstance(llm_config, dict) else {})
        except Exception as e:
            logger.warning("读取PDF结构解析LLM配置失败，跳过LLM兜底", error=str(e))
            return None

    async def _extract_questions_to_dict(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> List[Dict[str, Any]]:
        """
        将blocks提取为题目字典列表（不入库）
        用于后续的校验和修复
        """
        questions = []

        current_question_blocks = []
        current_question_start_kind: Optional[str] = None
        in_question = False

        for block in blocks:
            text = (block.content_text or "").strip()

            # 检测题目开始
            question_start_kind = self._question_start_kind(block)
            is_question_start = question_start_kind is not None
            if (
                in_question
                and question_start_kind == "paren"
                and current_question_start_kind != "paren"
            ):
                # 综合题的（1）（2）（3）通常是当前大题的小问，不能把大题拆散。
                is_question_start = False

            if is_question_start:
                # 保存前一个题目
                if in_question and current_question_blocks:
                    q_dict = await self._blocks_to_question_dict(
                        document_id, fallback_subject_id, current_question_blocks, section_mappings
                    )
                    if q_dict:
                        questions.append(q_dict)
                    current_question_blocks = []

                in_question = True
                current_question_start_kind = question_start_kind
                current_question_blocks.append(block)
            elif in_question:
                is_option_continuation = bool(OPTION_BLOCK_RE.match(text))
                if block.block_type in ('title', 'heading') and not is_option_continuation:
                    if current_question_blocks:
                        q_dict = await self._blocks_to_question_dict(
                            document_id, fallback_subject_id, current_question_blocks, section_mappings
                        )
                        if q_dict:
                            questions.append(q_dict)
                        current_question_blocks = []
                    in_question = False
                    current_question_start_kind = None
                else:
                    current_question_blocks.append(block)

        # 保存最后一个题目
        if in_question and current_question_blocks:
            q_dict = await self._blocks_to_question_dict(
                document_id, fallback_subject_id, current_question_blocks, section_mappings
            )
            if q_dict:
                questions.append(q_dict)

        return questions

    def _expand_blocks_with_embedded_question_starts(self, blocks: List[DocumentBlock]) -> List[DocumentBlock]:
        """拆分同一文本块内粘连的多道题，常见于页级解析把 12 和 13 合在一个 block。"""
        expanded: List[DocumentBlock] = []
        for block in blocks:
            expanded.extend(self._split_block_by_embedded_question_starts(block))
        return expanded

    def _split_block_by_embedded_question_starts(self, block: DocumentBlock) -> List[DocumentBlock]:
        text = block.content_md or block.content_text or ""
        if not text.strip() or block.block_type not in ("paragraph", "heading", "list"):
            return [block]

        first_number_match = QUESTION_NUMERIC_RE.match(text.strip())
        if not first_number_match:
            return [block]
        expected_number = int(first_number_match.group(1)) + 1

        split_positions = []
        for match in EMBEDDED_QUESTION_NUMERIC_RE.finditer(text):
            if match.start() == 0:
                continue
            if self._is_embedded_question_start(text, match, expected_number):
                split_positions.append(match.start())
                expected_number += 1

        if not split_positions:
            return [block]

        boundaries = [0] + split_positions + [len(text)]
        parts = []
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            part_text = text[start:end].strip()
            if not part_text:
                continue
            parts.append(SimpleNamespace(
                id=block.id,
                document_id=block.document_id,
                page_id=getattr(block, "page_id", None),
                page_no=block.page_no,
                block_type=block.block_type,
                order_no=(block.order_no or 0) * 100 + index,
                bbox=getattr(block, "bbox", None),
                content_text=part_text,
                content_md=part_text,
                content_json=getattr(block, "content_json", None),
                latex=getattr(block, "latex", None),
                html_table=getattr(block, "html_table", None),
                asset_id=getattr(block, "asset_id", None),
                confidence=getattr(block, "confidence", None),
                review_status=getattr(block, "review_status", None),
            ))

        return parts or [block]

    def _is_embedded_question_start(self, text: str, match: re.Match, expected_number: int) -> bool:
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            return False
        if number != expected_number:
            return False

        prefix = text[:match.start()].strip()
        suffix = text[match.start(): match.start() + 180].strip()
        if len(prefix) < 30 or len(suffix) < 20:
            return False
        if not QUESTION_CUE_RE.search(suffix):
            return False

        previous_number_match = QUESTION_NUMERIC_RE.match(prefix)
        if previous_number_match:
            previous_number = int(previous_number_match.group(1))
            if number <= previous_number:
                return False

        return True

    def _is_question_start_block(self, block: DocumentBlock, in_question: bool = False) -> bool:
        """判断 block 是否是题目起点，避免把 A/B/C/D 选项块误判为新题。"""
        return self._question_start_kind(block) is not None

    def _question_start_kind(self, block: DocumentBlock) -> Optional[str]:
        """返回题目起点类型；None 表示不是题目起点。"""
        text = (block.content_text or block.content_md or "").strip()
        if not text or block.block_type not in ('paragraph', 'heading', 'list'):
            return None

        if OPTION_BLOCK_RE.match(text):
            return None

        if QUESTION_TITLE_RE.match(text) or QUESTION_EXAMPLE_RE.match(text):
            return "title"

        if QUESTION_PAREN_RE.match(text):
            return "paren" if bool(QUESTION_CUE_RE.search(text)) or len(text) > 20 else None

        numeric_match = QUESTION_NUMERIC_RE.match(text)
        if numeric_match:
            number = int(numeric_match.group(1))
            if number > 200:
                return None
            if (
                bool(QUESTION_CUE_RE.search(text))
                or len(text) > 20
                or block.block_type == 'heading'
                or bool(OPTION_MARKER_RE.search(text))
            ):
                return "numeric"

        return None

    async def _blocks_to_question_dict(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> Optional[Dict[str, Any]]:
        """将blocks转换为题目字典"""
        if not blocks:
            return None

        first_block = blocks[0]
        mapping_info = self._resolve_mapping_for_page(first_block.page_no, section_mappings)

        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = mapping_info["subject_id"] if mapping_info else fallback_subject_id
        legacy_chapter_id = mapping_info["legacy_chapter_id"] if mapping_info else None
        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=subject_id,
            )

        # 组合内容
        content_parts = []
        for block in blocks:
            text = block.content_md or block.content_text or ""
            if text.strip():
                content_parts.append(text.strip())
        content = "\n".join(content_parts)

        if not content:
            return None

        stem, options = self._split_question_stem_options(content)

        # 判断题型
        question_type = "short_answer"
        if options:
            question_type = "choice"
        elif '判断' in content[:50]:
            question_type = "judge"
        elif '填空' in content[:50]:
            question_type = "fill"

        return {
            'id': generate_id(),
            'document_id': document_id,
            'subject_id': subject_id,
            'chapter_id': legacy_chapter_id,
            'primary_chapter_id': primary_chapter_id,
            'question_type': question_type,
            'type': question_type,
            'content': stem if options else content,
            'stem': stem if options else content,
            'options': options,
            'page_no': first_block.page_no,
            'block_ids': [b.id for b in blocks],
            'blocks': blocks,
            'raw_text': content,
        }

    def _split_question_stem_options(self, content: str) -> tuple[str, List[Dict[str, str]]]:
        """从题目全文中拆出题干和选项，选项文本不保留 A./A： 等标记。"""
        if not content:
            return "", []

        matches = list(OPTION_MARKER_RE.finditer(content))
        if not matches:
            return content.strip(), []

        option_sequence = self._find_best_option_sequence(content, matches)
        if not option_sequence:
            return content.strip(), []

        options: List[Dict[str, str]] = []
        seen_labels = set()
        first_option_start = option_sequence[0].start(1)

        for idx, match in enumerate(option_sequence):
            label = match.group(1).upper()
            if label in seen_labels:
                continue

            text_start = match.end()
            text_end = len(content)
            if idx + 1 < len(option_sequence):
                text_end = option_sequence[idx + 1].start(1)

            option_text = content[text_start:text_end].strip()
            option_text = self._strip_leading_option_marker(option_text)
            if not option_text:
                continue

            options.append({
                "key": label,
                "label": label,
                "option_label": label,
                "text": option_text,
            })
            seen_labels.add(label)

        if len(options) < 2:
            return content.strip(), []

        stem = content[:first_option_start].strip() if first_option_start is not None else content.strip()
        return stem or content.strip(), options

    def _find_best_option_sequence(
        self,
        content: str,
        matches: List[re.Match],
    ) -> List[re.Match]:
        """选出可信的连续选项序列，避免把题干中的 A/B/C/D 普通字母误判为选项。"""
        best: List[re.Match] = []
        best_score = -10_000

        for start_idx, first_match in enumerate(matches):
            first_label = first_match.group(1).upper()
            if first_label not in {"A", "B"}:
                continue
            if not self._is_valid_option_marker_match(content, first_match):
                continue
            if not self._has_choice_stem_signal(content[:first_match.start(1)]):
                continue

            for sequence in self._candidate_option_sequences(content, matches, start_idx):
                if len(sequence) < 2:
                    continue
                if not self._is_plausible_option_text(content[sequence[-1].end():], is_last=True):
                    continue
                score = self._score_option_sequence(content, sequence)
                if score > best_score:
                    best = sequence
                    best_score = score

        return best if len(best) >= 2 else []

    def _candidate_option_sequences(
        self,
        content: str,
        matches: List[re.Match],
        start_idx: int,
    ) -> List[List[re.Match]]:
        """枚举从 A 开始的连续选项候选，处理选项文本里也出现 A/B/C/D 的情况。"""
        results: List[List[re.Match]] = []
        max_results = 256

        def walk(sequence: List[re.Match], search_from: int, expected_ord: int) -> None:
            if len(results) >= max_results:
                return
            results.append(sequence)
            if len(sequence) >= 8 or expected_ord > ord("H"):
                return

            candidates_seen = 0
            for next_idx in range(search_from, len(matches)):
                next_match = matches[next_idx]
                if ord(next_match.group(1).upper()) != expected_ord:
                    continue
                if not self._is_valid_option_marker_match(content, next_match):
                    continue
                if not self._is_plausible_option_text(
                    content[sequence[-1].end():next_match.start(1)],
                    is_last=False,
                ):
                    continue
                walk(sequence + [next_match], next_idx + 1, expected_ord + 1)
                candidates_seen += 1
                if candidates_seen >= 8:
                    break

        first = matches[start_idx]
        walk([first], start_idx + 1, ord(first.group(1).upper()) + 1)
        return results

    def _is_valid_option_marker_match(self, content: str, match: re.Match) -> bool:
        """过滤明显不是选项标记的 A/B/C/D，例如 RISC 末尾 C 或 computer(A)。"""
        label_start = match.start(1)
        marker_text = content[label_start:match.end()]
        has_explicit_punctuation = bool(re.search(r'[.．、:：。]|<sub>', marker_text))

        previous_char = content[label_start - 1] if label_start > 0 else ""
        if previous_char and previous_char.isascii() and previous_char.isalnum() and not has_explicit_punctuation:
            return False

        previous_nonspace = ""
        for char in reversed(content[:label_start]):
            if not char.isspace():
                previous_nonspace = char
                break
        if previous_nonspace in "([{（【" and not has_explicit_punctuation:
            return False

        option_text_start = match.end()
        while option_text_start < len(content) and content[option_text_start].isspace():
            option_text_start += 1
        if option_text_start < len(content) and content[option_text_start] in ")]}）】;；":
            return False

        return True

    def _score_option_sequence(self, content: str, sequence: List[re.Match]) -> int:
        """给候选选项序列打分；分数高表示更像真实 A/B/C/D 选项边界。"""
        score = len(sequence) * 100
        labels = [match.group(1).upper() for match in sequence]
        if labels[:4] == ["A", "B", "C", "D"]:
            score += 80

        stem_tail = content[max(0, sequence[0].start(1) - 120):sequence[0].start(1)]
        if CHOICE_BLANK_RE.search(stem_tail):
            score += 30

        option_texts = []
        for idx, match in enumerate(sequence):
            start = match.end()
            end = sequence[idx + 1].start(1) if idx + 1 < len(sequence) else len(content)
            option_texts.append(self._strip_leading_option_marker(content[start:end]))

            marker_text = match.group(0)
            if re.search(r'[.．、:：。]|<sub>', marker_text):
                score += 4

        for idx, option_text in enumerate(option_texts):
            compact = re.sub(r'\s+', '', option_text)
            if len(compact) < 2:
                score -= 80
            if len(compact) > 120 and idx + 1 < len(option_texts):
                score -= min(60, (len(compact) - 120) // 3)
            if re.match(r'^[的和与及、，。；:：]', option_text):
                score -= 140
            if re.match(r'^[A-H]\s+[A-H]\s+', option_text):
                score += 10

        return score

    def _has_choice_stem_signal(self, stem: str) -> bool:
        """题干必须像选择题，才能启用宽松的 A/B/C/D 选项识别。"""
        stem = stem or ""
        tail = stem[-120:]
        if "下列问题" in tail or "以下问题" in tail:
            return False
        if CHOICE_BLANK_RE.search(stem):
            return True
        if any(keyword in tail for keyword in ("下列", "以下", "正确", "错误", "不是", "属于", "应采用", "哪种", "哪个", "哪些")):
            return True
        return False

    def _has_choice_blank_near_option_start(self, stem: str) -> bool:
        """只把 A 选项前最近的括号空位当作选择题信号，避免说明性括号误触发。"""
        if not stem:
            return False
        tail = stem[-80:]
        return bool(CHOICE_BLANK_RE.search(tail))

    def _is_plausible_option_text(self, text: str, is_last: bool) -> bool:
        """判断两个选项标记之间的文本是否像一个选项内容。"""
        cleaned = self._strip_leading_option_marker(text)
        compact = re.sub(r'\s+', '', cleaned)
        if not compact:
            return False
        if len(compact) > 180 and not is_last:
            return False
        return True

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

    def _extract_options_from_content(self, content: str) -> List[Dict[str, str]]:
        """从内容中提取选项"""
        _stem, options = self._split_question_stem_options(content)
        return options

    def _normalize_options(self, options: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
        """统一选择题选项结构，兼容前端 key/text 和校验器 label/text。"""
        normalized: List[Dict[str, str]] = []
        seen_labels = set()
        for option in options or []:
            label = _get_option_label(option)
            text = str(option.get("text") or option.get("content") or "").strip()
            text = self._strip_leading_option_marker(text, expected_label=label)
            if not label or not text or label in seen_labels:
                continue
            normalized.append({
                "key": label,
                "label": label,
                "option_label": label,
                "text": text,
            })
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

        if not subject_id or not legacy_chapter_id:
            logger.warning(
                "题目缺少有效章节归属，跳过入库",
                document_id=question_dict.get('document_id'),
                question_id=question_dict.get('id'),
                page_no=question_dict.get('page_no'),
                subject_id=subject_id,
                chapter_id=legacy_chapter_id,
            )
            if not subject_id and not legacy_chapter_id:
                return False, "missing_subject_and_chapter"
            if not subject_id:
                return False, "missing_subject"
            return False, "missing_legacy_chapter"

        try:
            async with self.db.begin_nested():
                options = self._normalize_options(question_dict.get('options'))
                question_content = (question_dict.get('stem') or question_dict.get('content') or "").strip()

                # 创建题目记录
                question = Question(
                    id=question_dict['id'],
                    subject_id=subject_id,
                    chapter_id=legacy_chapter_id,
                    primary_chapter_id=primary_chapter_id,
                    source_document_id=question_dict['document_id'],
                    type=question_dict['question_type'],
                    content=question_content,
                    options=options or None,
                    answer="",
                    question_no=str(_extract_question_number_simple(question_dict) or "") or None,
                    review_status="pending",
                )
                self.db.add(question)

                # 创建章节关联
                if primary_chapter_id:
                    link = QuestionChapterLink(
                        question_id=question_dict['id'],
                        canonical_chapter_id=primary_chapter_id,
                        is_primary=True,
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
            return True, "saved"
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
                history.append({
                    'question_index': i,
                    'question_id': q.get('id'),
                    'fix_type': 'llm',
                    'fix_action': 'llm_merge',
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
