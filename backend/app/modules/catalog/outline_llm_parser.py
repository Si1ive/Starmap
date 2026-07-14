"""大纲 LLM 返回内容的 JSON 容错解析。"""

import ast
import json
import re
from typing import Any, List

from app.core.logging import get_logger


logger = get_logger(__name__)


def repair_truncated_json(text: str) -> str:
    """丢弃截断的半截值并关闭仍开放的 JSON 括号。"""
    stack: List[str] = []
    in_string = False
    escape = False
    expecting_value = False
    last_safe = 0

    index = 0
    while index < len(text):
        char = text[index]
        if escape:
            escape = False
            index += 1
            continue
        if in_string:
            if char == "\\":
                escape = True
            elif char == '"':
                in_string = False
                expecting_value = False
                last_safe = index + 1
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char in "[{":
            stack.append(char)
            expecting_value = False
            last_safe = index + 1
        elif char in "]}":
            if stack:
                stack.pop()
            expecting_value = False
            last_safe = index + 1
        elif char == ":":
            expecting_value = True
            last_safe = index + 1
        elif char == ",":
            expecting_value = False
            last_safe = index + 1
        elif char not in " \t\n\r":
            expecting_value = False
        index += 1

    if in_string and last_safe < len(text):
        result = text[:last_safe]
        in_string = False
    else:
        result = text

    if expecting_value and not in_string:
        result += " null"

    while stack:
        result += "]" if stack.pop() == "[" else "}"

    return re.sub(r",(\s*[\]}])", r"\1", result)


def extract_outline_llm_json(text: str) -> Any:
    """解析可能带代码块、噪声、注释、尾逗号或截断的 LLM JSON。"""
    if not text:
        raise ValueError("LLM 返回为空")
    cleaned = text.strip()

    fence = re.search(
        r"```(?:json)?\s*(.*?)```",
        cleaned,
        re.DOTALL | re.IGNORECASE,
    )
    if fence:
        cleaned = fence.group(1).strip()

    if not cleaned.startswith("{") and not cleaned.startswith("["):
        start = cleaned.find("{")
        if start == -1:
            start = cleaned.find("[")
        end = cleaned.rfind("}")
        if end == -1:
            end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

    cleaned = re.sub(r"//.*?$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r",\s*}", "}", cleaned)
    cleaned = re.sub(r",\s*]", "]", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as error:
        error_message = str(error)
        if "Unterminated string" in error_message or "Expecting" in error_message:
            try:
                repaired = repair_truncated_json(cleaned)
                result = json.loads(repaired)
                logger.info(
                    "JSON 截断修复成功",
                    added_len=len(repaired) - len(cleaned),
                    added_tail=repaired[len(cleaned):][:50],
                )
                return result
            except json.JSONDecodeError:
                pass

        try:
            if cleaned.startswith("{") or cleaned.startswith("["):
                result = ast.literal_eval(cleaned)
                return json.loads(json.dumps(result))
        except Exception:
            pass

        logger.error(
            "JSON 解析失败",
            error=error_message,
            text_preview=text[:1000],
        )
        raise ValueError(
            f"JSON 解析失败: {error_message[:200]}。"
            f"原始文本前 500 字符: {text[:500]}"
        )
