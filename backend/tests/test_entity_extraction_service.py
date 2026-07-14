from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.entity_extraction_service import (
    cleanup_document_entities,
    OptionIntegrityChecker,
    EntityExtractionService,
    LLMFallbackFixer,
)
from app.modules.corpus.entity_persistence import (
    QuestionPersistence,
    build_knowledge_content,
    extract_answers_from_blocks,
)
from app.modules.corpus.document_mapping import (
    DocumentChapterMappingResolver,
)
from app.modules.corpus.entity_extraction_pipeline import (
    find_uncovered_pages,
    select_knowledge_blocks,
)
from app.modules.corpus.entity_reextraction import EntityReextractionService
from app.modules.corpus.extraction_tasks import EntityExtractionRunExecutor
from app.modules.corpus.question_builder import (
    build_extraction_meta,
    build_question_tags,
    detect_stem_year,
)
from app.modules.corpus.question_pipeline import QuestionExtractionPipeline
from app.modules.corpus.knowledge_pipeline import KnowledgeExtractionPipeline
from app.models.mysql_models import CorpusFile, Document, EntityExtractionRun


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


def test_question_builder_metadata_rules():
    assert detect_stem_year("【2024】下列说法正确的是") == 2024
    assert build_question_tags("choice", 2024, True) == [
        "选择题",
        "真题",
        "2024",
    ]

    metadata = build_extraction_meta(
        blocks=[object()],
        options=[
            {"key": "A", "text": "a"},
            {"key": "B", "text": "完整选项"},
        ],
        question_type="choice",
        question_no=None,
        has_figures=False,
    )

    assert metadata["group_source"] == "single_block"
    assert metadata["option_count"] == 2
    assert metadata["few_options"] is True
    assert metadata["suspected_truncated_options"] is True
    assert metadata["missing_question_no"] is True


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
        self.prompts = []

    async def chat(self, prompt: str, purpose=None) -> str:
        self.prompts.append(prompt)
        return self._response


def _choice(no: int, labels: str, *, raw_text: str = ""):
    return {
        "id": f"q{no}",
        "question_no": str(no),
        "question_type": "choice",
        "type": "choice",
        "stem": f"{no}。题干",
        "content": f"{no}。题干",
        "raw_text": raw_text or f"{no}。题干",
        "page_no": 1,
        "options": [{"key": label, "text": f"{label}选项"} for label in labels],
        "extraction_meta": {"few_options": len(labels) < 4},
    }


@pytest.mark.asyncio
async def test_question_pipeline_saves_and_reports_consumed_blocks(
    monkeypatch,
):
    pipeline = QuestionExtractionPipeline(None)
    question = _choice(1, "ABCD")
    question["block_ids"] = ["block-1", "block-2"]
    reports = []

    async def fake_extract_raw_questions(**_kwargs):
        return [question]

    async def fake_get_llm_client():
        return None

    async def fake_save_question(saved_question):
        assert saved_question["id"] == "q1"
        return True, "saved"

    async def fake_save_diagnostic(document_id, report):
        reports.append((document_id, report))

    monkeypatch.setattr(
        pipeline,
        "extract_raw_questions",
        fake_extract_raw_questions,
    )
    monkeypatch.setattr(
        pipeline,
        "get_llm_client",
        fake_get_llm_client,
    )
    monkeypatch.setattr(
        pipeline.persistence,
        "save_question",
        fake_save_question,
    )
    monkeypatch.setattr(
        pipeline,
        "save_diagnostic_report",
        fake_save_diagnostic,
    )

    result = await pipeline.extract(
        document_id="doc-1",
        fallback_subject_id="subject-1",
        blocks=[],
        section_mappings={},
    )

    assert result["saved_count"] == 1
    assert result["unassigned"] == []
    assert result["consumed_block_ids"] == {"block-1", "block-2"}
    assert result["diagnostic"]["saved_question_count"] == 1
    assert reports[0][0] == "doc-1"


async def test_llm_fallback_uses_only_previous_target_next_questions():
    llm = _MockLLM('{"action":"none","should_merge":false}')
    questions = [_choice(no, "ABCD") for no in range(1, 6)]
    report = {
        "summary": {
            "critical_issues": [{
                "question_index": 2,
                "issue_type": "too_few",
                "missing_options": ["D"],
            }]
        }
    }

    await LLMFallbackFixer(llm).fix_remaining_issues(questions, report)

    assert len(llm.prompts) == 1
    assert "2。题干" in llm.prompts[0]
    assert "3。题干" in llm.prompts[0]
    assert "4。题干" in llm.prompts[0]
    assert "1。题干" not in llm.prompts[0]
    assert "5。题干" not in llm.prompts[0]


async def test_llm_fallback_repairs_missing_option_and_tracks_source():
    response = """{
      "action": "repair_options",
      "should_merge": false,
      "repaired_question": {
        "stem": "30。下列关于文件系统的叙述中，正确的是（）。",
        "options": [
          {"key": "A", "text": "文件系统负责文件存储空间的管理", "source": "extracted"},
          {"key": "B", "text": "B选项", "source": "extracted"},
          {"key": "C", "text": "C选项", "source": "extracted"},
          {"key": "D", "text": "D选项", "source": "extracted"}
        ]
      }
    }"""
    question = _choice(
        30,
        "BCD",
        raw_text=(
            "30。下列关于文件系统的叙述中，正确的是（）。"
            "A 文件系统负责文件存储空间的管理 B B选项 C C选项 D D选项"
        ),
    )
    question["stem"] = question["content"] = (
        "30。下列关于文件系统的叙述中，正确的是（）。"
        "A 文件系统负责文件存储空间的管理"
    )
    report = {
        "summary": {
            "critical_issues": [{
                "question_index": 0,
                "question_number": 30,
                "issue_type": "missing_start",
                "missing_options": ["A"],
            }]
        }
    }

    fixed = await LLMFallbackFixer(_MockLLM(response)).fix_remaining_issues([question], report)

    assert fixed[0]["stem"] == "30。下列关于文件系统的叙述中，正确的是（）。"
    assert [option["key"] for option in fixed[0]["options"]] == ["A", "B", "C", "D"]
    assert fixed[0]["options"][0]["source"] == "extracted"
    assert fixed[0]["fixed_by_llm"] is True
    assert fixed[0]["extraction_meta"]["fixed_by_llm"] is True
    assert fixed[0]["extraction_meta"]["original_issues"][0]["issue_type"] == "missing_start"
    assert fixed[0]["extraction_meta"]["llm_fix_actions"][0]["action"] == "repair_options"


async def test_llm_fallback_marks_option_as_ai_generated_when_not_in_source():
    response = """{
      "action": "repair_options",
      "should_merge": false,
      "repaired_question": {
        "stem": "2。题干",
        "options": [
          {"key": "A", "text": "A选项", "source": "extracted"},
          {"key": "B", "text": "B选项", "source": "extracted"},
          {"key": "C", "text": "C选项", "source": "extracted"},
          {"key": "D", "text": "LLM补出的D选项", "source": "ai_generated"}
        ]
      }
    }"""
    question = _choice(2, "ABC", raw_text="2。题干 A A选项 B B选项 C C选项")
    report = {
        "summary": {
            "critical_issues": [{
                "question_index": 0,
                "question_number": 2,
                "issue_type": "too_few",
                "missing_options": ["D"],
            }]
        }
    }

    fixed = await LLMFallbackFixer(_MockLLM(response)).fix_remaining_issues([question], report)

    generated = next(option for option in fixed[0]["options"] if option["key"] == "D")
    assert generated["source"] == "ai_generated"
    assert fixed[0]["extraction_meta"]["original_issues"][0]["missing_options"] == ["D"]


def _subjective_register_question():
    raw_text = (
        "43 （12 分） 假设有两个整数 x 和 y，分别存放在寄存器 "
        "A 和 B 中。另外，还有两个寄存器 C 和 D。"
        "请回答下列问题：（1）寄存器 A 和 B 中的内容分别是什么？"
        "（2）相加结果存放在 C 寄存器中，内容是什么？"
        "（3）相减结果存放在 D 寄存器中，内容是什么？"
    )
    return {
        "id": "q43",
        "question_no": "43",
        "question_type": "choice",
        "type": "choice",
        "stem": raw_text.split(" A 和 B 中")[0],
        "content": raw_text.split(" A 和 B 中")[0],
        "raw_text": raw_text,
        "page_no": 4,
        "options": [
            {"key": "A", "text": "和"},
            {"key": "B", "text": "中。另外，还有两个寄存器"},
            {"key": "C", "text": "和"},
        ],
        "extraction_meta": {"few_options": True, "option_count": 3},
    }


async def test_llm_fallback_restores_false_choice_without_calling_llm():
    llm = _MockLLM('{"action":"none","should_merge":false}')
    question = _subjective_register_question()
    report = {
        "summary": {
            "critical_issues": [{
                "question_index": 0,
                "question_number": 43,
                "issue_type": "too_few",
                "missing_options": ["D"],
            }]
        }
    }

    fixed = await LLMFallbackFixer(llm).fix_remaining_issues(
        [question],
        report,
    )

    assert llm.prompts == []
    assert fixed[0]["question_type"] == "short_answer"
    assert fixed[0]["type"] == "short_answer"
    assert fixed[0]["options"] == []
    assert fixed[0]["stem"] == fixed[0]["raw_text"]
    assert fixed[0]["extraction_meta"]["few_options"] is False
    correction = fixed[0]["extraction_meta"]["structure_corrections"][0]
    assert correction["discarded_option_labels"] == ["A", "B", "C"]


def test_llm_fallback_uses_subjective_repair_prompt():
    question = _subjective_register_question()
    prompt = LLMFallbackFixer(_MockLLM(""))._build_fix_prompt(
        [question],
        target_idx=0,
        issue={"issue_type": "duplicate"},
    )

    assert "教材主观题结构分析专家" in prompt
    assert "repair_subjective" in prompt
    assert "不得生成选择题选项" in prompt
    assert "ai_generated" not in prompt


def test_llm_fallback_parses_subjective_repair_compatibly():
    response = """{
      "action": "fix_subjective",
      "should_merge": false,
      "repaired_question": {
        "stem": "43。完整主观题",
        "question_type": "short_answer",
        "options": []
      }
    }"""

    result = LLMFallbackFixer(
        _MockLLM(response)
    )._parse_llm_fix_result(response)

    assert result["action"] == "repair_subjective"


def test_llm_fallback_rejects_option_repair_for_subjective_question():
    question = _subjective_register_question()
    fixer = LLMFallbackFixer(_MockLLM(""))

    fixed = fixer._apply_llm_fix(
        [question],
        index=0,
        context_start=0,
        fix_action={
            "action": "repair_options",
            "issue": {
                "issue_type": "too_few",
                "missing_options": ["D"],
            },
            "repaired_question": {
                "stem": question["raw_text"],
                "options": [{"key": "D", "text": "错误生成的选项"}],
            },
        },
    )

    assert fixed[0]["question_type"] == "choice"
    assert [item["key"] for item in fixed[0]["options"]] == [
        "A",
        "B",
        "C",
    ]
    assert fixed[0].get("fixed_by_llm") is None


def test_normalize_options_preserves_llm_option_source():
    normalized = EntityExtractionService(None)._normalize_options([
        {"key": "D", "text": "AI 补充选项", "source": "ai_generated"},
    ])

    assert normalized[0]["source"] == "ai_generated"


def test_extract_answers_from_blocks_reads_only_answer_zone():
    blocks = [
        SimpleNamespace(content_text="1. A 题干内容", content_md=None),
        SimpleNamespace(content_text="参考答案 1.B 2、CD", content_md=None),
        SimpleNamespace(content_text="3：对 4) 错", content_md=None),
    ]

    assert extract_answers_from_blocks(blocks) == {
        "1": "B",
        "2": "CD",
        "3": "对",
        "4": "错",
    }


def test_extract_answers_from_blocks_requires_answer_header():
    blocks = [
        SimpleNamespace(content_text="1.B 2.C", content_md=None),
    ]

    assert extract_answers_from_blocks(blocks) == {}


def test_build_knowledge_content_prefers_markdown_and_skips_empty_blocks():
    blocks = [
        SimpleNamespace(content_md="  第一段 **正文**  ", content_text="第一段"),
        SimpleNamespace(content_md=None, content_text="  第二段正文  "),
        SimpleNamespace(content_md="", content_text="   "),
    ]

    assert build_knowledge_content(blocks) == "第一段 **正文**\n\n第二段正文"


@pytest.mark.asyncio
async def test_knowledge_pipeline_groups_by_title_and_resolves_mapping(
    monkeypatch,
):
    pipeline = KnowledgeExtractionPipeline(None)
    saved_groups = []

    async def fake_save_knowledge_point(**kwargs):
        saved_groups.append(kwargs)
        return True

    monkeypatch.setattr(
        pipeline.persistence,
        "save_knowledge_point",
        fake_save_knowledge_point,
    )
    blocks = [
        SimpleNamespace(
            id="title-1",
            page_no=1,
            block_type="heading",
            content_text="知识点一",
        ),
        SimpleNamespace(
            id="content-1",
            page_no=1,
            block_type="paragraph",
            content_text="正文一",
        ),
        SimpleNamespace(
            id="content-2",
            page_no=2,
            block_type="list",
            content_text="正文二",
        ),
        SimpleNamespace(
            id="title-2",
            page_no=3,
            block_type="title",
            content_text="知识点二",
        ),
        SimpleNamespace(
            id="content-3",
            page_no=3,
            block_type="paragraph",
            content_text="正文三",
        ),
    ]
    mappings = {
        1: {"chapter_id": "chapter-1"},
        3: {"chapter_id": "chapter-3"},
    }

    saved_count = await pipeline.extract(
        document_id="doc-1",
        fallback_subject_id="subject-1",
        blocks=blocks,
        section_mappings=mappings,
    )

    assert saved_count == 2
    assert [
        group["mapping_info"]["chapter_id"]
        for group in saved_groups
    ] == ["chapter-1", "chapter-3"]
    assert [
        block.id
        for block in saved_groups[0]["content_blocks"]
    ] == ["content-1", "content-2"]


def test_document_chapter_mapping_resolves_nearest_page():
    mappings = {
        3: {"chapter_id": "chapter-3"},
        8: {"chapter_id": "chapter-8"},
    }

    assert DocumentChapterMappingResolver.resolve(3, mappings) == mappings[3]
    assert DocumentChapterMappingResolver.resolve(6, mappings) == mappings[3]
    assert DocumentChapterMappingResolver.resolve(1, mappings) == mappings[3]
    assert DocumentChapterMappingResolver.resolve(None, mappings) is None


def test_document_pipeline_selects_remaining_knowledge_blocks():
    blocks = [
        SimpleNamespace(id="question", page_no=1),
        SimpleNamespace(id="knowledge", page_no=2),
        SimpleNamespace(id="unknown", page_no=3),
    ]

    selected = select_knowledge_blocks(
        blocks,
        consumed_block_ids={"question"},
        block_label_by_id={"knowledge": "knowledge"},
    )
    fallback = select_knowledge_blocks(
        blocks,
        consumed_block_ids={"question"},
        block_label_by_id={},
    )

    assert [block.id for block in selected] == ["knowledge"]
    assert [block.id for block in fallback] == ["knowledge", "unknown"]
    assert find_uncovered_pages(
        blocks,
        section_mappings={1: {}, 3: {}},
    ) == [2]


@pytest.mark.asyncio
async def test_link_extracted_answers_only_fills_empty_answers():
    empty_answer = SimpleNamespace(
        question_no="1",
        answer="",
        answer_source="none",
    )
    existing_answer = SimpleNamespace(
        question_no="2",
        answer="A",
        answer_source="manual",
    )

    class _ScalarResult:
        def scalars(self):
            return self

        def all(self):
            return [empty_answer, existing_answer]

    class _AnswerSession:
        flush_count = 0

        async def execute(self, _query):
            return _ScalarResult()

        async def flush(self):
            self.flush_count += 1

    session = _AnswerSession()
    linked = await QuestionPersistence(session).link_extracted_answers(
        "doc-1",
        [
            SimpleNamespace(
                content_text="参考答案 1.B 2.C",
                content_md=None,
            )
        ],
    )

    assert linked == 1
    assert empty_answer.answer == "B"
    assert empty_answer.answer_source == "extracted"
    assert existing_answer.answer == "A"
    assert existing_answer.answer_source == "manual"
    assert session.flush_count == 1


def test_question_diagnostic_counts_unassigned_question_as_saved():
    service = EntityExtractionService(None)

    diagnostic = service._build_question_extraction_diagnostic(
        raw_questions=[{"id": "q1", "page_no": 1}],
        final_questions=[{"id": "q1", "page_no": 1}],
        validation_report={},
        final_report={},
        saved_results=[{
            "question_id": "q1",
            "page_no": 1,
            "saved": True,
            "reason": "saved_unassigned",
        }],
    )

    assert diagnostic["saved_question_count"] == 1
    assert diagnostic["skipped_question_count"] == 0
    assert diagnostic["save_reasons"] == {"saved_unassigned": 1}


class _RunSession:
    def __init__(self, run, document=None, corpus_file=None):
        self.run = run
        self.document = document
        self.corpus_file = corpus_file
        self.commit_count = 0
        self.rollback_count = 0

    async def get(self, model, record_id):
        if model is EntityExtractionRun and record_id == self.run.id:
            return self.run
        if model is Document and self.document and record_id == self.document.id:
            return self.document
        if model is CorpusFile and self.corpus_file and record_id == self.corpus_file.id:
            return self.corpus_file
        return None

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1


@pytest.mark.asyncio
async def test_extraction_run_persists_success(monkeypatch):
    run = SimpleNamespace(
        id="run-1",
        document_id="doc-1",
        extract_knowledge=True,
        extract_questions=True,
        subject_id="subject-1",
        status="running",
        knowledge_count=0,
        question_count=0,
        result_json=None,
        error_detail=None,
        completed_at=None,
    )
    document = SimpleNamespace(id="doc-1", corpus_file_id="file-1")
    corpus_file = SimpleNamespace(
        id="file-1",
        status="parsed",
        error_detail="previous error",
    )
    session = _RunSession(run, document, corpus_file)

    async def fake_extract_entities(**kwargs):
        assert kwargs["document_id"] == "doc-1"
        return {"knowledge_count": 3, "question_count": 4}

    async def fake_index_document_entities(**kwargs):
        assert kwargs == {
            "document_id": "doc-1",
            "include_knowledge": True,
            "include_questions": True,
        }
        return {
            "knowledge_segments": {"segments_count": 6},
            "question_segments": {"segments_count": 8},
        }

    executor = EntityExtractionRunExecutor(
        session,
        pipeline=SimpleNamespace(extract=fake_extract_entities),
    )
    monkeypatch.setattr(
        executor,
        "index_document_entities",
        fake_index_document_entities,
    )

    result = await executor.execute("run-1")

    assert result == {
        "knowledge_count": 3,
        "question_count": 4,
        "indexing": {
            "knowledge_segments": {"segments_count": 6},
            "question_segments": {"segments_count": 8},
        },
    }
    assert run.status == "success"
    assert run.knowledge_count == 3
    assert run.question_count == 4
    assert run.result_json == result
    assert run.completed_at is not None
    assert corpus_file.status == "indexed"
    assert corpus_file.error_detail is None
    assert session.commit_count == 2
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_extraction_run_persists_failure(monkeypatch):
    run = SimpleNamespace(
        id="run-2",
        document_id="doc-2",
        extract_knowledge=False,
        extract_questions=True,
        subject_id=None,
        status="running",
        knowledge_count=0,
        question_count=0,
        result_json=None,
        error_detail=None,
        completed_at=None,
    )
    document = SimpleNamespace(id="doc-2", corpus_file_id="file-2")
    corpus_file = SimpleNamespace(id="file-2", status="parsed", error_detail=None)
    session = _RunSession(run, document, corpus_file)

    async def fake_extract_entities(**_kwargs):
        raise RuntimeError("LLM timeout")

    executor = EntityExtractionRunExecutor(
        session,
        pipeline=SimpleNamespace(extract=fake_extract_entities),
    )

    with pytest.raises(RuntimeError, match="LLM timeout"):
        await executor.execute("run-2")

    assert run.status == "failed"
    assert run.error_detail == "LLM timeout"
    assert run.completed_at is not None
    assert corpus_file.status == "failed"
    assert corpus_file.error_detail == "LLM timeout"
    assert session.rollback_count == 1
    assert session.commit_count == 2


@pytest.mark.asyncio
async def test_extraction_run_fails_when_indexing_fails(monkeypatch):
    run = SimpleNamespace(
        id="run-3",
        document_id="doc-3",
        extract_knowledge=True,
        extract_questions=False,
        subject_id=None,
        status="running",
        knowledge_count=0,
        question_count=0,
        result_json=None,
        error_detail=None,
        completed_at=None,
    )
    document = SimpleNamespace(id="doc-3", corpus_file_id="file-3")
    corpus_file = SimpleNamespace(id="file-3", status="parsed", error_detail=None)
    session = _RunSession(run, document, corpus_file)

    async def fake_extract_entities(**_kwargs):
        return {"knowledge_count": 2, "question_count": 0}

    async def fake_index_document_entities(**_kwargs):
        raise RuntimeError("Qdrant unavailable")

    executor = EntityExtractionRunExecutor(
        session,
        pipeline=SimpleNamespace(extract=fake_extract_entities),
    )
    monkeypatch.setattr(
        executor,
        "index_document_entities",
        fake_index_document_entities,
    )

    with pytest.raises(RuntimeError, match="Qdrant unavailable"):
        await executor.execute("run-3")

    assert run.status == "failed"
    assert run.error_detail == "Qdrant unavailable"
    assert corpus_file.status == "failed"
    assert corpus_file.error_detail == "Qdrant unavailable"
    assert session.rollback_count == 1
    assert session.commit_count == 2


@pytest.mark.asyncio
async def test_entity_reextraction_run_updates_only_target_task(monkeypatch):
    run = SimpleNamespace(
        id="run-entity-1",
        document_id="doc-1",
        scope="entity",
        target_entity_type="question",
        target_entity_id="question-43",
        extract_knowledge=False,
        extract_questions=True,
        subject_id="subject-1",
        status="running",
        knowledge_count=0,
        question_count=0,
        result_json=None,
        error_detail=None,
        completed_at=None,
    )
    document = SimpleNamespace(id="doc-1", corpus_file_id="file-1")
    corpus_file = SimpleNamespace(
        id="file-1",
        status="indexed",
        error_detail=None,
    )
    session = _RunSession(run, document, corpus_file)

    async def fake_reextract(**kwargs):
        assert kwargs == {
            "document_id": "doc-1",
            "entity_type": "question",
            "entity_id": "question-43",
        }
        return {
            "document_id": "doc-1",
            "entity_type": "question",
            "entity_id": "question-43",
            "knowledge_count": 0,
            "question_count": 1,
        }

    async def fake_index_entity(**kwargs):
        assert kwargs == {
            "entity_type": "question",
            "entity_id": "question-43",
        }
        return {"segments_count": 1}

    executor = EntityExtractionRunExecutor(
        session,
        entity_reextraction=SimpleNamespace(reextract=fake_reextract),
    )
    monkeypatch.setattr(executor, "index_entity", fake_index_entity)
    set_status = AsyncMock()
    monkeypatch.setattr(executor, "set_corpus_file_status", set_status)

    result = await executor.execute(run.id)

    assert result["question_count"] == 1
    assert result["indexing"] == {"segments_count": 1}
    assert run.status == "success"
    assert run.question_count == 1
    assert corpus_file.status == "indexed"
    set_status.assert_not_awaited()


def test_reextraction_selects_question_by_number_then_source_overlap():
    target_blocks = {"target-1", "target-2"}
    candidates = [
        {
            "id": "new-42",
            "question_no": "42",
            "block_ids": ["previous"],
        },
        {
            "id": "new-43",
            "question_no": "43",
            "block_ids": ["target-1"],
        },
        {
            "id": "new-44",
            "question_no": "44",
            "block_ids": ["target-2", "next"],
        },
    ]

    selected = EntityReextractionService.select_question_candidate(
        candidates,
        target_question_no="43",
        target_block_ids=target_blocks,
    )

    assert selected["id"] == "new-43"


def test_reextraction_falls_back_to_highest_source_overlap():
    candidates = [
        {"id": "weak", "question_no": None, "block_ids": ["target-1"]},
        {
            "id": "strong",
            "question_no": None,
            "block_ids": ["target-1", "target-2"],
        },
    ]

    selected = EntityReextractionService.select_question_candidate(
        candidates,
        target_question_no=None,
        target_block_ids={"target-1", "target-2"},
    )

    assert selected["id"] == "strong"


class _CleanupResult:
    def all(self):
        return [("question-1",)]


class _CleanupSession:
    async def execute(self, _statement):
        return _CleanupResult()


@pytest.mark.asyncio
async def test_cleanup_document_entities_deletes_qdrant_segments(monkeypatch):
    deleted = []

    async def fake_cleanup_entity_links(*_args, **_kwargs):
        return None

    async def fake_delete_entity_segments(
        _service,
        entity_type,
        entity_ids,
    ):
        deleted.append((entity_type, entity_ids))

    monkeypatch.setattr(
        "app.services.entity_asset_service.cleanup_entity_links",
        fake_cleanup_entity_links,
    )
    monkeypatch.setattr(
        "app.modules.retrieval.segment_service.SegmentService.delete_entity_segments",
        fake_delete_entity_segments,
    )

    removed = await cleanup_document_entities(
        _CleanupSession(),
        document_id="doc-1",
        entity_type="question",
    )

    assert removed == {"question": 1}
    assert deleted == [("question", ["question-1"])]


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
