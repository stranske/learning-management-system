"""Minimum Demo coverage fixtures and live-query reporting.

Two paths share this module:

- ``build_minimum_demo_smoke_summary`` returns hard-coded dataclasses for the
  CI-safe ``lms demo smoke`` command. No DB writes happen; this only proves
  the coverage matrix can be rendered without provider credentials or a
  30-day wait.
- ``compute_live_demo_summary`` (added 2026-05-30, issue #181) queries a real
  DB session that was first populated via :func:`lms.demo_seed.seed_minimum_demo`,
  so the Milestone-4 persistence wiring can be verified end-to-end. The live
  path is exposed via ``lms demo run``.

The two paths intentionally share the renderer line format so observers can
compare the same six-part coverage matrix across smoke vs. real-persistence
runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from lms.evidence.models import Attempt, EvidenceRecord
from lms.llm.models import LLMSession
from lms.prompts.models import Prompt
from lms.scheduling.models import ReviewQueueItem
from lms.sources.models import SourceReference

DEMO_REQUIREMENTS: tuple[str, ...] = (
    "10 notes",
    "30 prompts",
    "attempts and evidence",
    "review queue reason codes",
    "Inspect mastery data",
    "study-coach sessions and cost summary",
)


@dataclass(frozen=True)
class DemoNote:
    """A seeded source note used by the CI-safe demo smoke path."""

    note_id: str
    topic: str
    stable_locator: str


@dataclass(frozen=True)
class DemoPrompt:
    """A source-cited retrieval prompt generated from a demo note."""

    prompt_id: str
    note_id: str
    cognitive_action: str
    source_locator: str


@dataclass(frozen=True)
class DemoAttempt:
    """A simulated learner attempt with calibration metadata."""

    attempt_id: str
    prompt_id: str
    confidence_rating: int
    elapsed_seconds: int


@dataclass(frozen=True)
class DemoEvidence:
    """A verbose evidence row produced from a simulated attempt."""

    evidence_id: str
    attempt_id: str
    normalized_score: float
    review_reason_code: str


@dataclass(frozen=True)
class DemoInspectRow:
    """Inspect-facing mastery and scheduler summary for one topic."""

    topic: str
    mastery_score: float
    reason_code: str


@dataclass(frozen=True)
class DemoLLMSession:
    """A fake-provider study-coach session with trace and cost metadata."""

    session_id: str
    topic: str
    mode: str
    trace_class: str
    cost_micro_usd: int


@dataclass(frozen=True)
class DemoSmokeSummary:
    """Aggregate counts emitted by the Minimum Demo smoke command."""

    notes: tuple[DemoNote, ...]
    prompts: tuple[DemoPrompt, ...]
    attempts: tuple[DemoAttempt, ...]
    evidence: tuple[DemoEvidence, ...]
    inspect_rows: tuple[DemoInspectRow, ...]
    llm_sessions: tuple[DemoLLMSession, ...]
    coverage_matrix: tuple[tuple[str, str], ...]

    @property
    def review_reason_codes(self) -> tuple[str, ...]:
        """Return the distinct scheduler reason codes represented in the smoke data."""
        return tuple(sorted({row.review_reason_code for row in self.evidence}))

    @property
    def daily_cost_micro_usd(self) -> int:
        """Return the fake-provider daily LLM cost total."""
        return sum(session.cost_micro_usd for session in self.llm_sessions)


def build_minimum_demo_smoke_summary() -> DemoSmokeSummary:
    """Build a deterministic, CI-safe Minimum Demo smoke summary.

    The smoke path intentionally uses local fake data. Its job is to prove that
    the six-part demo can be exercised without real provider credentials or the
    actual day-30 waiting period.
    """
    notes = tuple(
        DemoNote(
            note_id=f"note-{index:02d}",
            topic=f"Topic {index:02d}",
            stable_locator=f"docs/demo/minimum-demo.md#topic-{index:02d}",
        )
        for index in range(1, 11)
    )
    actions = ("recall", "explain", "apply")
    prompts = tuple(
        DemoPrompt(
            prompt_id=f"prompt-{note_index:02d}-{action}",
            note_id=note.note_id,
            cognitive_action=action,
            source_locator=note.stable_locator,
        )
        for note_index, note in enumerate(notes, start=1)
        for action in actions
    )
    attempts = tuple(
        DemoAttempt(
            attempt_id=f"attempt-{index:02d}",
            prompt_id=prompt.prompt_id,
            confidence_rating=(index % 5) + 1,
            elapsed_seconds=35 + index,
        )
        for index, prompt in enumerate(prompts, start=1)
    )
    reason_cycle = ("due-review", "remediation", "mixed-practice", "new-instruction")
    evidence = tuple(
        DemoEvidence(
            evidence_id=f"evidence-{index:02d}",
            attempt_id=attempt.attempt_id,
            normalized_score=0.55 + ((index % 5) * 0.08),
            review_reason_code=reason_cycle[(index - 1) % len(reason_cycle)],
        )
        for index, attempt in enumerate(attempts, start=1)
    )
    inspect_rows = tuple(
        DemoInspectRow(
            topic=note.topic,
            mastery_score=0.50 + (index * 0.035),
            reason_code=reason_cycle[(index - 1) % len(reason_cycle)],
        )
        for index, note in enumerate(notes, start=1)
    )
    llm_sessions = tuple(
        DemoLLMSession(
            session_id=f"llm-session-{index:02d}",
            topic=note.topic,
            mode="study-coach",
            trace_class="formative",
            cost_micro_usd=125 + index,
        )
        for index, note in enumerate(notes, start=1)
    )
    coverage_evidence = (
        "seeded DemoNote records with stable source locators",
        "three source-cited prompts per note",
        "one confidence-rated attempt and evidence row per prompt",
        "due-review, remediation, mixed-practice, new-instruction",
        "one Inspect mastery row per topic",
        "one fake-provider formative session per topic",
    )
    coverage_matrix = tuple(zip(DEMO_REQUIREMENTS, coverage_evidence, strict=True))
    return DemoSmokeSummary(
        notes=notes,
        prompts=prompts,
        attempts=attempts,
        evidence=evidence,
        inspect_rows=inspect_rows,
        llm_sessions=llm_sessions,
        coverage_matrix=coverage_matrix,
    )


def render_minimum_demo_smoke(summary: DemoSmokeSummary) -> str:
    """Render the Minimum Demo smoke summary for CLI output."""
    lines = [
        "minimum demo smoke: ok",
        f"notes={len(summary.notes)}",
        f"prompts={len(summary.prompts)}",
        f"attempts={len(summary.attempts)}",
        f"evidence_rows={len(summary.evidence)}",
        f"review_queue_reason_codes={','.join(summary.review_reason_codes)}",
        f"inspect_rows={len(summary.inspect_rows)}",
        f"study_coach_sessions={len(summary.llm_sessions)}",
        f"daily_cost_micro_usd={summary.daily_cost_micro_usd}",
        "coverage_matrix:",
    ]
    lines.extend(
        f"- {requirement}: {evidence}" for requirement, evidence in summary.coverage_matrix
    )
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Live-query path (issue #181): the same coverage shape, sourced from DB rows.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class DemoLiveSummary:
    """Aggregate counts derived from real DB rows after ``demo run`` seeds them.

    Every field comes from a ``select(...)`` query against the live session;
    nothing is fixture-derived. This is the type the ``lms demo run`` CLI
    prints, and it's the contract the persistence-wiring test asserts on.
    """

    source_reference_count: int
    prompt_count: int
    attempt_count: int
    evidence_record_count: int
    review_reason_codes: tuple[str, ...]
    inspect_row_count: int
    study_coach_session_count: int
    daily_cost_micro_usd: int


def compute_live_demo_summary(session: Session) -> DemoLiveSummary:
    """Return a :class:`DemoLiveSummary` aggregated from real DB rows.

    Run this AFTER seeding (via ``lms.demo_seed.seed_minimum_demo``). Every
    count is a fresh ``select(count(...))`` so the renderer can never disagree
    with what is actually in the database — there's no intermediate fixture.

    The ``inspect_row_count`` is the number of distinct knowledge nodes that
    have at least one EvidenceRecord — i.e., topics the Inspect mastery view
    has data for. This mirrors the smoke fixture's ``inspect_rows`` (one per
    topic) but derives it from real attempts rather than a hard-coded loop.

    The ``daily_cost_micro_usd`` is the sum of ``LLMSession.cost_micro_usd``
    across all rows tagged with the study-coach mode — matching the smoke
    output's "daily cost summary" line.
    """
    source_reference_count = _scalar_count(session, select(func.count(SourceReference.id)))
    prompt_count = _scalar_count(session, select(func.count(Prompt.id)))
    attempt_count = _scalar_count(session, select(func.count(Attempt.id)))
    evidence_record_count = _scalar_count(session, select(func.count(EvidenceRecord.id)))

    reason_code_rows = session.execute(
        select(ReviewQueueItem.reason_code).distinct().order_by(ReviewQueueItem.reason_code)
    ).all()
    review_reason_codes = tuple(row[0] for row in reason_code_rows)

    # Inspect mastery row count: distinct knowledge nodes with ≥1 evidence row.
    inspect_row_count = _scalar_count(
        session,
        select(func.count(func.distinct(EvidenceRecord.knowledge_node_id))),
    )

    study_coach_session_count = _scalar_count(
        session,
        select(func.count(LLMSession.id)).where(LLMSession.mode == "study-coach"),
    )

    daily_cost = session.scalar(
        select(func.coalesce(func.sum(LLMSession.cost_micro_usd), 0)).where(
            LLMSession.mode == "study-coach"
        )
    )

    return DemoLiveSummary(
        source_reference_count=source_reference_count,
        prompt_count=prompt_count,
        attempt_count=attempt_count,
        evidence_record_count=evidence_record_count,
        review_reason_codes=review_reason_codes,
        inspect_row_count=inspect_row_count,
        study_coach_session_count=study_coach_session_count,
        daily_cost_micro_usd=int(daily_cost or 0),
    )


def render_live_demo_summary(summary: DemoLiveSummary) -> str:
    """Render :class:`DemoLiveSummary` in the same line format as the smoke renderer.

    Keeping the line shape identical means observers can diff smoke vs. run
    output and reason about persistence-wiring gaps directly. The header line
    is ``minimum demo run: ok`` (vs. ``smoke: ok``) so log scrapers can tell
    the two apart.
    """
    lines = [
        "minimum demo run: ok",
        f"notes={summary.source_reference_count}",
        f"prompts={summary.prompt_count}",
        f"attempts={summary.attempt_count}",
        f"evidence_rows={summary.evidence_record_count}",
        f"review_queue_reason_codes={','.join(summary.review_reason_codes)}",
        f"inspect_rows={summary.inspect_row_count}",
        f"study_coach_sessions={summary.study_coach_session_count}",
        f"daily_cost_micro_usd={summary.daily_cost_micro_usd}",
    ]
    return "\n".join(lines)


def _scalar_count(session: Session, stmt: Select[tuple[int]]) -> int:
    """Run a ``select(func.count(...))`` and return the result as a plain int.

    SQLAlchemy returns ``int | None`` from ``scalar()``. Coercing to int with
    a 0 fallback keeps callers' type annotations clean and avoids an
    ``Optional[int]`` leaking into the summary dataclass.
    """
    result = session.scalar(stmt)
    return int(result or 0)
