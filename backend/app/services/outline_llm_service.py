"""
大纲 LLM 拆分服务

把 MinerU/Docling 解析出的大纲 markdown，用 LLM 拆成结构化的章节树：
- 四门课（数据结构/计组/操作系统/计网）先按科目名粗切，再逐门细拆
- 每门课产出：考察目标（exam_objective）+ 多层章节树（每节点含 name/outline_code/description）
- 复习指导（exam_guidance）不在这一步生成，入库后另行批量触发

与题目抽取的「题干/选项分离 + 兜底」机制完全无关，是独立的大纲处理路径。
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import Document, Subject
from app.services.llm_client import BaseLLMClient
from app.services.system_settings_service import SystemSettingsService

logger = get_logger(__name__)

# 科目名 → code 的别名映射，用于在 markdown 里定位课程边界。
# key 是出现在大纲文本中的可能写法，value 是 subjects.code。
SUBJECT_ALIASES: Dict[str, str] = {
    "数据结构": "data_structure",
    "计算机组成原理": "computer_organization",
    "计算机组成": "computer_organization",
    "计组": "computer_organization",
    "操作系统": "operating_system",
    "计算机网络": "computer_network",
    "计网": "computer_network",
}


class OutlineLLMClient(BaseLLMClient):
    """大纲拆分专用客户端：继承 BaseLLMClient，覆盖默认温度/token/超时。"""

    called_by = "outline_llm"
    default_system_prompt = "你是408考研大纲解析专家，负责把大纲文本拆成结构化章节树。"
    default_temperature = 0.2

    def __init__(self, config: Dict[str, Any]):
        config = config or {}
        super().__init__(config)
        # 大纲拆分文本长，token/超时给更大默认值
        self.max_tokens = int(config.get("max_tokens", 4000))
        self.timeout_seconds = int(config.get("timeout_seconds", 120))


def _extract_json(text: str) -> Any:
    """
    从 LLM 返回里抠出 JSON（容忍 ```json 包裹 / 前后噪声 / 单引号 / 尾部逗号）。

    增强容错:
    1. 移除 markdown 代码块
    2. 查找 { } 边界
    3. 修复常见 JSON 错误（单引号、尾部逗号、注释）
    4. 解析并返回
    """
    if not text:
        raise ValueError("LLM 返回为空")
    cleaned = text.strip()

    # 去掉 ```json ... ``` 包裹
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()

    # 退而求其次：截取首个 { 到末个 }
    if not cleaned.startswith("{") and not cleaned.startswith("["):
        start = cleaned.find("{")
        if start == -1:
            start = cleaned.find("[")
        end = cleaned.rfind("}")
        if end == -1:
            end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

    # 修复常见 JSON 错误
    # 1. 移除注释（// 和 /* */）
    cleaned = re.sub(r'//.*?$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)

    # 2. 修复尾部逗号（,} 和 ,]）
    cleaned = re.sub(r',\s*}', '}', cleaned)
    cleaned = re.sub(r',\s*]', ']', cleaned)

    # 3. 尝试标准 JSON 解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # 错误位置信息
        error_msg = str(e)

        # 4. 如果是 "Unterminated string"，尝试修复截断的字符串
        if "Unterminated string" in error_msg:
            # 尝试在末尾添加闭合引号和大括号
            if not cleaned.endswith('}'):
                # 尝试补全：添加 " 和 }]}
                attempts = [
                    cleaned + '"}}]',
                    cleaned + '"}]',
                    cleaned + '"]}',
                    cleaned + '"}',
                    cleaned + '}]',
                    cleaned + ']',
                ]
                for attempt in attempts:
                    try:
                        return json.loads(attempt)
                    except:
                        continue

        # 5. 尝试用 ast.literal_eval（支持单引号）
        import ast
        try:
            if cleaned.startswith('{') or cleaned.startswith('['):
                result = ast.literal_eval(cleaned)
                # 转回 JSON 兼容格式
                return json.loads(json.dumps(result))
        except Exception:
            pass

        # 都失败了，记录详细错误并抛出
        logger.error("JSON 解析失败", error=error_msg, text_preview=text[:1000])
        raise ValueError(f"JSON 解析失败: {error_msg[:200]}。原始文本前 500 字符: {text[:500]}")


def _normalize_chapters(raw: Any) -> List[Dict[str, Any]]:
    """递归清洗 LLM 输出的章节树：name 必填，保留 outline_code/description/enhanced_description/keywords/children。"""
    result: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return result
    for idx, node in enumerate(raw):
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or node.get("title") or "").strip()
        if not name:
            continue
        children = _normalize_chapters(node.get("children") or [])

        # 处理 enhanced_description
        enhanced_desc = node.get("enhanced_description")
        if enhanced_desc:
            enhanced_desc = str(enhanced_desc).strip()[:1000]  # 限制长度

        # 处理 keywords
        keywords = node.get("keywords")
        if keywords:
            if isinstance(keywords, list):
                keywords = [str(k).strip() for k in keywords if k][:50]  # 最多50个关键词
            else:
                keywords = None

        result.append({
            "name": name[:200],
            "outline_code": (str(node.get("outline_code")).strip()[:50] if node.get("outline_code") else None),
            "description": (str(node.get("description")).strip() if node.get("description") else None),
            "enhanced_description": enhanced_desc,
            "keywords": keywords,
            "sort_order": idx,
            "children": children,
        })
    return result


def _count_tree(chapters: List[Dict[str, Any]]) -> int:
    n = 0
    for c in chapters:
        n += 1
        n += _count_tree(c.get("children") or [])
    return n


def _max_depth(chapters: List[Dict[str, Any]], current: int = 1) -> int:
    if not chapters:
        return 0
    return max(
        _max_depth(c.get("children") or [], current + 1) or current
        for c in chapters
    )


_SPLIT_PROMPT = """下面是一门课《{subject_name}》的考试大纲文本。请把它拆成结构化 JSON。

要求：
1. 先识别这门课开头的「考察目标」（概括性的整门课要求，通常三四句话），放进 exam_objective。
2. 再把后续内容拆成多层级章节树 chapters。层级用嵌套 children 表达（如 一 / (一) / 1. / (1) 这样的层级关系）。
3. 每个章节节点：
   - name：章节标题（去掉前面的编号），必填
   - outline_code：原始编号（如 "1.1.1" / "一" / "(一)"），没有就 null
   - description：该节点对应的考点正文原文（大纲里列的具体考点），没有就 null
   - enhanced_description：对该知识点的增强描述（2-3句话，包含：核心内容概括、常见考法、易混淆概念），用于帮助题目和知识点建立关联，必填
   - keywords：关键词标签列表（别名、英文名、相关术语、典型例题关键词），用于精确匹配，必填
   - children：子章节数组，没有就空数组
4. 增强描述示例：
   - 节点 "哈希表" 的 enhanced_description: "哈希表是基于哈希函数的键值对存储结构。常考冲突解决方法（链地址法、开放寻址法）、哈希函数设计、装填因子分析。易混淆：线性探测 vs 二次探测。"
   - 节点 "哈希表" 的 keywords: ["散列表", "Hash Table", "冲突解决", "链地址法", "开放寻址", "线性探测", "二次探测", "装填因子"]
5. 关键词标签原则：
   - 包含中英文名称
   - 包含同义词/别名（如"散列表"="哈希表"）
   - 包含该节点下的核心术语（如哈希表下的"链地址法"）
   - 包含典型考题中可能出现的关键词
6. 不要生成复习建议或重点分析，只忠实还原大纲结构并增强每个节点。
7. 只输出 JSON，不要任何解释文字。

输出格式：
{{
  "exam_objective": "……",
  "chapters": [
    {{
      "name": "哈希表",
      "outline_code": "1.5",
      "description": "大纲原文...",
      "enhanced_description": "哈希表是基于哈希函数的键值对存储结构。常考冲突解决方法...",
      "keywords": ["散列表", "Hash Table", "冲突解决", "链地址法"],
      "children": [...]
    }}
  ]
}}

大纲文本：
---
{content}
---"""


class OutlineLLMService:
    """大纲 LLM 拆分服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_client(self) -> OutlineLLMClient:
        runtime_settings = await SystemSettingsService(self.db).load()
        cfg = runtime_settings.get("outline_llm", {})
        return OutlineLLMClient(cfg if isinstance(cfg, dict) else {})

    async def _load_subjects(self) -> Dict[str, Subject]:
        """code → Subject。"""
        rows = (await self.db.execute(select(Subject))).scalars().all()
        return {s.code: s for s in rows}

    def _segment_by_subject(self, markdown: str) -> List[Tuple[str, int, int]]:
        """
        在 markdown 里按科目名定位课程边界，返回 [(subject_code, start, end), ...]。
        找不到边界返回空列表（交给调用方降级）。
        """
        hits: List[Tuple[int, str]] = []  # (pos, code)
        for alias, code in SUBJECT_ALIASES.items():
            for m in re.finditer(re.escape(alias), markdown):
                hits.append((m.start(), code))
        if not hits:
            return []
        hits.sort()
        # 每门课取首次出现位置作为段落起点（去重 code，保留最早）
        first_pos: Dict[str, int] = {}
        for pos, code in hits:
            if code not in first_pos:
                first_pos[code] = pos
        # 至少识别到 2 门课才认为粗切有效
        if len(first_pos) < 2:
            return []
        ordered = sorted(first_pos.items(), key=lambda kv: kv[1])  # [(code, pos)]
        segments: List[Tuple[str, int, int]] = []
        for i, (code, pos) in enumerate(ordered):
            end = ordered[i + 1][1] if i + 1 < len(ordered) else len(markdown)
            segments.append((code, pos, end))
        return segments

    async def split_outline(self, document_id: str) -> Dict[str, Any]:
        """
        拆分大纲文档，返回四门课结构（不入库）：
        {subjects: [{subject_id, subject_code, subject_name, exam_objective,
                     total_chapters, max_depth, chapters, error?}]}

        重要：每个科目失败不影响其他科目，失败的科目会在 result 中标记 error 字段。
        """
        document = (await self.db.execute(
            select(Document).where(Document.id == document_id)
        )).scalar_one_or_none()
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        markdown = (document.document_markdown or "").strip()
        if not markdown:
            raise ValueError("文档没有可用的 markdown，请先确认解析成功")

        client = await self._get_client()
        if not client.is_available:
            raise ValueError("大纲拆分 LLM 未启用或缺少配置，请在系统设置 -> outline_llm 配置后重试")

        subjects_by_code = await self._load_subjects()
        segments = self._segment_by_subject(markdown)

        results: List[Dict[str, Any]] = []
        if segments:
            # 逐门课细拆（捕获每个科目的异常，不中断流程）
            for code, start, end in segments:
                subject = subjects_by_code.get(code)
                if not subject:
                    continue
                seg_text = markdown[start:end].strip()
                try:
                    parsed = await self._split_one_subject(client, subject.name, seg_text)
                    results.append(self._pack_subject_result(subject, parsed))
                except Exception as e:
                    # 单个科目失败，记录错误但不中断
                    logger.warning("大纲拆分某科目失败，标记为失败但继续处理其他科目",
                                   subject=subject.name, error=str(e))
                    results.append({
                        "subject_id": subject.id,
                        "subject_code": subject.code,
                        "subject_name": subject.name,
                        "error": str(e),
                        "total_chapters": 0,
                        "max_depth": 0,
                        "chapters": [],
                    })
        else:
            # 降级：整篇喂一次，让 LLM 自己分四门课
            logger.warning("大纲粗切未命中科目边界，降级整篇拆分", document_id=document_id)
            results = await self._split_whole(client, markdown, subjects_by_code)

        if not results:
            raise ValueError("LLM 拆分未产出任何科目，请检查大纲内容或 LLM 配置")

        return {"document_id": document_id, "subjects": results}

    async def _split_one_subject(
        self, client: OutlineLLMClient, subject_name: str, content: str
    ) -> Dict[str, Any]:
        """
        拆单门课，返回 {exam_objective, chapters}。

        改进: 如果内容超过 40000 字符，按章节分块处理，避免超时。
        解析失败重试一次。
        """
        # 如果内容较短，直接处理
        if len(content) <= 40000:
            return await self._split_one_subject_direct(client, subject_name, content)

        # 内容过长，按一级章节分块处理
        logger.info("科目内容过长，按章节分块处理", subject=subject_name, length=len(content))
        return await self._split_one_subject_chunked(client, subject_name, content)

    async def _split_one_subject_direct(
        self, client: OutlineLLMClient, subject_name: str, content: str
    ) -> Dict[str, Any]:
        """直接处理单门课（内容不超过 40000 字符）"""
        prompt = _SPLIT_PROMPT.format(subject_name=subject_name, content=content[:40000])
        last_err: Optional[Exception] = None
        for attempt in range(2):
            try:
                text = await client.chat(prompt, purpose=f"大纲拆分-{subject_name}")
                data = _extract_json(text)
                chapters = _normalize_chapters(data.get("chapters") or [])
                if not chapters:
                    raise ValueError("拆分结果章节为空")
                return {
                    "exam_objective": (str(data.get("exam_objective")).strip() if data.get("exam_objective") else None),
                    "chapters": chapters,
                }
            except Exception as e:  # JSON 解析/校验失败重试
                last_err = e
                logger.warning("大纲单科拆分失败，准备重试", subject=subject_name, attempt=attempt, error=str(e))
        raise ValueError(f"《{subject_name}》大纲拆分失败: {last_err}")

    async def _split_one_subject_chunked(
        self, client: OutlineLLMClient, subject_name: str, content: str
    ) -> Dict[str, Any]:
        """
        分块处理单门课（内容超过 40000 字符）

        策略:
        1. 先用前 5000 字符提取考察目标
        2. 按一级章节标题分块（每块最多 30000 字符）
        3. 每块单独调用 LLM 拆分
        4. 合并结果
        """
        # 1. 提取考察目标（只看前部分）
        header = content[:5000]
        objective_prompt = f"""请从以下《{subject_name}》大纲片段中提取"考察目标"部分。

内容：
{header}

只输出 JSON：{{"exam_objective": "考察目标文本"}}
如果找不到，返回 {{"exam_objective": null}}"""

        exam_objective = None
        try:
            text = await client.chat(objective_prompt, purpose=f"提取考察目标-{subject_name}")
            data = _extract_json(text)
            exam_objective = data.get("exam_objective")
        except Exception as e:
            logger.warning("提取考察目标失败，继续处理", subject=subject_name, error=str(e))

        # 2. 按一级章节分块
        chunks = self._split_into_chapter_chunks(content, max_chunk_size=30000)
        logger.info("按章节分块", subject=subject_name, chunks=len(chunks))

        # 3. 每块单独拆分
        all_chapters = []
        for i, chunk in enumerate(chunks):
            chunk_prompt = f"""请拆分以下《{subject_name}》大纲片段（第 {i+1}/{len(chunks)} 块）。

{chunk[:30000]}

只输出 JSON 数组：{{"chapters": [...]}}
"""
            try:
                text = await client.chat(chunk_prompt, purpose=f"大纲拆分-{subject_name}-块{i+1}")
                data = _extract_json(text)
                chapters = _normalize_chapters(data.get("chapters") or [])
                all_chapters.extend(chapters)
            except Exception as e:
                logger.warning("某块拆分失败，跳过", subject=subject_name, chunk=i+1, error=str(e))

        if not all_chapters:
            raise ValueError(f"《{subject_name}》所有块拆分均失败")

        return {
            "exam_objective": exam_objective,
            "chapters": all_chapters,
        }

    def _split_into_chapter_chunks(self, content: str, max_chunk_size: int = 30000) -> List[str]:
        """
        按一级章节标题分块

        策略: 寻找 "第X章"、"一、"、"1." 等一级标题，在此处切分
        """
        lines = content.split('\n')
        chunks = []
        current_chunk = []
        current_size = 0

        # 一级标题模式（第X章、一、、1.）
        chapter_pattern = re.compile(r'^\s*(?:第[一二三四五六七八九十百千万零\d]+章|[一二三四五六七八九十]+\s*[、.]|\d+\s*[、.])')

        for line in lines:
            line_size = len(line) + 1  # +1 for newline

            # 如果是一级标题 且 当前块已有内容 且 加上这行会超过限制
            if chapter_pattern.match(line) and current_chunk and (current_size + line_size > max_chunk_size):
                # 保存当前块
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_size = line_size
            else:
                current_chunk.append(line)
                current_size += line_size

        # 保存最后一块
        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks if chunks else [content]

    async def _split_whole(
        self, client: OutlineLLMClient, markdown: str, subjects_by_code: Dict[str, Subject]
    ) -> List[Dict[str, Any]]:
        """降级路径：粗切失败时，按已知四门课各喂整篇让 LLM 抽取对应部分。"""
        results: List[Dict[str, Any]] = []
        for code, subject in subjects_by_code.items():
            try:
                parsed = await self._split_one_subject(client, subject.name, markdown)
                results.append(self._pack_subject_result(subject, parsed))
            except ValueError as e:
                logger.warning("降级拆分某科失败，跳过", subject=subject.name, error=str(e))
        return results

    @staticmethod
    def _pack_subject_result(subject: Subject, parsed: Dict[str, Any]) -> Dict[str, Any]:
        chapters = parsed["chapters"]
        return {
            "subject_id": subject.id,
            "subject_code": subject.code,
            "subject_name": subject.name,
            "exam_objective": parsed.get("exam_objective"),
            "total_chapters": _count_tree(chapters),
            "max_depth": _max_depth(chapters),
            "chapters": chapters,
        }

