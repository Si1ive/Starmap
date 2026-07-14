from app.modules.catalog.outline_prompts import (
    build_outline_enhancement_prompt,
    build_outline_guidance_prompt,
    build_outline_objective_prompt,
    build_outline_skeleton_prompt,
)


def test_build_outline_skeleton_prompt_keeps_skeleton_contract():
    prompt = build_outline_skeleton_prompt(
        "数据结构",
        "一、线性表\n顺序存储和链式存储",
    )

    assert "《数据结构》" in prompt
    assert "一、线性表\n顺序存储和链式存储" in prompt
    assert '"exam_objective"' in prompt
    assert '"chapters"' in prompt
    assert "不要生成 enhanced_description、keywords" in prompt


def test_build_outline_enhancement_prompt_keeps_reference_contract():
    prompt = build_outline_enhancement_prompt(
        "数据结构",
        "chap_linear 线性表\nchap_cache 高速缓存",
        [
            {
                "index": 0,
                "name": "线性表",
                "description": "顺序表和链表",
            }
        ],
    )

    assert "《数据结构》" in prompt
    assert "chap_linear 线性表" in prompt
    assert '"name": "线性表"' in prompt
    assert "\\u" not in prompt
    assert "target_chapter_id 必须从下方考点目录中选择" in prompt
    assert "enhanced_description" in prompt
    assert "keywords" in prompt
    assert "cross_references" in prompt
    for relation_type in (
        "similar_to",
        "prerequisite",
        "contrast_with",
        "common_confusion",
    ):
        assert relation_type in prompt


def test_build_outline_objective_prompt_requires_nullable_json_result():
    prompt = build_outline_objective_prompt(
        "操作系统",
        "考察目标：掌握进程、存储和文件管理。",
    )

    assert "《操作系统》" in prompt
    assert "掌握进程、存储和文件管理" in prompt
    assert '{"exam_objective": "考察目标文本"}' in prompt
    assert '{"exam_objective": null}' in prompt


def test_build_outline_guidance_prompt_keeps_chapter_id_mapping():
    prompt = build_outline_guidance_prompt(
        "掌握计算机网络体系结构",
        [
            {
                "id": "chapter-network",
                "name": "网络层",
                "points": "IP 协议和路由算法",
            }
        ],
    )

    assert "掌握计算机网络体系结构" in prompt
    assert '"id": "chapter-network"' in prompt
    assert '"name": "网络层"' in prompt
    assert "\\u" not in prompt
    assert '{"guidance": {"<章节id>": "复习指导文本", ...}}' in prompt


def test_build_outline_guidance_prompt_supplies_default_objective():
    prompt = build_outline_guidance_prompt("", [])

    assert "（未提供，按通用408要求）" in prompt
