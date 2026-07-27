"""内容检索向量召回记录器测试。"""

from app.modules.monitoring.vector_recalls import VectorRecallRecorder


def test_recorder_serializes_generic_qdrant_content_hits():
    recorder = VectorRecallRecorder(
        called_by="agent_rag",
        purpose="Agent RAG 内容向量召回",
        query_text="二分查找",
        subject_id="subject-ds",
    ).start()

    recorder.record_qdrant_results(
        [
            {
                "id": "point-low",
                "score": 0.61,
                "payload": {
                    "segment_id": "segment-low",
                    "entity_id": "question-low",
                    "entity_type": "question",
                    "content_preview": "低分题目",
                },
            },
            {
                "id": "point-high",
                "score": 0.93,
                "payload": {
                    "segment_id": "segment-high",
                    "entity_id": "kp-high",
                    "entity_type": "knowledge_point",
                    "title": "二分查找",
                },
            },
        ],
        threshold=0.55,
        collection_name="knowledge_segments",
    )

    assert recorder._status == "hit"
    assert recorder._result_count == 2
    assert recorder._top_score == 0.93
    assert recorder._threshold_hit is True
    assert recorder._top_results == [
        {
            "rank": 0,
            "collection": "knowledge_segments",
            "point_id": "point-high",
            "segment_id": "segment-high",
            "entity_id": "kp-high",
            "entity_type": "knowledge_point",
            "title": "二分查找",
            "score": 0.93,
        },
        {
            "rank": 1,
            "collection": "knowledge_segments",
            "point_id": "point-low",
            "segment_id": "segment-low",
            "entity_id": "question-low",
            "entity_type": "question",
            "title": "低分题目",
            "score": 0.61,
        },
    ]
