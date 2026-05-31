"""LMS scheduler policy invariants.

Properties that must hold for ANY scheduling decision, grounded directly in
``lms.scheduling.service`` (the v1 policy constants and ``_decide`` branches) --
NOT generic placeholders:

  * priority is a fraction:      0 <= priority <= 1
                                 (ReviewQueueItem.priority CHECK constraint)
  * non-negative interval:       next_interval_days >= 0
  * bounded interval:            next_interval_days <= max(SUCCESS_INTERVALS_DAYS)
                                 (the ramp caps at its last step; low-confidence
                                 and remediation are at or below 1 day)
  * non-negative repetition:     repetition_count >= 0
  * FSRS rating in range:        0 <= fsrs_rating_value <= 4
                                 (0=excluded/None, 1=again .. 4=easy)
  * signal severity in range:    0 <= signal_severity <= 2
  * reason flags are one-hot:    is_remediation + is_due_review == 1
                                 (every emitted item is exactly one of these)
  * reset == remediation:        is_reset == is_remediation
                                 (a reset IS the immediate-remediation branch)
  * fail <=> reset:              a "fail" signal (severity 0) resets and is due
                                 immediately (interval 0, priority 0.9); a
                                 non-fail never resets
  * success priority floor:      a clean success (severity 2) carries the
                                 lowest priority band (0.4) and is a due-review
  * low-confidence interval cap: a low-confidence success (severity 1) is due
                                 within LOW_CONFIDENCE_INTERVAL_DAYS (1 day)

The result type and assertion helper are shared
(``baseline_kit.InvariantResult`` / ``assert_invariants``).
"""

from __future__ import annotations

from typing import Any

from baseline_kit import InvariantResult

# Policy constants pulled from the surface so the bounds track the source.
from lms.scheduling.service import (
    LOW_CONFIDENCE_INTERVAL_DAYS,
    SUCCESS_INTERVALS_DAYS,
)

from . import adapter

_MAX_RAMP_DAYS = max(SUCCESS_INTERVALS_DAYS)
_FAIL_PRIORITY = 0.9
_SUCCESS_PRIORITY = 0.4
_EPS = 1e-9


def check_scenario(scenario: dict[str, Any]) -> list[InvariantResult]:
    """Run every policy invariant against one scenario's emitted metrics."""
    m = adapter.run_scenario(scenario)
    results: list[InvariantResult] = []

    def add(name: str, ok: bool, detail: str, severity: str = "error") -> None:
        results.append(InvariantResult(name, bool(ok), severity, detail))

    interval = m["next_interval_days"]
    priority = m["priority"]
    rep = m["repetition_count"]
    fsrs = m["fsrs_rating_value"]
    severity = m["signal_severity"]
    is_reset = m["is_reset"]
    is_rem = m["is_remediation"]
    is_due = m["is_due_review"]

    # Priority is a unit-interval fraction (table CHECK constraint).
    add("priority_in_unit_interval", -_EPS <= priority <= 1.0 + _EPS, f"priority={priority}")

    # Interval is non-negative and bounded by the ramp cap.
    add("interval_non_negative", interval >= 0, f"interval={interval}")
    add(
        "interval_le_ramp_cap",
        interval <= _MAX_RAMP_DAYS,
        f"interval={interval} cap={_MAX_RAMP_DAYS}",
    )

    # Repetition count never goes negative.
    add("repetition_non_negative", rep >= 0, f"repetition_count={rep}")

    # FSRS rating value range: 0 (excluded/None) .. 4 (easy).
    add("fsrs_rating_in_range", 0 <= fsrs <= 4, f"fsrs_rating_value={fsrs}")

    # Internal signal severity ordinal range.
    add("signal_severity_in_range", 0 <= severity <= 2, f"signal_severity={severity}")

    # Reason flags partition the outcome: exactly one of remediation / due-review.
    add(
        "reason_flags_one_hot",
        (is_rem + is_due) == 1,
        f"is_remediation={is_rem} is_due_review={is_due}",
    )

    # A reset is, by construction, the immediate-remediation branch.
    add("reset_iff_remediation", is_reset == is_rem, f"is_reset={is_reset} is_remediation={is_rem}")

    if severity == 0:
        # Failed retrieval: reset, due immediately, top priority band.
        add(
            "fail_resets_immediately",
            is_reset == 1 and interval == 0,
            f"is_reset={is_reset} interval={interval}",
        )
        add(
            "fail_priority_is_remediation_band",
            abs(priority - _FAIL_PRIORITY) <= _EPS,
            f"priority={priority} expected={_FAIL_PRIORITY}",
        )
    else:
        # Any non-fail signal is a forward-scheduled due-review (never a reset).
        add("non_fail_never_resets", is_reset == 0 and is_due == 1, f"is_reset={is_reset}")

    if severity == 1:
        # Low-confidence success: due within the documented short window.
        add(
            "low_confidence_interval_capped",
            0 < interval <= LOW_CONFIDENCE_INTERVAL_DAYS,
            f"interval={interval} cap={LOW_CONFIDENCE_INTERVAL_DAYS}",
        )

    if severity == 2:
        # Clean success: lowest priority band and a forward due-review.
        add(
            "success_priority_is_lowest_band",
            abs(priority - _SUCCESS_PRIORITY) <= _EPS,
            f"priority={priority} expected={_SUCCESS_PRIORITY}",
        )
        add("success_is_due_review", is_due == 1, f"is_due_review={is_due}")

    return results
