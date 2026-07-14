"""题目 LLM 修复 Prompt 分流测试。"""

from app.modules.corpus.question_repair_prompts import build_fix_prompt


def test_choice_prompt_allows_source_marked_option_repair() -> None:
    context = [
        {
            "question_no": 1,
            "question_type": "choice",
            "stem": "1。循环队列队首位置是（ ）。",
            "raw_text": "1。题干 A 甲 B 乙 C 丙",
            "page_no": 1,
            "options": [
                {"key": "A", "text": "甲"},
                {"key": "B", "text": "乙"},
                {"key": "C", "text": "丙"},
            ],
        }
    ]

    prompt = build_fix_prompt(
        context,
        target_idx=0,
        issue={
            "issue_type": "too_few",
            "missing_options": ["D"],
        },
    )

    assert "教材选择题结构分析专家" in prompt
    assert "repair_options" in prompt
    assert "ai_generated" in prompt
    assert "缺失选项: ['D']" in prompt


def test_subjective_prompt_forbids_generated_choice_options() -> None:
    raw_text = (
        "43 （12 分）整数 x 和 y 分别存放在寄存器 A 和 B 中，"
        "另有寄存器 C 和 D。请回答下列问题："
        "（1）寄存器内容分别是什么？（2）相加结果是什么？"
    )
    context = [
        {
            "question_no": 43,
            "question_type": "choice",
            "stem": raw_text.split(" A 和 B 中")[0],
            "raw_text": raw_text,
            "page_no": 4,
            "options": [
                {"key": "A", "text": "和"},
                {"key": "B", "text": "中"},
                {"key": "C", "text": "和"},
            ],
        }
    ]

    prompt = build_fix_prompt(
        context,
        target_idx=0,
        issue={"issue_type": "too_few"},
    )

    assert "教材主观题结构分析专家" in prompt
    assert "repair_subjective" in prompt
    assert "不得生成选择题选项" in prompt
    assert "ai_generated" not in prompt


def test_prompt_marks_only_target_question() -> None:
    context = [
        {
            "question_no": number,
            "question_type": "choice",
            "stem": f"{number}。题干",
            "raw_text": f"{number}。题干 A 甲 B 乙 C 丙 D 丁",
            "options": [],
        }
        for number in (1, 2, 3)
    ]

    prompt = build_fix_prompt(
        context,
        target_idx=1,
        issue={"issue_type": "duplicate"},
    )

    assert prompt.count("← 【目标】") == 1
    assert "题目2 ← 【目标】" in prompt
