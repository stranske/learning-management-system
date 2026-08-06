"""Gate for reference-class anchor grading.

The owner's requirement: numbers in research pieces matter for judging whether
an environment is typical or atypical, not for exact recall. These tests use
the REAL anchors drafted from the GS IPO piece so the grading contract is
pinned against material someone actually wants to remember.
"""

from __future__ import annotations

import pytest

from lms.maintenance.anchors import (
    AnchorSpec,
    Extreme,
    grade_anchor_recall,
    grade_typicality_judgment,
    parse_reading,
)
from lms.maintenance.seeds import ipo_surge_2026

IPO_COUNT = AnchorSpec.from_payload(ipo_surge_2026.ANCHOR_ITEMS[0]["payload"])
IPO_VALUATION = AnchorSpec.from_payload(ipo_surge_2026.ANCHOR_ITEMS[1]["payload"])


@pytest.mark.parametrize("answer", ["about 100", "~90", "100ish", "roughly 120 a year"])
def test_band_mode_accepts_answers_in_the_right_part_of_the_distribution(answer: str) -> None:
    """Being roughly right is the point; 90 and 120 are both fine for a ~100 median."""
    assert grade_anchor_recall(IPO_COUNT, answer).passed


@pytest.mark.parametrize("answer", ["about 250", "400", "10"])
def test_band_mode_rejects_answers_from_the_wrong_part(answer: str) -> None:
    """Boom-level or trivial answers are wrong even though they are numbers."""
    assert not grade_anchor_recall(IPO_COUNT, answer).passed


def test_precision_mode_tightens_the_requirement() -> None:
    """The same answer can pass on band and fail on exact — that is the dial."""
    # 130 is inside the typical band (75-150) but outside +/-20% of the
    # 100 median, so it separates the two looser modes cleanly.
    answer = "about 130"
    assert grade_anchor_recall(IPO_COUNT, answer, precision_mode="band").passed
    assert not grade_anchor_recall(IPO_COUNT, answer, precision_mode="approximate").passed
    assert not grade_anchor_recall(IPO_COUNT, answer, precision_mode="exact").passed
    # 115 is within tolerance, so approximate accepts it while exact does not.
    assert grade_anchor_recall(IPO_COUNT, "115", precision_mode="approximate").passed
    assert not grade_anchor_recall(IPO_COUNT, "115", precision_mode="exact").passed
    assert grade_anchor_recall(IPO_COUNT, "100", precision_mode="exact").passed


def test_explanation_supplies_the_distribution_not_just_a_verdict() -> None:
    """A wrong answer should leave the learner with the reference class."""
    result = grade_anchor_recall(IPO_COUNT, "about 300")

    assert not result.passed
    assert "median" in result.explanation
    assert "Dot-Com peak" in result.explanation
    assert "1999" in result.explanation


def test_typicality_judgment_is_the_comparative_skill() -> None:
    """Judging a reading against the distribution is the actual job skill."""
    # 2026's ~60 YTD sits below the typical band.
    assert grade_typicality_judgment(IPO_COUNT, "below normal", reading=60).passed
    # 1999's ~400 is far above it.
    assert grade_typicality_judgment(IPO_COUNT, "far above anything normal", reading=400).passed
    # And a reading at the median is typical.
    assert grade_typicality_judgment(IPO_COUNT, "pretty typical", reading=100).passed


def test_adjacent_band_earns_partial_credit() -> None:
    """Calling a far-above reading merely 'above' is a small error, not a total one."""
    near_miss = grade_typicality_judgment(IPO_COUNT, "above normal", reading=400)
    way_off = grade_typicality_judgment(IPO_COUNT, "typical", reading=400)

    assert near_miss.score == 0.5
    assert not near_miss.passed
    assert way_off.score == 0.0


def test_valuation_anchor_uses_its_own_band() -> None:
    """Each anchor carries its own distribution; 5x is normal-ish, 9x is not."""
    assert grade_typicality_judgment(IPO_VALUATION, "in line", reading=5).passed
    assert grade_typicality_judgment(IPO_VALUATION, "far above", reading=9).passed


def test_unparseable_answers_fail_informatively_rather_than_crashing() -> None:
    result = grade_anchor_recall(IPO_COUNT, "I don't remember")

    assert not result.passed
    assert result.score == 0.0
    assert "median" in result.explanation


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("~100", 100.0),
        ("about $125bn", 125.0),
        ("1.5%", 1.5),
        ("5x", 5.0),
        ("1,250", 1250.0),
        ("no number here", None),
    ],
)
def test_reading_parser_handles_how_people_actually_type(text: str, expected: float | None) -> None:
    assert parse_reading(text) == expected


def test_non_finite_values_are_rejected_at_construction() -> None:
    """NaN must never define a band — it would defeat every comparison."""
    with pytest.raises(ValueError, match="finite"):
        AnchorSpec(
            metric="broken",
            unit="x",
            central_value=float("nan"),
            statistic_type="median",
            typical_low=1,
            typical_high=2,
        )


def test_classify_rejects_non_finite_readings() -> None:
    with pytest.raises(ValueError, match="finite"):
        IPO_COUNT.classify(float("inf"))


def test_spec_round_trips_through_its_payload() -> None:
    """Stored payloads must rebuild identical specs, extremes included."""
    spec = AnchorSpec(
        metric="test",
        unit="units",
        central_value=10,
        statistic_type="mean",
        typical_low=8,
        typical_high=12,
        central_as_of="2026",
        extremes=(Extreme("peak", 30, "1999"),),
    )

    rebuilt = AnchorSpec.from_payload(spec.to_payload())

    assert rebuilt == spec


def test_seed_anchors_are_internally_consistent() -> None:
    """Every drafted anchor's central value must sit inside its own typical band.

    Cheap guard against a transcription slip in drafted items — which matters
    because the source PDF is scanned and its OCR is imperfect.
    """
    for item in ipo_surge_2026.ANCHOR_ITEMS:
        spec = AnchorSpec.from_payload(item["payload"])
        assert spec.classify(spec.central_value) == "typical", item["title"]
        for extreme in spec.extremes:
            assert (
                spec.classify(extreme.value) != "typical"
            ), f"{item['title']}: extreme {extreme.label} should not read as typical"
