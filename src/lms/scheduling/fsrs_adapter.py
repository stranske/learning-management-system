"""Map evidence records to deterministic FSRS-style ratings."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from lms.evidence.models import EvidenceRecord


@dataclass(frozen=True)
class FSRSRating:
    """A scheduler-ready rating; scheduling_included gates every FSRS mutation."""

    label: str
    value: int | None
    scheduling_included: bool
    rule_id: str
    reason: str


@dataclass(frozen=True)
class FSRSRule:
    """Data-driven rule row for the v1 placeholder adapter."""

    rule_id: str
    rating: str
    value: int | None
    scheduling_included: bool
    reason: str
    applies: Callable[[EvidenceRecord], bool]


TRANSFER_EXCLUDED_DISTANCES = frozenset({"near", "far", "novel"})
LOW_CONFIDENCE_MAX = 2
MEDIUM_CONFIDENCE_MIN = 3
HIGH_CONFIDENCE_MIN = 5
SUPPORTED_LEVELS = frozenset(
    {
        "hint",
        "reference",
        "worked-example",
        "coach",
    }
)


def _has_non_finite_score(record: EvidenceRecord) -> bool:
    """Reject non-finite inputs and overflowed ratios as unusable evidence."""
    values = (record.normalized_score, record.raw_score, record.max_score)
    if any(value is not None and not math.isfinite(value) for value in values):
        return True
    return (
        record.normalized_score is None
        and record.raw_score is not None
        and record.max_score is not None
        and record.max_score != 0
        and not math.isfinite(record.raw_score / record.max_score)
    )


def _score(record: EvidenceRecord) -> float | None:
    """Normalize explicit score signals before boolean correctness rules."""
    if _has_non_finite_score(record):
        return None
    if record.normalized_score is not None:
        return record.normalized_score
    if record.raw_score is not None and record.max_score:
        return record.raw_score / record.max_score
    return None


def _has_support(record: EvidenceRecord) -> bool:
    support_level = (record.support_level or "").strip().lower()
    return record.hint_used or record.reference_accessed or support_level in SUPPORTED_LEVELS


def _is_supported_correct_or_low_confidence(record: EvidenceRecord) -> bool:
    if record.correctness is not True and not (
        record.correctness is None and (_score(record) or 0) >= 0.5
    ):
        return False
    return _has_support(record) or (
        record.confidence_rating is not None and record.confidence_rating <= LOW_CONFIDENCE_MAX
    )


def _is_low_confidence_correct(record: EvidenceRecord) -> bool:
    return (
        record.correctness is True
        and record.confidence_rating is not None
        and record.confidence_rating <= LOW_CONFIDENCE_MAX
    )


def _is_fast_first_attempt(record: EvidenceRecord) -> bool:
    """Return true for explicitly first-attempt, fast, high-confidence correctness."""

    attempt_context = record.attempt_context or {}
    attempt_number = attempt_context.get("attempt_number")
    is_first_attempt = (
        attempt_number == 1
        if isinstance(attempt_number, int)
        else record.time_since_last_attempt_seconds is None
    )

    return (
        record.correctness is True
        and not _has_support(record)
        and (record.confidence_rating or 0) >= HIGH_CONFIDENCE_MIN
        and record.response_time_seconds is not None
        and is_first_attempt
    )


def _is_good_unsupported_correct(record: EvidenceRecord) -> bool:
    return (
        record.correctness is True
        and not _has_support(record)
        and record.confidence_rating is not None
        and record.confidence_rating >= MEDIUM_CONFIDENCE_MIN
    )


def _is_score_under_half(record: EvidenceRecord) -> bool:
    score = _score(record)
    return record.correctness is not False and score is not None and score < 0.5


def _is_score_under_mastery(record: EvidenceRecord) -> bool:
    score = _score(record)
    return (
        record.correctness is not False
        and not _has_support(record)
        and score is not None
        and 0.5 <= score < 0.85
    )


def _is_score_at_mastery(record: EvidenceRecord) -> bool:
    score = _score(record)
    return (
        record.correctness is not False
        and not _has_support(record)
        and not _is_low_confidence_correct(record)
        and score is not None
        and score >= 0.85
        and not (record.scoring_method == "binary" and _is_good_unsupported_correct(record))
    )


FSRS_RULES: tuple[FSRSRule, ...] = (
    FSRSRule(
        rule_id="transfer-excluded",
        rating="excluded",
        value=None,
        scheduling_included=False,
        reason="Transfer evidence is retained but excluded from FSRS interval calculation.",
        applies=lambda record: (
            (record.transfer_distance or "").strip().lower() in TRANSFER_EXCLUDED_DISTANCES
        ),
    ),
    FSRSRule(
        rule_id="incorrect",
        rating="again",
        value=1,
        scheduling_included=True,
        reason="Incorrect evidence maps to FSRS Again.",
        applies=lambda record: record.correctness is False,
    ),
    FSRSRule(
        rule_id="insufficient-signal",
        rating="again",
        value=1,
        scheduling_included=True,
        reason="Non-finite score evidence cannot establish mastery; schedule conservatively.",
        applies=_has_non_finite_score,
    ),
    FSRSRule(
        rule_id="supported-or-low-confidence-correct",
        rating="hard",
        value=2,
        scheduling_included=True,
        reason="Correct evidence with support or low confidence maps to FSRS Hard.",
        applies=_is_supported_correct_or_low_confidence,
    ),
    FSRSRule(
        rule_id="partial-under-half",
        rating="again",
        value=1,
        scheduling_included=True,
        reason="Normalized or partial-credit score is below the 0.5 retrieval threshold.",
        applies=_is_score_under_half,
    ),
    FSRSRule(
        rule_id="partial-under-mastery",
        rating="hard",
        value=2,
        scheduling_included=True,
        reason="Normalized or partial-credit score is below the 0.85 mastery threshold.",
        applies=_is_score_under_mastery,
    ),
    FSRSRule(
        rule_id="partial-at-mastery",
        rating="good",
        value=3,
        scheduling_included=True,
        reason="Normalized or partial-credit score meets the 0.85 mastery threshold.",
        applies=_is_score_at_mastery,
    ),
    FSRSRule(
        rule_id="fast-first-attempt",
        rating="easy",
        value=4,
        scheduling_included=True,
        reason="Fast high-confidence first-attempt correctness maps to FSRS Easy.",
        applies=_is_fast_first_attempt,
    ),
    FSRSRule(
        rule_id="unsupported-correct",
        rating="good",
        value=3,
        scheduling_included=True,
        reason="Unsupported medium-or-higher confidence correctness maps to FSRS Good.",
        applies=_is_good_unsupported_correct,
    ),
)


def evidence_to_fsrs_rating(
    record: EvidenceRecord,
    *,
    prompt_class_median_seconds: float | None = None,
    first_attempt: bool | None = None,
) -> FSRSRating:
    """Return the first matching deterministic FSRS-style rating for evidence."""
    for rule in FSRS_RULES:
        if rule.rule_id == "fast-first-attempt" and (
            first_attempt is False
            or prompt_class_median_seconds is None
            or not math.isfinite(prompt_class_median_seconds)
            or prompt_class_median_seconds <= 0
            or record.response_time_seconds is None
            or record.response_time_seconds > prompt_class_median_seconds
        ):
            continue
        if rule.applies(record):
            return FSRSRating(
                label=rule.rating,
                value=rule.value,
                scheduling_included=rule.scheduling_included,
                rule_id=rule.rule_id,
                reason=rule.reason,
            )
    return FSRSRating(
        label="again",
        value=1,
        scheduling_included=True,
        rule_id="insufficient-signal",
        reason="Evidence lacks enough positive correctness signal; schedule conservatively.",
    )


# ---------------------------------------------------------------------------
# Bounded seam inventory (issue #762)
#
# Machine-checkable map of every rating rule, signal adapter and direct
# scheduler/card/queue consumer inside the evidence→FSRS translation seam.
# Dispositions are audit classifications only; they do not change policy.
# ---------------------------------------------------------------------------

SEAM_DISPOSITIONS = frozenset({"confirmed", "intentional", "unknown"})


@dataclass(frozen=True)
class SeamInventoryEntry:
    """One inventoried producer→consumer hop inside the evidence→FSRS seam."""

    entry_id: str
    kind: str  # rating-rule | rating-adapter | signal-adapter | consumer
    contract: str
    producer: str
    consumer: str
    evidence: str
    disposition: str


def _rule_entry(
    rule: FSRSRule,
    *,
    producer: str,
    consumer: str,
    evidence: str,
    disposition: str,
) -> SeamInventoryEntry:
    inclusion = "included" if rule.scheduling_included else "excluded"
    value = "none" if rule.value is None else str(rule.value)
    return SeamInventoryEntry(
        entry_id=rule.rule_id,
        kind="rating-rule",
        contract=f"{rule.rating}/{value}/{inclusion}: {rule.reason}",
        producer=producer,
        consumer=consumer,
        evidence=evidence,
        disposition=disposition,
    )


_RULE_BY_ID = {rule.rule_id: rule for rule in FSRS_RULES}


FSRS_SEAM_INVENTORY: tuple[SeamInventoryEntry, ...] = (
    SeamInventoryEntry(
        entry_id="evidence_to_fsrs_rating",
        kind="rating-adapter",
        contract=(
            "First matching FSRS_RULES row → FSRSRating; unmatched evidence "
            "falls back to insufficient-signal Again=1 / included"
        ),
        producer="EvidenceRecord (+ optional prompt-class median / first_attempt)",
        consumer="schedule_from_attempt / _prompt_class_timing_context samples",
        evidence="tests/scheduling/test_fsrs_adapter.py; FSRS_RULES order test",
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["transfer-excluded"],
        producer="evidence_to_fsrs_rating",
        consumer="schedule_from_attempt exclusion gate → attempt.response_metadata",
        evidence=(
            "test_fsrs_consumer_audit near/far/novel; transfer cold/existing-card "
            "controls; PR #779 / issue #760"
        ),
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["incorrect"],
        producer="evidence_to_fsrs_rating",
        consumer="_fsrs_to_signal → advance_card_state / queue / schedule / decision",
        evidence="test_fsrs_consumer_audit[incorrect]; test_incorrect_maps_to_again",
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["insufficient-signal"],
        producer="evidence_to_fsrs_rating non-finite guard",
        consumer="_fsrs_to_signal drops rule_id → _classify_signal fallback",
        evidence=(
            "adapter non-finite tests; lms762-nonfinite-probe.py shows adapter "
            "Again=1 can still advance via success fallback"
        ),
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["supported-or-low-confidence-correct"],
        producer="evidence_to_fsrs_rating",
        consumer="_fsrs_to_signal → Hard=2 engine rating and persisted card",
        evidence="test_fsrs_consumer_audit hint/reference; low-confidence adapter tests",
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["partial-under-half"],
        producer="evidence_to_fsrs_rating",
        consumer="_fsrs_to_signal → Again=1 engine rating and persisted card",
        evidence="test_fsrs_consumer_audit[under-half]",
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["partial-under-mastery"],
        producer="evidence_to_fsrs_rating",
        consumer="_fsrs_to_signal → Hard=2 engine rating and persisted card",
        evidence="test_fsrs_consumer_audit[half|under-mastery]",
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["partial-at-mastery"],
        producer="evidence_to_fsrs_rating",
        consumer="_fsrs_to_signal → Good=3 engine rating and persisted card",
        evidence="test_fsrs_consumer_audit[mastery]",
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["fast-first-attempt"],
        producer="evidence_to_fsrs_rating + timing median gate",
        consumer=(
            "_signal_to_rating_value preserves Easy=4 on success blend → " "advance_card_state"
        ),
        evidence="test_fsrs_consumer_audit[easy]; PR #781 / issue #761",
        disposition="confirmed",
    ),
    _rule_entry(
        _RULE_BY_ID["unsupported-correct"],
        producer="evidence_to_fsrs_rating",
        consumer="_fsrs_to_signal → Good=3 engine rating and persisted card",
        evidence="test_fsrs_consumer_audit[good]; Easy vs Good timing controls",
        disposition="confirmed",
    ),
    SeamInventoryEntry(
        entry_id="insufficient-signal-fallback",
        kind="rating-rule",
        contract=(
            "No FSRS_RULES match → Again=1 / included / insufficient-signal "
            "(same rule_id as non-finite guard)"
        ),
        producer="evidence_to_fsrs_rating terminal return",
        consumer="_fsrs_to_signal returns None → internal classifier path",
        evidence="test_low_confidence_without_true_correctness_does_not_map_to_hard",
        disposition="intentional",
    ),
    SeamInventoryEntry(
        entry_id="_fsrs_to_signal",
        kind="signal-adapter",
        contract=(
            "Excluded or insufficient-signal → None; value 1→fail, 2→low-confidence-"
            "success, else success (Easy and Good both become success here)"
        ),
        producer="FSRSRating from evidence_to_fsrs_rating",
        consumer="_conservative_signal / _signal_to_rating_value in schedule_from_attempt",
        evidence="service.py:_fsrs_to_signal; consumer audit engine spy",
        disposition="intentional",
    ),
    SeamInventoryEntry(
        entry_id="_classify_signal",
        kind="signal-adapter",
        contract=(
            "Internal fail / low-confidence-success / success from correctness, "
            "score, confidence and support"
        ),
        producer="EvidenceRecord fields on schedule_from_attempt",
        consumer="_conservative_signal blend or solo fallback when fsrs_signal is None",
        evidence="service.py:_classify_signal; existing scheduler boundary tests",
        disposition="intentional",
    ),
    SeamInventoryEntry(
        entry_id="_conservative_signal",
        kind="signal-adapter",
        contract="Prefer the lower-confidence of fsrs_signal and internal_signal",
        producer="_fsrs_to_signal and _classify_signal",
        consumer="_signal_to_rating_value",
        evidence="service.py:_conservative_signal; supported/low-confidence caps",
        disposition="intentional",
    ),
    SeamInventoryEntry(
        entry_id="_signal_to_rating_value",
        kind="signal-adapter",
        contract=(
            "Map blended signal to 1–3; when fsrs_signal present, retain Easy=4 "
            "on success via min(fsrs_value, 4)"
        ),
        producer="blended signal + optional FSRSRating.value",
        consumer="advance_card_state / fsrs_engine.review",
        evidence="PR #781 Easy preservation; test_fsrs_consumer_audit[easy|good]",
        disposition="confirmed",
    ),
    SeamInventoryEntry(
        entry_id="schedule_for_evidence",
        kind="consumer",
        contract="Scored evidence enters schedule_from_attempt in the same transaction",
        producer="evidence.service.record_attempt / UI self-grade / rubric / revision",
        consumer="schedule_from_attempt",
        evidence="attempt-loop e2e; ui self-grade; rubric and revision request tests",
        disposition="confirmed",
    ),
    SeamInventoryEntry(
        entry_id="schedule_from_attempt",
        kind="consumer",
        contract=(
            "scheduling_included=false returns ExcludedSchedulingOutcome before any "
            "card/queue/schedule/decision write; included path blends signals and advances"
        ),
        producer="evidence_to_fsrs_rating + signal adapters",
        consumer="ReviewCardState / ReviewQueueItem / ReviewSchedule / SchedulerDecision",
        evidence="test_service_honors_adapter_eligibility; consumer audit matrix",
        disposition="confirmed",
    ),
    SeamInventoryEntry(
        entry_id="advance_card_state",
        kind="consumer",
        contract="Persist FSRS engine result onto ReviewCardState (count, due_at, card_state)",
        producer="_signal_to_rating_value via schedule_from_attempt",
        consumer="ReviewCardState row",
        evidence="test_fsrs_consumer_audit committed-card checks; test_card_state.py",
        disposition="confirmed",
    ),
    SeamInventoryEntry(
        entry_id="queue_schedule_decision",
        kind="consumer",
        contract=(
            "Queue item links evidence/attempt; schedule due_at matches; decision "
            "rows join the same queue item"
        ),
        producer="schedule_from_attempt included path",
        consumer="ReviewQueueItem / ReviewSchedule / SchedulerDecision",
        evidence="test_fsrs_consumer_audit identity joins",
        disposition="confirmed",
    ),
    SeamInventoryEntry(
        entry_id="feedback.repository._ensure_revision_scheduling",
        kind="consumer",
        contract="Schedule revision evidence via schedule_for_evidence when no queue item exists",
        producer="feedback.repository revision path",
        consumer="schedule_for_evidence",
        evidence=("revision request tests; multi-grade first-by-ID selection is static-only"),
        disposition="unknown",
    ),
)


def seam_inventory_by_kind(kind: str) -> tuple[SeamInventoryEntry, ...]:
    """Return inventory rows of one kind (rating-rule, signal-adapter, …)."""
    return tuple(entry for entry in FSRS_SEAM_INVENTORY if entry.kind == kind)


def seam_rating_rule_ids() -> tuple[str, ...]:
    """Rule ids inventoried from FSRS_RULES (excludes the terminal fallback row)."""
    return tuple(
        entry.entry_id
        for entry in FSRS_SEAM_INVENTORY
        if entry.kind == "rating-rule" and entry.entry_id in _RULE_BY_ID
    )
