"""The coercions and validators behind a capability estimate.

A capability estimate is a claim about what a learner can do, computed from evidence rows whose
fields arrive as JSON — so every value passes through a coercion before it reaches the arithmetic.
None of those coercions were tested, and each has a failure mode that changes a score rather than
raising: a string that silently becomes 0, a boolean that becomes 1.0, a weighted average over
zero total weight.

The validators beside them are ownership and scope guards. Those decide whose evidence counts
toward whose target, which is the one property in this module where being wrong is not a bad
number but a wrong learner.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from lms.capability.repository import (
    CAPABILITY_TARGET_STATUSES,
    MAINTENANCE_PLAN_STATUSES,
    _as_bool,
    _as_float,
    _as_int,
    _coverage_factor,
    _json_safe,
    _normalized_strings,
    _require_confidence_threshold,
    _require_maintenance_plan_status,
    _require_personal_scope,
    _require_status,
)

# ---------------------------------------------------------------------------------------------
# Numeric coercion.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [(3, 3), (3.9, 3), ("4", 4), ("4.7", 4), (0, 0), (-2, -2)])
def test_an_evidence_count_is_truncated_not_rounded(raw, expected):
    """`int(float(x))` truncates. 3.9 evidence records is 3, and rounding it to 4 would credit a
    record that does not exist."""
    assert _as_int(raw) == expected


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "1e400"])
def test_a_non_finite_count_reads_as_zero_rather_than_raising(raw):
    """`int(float("inf"))` raises OverflowError and `float("nan")` raises ValueError — both from
    inside a coverage calculation, where the only correct answer is "no evidence"."""
    assert _as_int(raw) == 0


@pytest.mark.parametrize("raw", ["x", "", None, [1], {"a": 1}, object()])
def test_an_uncoercible_count_reads_as_zero(raw):
    assert _as_int(raw) == 0


@pytest.mark.parametrize("raw", [True, False])
def test_a_boolean_is_not_counted_as_evidence(raw):
    """`bool` is a subclass of `int`, so `True` would otherwise count as one evidence record —
    turning a flag stored in the wrong field into a covered node."""
    assert _as_int(raw) == 0


@pytest.mark.parametrize("raw,expected", [(3, 3.0), (3.5, 3.5), ("4.5", 4.5), ("0", 0.0)])
def test_a_score_is_coerced_to_float(raw, expected):
    assert _as_float(raw) == expected


@pytest.mark.parametrize("raw", [None, [1], {"a": 1}, object()])
def test_an_uncoercible_score_reads_as_zero(raw):
    assert _as_float(raw) == 0.0


def test_the_two_coercions_disagree_about_booleans_and_that_is_the_current_behaviour():
    """`_as_int` excludes `bool` by name; `_as_float` does not, so `True` becomes a perfect 1.0
    score while becoming zero evidence.

    Pinned rather than quietly aligned: making them agree changes computed scores wherever a
    boolean reaches a score field, and that is a decision with data consequences rather than a
    tidy-up. The test exists so the divergence is visible and any change to it is deliberate.
    """
    assert _as_int(True) == 0
    assert _as_float(True) == 1.0


# ---------------------------------------------------------------------------------------------
# Boolean coercion.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", " Yes ", "y", "YES"])
def test_the_documented_truthy_spellings_are_accepted(raw):
    assert _as_bool(raw) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "n", "", "   ", "maybe"])
def test_everything_else_is_false(raw):
    assert _as_bool(raw) is False


@pytest.mark.parametrize("raw", [1, 0, None, [], {"a": 1}])
def test_a_non_string_non_bool_is_false_rather_than_truthy(raw):
    """`1` is not accepted, while `"1"` is. Treating a bare int as truthy would make any non-zero
    count read as a flag."""
    assert _as_bool(raw) is False


def test_an_actual_boolean_passes_through():
    assert _as_bool(True) is True
    assert _as_bool(False) is False


# ---------------------------------------------------------------------------------------------
# Coverage.
# ---------------------------------------------------------------------------------------------


def test_a_target_with_nothing_to_cover_scores_zero_not_one():
    """`0/0` is the tempting "everything covered" answer, and it is the wrong one: a target with
    no nodes and no competencies has no evidence, so claiming full coverage would mark an empty
    target complete."""
    assert _coverage_factor(node_rows=[], competency_rows=[]) == 0.0


def test_coverage_counts_rows_with_evidence_over_all_rows():
    node_rows = [{"evidence_count": 2}, {"evidence_count": 0}]
    competency_rows = [{"evidence_count": 1}, {"evidence_count": 0}]
    assert _coverage_factor(node_rows=node_rows, competency_rows=competency_rows) == 0.5


def test_nodes_and_competencies_are_weighted_equally():
    """One denominator over both. Counting them separately and averaging would let a target with
    one node and ten competencies be half-covered by that single node."""
    one_node = _coverage_factor(node_rows=[{"evidence_count": 1}], competency_rows=[])
    node_plus_empty_competency = _coverage_factor(
        node_rows=[{"evidence_count": 1}], competency_rows=[{"evidence_count": 0}]
    )
    assert one_node == 1.0
    assert node_plus_empty_competency == 0.5


def test_coverage_is_rounded_to_four_places():
    """Three rows out of seven is a repeating decimal; an unrounded float would make two runs
    over identical evidence produce different stored values."""
    rows = [{"evidence_count": 1}] * 3 + [{"evidence_count": 0}] * 4
    assert _coverage_factor(node_rows=rows, competency_rows=[]) == 0.4286


def test_a_string_evidence_count_still_counts():
    """Counts arrive from JSON, where a number may be a string."""
    assert _coverage_factor(node_rows=[{"evidence_count": "2"}], competency_rows=[]) == 1.0


# ---------------------------------------------------------------------------------------------
# Validators.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0.0, 0.25, 0.5, 1.0])
def test_a_confidence_threshold_in_range_is_accepted(value):
    _require_confidence_threshold(value)


@pytest.mark.parametrize("value", [-0.1, 1.1, 100.0, -1.0])
def test_a_confidence_threshold_outside_zero_to_one_is_refused(value):
    """A threshold of 100 means somebody typed a percentage, and a target that can never be met
    reads as a stalled learner rather than a mistyped setting."""
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        _require_confidence_threshold(value)


@pytest.mark.parametrize("status", CAPABILITY_TARGET_STATUSES)
def test_every_declared_target_status_is_accepted(status):
    _require_status(status)


def test_an_unknown_target_status_is_refused_with_the_options_listed():
    """A typo'd status would otherwise reach a filter and match nothing, which looks like an empty
    result rather than a bad query."""
    with pytest.raises(ValueError) as excinfo:
        _require_status("activ")

    message = str(excinfo.value)
    assert "activ" in message
    for status in CAPABILITY_TARGET_STATUSES:
        assert status in message


@pytest.mark.parametrize("status", MAINTENANCE_PLAN_STATUSES)
def test_every_declared_plan_status_is_accepted(status):
    _require_maintenance_plan_status(status)


def test_an_unknown_plan_status_is_refused_with_the_options_listed():
    with pytest.raises(ValueError) as excinfo:
        _require_maintenance_plan_status("done")

    message = str(excinfo.value)
    assert "done" in message
    for status in MAINTENANCE_PLAN_STATUSES:
        assert status in message


def test_the_two_status_vocabularies_are_not_interchangeable():
    """`completed` is a plan status and not a target status. A single shared check would accept
    either everywhere, and the mismatch would only surface as a filter returning nothing."""
    _require_maintenance_plan_status("completed")
    with pytest.raises(ValueError):
        _require_status("completed")


def test_only_personal_scope_is_supported():
    _require_personal_scope("personal")
    with pytest.raises(ValueError, match="ownership_scope='personal'"):
        _require_personal_scope("shared")


# ---------------------------------------------------------------------------------------------
# Evidence-type normalisation.
# ---------------------------------------------------------------------------------------------


def test_evidence_types_are_stripped_and_blanks_dropped():
    assert _normalized_strings([" attempt ", "review", "", "   "]) == ["attempt", "review"]


def test_order_is_preserved():
    """These are requirements, and a reordered list reads as a different requirement set in any
    diff of the stored target."""
    assert _normalized_strings(["review", "attempt", "quiz"]) == ["review", "attempt", "quiz"]


def test_duplicates_are_refused_after_stripping():
    """`"attempt"` and `" attempt "` are the same requirement. Accepting both would make a target
    demand the same evidence twice, which no learner can satisfy differently."""
    with pytest.raises(ValueError, match="must not contain duplicates"):
        _normalized_strings(["attempt", " attempt "])


def test_an_empty_list_is_allowed():
    """No required evidence types is a valid target; only a contradictory list is not."""
    assert _normalized_strings([]) == []
    assert _normalized_strings(["", "  "]) == []


# ---------------------------------------------------------------------------------------------
# JSON safety for the stored breakdown.
# ---------------------------------------------------------------------------------------------


def test_dates_and_datetimes_become_iso_strings():
    """The breakdown is stored as JSON. A `date` reaching the serializer raises at write time,
    long after the estimate was computed."""
    converted = _json_safe({"as_of": date(2026, 1, 1), "at": datetime(2026, 1, 1, 12, 30)})
    assert converted == {"as_of": "2026-01-01", "at": "2026-01-01T12:30:00"}


def test_nested_structures_are_converted_throughout():
    converted = _json_safe(
        {"rows": [{"at": date(2026, 1, 1)}], "n": {"m": {"at": date(2026, 2, 2)}}}
    )
    assert converted["rows"] == [{"at": "2026-01-01"}]
    assert converted["n"] == {"m": {"at": "2026-02-02"}}


def test_non_string_keys_become_strings():
    """JSON objects have string keys; an int key would round-trip as a different key."""
    assert _json_safe({1: "a"}) == {"1": "a"}


@pytest.mark.parametrize("value", [[1, 2], "a string", 42, None])
def test_a_breakdown_that_is_not_an_object_is_refused(value):
    """The column holds an object. A list stored there parses back as a list, and every reader
    that does `breakdown.get(...)` fails far from here."""
    with pytest.raises(TypeError, match="must be a JSON object"):
        _json_safe(value)
