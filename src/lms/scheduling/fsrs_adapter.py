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


# ---------------------------------------------------------------------------
# Preservation invariants (issue #762)
#
# Declares what the existing scheduling policy must keep distinct at this seam.
# These are audit obligations under current policy — not new rating rules,
# algorithm changes, or FSRS parameter tuning. Known repairs: #760 / PR #779
# (exclusion gate) and #761 / PR #781 (Easy vs Good + binary score selection).
# ---------------------------------------------------------------------------

REQUIRED_PRESERVATION_IDS = (
    "scheduling-included-false",
    "easy-versus-good",
    "upstream-score-selection",
)


@dataclass(frozen=True)
class SeamPreservationInvariant:
    """One declared preservation obligation under the existing scheduling policy."""

    invariant_id: str
    semantics: str
    policy_basis: str
    adapter_commitment: str
    consumer_commitment: str
    owner_issue: str
    owner_pr: str
    evidence: str


FSRS_PRESERVATION_INVARIANTS: tuple[SeamPreservationInvariant, ...] = (
    SeamPreservationInvariant(
        invariant_id="scheduling-included-false",
        semantics=(
            "scheduling_included=false remains an exclusion gate: transfer "
            "evidence stays retained but must not fall back into FSRS card, "
            "queue, schedule or decision mutation"
        ),
        policy_basis=(
            "docs/product/project-plan.md transfer exclusion; " "FSRS_RULES transfer-excluded row"
        ),
        adapter_commitment=(
            "transfer-excluded emits label=excluded, value=None, "
            "scheduling_included=False for near/far/novel distances"
        ),
        consumer_commitment=(
            "schedule_from_attempt returns ExcludedSchedulingOutcome before "
            "get_or_seed_card_state / advance_card_state / queue writes"
        ),
        owner_issue="#760",
        owner_pr="#779",
        evidence=(
            "test_transfer_distance_is_excluded_from_scheduling; "
            "test_service_honors_adapter_eligibility_before_any_card_write; "
            "test_fsrs_consumer_audit near/far/novel"
        ),
    ),
    SeamPreservationInvariant(
        invariant_id="easy-versus-good",
        semantics=(
            "Easy (value=4) and Good (value=3) remain distinct grades under "
            "the existing four-grade policy; timing-eligible Easy must not "
            "collapse into Good at the adapter or through the success blend"
        ),
        policy_basis=(
            "docs/product/project-plan.md Easy/Good rows; "
            "FSRS_RULES fast-first-attempt vs unsupported-correct"
        ),
        adapter_commitment=(
            "fast-first-attempt → easy/4; unsupported-correct → good/3; "
            "eligible timing context is required for Easy"
        ),
        consumer_commitment=(
            "_signal_to_rating_value retains Easy=4 on success via "
            "min(fsrs_value, 4); Good stays 3"
        ),
        owner_issue="#761",
        owner_pr="#781",
        evidence=(
            "test_fast_high_confidence_first_attempt_maps_to_easy; "
            "test_ui_self_grades_preserve_distinct_ratings; "
            "test_fsrs_consumer_audit[easy|good]"
        ),
    ),
    SeamPreservationInvariant(
        invariant_id="upstream-score-selection",
        semantics=(
            "Upstream score selection prefers normalized_score, then "
            "raw/max; binary scoring_method must not be intercepted as "
            "partial-at-mastery before Easy when Good-unsupported applies"
        ),
        policy_basis=(
            "docs/product/project-plan.md partial-credit pre-threshold vs "
            "binary Easy path; _score and _is_score_at_mastery binary gate"
        ),
        adapter_commitment=(
            "_score prefers normalized_score over raw/max; "
            "partial-at-mastery skips binary+good-unsupported so "
            "fast-first-attempt can still match"
        ),
        consumer_commitment=(
            "UI self-grade binary payloads keep scoring_method=binary into "
            "schedule_for_evidence (no new rating policy)"
        ),
        owner_issue="#761",
        owner_pr="#781",
        evidence=(
            "test_binary_mastery_without_confidence_keeps_good; "
            "test_ui_binary_correct_requires_eligible_timing_context_for_easy; "
            "lms762-controls.json binary negative control"
        ),
    ),
)


def preservation_invariant(invariant_id: str) -> SeamPreservationInvariant:
    """Return one declared preservation invariant by id."""
    for entry in FSRS_PRESERVATION_INVARIANTS:
        if entry.invariant_id == invariant_id:
            return entry
    raise KeyError(f"unknown preservation invariant: {invariant_id}")


def adapter_preservation_holds() -> dict[str, bool]:
    """Evaluate pure-adapter commitments for each declared preservation invariant.

    Consumer mutation gates live in ``service.schedule_from_attempt`` and are
    covered by existing eligibility / audit controls; this helper only checks
    commitments that ``fsrs_adapter`` itself can prove against live ``FSRS_RULES``
    and ``evidence_to_fsrs_rating``.
    """
    transfer_rule = _RULE_BY_ID["transfer-excluded"]
    easy_rule = _RULE_BY_ID["fast-first-attempt"]
    good_rule = _RULE_BY_ID["unsupported-correct"]
    mastery_rule = _RULE_BY_ID["partial-at-mastery"]

    near = EvidenceRecord(
        learner_id="preservation-check",
        knowledge_node_id="node",
        correctness=True,
        confidence_rating=5,
        transfer_distance="near",
    )
    far = EvidenceRecord(
        learner_id="preservation-check",
        knowledge_node_id="node",
        correctness=True,
        confidence_rating=5,
        transfer_distance="far",
    )
    novel = EvidenceRecord(
        learner_id="preservation-check",
        knowledge_node_id="node",
        correctness=True,
        confidence_rating=5,
        transfer_distance="novel",
    )
    binary_easy = EvidenceRecord(
        learner_id="preservation-check",
        knowledge_node_id="node",
        scoring_method="binary",
        correctness=True,
        confidence_rating=5,
        normalized_score=1.0,
        response_time_seconds=10,
        support_level="none",
        attempt_context={"attempt_number": 1},
    )
    binary_good = EvidenceRecord(
        learner_id="preservation-check",
        knowledge_node_id="node",
        scoring_method="binary",
        correctness=True,
        confidence_rating=4,
        normalized_score=1.0,
        support_level="none",
    )
    partial_mastery = EvidenceRecord(
        learner_id="preservation-check",
        knowledge_node_id="node",
        scoring_method="partial-credit",
        correctness=True,
        confidence_rating=5,
        normalized_score=0.9,
        support_level="none",
    )
    score_prefers_normalized = EvidenceRecord(
        learner_id="preservation-check",
        knowledge_node_id="node",
        normalized_score=0.4,
        raw_score=9.0,
        max_score=10.0,
    )

    excluded_ok = (
        transfer_rule.scheduling_included is False
        and transfer_rule.value is None
        and all(
            evidence_to_fsrs_rating(record).scheduling_included is False
            and evidence_to_fsrs_rating(record).value is None
            and evidence_to_fsrs_rating(record).rule_id == "transfer-excluded"
            for record in (near, far, novel)
        )
    )

    easy_rating = evidence_to_fsrs_rating(binary_easy, prompt_class_median_seconds=10)
    good_rating = evidence_to_fsrs_rating(binary_good)
    easy_vs_good_ok = (
        easy_rule.value == 4
        and easy_rule.rating == "easy"
        and good_rule.value == 3
        and good_rule.rating == "good"
        and easy_rating.value == 4
        and easy_rating.rule_id == "fast-first-attempt"
        and good_rating.value == 3
        and good_rating.rule_id == "unsupported-correct"
        and easy_rating.value != good_rating.value
    )

    # Binary+good-unsupported must skip partial-at-mastery so Easy stays reachable.
    binary_skips_mastery = not mastery_rule.applies(binary_easy)
    partial_still_mastery = mastery_rule.applies(partial_mastery)
    score_selection_ok = (
        binary_skips_mastery
        and partial_still_mastery
        and _score(score_prefers_normalized) == 0.4
        and evidence_to_fsrs_rating(score_prefers_normalized).rule_id == "partial-under-half"
        and easy_rating.rule_id == "fast-first-attempt"
    )

    return {
        "scheduling-included-false": excluded_ok,
        "easy-versus-good": easy_vs_good_ok,
        "upstream-score-selection": score_selection_ok,
    }


# ---------------------------------------------------------------------------
# Persisted-effect traces + already-correct controls (issue #762)
#
# Traces adapter outcomes into ReviewCardState / queue / schedule / decision
# effects and names the deliberate negative controls that detect fallback
# mutation or Easy/Good/binary semantic collapse. Controls match the offline
# receipts under docs/audits/evidence/fsrs-consumer-762/; they do not change
# scheduling policy.
# ---------------------------------------------------------------------------

REQUIRED_NEGATIVE_CONTROL_IDS = (
    "excluded-fallback-mutation",
    "easy-good-collapse",
    "binary-score-selection",
)


@dataclass(frozen=True)
class SeamNegativeControl:
    """One already-correct negative control that detects a seam collapse."""

    control_id: str
    invariant_id: str
    target_module: str
    healthy_fragment: str
    broken_fragment: str
    collapse_or_fallback: str
    detection_evidence: str


@dataclass(frozen=True)
class PersistedEffectTrace:
    """How one adapter outcome must land in durable scheduler state."""

    trace_id: str
    adapter_result: str
    persisted_effects: str
    mutation_allowed: bool
    collapse_or_fallback_if_broken: str
    control_id: str | None
    evidence: str


FSRS_NEGATIVE_CONTROLS: tuple[SeamNegativeControl, ...] = (
    SeamNegativeControl(
        control_id="excluded-fallback-mutation",
        invariant_id="scheduling-included-false",
        target_module="src/lms/scheduling/service.py",
        healthy_fragment="if not fsrs_rating.scheduling_included:",
        broken_fragment="if False and not fsrs_rating.scheduling_included:",
        collapse_or_fallback=(
            "Excluded adapter output falls through into get_or_seed_card_state / "
            "advance_card_state; transfer card columns mutate and queue/schedule/"
            "decision rows appear"
        ),
        detection_evidence=(
            "lms762-controls.json excluded; lms762-excluded-red.txt; "
            "test_fsrs_consumer_audit near/far/novel"
        ),
    ),
    SeamNegativeControl(
        control_id="easy-good-collapse",
        invariant_id="easy-versus-good",
        target_module="src/lms/scheduling/service.py",
        healthy_fragment=('return min(fsrs_value, 4 if signal == "success" else value)'),
        broken_fragment="return value",
        collapse_or_fallback=(
            "Timing-eligible Easy (adapter value 4) collapses to Good (3) at "
            "_signal_to_rating_value; fsrs_engine.review and persisted card "
            "advance under the Good grade"
        ),
        detection_evidence=(
            "lms762-controls.json easy; lms762-easy-red.txt; " "test_fsrs_consumer_audit[easy|good]"
        ),
    ),
    SeamNegativeControl(
        control_id="binary-score-selection",
        invariant_id="upstream-score-selection",
        target_module="src/lms/scheduling/fsrs_adapter.py",
        healthy_fragment='record.scoring_method == "binary"',
        broken_fragment="False",
        collapse_or_fallback=(
            "Binary mastery is intercepted by partial-at-mastery before "
            "fast-first-attempt; Easy becomes unreachable and persists as Good"
        ),
        detection_evidence=(
            "lms762-controls.json binary; lms762-binary-red.txt; "
            "adapter_preservation_holds upstream-score-selection"
        ),
    ),
)


FSRS_PERSISTED_EFFECT_TRACES: tuple[PersistedEffectTrace, ...] = (
    PersistedEffectTrace(
        trace_id="transfer-excluded-freeze",
        adapter_result=(
            "transfer-excluded → label=excluded, value=None, scheduling_included=false"
        ),
        persisted_effects=(
            "ExcludedSchedulingOutcome; attempt.response_metadata.scheduling_outcome "
            "with card_mutated=false; zero new ReviewQueueItem / ReviewSchedule / "
            "SchedulerDecision; existing ReviewCardState columns unchanged"
        ),
        mutation_allowed=False,
        collapse_or_fallback_if_broken=(
            "Fallback mutation into card/queue/schedule/decision despite exclusion"
        ),
        control_id="excluded-fallback-mutation",
        evidence=(
            "test_transfer_exclusion_trace_freezes_persisted_card_state; "
            "test_fsrs_consumer_audit near/far/novel; "
            "test_service_honors_adapter_eligibility_before_any_card_write"
        ),
    ),
    PersistedEffectTrace(
        trace_id="easy-persisted-rating-four",
        adapter_result="fast-first-attempt → easy/4 / scheduling_included=true",
        persisted_effects=(
            "fsrs_engine.review receives rating_value=4; ReviewCardState review_count "
            "increments; queue/schedule/decision rows join the attempt; decision_log "
            "fsrs_rating.value stays 4"
        ),
        mutation_allowed=True,
        collapse_or_fallback_if_broken="Easy collapses to engine rating 3 (Good)",
        control_id="easy-good-collapse",
        evidence=(
            "test_easy_versus_good_persist_distinct_engine_ratings; "
            "test_fsrs_consumer_audit[easy]"
        ),
    ),
    PersistedEffectTrace(
        trace_id="good-persisted-rating-three",
        adapter_result="unsupported-correct → good/3 / scheduling_included=true",
        persisted_effects=(
            "fsrs_engine.review receives rating_value=3; ReviewCardState advances; "
            "queue/schedule/decision rows join the attempt; decision_log "
            "fsrs_rating.value stays 3"
        ),
        mutation_allowed=True,
        collapse_or_fallback_if_broken=(
            "Good is no longer distinguishable from collapsed Easy in persisted effects"
        ),
        control_id="easy-good-collapse",
        evidence=(
            "test_easy_versus_good_persist_distinct_engine_ratings; "
            "test_fsrs_consumer_audit[good]"
        ),
    ),
    PersistedEffectTrace(
        trace_id="binary-easy-reachable",
        adapter_result=(
            "binary + good-unsupported skips partial-at-mastery so "
            "fast-first-attempt can still emit Easy under eligible timing"
        ),
        persisted_effects=(
            "Same Easy persisted path as easy-persisted-rating-four when timing "
            "context qualifies; otherwise Good=3 persists"
        ),
        mutation_allowed=True,
        collapse_or_fallback_if_broken=(
            "Upstream score selection steals Easy into partial-at-mastery Good"
        ),
        control_id="binary-score-selection",
        evidence=(
            "test_adapter_preservation_commitments_hold_under_existing_policy; "
            "lms762-controls.json binary"
        ),
    ),
    PersistedEffectTrace(
        trace_id="included-rating-mutates-card",
        adapter_result=(
            "Any scheduling_included=true rating (Again/Hard/Good/Easy) blends "
            "through signal adapters into advance_card_state"
        ),
        persisted_effects=(
            "ReviewCardState mutates; one ReviewQueueItem / ReviewSchedule / "
            "SchedulerDecision per attempt with matching evidence identity"
        ),
        mutation_allowed=True,
        collapse_or_fallback_if_broken=(
            "Included ratings fail to persist queue/schedule/decision or card advance"
        ),
        control_id=None,
        evidence="test_fsrs_consumer_audit included matrix rows",
    ),
)


def rating_allows_persisted_mutation(rating: FSRSRating) -> bool:
    """Return whether this adapter rating may mutate card/queue/schedule state."""
    return rating.scheduling_included


def negative_control(control_id: str) -> SeamNegativeControl:
    """Return one already-correct negative control by id."""
    for entry in FSRS_NEGATIVE_CONTROLS:
        if entry.control_id == control_id:
            return entry
    raise KeyError(f"unknown negative control: {control_id}")


def persisted_effect_trace(trace_id: str) -> PersistedEffectTrace:
    """Return one persisted-effect trace by id."""
    for entry in FSRS_PERSISTED_EFFECT_TRACES:
        if entry.trace_id == trace_id:
            return entry
    raise KeyError(f"unknown persisted-effect trace: {trace_id}")


# ---------------------------------------------------------------------------
# Known repairs + additional findings for human review (issue #762)
#
# Links already-owned per-instance repairs. Returns one additional confirmed
# internal-path loss without algorithm tuning, new rating policy, bundled
# production repair, or automatic issue filing.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeamKnownRepair:
    """One already-owned repair for a confirmed seam loss."""

    repair_id: str
    loss: str
    owner_issue: str
    owner_pr: str
    invariant_id: str
    control_id: str
    evidence: str


@dataclass(frozen=True)
class SeamAdditionalFinding:
    """Confirmed loss returned for human review; not auto-filed or repaired here."""

    finding_id: str
    loss: str
    adapter_observation: str
    consumer_observation: str
    evidence_limits: str
    prevention_check: str
    evidence: str
    auto_filed_issue: bool
    bundled_repair: bool


FSRS_KNOWN_REPAIRS: tuple[SeamKnownRepair, ...] = (
    SeamKnownRepair(
        repair_id="transfer-exclusion-gate",
        loss=(
            "scheduling_included=false transfer evidence fell back into FSRS "
            "card / queue / schedule mutation"
        ),
        owner_issue="#760",
        owner_pr="#779",
        invariant_id="scheduling-included-false",
        control_id="excluded-fallback-mutation",
        evidence=(
            "PR #779 Exclude transfer evidence before FSRS card updates; "
            "test_transfer_exclusion_trace_freezes_persisted_card_state"
        ),
    ),
    SeamKnownRepair(
        repair_id="easy-versus-good-preservation",
        loss="Distinct Easy (4) collapsed into Good (3) through the success blend",
        owner_issue="#761",
        owner_pr="#781",
        invariant_id="easy-versus-good",
        control_id="easy-good-collapse",
        evidence=(
            "PR #781 preserve FSRS grades with learner-scoped timing; "
            "test_easy_versus_good_persist_distinct_engine_ratings"
        ),
    ),
    SeamKnownRepair(
        repair_id="binary-score-selection",
        loss=(
            "Upstream binary mastery was intercepted as partial-at-mastery "
            "before Easy could match"
        ),
        owner_issue="#761",
        owner_pr="#781",
        invariant_id="upstream-score-selection",
        control_id="binary-score-selection",
        evidence=(
            "PR #781 binary gate on partial-at-mastery; "
            "adapter_preservation_holds upstream-score-selection"
        ),
    ),
)


FSRS_ADDITIONAL_FINDINGS: tuple[SeamAdditionalFinding, ...] = (
    SeamAdditionalFinding(
        finding_id="insufficient-signal-success-fallback",
        loss=(
            "Non-finite raw score evidence maps to adapter Again=1 / "
            "insufficient-signal, but schedule_from_attempt drops that verdict "
            "via _fsrs_to_signal and advances the card through the internal "
            "success classifier"
        ),
        adapter_observation=(
            "evidence_to_fsrs_rating → value=1, rule_id=insufficient-signal, "
            "scheduling_included=true"
        ),
        consumer_observation=(
            "decision_log retains fsrs_rating Again=1 while signal=success and "
            "ReviewCardState.review_count advances with a future due_at"
        ),
        evidence_limits=(
            "Direct/internal schedule_from_attempt path only; public API "
            "reachability of non-finite raw scores remains unknown"
        ),
        prevention_check=(
            "test_documents_current_nonfinite_fallback_behavior documents the current "
            "known adapter Again=1 plus consumer success loss, not a prevention gate; without repairing "
            "service.py or filing a follow-up issue"
        ),
        evidence=(
            "lms762-nonfinite-probe.py; lms762-nonfinite.txt; "
            "FSRS_SEAM_INVENTORY insufficient-signal disposition=confirmed"
        ),
        auto_filed_issue=False,
        bundled_repair=False,
    ),
)


def known_repair(repair_id: str) -> SeamKnownRepair:
    """Return one known owned repair by id."""
    for entry in FSRS_KNOWN_REPAIRS:
        if entry.repair_id == repair_id:
            return entry
    raise KeyError(f"unknown seam repair: {repair_id}")


def additional_finding(finding_id: str) -> SeamAdditionalFinding:
    """Return one additional confirmed finding by id."""
    for entry in FSRS_ADDITIONAL_FINDINGS:
        if entry.finding_id == finding_id:
            return entry
    raise KeyError(f"unknown additional finding: {finding_id}")


def nonfinite_insufficient_signal_probe_record() -> EvidenceRecord:
    """Build the offline non-finite probe EvidenceRecord (in-memory only)."""
    return EvidenceRecord(
        learner_id="lms762-nonfinite",
        knowledge_node_id="node-nonfinite",
        correctness=True,
        confidence_rating=5,
        raw_score=float("inf"),
        max_score=1.0,
        support_level="none",
    )


def additional_finding_adapter_contract_holds() -> bool:
    """True when the returned finding's adapter observation still matches live rules."""
    rating = evidence_to_fsrs_rating(nonfinite_insufficient_signal_probe_record())
    return (
        rating.value == 1
        and rating.label == "again"
        and rating.rule_id == "insufficient-signal"
        and rating.scheduling_included is True
    )
