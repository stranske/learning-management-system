"""Unit tests for mastery scoring policy."""

from __future__ import annotations

from math import isfinite

import pytest

from lms.evidence.models import EvidenceRecord
from lms.evidence.repository import _resolved_normalized_score
from lms.evidence.scoring import record_score
from lms.mastery.policy import MasteryEstimatorPolicy


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
    assert record_score(record) == 0.75


def test_record_score_uses_raw_over_max_when_normalized_missing() -> None:
    record = _record(raw_score=3.0, max_score=4.0, correctness=False)
    assert record_score(record) == 0.75


def test_record_score_uses_correctness_when_scores_missing() -> None:
    assert record_score(_record(correctness=True)) == 1.0
    assert record_score(_record(correctness=False)) == 0.0


def test_record_score_defaults_to_midpoint_when_no_signal() -> None:
    assert record_score(_record()) == 0.5


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


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("correctness, expected", [(True, 1.0), (False, 0.0), (None, 0.5)])
def test_record_score_rejects_nan_normalized_score(
    score: float, correctness: bool | None, expected: float
) -> None:
    result = record_score(_record(normalized_score=score, correctness=correctness))
    assert isfinite(result)
    assert result == expected


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf"), None])
def test_invalid_normalized_score_uses_finite_raw_ratio(score: float | None) -> None:
    assert record_score(_record(normalized_score=score, raw_score=3.0, max_score=4.0)) == 0.75
    assert _resolved_normalized_score(normalized_score=score, raw_score=3.0, max_score=4.0) == 0.75
    assert (
        _resolved_normalized_score(normalized_score=score, raw_score=None, max_score=None) is None
    )


@pytest.mark.parametrize(
    "raw_score, max_score",
    [
        (float("nan"), 2.0),
        (float("inf"), 2.0),
        (float("-inf"), 2.0),
        (1.0, float("nan")),
        (1.0, float("inf")),
        (1.0, float("-inf")),
        (1.0, 0.0),
        (1e308, 1e-308),
    ],
)
def test_invalid_raw_ratio_falls_back_to_correctness(raw_score: float, max_score: float) -> None:
    assert record_score(_record(raw_score=raw_score, max_score=max_score, correctness=True)) == 1.0
    assert (
        _resolved_normalized_score(normalized_score=None, raw_score=raw_score, max_score=max_score)
        is None
    )


def test_zero_normalized_score_remains_valid() -> None:
    assert record_score(_record(normalized_score=0.0, correctness=True)) == 0.0
    assert _resolved_normalized_score(normalized_score=0.0, raw_score=1.0, max_score=2.0) == 0.0
