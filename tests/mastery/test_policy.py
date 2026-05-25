"""Unit tests for mastery scoring policy."""

from __future__ import annotations

from lms.evidence.models import EvidenceRecord
from lms.mastery.policy import MasteryEstimatorPolicy, _record_score


def _record(**overrides: object) -> EvidenceRecord:
    base: dict[str, object] = {
        "learner_id": "learner-1",
        "knowledge_node_id": "node-1",
        "prompt_id": "prompt-1",
    }
    base.update(overrides)
    return EvidenceRecord(**base)


def test_record_score_prefers_normalized_score() -> None:
    record = _record(normalized_score=0.75, raw_score=1.0, max_score=2.0, correctness=False)
    assert _record_score(record) == 0.75


def test_record_score_uses_raw_over_max_when_normalized_missing() -> None:
    record = _record(raw_score=3.0, max_score=4.0, correctness=False)
    assert _record_score(record) == 0.75


def test_record_score_uses_correctness_when_scores_missing() -> None:
    assert _record_score(_record(correctness=True)) == 1.0
    assert _record_score(_record(correctness=False)) == 0.0


def test_record_score_defaults_to_midpoint_when_no_signal() -> None:
    assert _record_score(_record()) == 0.5


def test_estimate_returns_zeroes_when_no_records() -> None:
    policy = MasteryEstimatorPolicy()
    assert policy.estimate([]) == (0.0, 0.0)


def test_estimate_applies_recency_weighting_and_confidence_growth() -> None:
    policy = MasteryEstimatorPolicy()
    records = [
        _record(correctness=False),
        _record(correctness=False),
        _record(correctness=True),
    ]

    mastery, confidence = policy.estimate(records)

    assert mastery == 0.3768
    assert confidence == 0.71
