from pydantic_ai.messages import ModelResponse, ToolCallPart

from app.modules.agent.model_runtime.config import _audit_model_response
from app.modules.agent.tools.retrieve_knowledge import _normalize_agent_result
from app.modules.agent.workflows.explain import _render_artifact_node
from app.modules.agent.workflows.contracts import ExecutionContext


def test_retrieval_result_decodes_literal_unicode_escapes():
    result = _normalize_agent_result(
        {
            "entity_id": "kp_udp",
            "entity_type": "knowledge_point",
            "content_text": r"UDP \u662f\u65e0\u8fde\u63a5\u534f\u8bae",
            "context_text": r"\u4f20\u8f93\u5c42",
        }
    )

    assert result["content_text"] == "UDP 是无连接协议"
    assert result["context_text"] == "传输层"


def test_retrieval_result_decodes_nested_titles_and_source_labels():
    result = _normalize_agent_result(
        {
            "entity_id": "question_udp",
            "entity_type": "question",
            "title": r"UDP \u7ec3\u4e60\u9898",
            "entity": {"title": r"\u4f20\u8f93\u5c42\u9898\u76ee"},
            "source": {"filename": r"\u8ba1\u7b97\u673a\u7f51\u7edc.pdf"},
            "question_meta": {"paper_name": r"\u6a21\u62df\u5377"},
        }
    )

    assert result["entity_title"] == "UDP 练习题"
    assert result["entity"]["title"] == "传输层题目"
    assert result["source"]["filename"] == "计算机网络.pdf"
    assert result["question_meta"]["paper_name"] == "模拟卷"


def test_audit_uses_structured_tool_arguments_when_model_has_no_text_part():
    response = ModelResponse(
        parts=[ToolCallPart("final_result", {"content": "UDP 讲解"})]
    )

    text, full = _audit_model_response(response)

    assert "UDP 讲解" in text
    assert full["parts"][0]["part_kind"] == "tool-call"


async def test_explanation_artifact_precedes_body_with_knowledge_sources():
    context = ExecutionContext(
        run_id="run_rag_source",
        user_id="user_1",
        db=None,
    )
    context.set("input_message", "讲解 UDP")
    context.set(
        "explanation",
        {
            "body": "## UDP 正文",
            "citations": [{"title": "UDP 知识点"}, {"title": "传输层章节"}],
            "outline": [],
            "summary": "UDP 是无连接协议。",
        },
    )

    result = await _render_artifact_node(context, None)

    content = result.artifact["content"]
    assert content.startswith("## 本次知识库检索来源")
    assert "- UDP 知识点" in content
    assert content.endswith("## UDP 正文")
