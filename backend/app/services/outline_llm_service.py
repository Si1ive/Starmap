"""
大纲 LLM 拆分服务

把 MinerU/Docling 解析出的大纲 markdown，用 LLM 拆成结构化的章节树：
- 四门课（数据结构/计组/操作系统/计网）先按科目名粗切，再逐门细拆
- 每门课产出：考察目标（exam_objective）+ 多层章节树（每节点含 name/outline_code/description）
- 复习指导（exam_guidance）不在这一步生成，入库后另行批量触发

与题目抽取的「题干/选项分离 + 兜底」机制完全无关，是独立的大纲处理路径。
"""

import ast
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
        # 如果配置中未显式设置，使用大纲拆分的合理默认值
        if not config.get("max_tokens"):
            self.max_tokens = 16000
        if not config.get("timeout_seconds"):
            self.timeout_seconds = 180


def _repair_truncated_json(s: str) -> str:
    """
    修复被截断的 JSON：扫描一遍源串，追踪字符串状态和括号栈。
    当截断点在字符串内部时，回退到该字符串开始前最后一个完整元素的位置，
    丢弃残缺的半截值，然后关闭所有开放括号。

    核心修复：解决了截断在 array 元素字符串中间时产生的悬挂逗号问题。
    例如 ["val1", "val2" ← 截断 → 回退到 ["val1" → 补 "]" → ["val1"]（合法）
    """
    stack: List[str] = []          # 括号栈
    in_string = False
    escape = False
    expecting_value = False        # 紧跟 ':' 后在等值

    # 记录上一个 "安全截断点"：最近一次完成一个完整值/键之后的位置
    last_safe = 0

    i = 0
    length = len(s)
    while i < length:
        ch = s[i]
        if escape:
            escape = False
            i += 1
            continue
        if in_string:
            if ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
                expecting_value = False
                # 一个完整字符串刚结束，从此处往后都是安全的
                last_safe = i + 1
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch in '[{':
            stack.append(ch)
            expecting_value = False
            last_safe = i + 1
        elif ch in ']}':
            if stack:
                stack.pop()
            expecting_value = False
            last_safe = i + 1
        elif ch == ':':
            expecting_value = True
            last_safe = i + 1
        elif ch == ',':
            expecting_value = False
            last_safe = i + 1
        elif ch in ' \t\n\r':
            pass
        else:  # 数字 / 字面量字符
            expecting_value = False
        i += 1

    # 如果截断在一个未闭合的字符串内，回退到 last_safe（丢弃半截值），
    # 并重置 in_string（半截值已丢弃，不再处于字符串内）
    if in_string and last_safe < length:
        result = s[:last_safe]
        in_string = False
    else:
        result = s

    # 如果':'后没有值，补 null
    if expecting_value and not in_string:
        result += ' null'

    # 关闭所有开放括号
    while stack:
        result += ']' if stack.pop() == '[' else '}'

    # 清理悬挂逗号: ",]" → "]"，",}" → "}"
    result = re.sub(r',(\s*[\]}])', r'\1', result)
    return result


def _extract_json(text: str) -> Any:
    """
    从 LLM 返回里抠出 JSON（容忍 ```json 包裹 / 前后噪声 / 单引号 / 尾部逗号 / 截断）。
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

    # 移除注释 (// 和 /* */)
    cleaned = re.sub(r'//.*?$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)

    # 修复尾部逗号
    cleaned = re.sub(r',\s*}', '}', cleaned)
    cleaned = re.sub(r',\s*]', ']', cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        error_msg = str(e)

        # 截断修复：基于括号栈和字符串状态智能补全
        if "Unterminated string" in error_msg or "Expecting" in error_msg:
            try:
                repaired = _repair_truncated_json(cleaned)
                result = json.loads(repaired)
                logger.info(
                    "JSON 截断修复成功",
                    added_len=len(repaired) - len(cleaned),
                    added_tail=repaired[len(cleaned):][:50],
                )
                return result
            except json.JSONDecodeError:
                pass

        # 兜底：ast.literal_eval（支持单引号字典字面量）
        try:
            if cleaned.startswith('{') or cleaned.startswith('['):
                result = ast.literal_eval(cleaned)
                return json.loads(json.dumps(result))
        except Exception:
            pass

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
   - children：子章节数组，没有就空数组
4. 不要生成复习建议或重点分析，只忠实还原大纲结构。
5. 只输出 JSON，不要任何解释文字。

输出格式：
{{
  "exam_objective": "……",
  "chapters": [
    {{
      "name": "哈希表",
      "outline_code": "1.5",
      "description": "大纲原文...",
      "children": [...]
    }}
  ]
}}

大纲文本：
---
{content}
---"""


# 骨架拆分 prompt（不生成 enhanced_description 和 keywords，输出量小不会截断）
_SKELETON_PROMPT = """下面是一门课《{subject_name}》的考试大纲文本。请把它拆成结构化的章节树（骨架）。

要求：
1. 先识别这门课开头的「考察目标」（概括性的整门课要求，通常三四句话），放进 exam_objective。
2. 再把后续内容拆成多层级章节树 chapters。层级用嵌套 children 表达（如 一 / (一) / 1. / (1) 这样的层级关系）。
3. 每个章节节点只包含：
   - name：章节标题（去掉前面的编号），必填
   - outline_code：原始编号（如 "1.1.1" / "一" / "(一)"），没有就 null
   - description：该节点对应的考点正文原文（大纲里列的具体考点），没有就 null
   - children：子章节数组，没有就空数组
4. 重要：不要生成 enhanced_description、keywords 或任何其他字段。
5. 只输出 JSON，不要任何解释文字。

输出格式：
{{
  "exam_objective": "……",
  "chapters": [
    {{
      "name": "哈希表",
      "outline_code": "1.5",
      "description": "大纲原文...",
      "children": [...]
    }}
  ]
}}

大纲文本：
---
{content}
---"""


# 批量增强 prompt：为一批叶子节点生成 enhanced_description + keywords
# 每批 10-15 个节点，保证输出量不超 max_tokens
_BATCH_ENHANCE_PROMPT = """你是408考研大纲解析专家。下面是一些《{subject_name}》的章节节点（每个节点含考点原文 description）。请为每个节点生成 enhanced_description 和 keywords。

每个节点的 enhanced_description 要求（2-3句话，包含）：
- 核心内容概括
- 常见考法
- 易混淆概念

keywords 要求（5-10个）：
- 包含中英文名称
- 包含同义词/别名
- 包含该节点下的核心术语

示例：
节点 "哈希表" 考点 "哈希函数、冲突解决、链地址法、开放寻址法"
→ enhanced_description: "哈希表是基于哈希函数的键值对存储结构。常考冲突解决方法（链地址法、开放寻址法）、哈希函数设计、装填因子分析。易混淆：线性探测 vs 二次探测。"
→ keywords: ["散列表", "Hash Table", "冲突解决", "链地址法", "开放寻址", "线性探测", "二次探测", "装填因子"]

只输出 JSON 对象（不要数组），格式：
{{
  "items": [
    {{"index": 0, "enhanced_description": "...", "keywords": ["...", ...]}},
    ...
  ]
}}

节点列表：
{items_json}"""


# 每批最多 12 个叶子节点（保守估计每节点 300 token 输出 = 3600，远低于 16K 上限）
_BATCH_SIZE = 12
# 默认最大并发数（可通过 outline_llm.max_concurrency 配置覆盖）
_DEFAULT_MAX_CONCURRENCY = 3


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

    async def split_outline_with_progress(self, run_id: str, document_id: str) -> Dict[str, Any]:
        """
        拆分大纲文档并更新 OutlineIngestionRun 的进度（用于异步后台任务）

        与 split_outline 的区别：
        1. 接收 run_id，在处理每门课时更新 run.current_subject_name / processed_subjects
        2. 返回相同的结构，但过程中实时写入进度到 DB
        """
        from app.models.mysql_models import OutlineIngestionRun

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

        # 获取 run 记录
        run = await self.db.get(OutlineIngestionRun, run_id)
        if not run:
            raise ValueError(f"OutlineIngestionRun 不存在: {run_id}")

        results: List[Dict[str, Any]] = []
        if segments:
            run.total_subjects = len(segments)
            await self.db.commit()

            # 逐门课细拆，每门完成后更新进度
            for idx, (code, start, end) in enumerate(segments):
                subject = subjects_by_code.get(code)
                if not subject:
                    continue

                # 更新当前处理的科目
                run.current_subject_name = subject.name
                run.processed_subjects = idx + 1
                run.stage_detail = f"正在拆分《{subject.name}》({idx+1}/{len(segments)})..."
                await self.db.commit()

                seg_text = markdown[start:end].strip()
                try:
                    parsed = await self._split_one_subject(client, subject.name, seg_text)
                    results.append(self._pack_subject_result(subject, parsed))
                    run.successful_subjects = len(results)
                except Exception as e:
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

                run.processed_subjects = idx + 1
                await self.db.commit()
        else:
            # 降级：整篇喂一次，让 LLM 自己分四门课
            logger.warning("大纲粗切未命中科目边界，降级整篇拆分", document_id=document_id)
            run.stage_detail = "未识别到科目边界，尝试整篇拆分..."
            await self.db.commit()
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
        """
        两轮拆分单门课：

        第1轮 — 拆骨架：只输出 name/outline_code/description/children，
                 不生成 enhanced_description 和 keywords。输出量小，不会截断。
        第2轮 — 批量增强：收集所有叶子节点，按 _BATCH_SIZE 分批并发调用 LLM，
                 为每批节点生成 enhanced_description + keywords，写回骨架树。
        """
        # ===== 第1轮：拆骨架 =====
        prompt = _SKELETON_PROMPT.format(subject_name=subject_name, content=content[:40000])
        last_err: Optional[Exception] = None
        skeleton: Optional[Dict[str, Any]] = None
        for attempt in range(2):
            try:
                text = await client.chat(prompt, purpose=f"大纲骨架拆分-{subject_name}")
                data = _extract_json(text)
                chapters = _normalize_chapters(data.get("chapters") or [])
                if not chapters:
                    raise ValueError("骨架拆分结果章节为空")
                skeleton = {
                    "exam_objective": (str(data.get("exam_objective")).strip() if data.get("exam_objective") else None),
                    "chapters": chapters,
                }
                break
            except Exception as e:
                last_err = e
                logger.warning("大纲骨架拆分失败，准备重试", subject=subject_name, attempt=attempt, error=str(e))

        if skeleton is None:
            raise ValueError(f"《{subject_name}》骨架拆分失败: {last_err}")

        # ===== 第2轮：批量增强叶子节点 =====
        leaf_nodes = self._collect_leaf_nodes(skeleton["chapters"])
        if leaf_nodes:
            logger.info("开始批量增强叶子节点", subject=subject_name, leaf_count=len(leaf_nodes))
            await self._enhance_leaf_nodes_batched(client, subject_name, leaf_nodes)
        else:
            logger.info("无叶子节点需要增强", subject=subject_name)

        return skeleton

    @staticmethod
    def _collect_leaf_nodes(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """收集章节树中所有叶子节点（无 children 或 children 为空的节点）。"""
        result: List[Dict[str, Any]] = []
        for ch in chapters:
            children = ch.get("children") or []
            if children:
                result.extend(OutlineLLMService._collect_leaf_nodes(children))
            else:
                result.append(ch)
        return result

    async def _enhance_leaf_nodes_batched(
        self, client: OutlineLLMClient, subject_name: str, leaf_nodes: List[Dict[str, Any]]
    ) -> None:
        """分批并发调用 LLM 为叶子节点生成 enhanced_description + keywords。"""
        import asyncio

        # 从配置读取最大并发数
        runtime_settings = await SystemSettingsService(self.db).load()
        cfg = runtime_settings.get("outline_llm", {})
        max_concurrency = int(cfg.get("max_concurrency", _DEFAULT_MAX_CONCURRENCY))
        if max_concurrency < 1:
            max_concurrency = _DEFAULT_MAX_CONCURRENCY

        semaphore = asyncio.Semaphore(max_concurrency)

        # 按 _BATCH_SIZE 分片
        batches = [
            leaf_nodes[i:i + _BATCH_SIZE]
            for i in range(0, len(leaf_nodes), _BATCH_SIZE)
        ]

        async def _enhance_one_batch(batch: List[Dict[str, Any]], batch_idx: int) -> None:
            async with semaphore:
                items = [
                    {"index": j, "name": node["name"], "description": node.get("description") or ""}
                    for j, node in enumerate(batch)
                ]
                items_json = json.dumps(items, ensure_ascii=False, indent=2)
                prompt = _BATCH_ENHANCE_PROMPT.format(
                    subject_name=subject_name, items_json=items_json
                )
                try:
                    text = await client.chat(prompt, purpose=f"大纲增强-{subject_name}-批{batch_idx+1}")
                    data = _extract_json(text)
                    enhancements = data.get("items") if isinstance(data, dict) else data
                    if not isinstance(enhancements, list):
                        logger.warning("增强返回格式不正确，跳过此批", batch_idx=batch_idx)
                        return
                    # 写回叶子节点
                    for item in enhancements:
                        if not isinstance(item, dict):
                            continue
                        idx = item.get("index")
                        if idx is None or idx >= len(batch):
                            continue
                        batch[idx]["enhanced_description"] = str(item.get("enhanced_description") or "").strip()[:1000]
                        kw = item.get("keywords")
                        if isinstance(kw, list):
                            batch[idx]["keywords"] = [str(k).strip() for k in kw if k][:50]
                    logger.info("批量增强完成", batch_idx=batch_idx, nodes=len(batch))
                except Exception as e:
                    logger.warning("某批增强失败，跳过", batch_idx=batch_idx, error=str(e))

        # 并发执行所有批次（受 semaphore 限流）
        tasks = [_enhance_one_batch(batch, i) for i, batch in enumerate(batches)]
        await asyncio.gather(*tasks)

    async def _split_one_subject_chunked(
        self, client: OutlineLLMClient, subject_name: str, content: str
    ) -> Dict[str, Any]:
        """
        分块处理单门课（内容超过 40000 字符）

        策略:
        1. 先用前 5000 字符提取考察目标
        2. 按一级章节标题分块（每块最多 30000 字符）
        3. 每块单独调用 LLM 拆骨架
        4. 合并骨架，收集所有叶子节点，批量增强
        """
        # 1. 提取考察目标
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

        # 3. 每块单独拆骨架
        all_chapters = []
        for i, chunk in enumerate(chunks):
            chunk_prompt = _SKELETON_PROMPT.format(subject_name=subject_name, content=chunk[:30000])
            try:
                text = await client.chat(chunk_prompt, purpose=f"大纲骨架拆分-{subject_name}-块{i+1}")
                data = _extract_json(text)
                chapters = _normalize_chapters(data.get("chapters") or [])
                all_chapters.extend(chapters)
            except Exception as e:
                logger.warning("某块骨架拆分失败，跳过", subject=subject_name, chunk=i+1, error=str(e))

        if not all_chapters:
            raise ValueError(f"《{subject_name}》所有块拆分均失败")

        # 4. 批量增强叶子节点
        leaf_nodes = self._collect_leaf_nodes(all_chapters)
        if leaf_nodes:
            logger.info("开始批量增强叶子节点（分块模式）", subject=subject_name, leaf_count=len(leaf_nodes))
            await self._enhance_leaf_nodes_batched(client, subject_name, leaf_nodes)

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

