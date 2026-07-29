"""阶段六薄弱点 finding 的确定性投影边界。"""

from datetime import datetime, timedelta

from app.modules.agent.weakness_projector import WeaknessProjector

NOW = datetime(2026, 7, 29, 12, 0, 0)


def _record(**overrides):
    payload = {
        "source_id": "evidence-1",
        "source_type": "agent_grade",
        "evidence_type": "objective_assessment",
        "evidence_outcome": "incorrect",
        "evidence_strength": 1.0,
        "assessment_confidence": 0.95,
        "knowledge_point_ids": ["kp-binary"],
        "knowledge_point_coverage": {"kp-binary": 1.0},
        "occurred_at": NOW,
        "error_tags": ["misconception"],
    }
    payload.update(overrides)
    return payload


def test_incorrect_verdict_projects_confirmed_finding_with_reason_and_sources():
    finding = WeaknessProjector().project(
        [_record()],
        now=NOW + timedelta(hours=1),
        knowledge_point_titles={"kp-binary": "二分查找"},
    )[0]

    assert finding.status == "confirmed"
    assert finding.knowledge_point_id == "kp-binary"
    assert finding.title == "二分查找"
    assert finding.reason_code == "misconception"
    assert finding.error_tags == ["misconception"]
    assert finding.evidence_ids == ["evidence-1"]
    assert finding.evidence_sources[0]["evidence_outcome"] == "incorrect"


def test_exposure_or_observation_only_needs_diagnostic_and_is_not_confirmed():
    findings = WeaknessProjector().project(
        [
            _record(
                source_id="exposure-1",
                source_type="agent_discussion",
                evidence_type="exposure",
                evidence_outcome="unknown",
                evidence_strength=0.0,
                assessment_confidence=0.86,
                error_tags=[],
                diagnostic_need=True,
            )
        ],
        now=NOW,
        knowledge_point_titles={"kp-binary": "二分查找"},
    )

    assert len(findings) == 1
    assert findings[0].status == "needs_diagnostic"
    assert findings[0].wrong_count == 0
    assert (
        findings[0].recommended_review_reason
        == "只有主题暴露或困惑假设，先做一道独立诊断题"
    )


def test_later_correct_answer_keeps_history_and_enters_interval_verification():
    finding = WeaknessProjector().project(
        [
            _record(source_id="wrong-1", occurred_at=NOW - timedelta(days=2)),
            _record(
                source_id="correct-1",
                evidence_outcome="correct",
                error_tags=[],
                occurred_at=NOW - timedelta(hours=1),
            ),
        ],
        now=NOW,
    )[0]

    assert finding.status == "awaiting_interval_verification"
    assert finding.wrong_count == 1
    assert finding.positive_count == 1
    assert finding.last_wrong_at is not None


def test_old_negative_evidence_has_time_decay_but_remains_a_confirmed_history():
    fresh = WeaknessProjector().project([_record()], now=NOW)[0]
    old = WeaknessProjector().project(
        [_record(occurred_at=NOW - timedelta(days=90))],
        now=NOW,
    )[0]

    assert fresh.status == "confirmed"
    assert old.status == "confirmed"
    assert old.severity < fresh.severity
