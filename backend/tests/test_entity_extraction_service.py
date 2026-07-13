from app.services.entity_extraction_service import (
    OptionIntegrityChecker,
    EntityExtractionService,
)


def test_option_integrity_accepts_key_field():
    checker = OptionIntegrityChecker()

    result = checker.check({
        "question_type": "choice",
        "options": [
            {"key": "A", "text": "选项一"},
            {"key": "B", "text": "选项二"},
            {"key": "C", "text": "选项三"},
            {"key": "D", "text": "选项四"},
        ],
    })

    assert result["is_complete"] is True


# ===== LLM 切分兜底：预筛检测 =====

def test_detect_merged_question_nos_hits_successor():
    """第7题组文本里粘着第8题题号 → 检出后继题号 [8]。"""
    text = "7。 若 G 是一个具有 36 条边的图 A。11 B。10 C。9 D。8 8。 在有向图 G 的拓扑序列中"
    assert EntityExtractionService._detect_merged_question_nos(text, base_no=7) == [8]


def test_detect_merged_question_nos_no_false_positive_on_options():
    """选项里的数字（如 D。8 的答案值 8）不应被当成后继题号。"""
    # base_no=20 时，8 不在 21..23 范围内，不误报
    text = "20。 下列说法正确的是 A。11 B。10 C。9 D。8"
    assert EntityExtractionService._detect_merged_question_nos(text, base_no=20) == []


def test_detect_merged_question_nos_none_base():
    """无题号组无法判断后继，返回空。"""
    assert EntityExtractionService._detect_merged_question_nos("任意文本 3。 xxx", base_no=None) == []


def test_detect_merged_question_nos_multiple_successors():
    """连续粘连多题 → 检出全部后继。"""
    text = "5。 题干 A。x B。y C。z D。w 6。 第六题 A。1 B。2 7。 第七题"
    assert EntityExtractionService._detect_merged_question_nos(text, base_no=5) == [6, 7]


# ===== LLM 切分兜底：解析 mock LLM 返回 =====

class _MockLLM:
    """返回预设 JSON 的假 LLM client。"""
    def __init__(self, response: str):
        self._response = response

    async def chat(self, prompt: str, purpose=None) -> str:
        return self._response


async def test_llm_split_parses_two_questions():
    """LLM 返回合法 JSON 数组 → 切成两道题，选项归一化为 key/text。"""
    resp = '''这是切分结果：
[
  {"question_no": 7, "stem": "第七题题干", "options": [{"key":"A","text":"11"},{"key":"B","text":"10"},{"key":"C","text":"9"},{"key":"D","text":"8"}]},
  {"question_no": 8, "stem": "第八题题干", "options": [{"key":"A","text":"甲"},{"key":"B","text":"乙"},{"key":"C","text":"丙"},{"key":"D","text":"丁"}]}
]'''
    svc = EntityExtractionService(None)
    parts = await svc._llm_split_merged_questions(_MockLLM(resp), "原始粘连文本", base_no=7, successor_nos=[8])
    assert parts is not None
    assert len(parts) == 2
    assert parts[0]["question_no"] == 7 and len(parts[0]["options"]) == 4
    assert parts[1]["stem"] == "第八题题干"
    assert parts[1]["options"][0]["key"] == "A"


async def test_llm_split_returns_none_on_single_question():
    """LLM 判定只有一道题（数组长度 < 2）→ 返回 None，交回原逻辑。"""
    resp = '[{"question_no": 7, "stem": "只有一道", "options": []}]'
    svc = EntityExtractionService(None)
    parts = await svc._llm_split_merged_questions(_MockLLM(resp), "文本", base_no=7, successor_nos=[8])
    assert parts is None


async def test_llm_split_returns_none_on_garbage():
    """LLM 返回非 JSON → 返回 None，不阻断主流程。"""
    svc = EntityExtractionService(None)
    parts = await svc._llm_split_merged_questions(_MockLLM("抱歉我无法处理"), "文本", base_no=7, successor_nos=[8])
    assert parts is None
