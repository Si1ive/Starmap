from types import SimpleNamespace

import pytest

from app.services.entity_extraction_service import (
    cleanup_document_entities,
    OptionIntegrityChecker,
    EntityExtractionService,
    LLMFallbackFixer,
)
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


def test_normalize_options_preserves_llm_option_source():
    normalized = EntityExtractionService(None)._normalize_options([
        {"key": "D", "text": "AI 补充选项", "source": "ai_generated"},
    ])

    assert normalized[0]["source"] == "ai_generated"


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
    service = EntityExtractionService(session)

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

    monkeypatch.setattr(service, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(
        service,
        "_index_document_entities",
        fake_index_document_entities,
    )

    result = await service.extract_entities_with_run_id("run-1")

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
    service = EntityExtractionService(session)

    async def fake_extract_entities(**_kwargs):
        raise RuntimeError("LLM timeout")

    monkeypatch.setattr(service, "extract_entities", fake_extract_entities)

    with pytest.raises(RuntimeError, match="LLM timeout"):
        await service.extract_entities_with_run_id("run-2")

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
    service = EntityExtractionService(session)

    async def fake_extract_entities(**_kwargs):
        return {"knowledge_count": 2, "question_count": 0}

    async def fake_index_document_entities(**_kwargs):
        raise RuntimeError("Qdrant unavailable")

    monkeypatch.setattr(service, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(
        service,
        "_index_document_entities",
        fake_index_document_entities,
    )

    with pytest.raises(RuntimeError, match="Qdrant unavailable"):
        await service.extract_entities_with_run_id("run-3")

    assert run.status == "failed"
    assert run.error_detail == "Qdrant unavailable"
    assert corpus_file.status == "failed"
    assert corpus_file.error_detail == "Qdrant unavailable"
    assert session.rollback_count == 1
    assert session.commit_count == 2


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
        "app.services.segment_service.SegmentService.delete_entity_segments",
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
