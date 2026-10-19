"""Tests for the EvidenceRecord to FSRS rating adapter."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.evidence.models import EvidenceRecord
from lms.evidence.repository import create_evidence_record
from lms.scheduling.fsrs_adapter import (
    FSRS_ADDITIONAL_FINDINGS,
    FSRS_KNOWN_REPAIRS,
    FSRS_NEGATIVE_CONTROLS,
    FSRS_PERSISTED_EFFECT_TRACES,
    FSRS_PRESERVATION_INVARIANTS,
    FSRS_RULES,
    FSRS_SEAM_INVENTORY,
    REQUIRED_NEGATIVE_CONTROL_IDS,
    REQUIRED_PRESERVATION_IDS,
    SEAM_DISPOSITIONS,
    _score,
    adapter_preservation_holds,
    additional_finding,
    additional_finding_adapter_contract_holds,
    evidence_to_fsrs_rating,
    known_repair,
    negative_control,
    nonfinite_insufficient_signal_probe_record,
    persisted_effect_trace,
    preservation_invariant,
    rating_allows_persisted_mutation,
    seam_inventory_by_kind,
    seam_rating_rule_ids,
)


def test_incorrect_maps_to_again(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=False,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.scheduling_included is True
    assert rating.rule_id == "incorrect"


def test_supported_correct_maps_to_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=5,
        support_level="hint",
        hint_used=True,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.scheduling_included is True
    assert rating.rule_id == "supported-or-low-confidence-correct"


def test_supported_high_score_is_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        support_level="hint",
        hint_used=True,
        normalized_score=0.95,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.scheduling_included is True
    assert rating.rule_id == "supported-or-low-confidence-correct"


def test_reference_accessed_maps_to_hard_even_without_support_level(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=5,
        support_level="none",
        hint_used=False,
        reference_accessed=True,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.rule_id == "supported-or-low-confidence-correct"


def test_low_confidence_unsupported_correct_maps_to_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=2,
        support_level="none",
        hint_used=False,
        reference_accessed=False,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.scheduling_included is True
    assert rating.rule_id == "supported-or-low-confidence-correct"


def test_low_confidence_high_score_is_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=2,
        support_level="none",
        hint_used=False,
        reference_accessed=False,
        normalized_score=0.95,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.scheduling_included is True
    assert rating.rule_id == "supported-or-low-confidence-correct"


def _self_grade_partial_record(
    db_session: Session,
    *,
    normalized_score: float,
    confidence_rating: int = 5,
) -> EvidenceRecord:
    """Build evidence from the real UI partial self-grade shape in attempts.py."""
    from lms.ui.attempts import _SELF_GRADES

    grade = dict(_SELF_GRADES["partial"])
    # Pin the contract the adapter must honor: unspecified correctness and
    # partial-credit scoring, with only the normalized score under test varying.
    assert grade["correctness"] is None
    assert grade["scoring_method"] == "partial-credit"
    grade["normalized_score"] = normalized_score
    return create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        confidence_rating=confidence_rating,
        **grade,
    )


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_value", "expected_rule_id"),
    [
        (0.30, "again", 1, "partial-under-half"),
        (0.70, "hard", 2, "partial-under-mastery"),
        (0.90, "good", 3, "partial-at-mastery"),
    ],
    ids=["representative-under-half", "representative-under-mastery", "representative-at-mastery"],
)
def test_partial_credit_representative_cases(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_value: int,
    expected_rule_id: str,
) -> None:
    record = _self_grade_partial_record(db_session, normalized_score=score)
    rating = evidence_to_fsrs_rating(record)
    assert record.correctness is None
    assert record.scoring_method == "partial-credit"
    assert rating.label == expected_label
    assert rating.value == expected_value
    assert rating.rule_id == expected_rule_id


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_value", "expected_rule_id"),
    [
        (0.49, "again", 1, "partial-under-half"),
        (0.50, "hard", 2, "partial-under-mastery"),
    ],
    ids=["under-half-upper-boundary", "under-mastery-lower-boundary"],
)
def test_partial_credit_half_threshold_boundary(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_value: int,
    expected_rule_id: str,
) -> None:
    record = _self_grade_partial_record(db_session, normalized_score=score)
    rating = evidence_to_fsrs_rating(record)
    assert record.correctness is None
    assert rating.label == expected_label
    assert rating.value == expected_value
    assert rating.rule_id == expected_rule_id


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_value", "expected_rule_id"),
    [
        (0.84, "hard", 2, "partial-under-mastery"),
        (0.85, "good", 3, "partial-at-mastery"),
    ],
    ids=["under-mastery-upper-boundary", "at-mastery-lower-boundary"],
)
def test_partial_credit_mastery_threshold_boundary(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_value: int,
    expected_rule_id: str,
) -> None:
    record = _self_grade_partial_record(db_session, normalized_score=score)
    rating = evidence_to_fsrs_rating(record)
    assert record.correctness is None
    assert rating.label == expected_label
    assert rating.value == expected_value
    assert rating.rule_id == expected_rule_id


def test_canonical_ui_partial_self_grade_maps_to_hard(db_session: Session) -> None:
    """The exact UI partial payload (score 0.7, correctness=None) is Hard."""
    from lms.ui.attempts import _SELF_GRADES

    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        confidence_rating=5,
        **_SELF_GRADES["partial"],
    )
    rating = evidence_to_fsrs_rating(record)
    assert record.correctness is None
    assert record.normalized_score == 0.7
    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.rule_id == "partial-under-mastery"


@pytest.mark.parametrize("score", [0.7, 0.85], ids=["partial", "mastery-boundary"])
@pytest.mark.parametrize(
    "confidence, support_level, hint_used, reference_accessed",
    [
        (2, "none", False, False),
        (5, "none", True, False),
        (5, "none", False, True),
        (5, "coach", False, False),
    ],
    ids=["low-confidence", "hint", "reference", "coach"],
)
def test_ui_partial_self_grade_caps_at_mastery(
    db_session: Session,
    score: float,
    confidence: int,
    support_level: str,
    hint_used: bool,
    reference_accessed: bool,
) -> None:
    """Unspecified correctness must retain caps even at the Good threshold."""
    record = _self_grade_partial_record(
        db_session, normalized_score=score, confidence_rating=confidence
    )
    record.support_level = support_level
    record.hint_used = hint_used
    record.reference_accessed = reference_accessed
    record.response_time_seconds = 20

    rating = evidence_to_fsrs_rating(record, prompt_class_median_seconds=20)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.rule_id == "supported-or-low-confidence-correct"
    assert rating.scheduling_included is True


def test_mastery_score_without_correctness_maps_to_good(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=None,
        normalized_score=0.85,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.scheduling_included is True
    assert rating.rule_id == "partial-at-mastery"


def test_incorrect_precedes_partial_credit_rules(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=False,
        normalized_score=0.84,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.rule_id == "incorrect"


def test_transfer_evidence_is_excluded_from_fsrs_scheduling(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=1.0,
        transfer_distance="near",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "excluded"
    assert rating.value is None
    assert rating.scheduling_included is False
    assert rating.rule_id == "transfer-excluded"


def test_transfer_distance_is_trimmed_and_case_insensitive(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=1.0,
        transfer_distance=" Near ",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "excluded"
    assert rating.value is None
    assert rating.scheduling_included is False
    assert rating.rule_id == "transfer-excluded"


def test_medium_confidence_unsupported_correct_maps_to_good(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=3,
        support_level="none",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.rule_id == "unsupported-correct"


def test_unsupported_correct_without_confidence_does_not_map_to_good(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        support_level="none",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.rule_id == "insufficient-signal"


def test_fast_high_confidence_first_attempt_maps_to_easy(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=5,
        response_time_seconds=12,
        support_level="none",
    )

    rating = evidence_to_fsrs_rating(record, prompt_class_median_seconds=12)

    assert rating.label == "easy"
    assert rating.value == 4
    assert rating.rule_id == "fast-first-attempt"


def test_fast_high_confidence_non_first_attempt_does_not_map_to_easy(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=5,
        response_time_seconds=12,
        support_level="none",
        attempt_context={"attempt_number": 2},
    )

    rating = evidence_to_fsrs_rating(record, prompt_class_median_seconds=12)

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.rule_id == "unsupported-correct"


@pytest.mark.parametrize(
    "median, seconds, first_attempt",
    [
        (None, 1, True),
        (0, 1, True),
        (-1, 1, True),
        (float("nan"), 1, True),
        (float("inf"), 1, True),
        (float("-inf"), 1, True),
        (20, None, True),
        (20, 1, False),
    ],
    ids=[
        "missing-median",
        "zero-median",
        "negative-median",
        "nan-median",
        "infinite-median",
        "negative-infinite-median",
        "missing-response-time",
        "service-detected-repeat",
    ],
)
def test_ui_binary_correct_requires_eligible_timing_context_for_easy(
    median: float | None, seconds: int | None, first_attempt: bool
) -> None:
    from lms.ui.attempts import _SELF_GRADES

    record = EvidenceRecord(
        learner_id="learner-1",
        knowledge_node_id="node-1",
        confidence_rating=5,
        response_time_seconds=seconds,
        attempt_context={"attempt_number": 1},
        **_SELF_GRADES["correct"],
    )

    rating = evidence_to_fsrs_rating(
        record, prompt_class_median_seconds=median, first_attempt=first_attempt
    )

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.rule_id == "unsupported-correct"
    assert rating.scheduling_included is True


def test_partial_credit_uses_raw_score_divided_by_max_score(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        raw_score=3.0,
        max_score=4.0,
        normalized_score=None,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.rule_id == "partial-under-mastery"


def test_low_confidence_without_true_correctness_does_not_map_to_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=None,
        confidence_rating=1,
        support_level="none",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.rule_id == "insufficient-signal"


def test_adapter_rule_table_is_data_driven() -> None:
    assert [rule.rule_id for rule in FSRS_RULES] == [
        "transfer-excluded",
        "incorrect",
        "insufficient-signal",
        "supported-or-low-confidence-correct",
        "partial-under-half",
        "partial-under-mastery",
        "partial-at-mastery",
        "fast-first-attempt",
        "unsupported-correct",
    ]


def test_seam_inventory_covers_every_rating_rule() -> None:
    """Every FSRS_RULES row must appear once in the bounded seam inventory."""
    assert seam_rating_rule_ids() == tuple(rule.rule_id for rule in FSRS_RULES)


def test_seam_inventory_records_adapters_consumers_and_dispositions() -> None:
    """Inventory entries must carry contract / producer / consumer / evidence / disposition."""
    kinds = {entry.kind for entry in FSRS_SEAM_INVENTORY}
    assert kinds == {"rating-adapter", "rating-rule", "signal-adapter", "consumer"}

    signal_ids = {entry.entry_id for entry in seam_inventory_by_kind("signal-adapter")}
    assert signal_ids == {
        "_fsrs_to_signal",
        "_classify_signal",
        "_conservative_signal",
        "_signal_to_rating_value",
    }

    consumer_ids = {entry.entry_id for entry in seam_inventory_by_kind("consumer")}
    assert {
        "schedule_for_evidence",
        "schedule_from_attempt",
        "advance_card_state",
        "queue_schedule_decision",
    }.issubset(consumer_ids)

    seen: set[str] = set()
    for entry in FSRS_SEAM_INVENTORY:
        assert entry.entry_id, "entry_id required"
        assert entry.entry_id not in seen, f"duplicate inventory id: {entry.entry_id}"
        seen.add(entry.entry_id)
        assert entry.contract.strip()
        assert entry.producer.strip()
        assert entry.consumer.strip()
        assert entry.evidence.strip()
        assert entry.disposition in SEAM_DISPOSITIONS


def test_preservation_invariants_declare_required_semantics() -> None:
    """Existing policy must declare exclusion, Easy/Good and score-selection preservation."""
    ids = tuple(entry.invariant_id for entry in FSRS_PRESERVATION_INVARIANTS)
    assert ids == REQUIRED_PRESERVATION_IDS

    for entry in FSRS_PRESERVATION_INVARIANTS:
        assert entry.semantics.strip()
        assert entry.policy_basis.strip()
        assert entry.adapter_commitment.strip()
        assert entry.consumer_commitment.strip()
        assert entry.owner_issue.startswith("#")
        assert entry.owner_pr.startswith("#")
        assert entry.evidence.strip()
        assert preservation_invariant(entry.invariant_id) is entry


def test_adapter_preservation_commitments_hold_under_existing_policy() -> None:
    """Live FSRS_RULES / evidence_to_fsrs_rating must satisfy declared adapter commitments."""
    holds = adapter_preservation_holds()
    assert set(holds) == set(REQUIRED_PRESERVATION_IDS)
    assert all(holds.values()), holds

    # Explicit semantic spot-checks so a silent helper change cannot greenwash.
    transfer = evidence_to_fsrs_rating(
        EvidenceRecord(
            learner_id="l",
            knowledge_node_id="n",
            correctness=True,
            confidence_rating=5,
            transfer_distance="near",
        )
    )
    assert transfer.scheduling_included is False
    assert transfer.value is None

    easy = evidence_to_fsrs_rating(
        EvidenceRecord(
            learner_id="l",
            knowledge_node_id="n",
            scoring_method="binary",
            correctness=True,
            confidence_rating=5,
            normalized_score=1.0,
            response_time_seconds=8,
            support_level="none",
            attempt_context={"attempt_number": 1},
        ),
        prompt_class_median_seconds=8,
    )
    good = evidence_to_fsrs_rating(
        EvidenceRecord(
            learner_id="l",
            knowledge_node_id="n",
            scoring_method="binary",
            correctness=True,
            confidence_rating=4,
            normalized_score=1.0,
            support_level="none",
        )
    )
    assert easy.value == 4 and easy.rule_id == "fast-first-attempt"
    assert good.value == 3 and good.rule_id == "unsupported-correct"
    assert easy.value != good.value

    # Binary mastery must not steal the Easy lane via partial-at-mastery.
    binary_mastery_candidate = EvidenceRecord(
        learner_id="l",
        knowledge_node_id="n",
        scoring_method="binary",
        correctness=True,
        confidence_rating=5,
        normalized_score=1.0,
        support_level="none",
        attempt_context={"attempt_number": 1},
        response_time_seconds=8,
    )
    assert not next(r for r in FSRS_RULES if r.rule_id == "partial-at-mastery").applies(
        binary_mastery_candidate
    )


def test_persisted_effect_traces_and_negative_controls_are_complete() -> None:
    """Traces name mutation gates; controls cover every declared preservation invariant."""
    control_ids = tuple(entry.control_id for entry in FSRS_NEGATIVE_CONTROLS)
    assert control_ids == REQUIRED_NEGATIVE_CONTROL_IDS

    for entry in FSRS_NEGATIVE_CONTROLS:
        assert entry.invariant_id in REQUIRED_PRESERVATION_IDS
        assert entry.target_module.endswith(".py")
        assert entry.healthy_fragment.strip()
        assert entry.broken_fragment.strip()
        assert entry.healthy_fragment != entry.broken_fragment
        assert entry.collapse_or_fallback.strip()
        assert entry.detection_evidence.strip()
        assert negative_control(entry.control_id) is entry

    linked_invariants = {entry.invariant_id for entry in FSRS_NEGATIVE_CONTROLS}
    assert linked_invariants == set(REQUIRED_PRESERVATION_IDS)

    seen: set[str] = set()
    for entry in FSRS_PERSISTED_EFFECT_TRACES:
        assert entry.trace_id not in seen
        seen.add(entry.trace_id)
        assert entry.adapter_result.strip()
        assert entry.persisted_effects.strip()
        assert entry.collapse_or_fallback_if_broken.strip()
        assert entry.evidence.strip()
        if entry.control_id is not None:
            assert entry.control_id in REQUIRED_NEGATIVE_CONTROL_IDS
        assert persisted_effect_trace(entry.trace_id) is entry

    assert persisted_effect_trace("transfer-excluded-freeze").mutation_allowed is False
    assert all(
        trace.mutation_allowed
        for trace in FSRS_PERSISTED_EFFECT_TRACES
        if trace.trace_id != "transfer-excluded-freeze"
    )


def test_negative_controls_match_recorded_offline_receipts() -> None:
    """Machine-checkable controls must stay aligned with the offline red receipts."""
    import json
    from pathlib import Path

    receipt_path = (
        Path(__file__).resolve().parents[2]
        / "docs/audits/evidence/fsrs-consumer-762/lms762-controls.json"
    )
    receipts = json.loads(receipt_path.read_text(encoding="utf-8"))
    by_legacy = {row["control"]: row for row in receipts}
    legacy_ids = {
        "excluded-fallback-mutation": "excluded",
        "easy-good-collapse": "easy",
        "binary-score-selection": "binary",
    }
    for control in FSRS_NEGATIVE_CONTROLS:
        row = by_legacy[legacy_ids[control.control_id]]
        assert row["path"] == control.target_module
        assert row["original"] == control.healthy_fragment
        assert row["replacement"] == control.broken_fragment


def test_transfer_exclusion_trace_freezes_persisted_card_state(db_session: Session) -> None:
    """scheduling_included=false must not fall back into card/queue/schedule mutation."""
    import copy

    from lms.scheduling.card_state import get_or_seed_card_state
    from lms.scheduling.models import ReviewCardState, ReviewQueueItem, ReviewSchedule
    from lms.scheduling.service import ExcludedSchedulingOutcome, schedule_from_attempt
    from tests.scheduling.test_review_queue import _make_attempt

    card = get_or_seed_card_state(
        db_session, learner_id="learner-1", subject_id="node-1", prior_successes=0
    )
    before = copy.deepcopy(
        {column.key: getattr(card, column.key) for column in ReviewCardState.__table__.columns}
    )
    attempt, evidence = _make_attempt(db_session, correctness=True, confidence_rating=5)
    evidence.transfer_distance = "near"
    db_session.flush()

    rating = evidence_to_fsrs_rating(evidence)
    assert rating.rule_id == "transfer-excluded"
    assert rating_allows_persisted_mutation(rating) is False

    outcome = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    assert isinstance(outcome, ExcludedSchedulingOutcome)
    assert outcome.decision_log["card_mutated"] is False
    assert outcome.decision_log["fsrs_rating"]["scheduling_included"] is False
    assert outcome.due_at is None
    assert {
        column.key: getattr(card, column.key) for column in ReviewCardState.__table__.columns
    } == before
    assert db_session.query(ReviewQueueItem).count() == 0
    assert db_session.query(ReviewSchedule).count() == 0
    assert attempt.response_metadata is not None
    assert attempt.response_metadata["scheduling_outcome"]["card_mutated"] is False


@pytest.mark.parametrize("distance", ["near", "far", "novel"])
@pytest.mark.parametrize("has_history", [False, True], ids=["cold", "existing"])
def test_transfer_exclusion_preserves_all_committed_consumers(
    db_session: Session, distance: str, has_history: bool
) -> None:
    """Excluded evidence preserves existing rows as well as avoiding new ones."""
    from copy import deepcopy
    from typing import Any

    from sqlalchemy import select

    from lms.evidence.models import Attempt
    from lms.scheduling.models import (
        ReviewCardState,
        ReviewQueueItem,
        ReviewSchedule,
        SchedulerDecision,
    )
    from lms.scheduling.service import ExcludedSchedulingOutcome, schedule_from_attempt
    from tests.scheduling.test_review_queue import _make_attempt

    def snapshot(session: Session) -> dict[str, list[dict[str, Any]]]:
        return {
            model.__tablename__: [
                deepcopy(
                    {column.key: getattr(row, column.key) for column in model.__table__.columns}
                )
                for row in session.scalars(select(model).order_by(model.id))
            ]
            for model in (ReviewCardState, ReviewQueueItem, ReviewSchedule, SchedulerDecision)
        }

    if has_history:
        prior_attempt, prior_evidence = _make_attempt(db_session)
        prior_item = schedule_from_attempt(
            db_session, attempt=prior_attempt, evidence_record=prior_evidence
        )
        assert isinstance(prior_item, ReviewQueueItem)
        db_session.commit()

    # Both snapshots use fresh sessions so ORM identity-map state cannot hide
    # writes, and SQLite datetime values have the same persisted representation.
    bind = db_session.get_bind()
    with Session(bind) as session:
        before = snapshot(session)
        assert all(len(rows) == int(has_history) for rows in before.values())

    attempt, evidence = _make_attempt(db_session, prompt_id="transfer-prompt")
    evidence.transfer_distance = distance
    db_session.flush()
    outcome = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    assert isinstance(outcome, ExcludedSchedulingOutcome)
    attempt_id, evidence_id = attempt.id, evidence.id
    db_session.commit()

    with Session(bind) as session:
        persisted_attempt = session.get(Attempt, attempt_id)
        persisted_evidence = session.get(EvidenceRecord, evidence_id)
        assert persisted_evidence is not None
        assert persisted_evidence.attempt_id == attempt_id
        assert persisted_evidence.transfer_distance == distance
        assert persisted_attempt is not None
        assert persisted_attempt.response_metadata is not None
        receipt = persisted_attempt.response_metadata["scheduling_outcome"]
        assert receipt["fsrs_rating"]["rule_id"] == "transfer-excluded"
        assert receipt["fsrs_rating"]["scheduling_included"] is False
        assert receipt["card_mutated"] is False
        assert receipt["output"]["due_at"] is None
        assert snapshot(session) == before


def test_easy_versus_good_persist_distinct_engine_ratings(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Easy and Good must remain distinct through the real engine and persisted decision log."""
    from lms.scheduling import fsrs_engine, service
    from lms.scheduling.models import ReviewQueueItem
    from tests.scheduling.test_review_queue import _make_attempt

    observed: list[int] = []
    real_review = fsrs_engine.review

    def recording_review(**kwargs: object) -> object:
        rating_value = kwargs["rating_value"]
        assert isinstance(rating_value, int)
        observed.append(rating_value)
        return real_review(**kwargs)

    monkeypatch.setattr(fsrs_engine, "review", recording_review)
    monkeypatch.setattr(
        service,
        "_prompt_class_timing_context",
        lambda *_args, **_kwargs: (20.0, 3, True),
    )

    easy_attempt, easy_evidence = _make_attempt(
        db_session,
        learner_id="learner-easy",
        prompt_id="prompt-easy",
        knowledge_node_id="node-easy",
        correctness=True,
        confidence_rating=5,
        response_time_seconds=10,
    )
    easy_evidence.scoring_method = "binary"
    easy_evidence.normalized_score = 1.0
    easy_evidence.support_level = "none"
    db_session.flush()

    easy_item = service.schedule_from_attempt(
        db_session, attempt=easy_attempt, evidence_record=easy_evidence
    )
    assert isinstance(easy_item, ReviewQueueItem)
    assert observed == [4]
    assert easy_item.decision_log["fsrs_rating"]["value"] == 4
    assert easy_item.decision_log["fsrs_rating"]["rule_id"] == "fast-first-attempt"
    assert rating_allows_persisted_mutation(
        evidence_to_fsrs_rating(easy_evidence, prompt_class_median_seconds=20.0, first_attempt=True)
    )

    observed.clear()
    good_attempt, good_evidence = _make_attempt(
        db_session,
        learner_id="learner-good",
        prompt_id="prompt-good",
        knowledge_node_id="node-good",
        correctness=True,
        confidence_rating=4,
        response_time_seconds=10,
    )
    good_evidence.scoring_method = "binary"
    good_evidence.normalized_score = 1.0
    good_evidence.support_level = "none"
    db_session.flush()

    good_item = service.schedule_from_attempt(
        db_session, attempt=good_attempt, evidence_record=good_evidence
    )
    assert isinstance(good_item, ReviewQueueItem)
    assert observed == [3]
    assert good_item.decision_log["fsrs_rating"]["value"] == 3
    assert good_item.decision_log["fsrs_rating"]["rule_id"] == "unsupported-correct"
    assert (
        easy_item.decision_log["fsrs_rating"]["value"]
        != good_item.decision_log["fsrs_rating"]["value"]
    )


def test_known_repairs_link_owned_work_to_controls() -> None:
    """Known per-instance losses must point at existing owned issues/PRs and controls."""
    repair_ids = {entry.repair_id for entry in FSRS_KNOWN_REPAIRS}
    assert repair_ids == {
        "transfer-exclusion-gate",
        "easy-versus-good-preservation",
        "binary-score-selection",
    }

    linked_invariants = {entry.invariant_id for entry in FSRS_KNOWN_REPAIRS}
    assert linked_invariants == set(REQUIRED_PRESERVATION_IDS)

    for entry in FSRS_KNOWN_REPAIRS:
        assert entry.owner_issue.startswith("#")
        assert entry.owner_pr.startswith("#")
        assert entry.loss.strip()
        assert entry.control_id in REQUIRED_NEGATIVE_CONTROL_IDS
        assert negative_control(entry.control_id).invariant_id == entry.invariant_id
        assert preservation_invariant(entry.invariant_id).owner_issue == entry.owner_issue
        assert preservation_invariant(entry.invariant_id).owner_pr == entry.owner_pr
        assert known_repair(entry.repair_id) is entry


def test_additional_findings_are_returned_without_auto_filing_or_repair() -> None:
    """Additional confirmed losses stay review-only: no auto-filed issue, no bundled fix."""
    assert len(FSRS_ADDITIONAL_FINDINGS) == 1
    finding = additional_finding("insufficient-signal-success-fallback")
    assert finding.auto_filed_issue is False
    assert finding.bundled_repair is False
    assert finding.evidence_limits.strip()
    assert finding.prevention_check.strip()
    assert "unknown" in finding.evidence_limits.lower()
    assert additional_finding_adapter_contract_holds() is True


def test_documents_current_nonfinite_fallback_behavior(db_session: Session) -> None:
    """Document the current known loss; this is not a prevention/regression gate.

    An eventual service repair must update this observation alongside the finding.
    This audit deliberately does not claim that current behavior is correct.
    """
    from sqlalchemy import select

    from lms.scheduling.models import ReviewCardState
    from lms.scheduling.service import schedule_from_attempt
    from tests.scheduling.test_review_queue import _make_attempt

    finding = additional_finding("insufficient-signal-success-fallback")
    assert finding.auto_filed_issue is False
    assert finding.bundled_repair is False

    probe = nonfinite_insufficient_signal_probe_record()
    adapter_rating = evidence_to_fsrs_rating(probe)
    assert adapter_rating.value == 1
    assert adapter_rating.rule_id == "insufficient-signal"
    assert adapter_rating.scheduling_included is True

    attempt, evidence = _make_attempt(
        db_session,
        correctness=True,
        confidence_rating=5,
        normalized_score=None,
    )
    evidence.raw_score = float("inf")
    evidence.max_score = 1.0
    evidence.normalized_score = None
    db_session.flush()

    rating = evidence_to_fsrs_rating(evidence)
    assert rating.value == 1
    assert rating.rule_id == "insufficient-signal"

    item = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    db_session.flush()
    card = db_session.scalars(select(ReviewCardState)).one()

    # Confirmed consumer loss: adapter Again is logged, but success mutates the card.
    assert item.decision_log["fsrs_rating"]["value"] == 1
    assert item.decision_log["fsrs_rating"]["rule_id"] == "insufficient-signal"
    assert item.decision_log["signal"] == "success"
    assert card.review_count == 1
    assert card.due_at is not None


@pytest.mark.parametrize("correctness", [None, True])
@pytest.mark.parametrize("confidence", [3, 5])
@pytest.mark.parametrize(
    ("normalized_score", "raw_score", "max_score"),
    [
        (float("nan"), None, None),
        (float("inf"), None, None),
        (float("-inf"), None, None),
        (None, float("nan"), 4.0),
        (None, float("inf"), 4.0),
        (None, float("-inf"), 4.0),
        (None, 3.0, float("nan")),
        (None, 3.0, float("inf")),
        (None, 3.0, float("-inf")),
        (None, 1e308, 1e-308),
    ],
    ids=[
        "normalized-nan",
        "normalized-inf",
        "normalized-negative-inf",
        "raw-nan",
        "raw-inf",
        "raw-negative-inf",
        "max-nan",
        "max-inf",
        "max-negative-inf",
        "ratio-overflow",
    ],
)
def test_non_finite_scores_schedule_conservatively(
    normalized_score: float | None,
    raw_score: float | None,
    max_score: float | None,
    correctness: bool | None,
    confidence: int,
) -> None:
    # Keep the non-finite values in memory: SQLite can coerce NaN to SQL NULL.
    record = EvidenceRecord(
        learner_id="learner-1",
        knowledge_node_id="node-1",
        normalized_score=normalized_score,
        raw_score=raw_score,
        max_score=max_score,
        correctness=correctness,
        confidence_rating=confidence,
        response_time_seconds=12,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.rule_id == "insufficient-signal"
    assert rating.scheduling_included is True
    assert _score(record) is None


@pytest.mark.parametrize("correctness", [False, True])
def test_non_finite_transfer_evidence_remains_excluded(correctness: bool) -> None:
    record = EvidenceRecord(
        learner_id="learner-1",
        knowledge_node_id="node-1",
        normalized_score=float("nan"),
        correctness=correctness,
        transfer_distance="near",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.rule_id == "transfer-excluded"
    assert rating.scheduling_included is False
    assert rating.value is None


def test_service_honors_adapter_eligibility_before_any_card_write(db_session, monkeypatch):
    from lms.scheduling import service
    from lms.scheduling.fsrs_adapter import FSRSRating
    from lms.scheduling.models import ReviewCardState
    from tests.scheduling.test_review_queue import _make_attempt

    attempt, evidence = _make_attempt(db_session)
    monkeypatch.setattr(
        service,
        "evidence_to_fsrs_rating",
        lambda _, **context: FSRSRating(
            label="excluded",
            value=None,
            scheduling_included=False,
            rule_id="custom-exclusion",
            reason="excluded",
        ),
    )
    outcome = service.schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    assert outcome.decision_log["rule"] == "custom-exclusion"
    assert outcome.due_at is None
    assert db_session.query(ReviewCardState).count() == 0


@pytest.mark.parametrize(
    "grade, median, seconds, expected",
    [
        ("correct", 20, 20, 4),
        ("correct", 20, 21, 3),
        ("correct", 10, 20, 3),
        ("correct", None, 1, 3),
        ("partial", 20, 20, 2),
        ("incorrect", 20, 20, 1),
    ],
)
def test_ui_self_grades_preserve_distinct_ratings(
    db_session: Session, grade: str, median: int | None, seconds: int, expected: int
) -> None:
    from lms.ui.attempts import _SELF_GRADES

    record = create_evidence_record(
        db_session,
        learner_id="l",
        knowledge_node_id="n",
        confidence_rating=5,
        response_time_seconds=seconds,
        **_SELF_GRADES[grade],
    )
    rating = evidence_to_fsrs_rating(record, prompt_class_median_seconds=median)
    assert rating.value == expected
    assert rating.scheduling_included is True


@pytest.mark.parametrize("correctness", [True, None])
def test_binary_mastery_without_confidence_keeps_good(db_session, correctness):
    record = create_evidence_record(
        db_session,
        learner_id="l",
        knowledge_node_id="n",
        scoring_method="binary",
        correctness=correctness,
        normalized_score=1.0,
    )
    rating = evidence_to_fsrs_rating(record)
    assert rating.value == 3
    assert rating.rule_id != "insufficient-signal"
