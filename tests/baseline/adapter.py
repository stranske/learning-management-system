"""App-specific adapter for the LMS spaced-repetition scheduler.

This is the ONLY app-specific piece the shared ``baseline_kit`` needs: a way to
turn an input (here, a learner *attempt/evidence signal* plus optional prior
history) into a flat dict of named scalar metrics. Everything else --
directional checks, invariants, golden masters, the coverage manifest -- is
generic and lives in ``baseline_kit``.

Target surface
--------------
``lms.scheduling.service.schedule_from_attempt`` -- the v1 review scheduler.
It is DB-backed (takes a SQLAlchemy ``Session``, reads prior completed reviews,
writes durable rows), so unlike a pure compute the adapter stands up an
in-memory SQLite session per scenario, seeds prior history, runs the scheduler
at a FIXED ``now``, then reduces the emitted ``ReviewQueueItem`` to scalars.

Scenario model
--------------
A *scenario* (``catalog.yaml`` ``scenarios``) is a flat bundle of the evidence
signal fields the scheduler keys on, plus optional prior history:

* ``correctness``            -- bool | None (retrieval correct?)
* ``normalized_score``       -- float in [0, 1] | None (rubric fraction)
* ``confidence_rating``      -- int 1..5 | None (self-rated confidence)
* ``support_level``          -- one of SUPPORT_LEVELS ("none", "hint", ...)
* ``response_time_seconds``  -- int | None (latency; gates FSRS "easy")
* ``transfer_distance``      -- str | None ("near"/"far"/"novel" => FSRS excluded)
* ``prior_successes``        -- int >= 0 completed prior reviews to SEED first
                                (each one steps the success interval ramp)

The same learner + knowledge node is reused across the seeded history and the
final scored attempt so ``_count_prior_successful_reviews`` sees them.

Metric flattening
-----------------
``schedule_from_attempt`` returns one ``ReviewQueueItem`` (plus a decision log).
We reduce it to named scalars (see ``METRIC_NAMES``). The LMS scheduler is a
fixed-ramp policy, NOT classic SM-2: there is no per-item ``ease_factor`` or
mutable ``repetition_count`` stored on the item. The faithful analogues are:

* ``next_interval_days``  -- days from ``now`` to the emitted ``due_at``
  (0 for an immediate remediation; 1/3/7/14/28 up the success ramp;
  1 for a low-confidence success).
* ``repetition_count``    -- the ``prior_successful_reviews`` count the scheduler
  read; this is what advances the ramp (the system's repetition analogue).
* ``fsrs_rating_value``   -- the deterministic FSRS rating (1=again .. 4=easy,
  0 when the rating is "excluded"/None). This is the closest "ease/grade"-like
  severity signal the surface actually produces -- there is deliberately no
  invented ease_factor.
* ``signal_severity``     -- the blended internal signal as an ordinal
  (0=fail, 1=low-confidence-success, 2=success).
* ``priority``            -- the queue priority the policy assigns.
* ``is_reset``            -- 1 when the decision resets the schedule to an
  immediate remediation item (a failed retrieval), else 0.
* ``is_remediation`` / ``is_due_review`` -- one-hot reason-code flags.
* ``fsrs_scheduling_included`` -- 1 when the FSRS rating feeds the interval, else 0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# The scalar metric names this surface reduces to (the kit's coverage space).
METRIC_NAMES: tuple[str, ...] = (
    "next_interval_days",
    "repetition_count",
    "fsrs_rating_value",
    "signal_severity",
    "priority",
    "is_reset",
    "is_remediation",
    "is_due_review",
    "fsrs_scheduling_included",
)

# A single deterministic reference instant shared by every scenario so the
# emitted ``due_at`` offsets are stable and golden-able.
FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

# Maps the blended internal signal string to an ordinal severity (low = worse
# retrieval). Mirrors ``lms.scheduling.service._SIGNAL_ORDER`` exactly.
_SIGNAL_SEVERITY: dict[str, int] = {
    "fail": 0,
    "low-confidence-success": 1,
    "success": 2,
}


def _make_session() -> Any:
    """Stand up an isolated in-memory SQLite session with all LMS tables.

    Mirrors the ``db_session`` fixture in ``tests/conftest.py`` -- importing the
    model modules registers them on ``Base.metadata`` before ``create_all``.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import lms.audit.models  # noqa: F401  # register Base.metadata
    import lms.evidence.models  # noqa: F401  # register Base.metadata
    import lms.feedback.models  # noqa: F401  # register Base.metadata
    import lms.graphs.models  # noqa: F401  # register Base.metadata
    import lms.learners.models  # noqa: F401  # register Base.metadata
    import lms.llm.models  # noqa: F401  # register Base.metadata
    import lms.prompts.models  # noqa: F401  # register Base.metadata
    import lms.scheduling.models  # noqa: F401  # register Base.metadata
    import lms.sources.models  # noqa: F401  # register Base.metadata
    from lms.db.base import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return factory()


def _make_attempt(
    session: Any,
    *,
    learner_id: str,
    knowledge_node_id: str,
    prompt_id: str,
    correctness: bool | None,
    normalized_score: float | None,
    confidence_rating: int | None,
    support_level: str,
    response_time_seconds: int | None,
    transfer_distance: str | None,
    response_metadata: dict[str, Any] | None,
) -> tuple[Any, Any]:
    """Create an Attempt with a linked EvidenceRecord carrying the signal.

    Built directly via the evidence repository so the scheduler sees the same
    shapes production uses (this mirrors ``tests/scheduling`` fixtures).
    """
    from lms.evidence.repository import create_attempt

    attempt = create_attempt(
        session,
        learner_id=learner_id,
        prompt_id=prompt_id,
        response_text="baseline-kit response",
        feedback={"goal": "g", "observed_evidence": "o", "next_action": "n"},
        response_metadata=response_metadata,
        confidence_rating=confidence_rating,
        support_level=support_level,
        evidence={
            "knowledge_node_id": knowledge_node_id,
            "evidence_kind": "observed",
            "correctness": correctness,
            "normalized_score": normalized_score,
            "confidence_rating": confidence_rating,
            "support_level": support_level,
            "response_time_seconds": response_time_seconds,
            "transfer_distance": transfer_distance,
        },
    )
    return attempt, attempt.evidence_records[0]


def run_scenario(scenario: dict[str, Any]) -> dict[str, float | int]:
    """Run ``schedule_from_attempt`` for one scenario and flatten to scalars.

    Seeds ``prior_successes`` completed reviews on the same learner+node first
    (so the success ramp advances), then scores the scenario's attempt at
    ``FIXED_NOW`` and reduces the resulting queue item to a flat metrics dict.
    """
    from lms.scheduling.service import schedule_from_attempt

    session = _make_session()
    try:
        learner_id = "baseline-learner"
        node_id = "baseline-node"
        prior = int(scenario.get("prior_successes", 0) or 0)

        # Seed prior COMPLETED successful reviews to step the ramp. Each seed is a
        # confident, unsupported correct retrieval -> a "success" signal.
        for index in range(prior):
            seed_attempt, seed_evidence = _make_attempt(
                session,
                learner_id=learner_id,
                knowledge_node_id=node_id,
                prompt_id=f"seed-prompt-{index}",
                correctness=True,
                normalized_score=0.95,
                confidence_rating=5,
                support_level="none",
                response_time_seconds=60,
                transfer_distance=None,
                response_metadata=None,
            )
            seed_item = schedule_from_attempt(
                session,
                attempt=seed_attempt,
                evidence_record=seed_evidence,
                now=FIXED_NOW,
            )
            seed_item.status = "completed"
            session.flush()

        attempt, evidence = _make_attempt(
            session,
            learner_id=learner_id,
            knowledge_node_id=node_id,
            prompt_id="scored-prompt",
            correctness=scenario.get("correctness"),
            normalized_score=scenario.get("normalized_score"),
            confidence_rating=scenario.get("confidence_rating"),
            support_level=scenario.get("support_level", "none"),
            response_time_seconds=scenario.get("response_time_seconds"),
            transfer_distance=scenario.get("transfer_distance"),
            response_metadata=scenario.get("response_metadata"),
        )
        item = schedule_from_attempt(
            session,
            attempt=attempt,
            evidence_record=evidence,
            now=FIXED_NOW,
        )
        session.flush()
        return _flatten(item, prior_successes=prior)
    finally:
        session.close()


def _flatten(item: Any, *, prior_successes: int) -> dict[str, float | int]:
    """Reduce a ReviewQueueItem + its decision log to named scalars."""
    log = item.decision_log
    signal = str(log["signal"])
    fsrs = log["fsrs_rating"]
    fsrs_value = fsrs.get("value")
    reason_code = item.reason_code

    interval_days = round((item.due_at - FIXED_NOW).total_seconds() / 86400.0)
    return {
        "next_interval_days": int(interval_days),
        # The scheduler reads prior_successful_reviews to advance the ramp; that
        # count is the system's repetition analogue (no mutable per-item counter).
        "repetition_count": int(log["inputs"]["prior_successful_reviews"]),
        # FSRS rating value: 1=again .. 4=easy; 0 when excluded/None.
        "fsrs_rating_value": int(fsrs_value) if fsrs_value is not None else 0,
        "signal_severity": int(_SIGNAL_SEVERITY[signal]),
        "priority": float(item.priority),
        # A failed retrieval resets the schedule to an immediate remediation item.
        "is_reset": 1 if reason_code == "remediation" else 0,
        "is_remediation": 1 if reason_code == "remediation" else 0,
        "is_due_review": 1 if reason_code == "due-review" else 0,
        "fsrs_scheduling_included": 1 if fsrs.get("scheduling_included") else 0,
    }


def metric_names() -> list[str]:
    return list(METRIC_NAMES)
