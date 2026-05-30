"""Seed a deterministic Minimum Demo dataset through the real repository writers.

This is the production-shaped counterpart to ``src/lms/demo.py``'s smoke
fixtures. Where ``build_minimum_demo_smoke_summary()`` returns hard-coded
dataclasses (CI-safe, no DB writes), :func:`seed_minimum_demo` writes the same
six-part coverage matrix through the actual repository writers
(``create_source_reference``, ``create_knowledge_node``,
``create_learning_goal``, ``create_prompt``, ``publish_prompt``,
``create_attempt`` + evidence, ``create_review_queue_item``, ``LLMSession``)
so the persistence wiring of the Milestone-4 gate can be verified end-to-end.

The seed content is synthetic. The real owner-note slice remains the manual
protocol described in ``docs/handoff/minimum-demo-coverage.md``.

Reason codes
------------
The smoke fixture used illustrative names (``mixed-practice``,
``new-instruction``) that pre-date the scheduling model's
``CheckConstraint``. The real DB only accepts the codes declared in
``lms.scheduling.models.REASON_CODES``: ``new-learning``, ``due-review``,
``overdue``, ``remediation``, ``stale``, ``blocked-prerequisite``. The seeder
covers four distinct real codes so the acceptance criterion ("at least one of
each review reason code") is satisfied against the production schema, not the
fixture. The smoke output's fake labels remain for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.auth.repository import LOCAL_DEV_USERNAME, get_or_create_local_dev_user
from lms.evidence.models import EvidenceRecord
from lms.evidence.repository import create_attempt
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.llm.models import LLMSession
from lms.prompts.repository import create_prompt, publish_prompt
from lms.scheduling.repository import create_review_queue_item
from lms.sources.repository import create_source_reference

# Cognitive actions covered, three per note → 30 prompts across 10 notes.
SEED_COGNITIVE_ACTIONS: tuple[str, ...] = ("recall", "explain", "apply")

# Four distinct codes from REASON_CODES — the seeder cycles through them so
# every queue item has a valid code and all four show up in the live summary.
SEED_REASON_CODES: tuple[str, ...] = (
    "due-review",
    "remediation",
    "new-learning",
    "overdue",
)

# Default seed dimensions. Exposed as constants so the test can assert exact
# counts without re-computing the cross product inline. Derive the
# prompts-per-note from SEED_COGNITIVE_ACTIONS so the seed dimensions stay
# self-consistent: the seeding loop emits exactly one prompt per cognitive
# action per note, so hardcoding a separate count could drift from the actual
# number of created prompts and trip the zip(..., strict=True) loop below.
SEED_NOTE_COUNT: int = 10
SEED_PROMPTS_PER_NOTE: int = len(SEED_COGNITIVE_ACTIONS)
SEED_PROMPT_COUNT: int = SEED_NOTE_COUNT * SEED_PROMPTS_PER_NOTE


@dataclass(frozen=True)
class SeedResult:
    """Identifiers returned by :func:`seed_minimum_demo`.

    The CLI doesn't need these (it queries the DB by other means), but tests
    use them to verify that the writers produced the expected rows.
    """

    user_id: str
    learner_id: str
    goal_id: str
    node_ids: tuple[str, ...]
    source_reference_ids: tuple[str, ...]
    prompt_ids: tuple[str, ...]
    attempt_ids: tuple[str, ...]
    evidence_record_ids: tuple[str, ...]
    review_queue_item_ids: tuple[str, ...]
    llm_session_ids: tuple[str, ...]


def seed_minimum_demo(session: Session, *, actor_id: str = "system:demo-run") -> SeedResult:
    """Write a synthetic Minimum Demo dataset through the real repositories.

    Creates: 1 user, 1 learner, 10 published knowledge nodes, 10 source
    references, 1 learning goal targeting all nodes, 30 published prompts
    (3 per node), 30 attempts (1 per prompt) each with an evidence record,
    4 review queue items covering 4 distinct ``REASON_CODES``, and 1
    LLMSession row (mode=study-coach, trace_class=formative).

    The caller commits the session. The function flushes after each batch so
    SQL CHECK constraints surface immediately rather than at commit time.
    """
    user = get_or_create_local_dev_user(session)
    # The local-dev user already has username=local-dev. We reuse it instead
    # of creating a new credential row — the demo cares about persistence
    # wiring, not identity provisioning.
    assert user.username == LOCAL_DEV_USERNAME  # noqa: S101 (sanity check)

    learner = create_learner_for_user(
        session,
        user_id=user.id,
        display_name="Demo Learner",
    )
    session.flush()

    # 10 source references, one per note topic.
    source_reference_ids: list[str] = []
    node_ids: list[str] = []
    for index in range(1, SEED_NOTE_COUNT + 1):
        ref = create_source_reference(
            session,
            # ``internal-note`` is the SOURCE_TYPES entry that fits a
            # local synthetic note. ``markdown-file`` would also pass the
            # CHECK constraint but implies a real file on disk.
            source_type="internal-note",
            stable_locator=f"docs/demo/topic-{index:02d}.md",
            content=f"Demo note {index:02d} synthetic content for persistence testing.",
            actor_id=actor_id,
            source_visibility="local-only",
        )
        source_reference_ids.append(ref.id)

        node = create_knowledge_node(
            session,
            title=f"Demo topic {index:02d}",
            knowledge_type="conceptual",
            scope="personal",
            status="published",
            actor_id=actor_id,
            description=f"Synthetic node for demo topic {index:02d}.",
            source_reference_id=ref.id,
        )
        node_ids.append(node.id)
    session.flush()

    goal = create_learning_goal(
        session,
        learner_id=learner.id,
        title="Retain demo topic concepts",
        knowledge_type="conceptual",
        target_node_ids=node_ids,
        ownership_scope="personal",
    )
    session.flush()

    # 30 prompts: 3 cognitive actions per node, each tied to its source ref.
    prompt_ids: list[str] = []
    for node_index, node_id in enumerate(node_ids, start=1):
        for action in SEED_COGNITIVE_ACTIONS:
            prompt = create_prompt(
                session,
                target_node_id=node_id,
                learning_goal_id=goal.id,
                knowledge_type="conceptual",
                intended_cognitive_action=action,
                demand_level="medium",
                expected_answer_form="short-text",
                body=f"Demo prompt: {action} topic {node_index:02d}.",
                source_reference_ids=[source_reference_ids[node_index - 1]],
                authoring_method="human-authored",
                authoring_actor=actor_id,
            )
            # Publish so downstream consumers (review queue, mastery) treat
            # the prompt as live. publish_prompt takes the loaded Prompt
            # instance and a reviewing_actor; the function moves status
            # ``draft`` → ``published``.
            publish_prompt(session, prompt, reviewing_actor=actor_id)
            prompt_ids.append(prompt.id)
    session.flush()

    # 30 attempts + 30 evidence records (one each per prompt).
    attempt_ids: list[str] = []
    evidence_record_ids: list[str] = []
    for index, (prompt_id, node_id) in enumerate(
        zip(prompt_ids, _cycle_nodes(node_ids, SEED_PROMPT_COUNT), strict=True),
        start=1,
    ):
        attempt = create_attempt(
            session,
            learner_id=learner.id,
            prompt_id=prompt_id,
            response_text=f"Demo attempt {index:02d} response.",
            feedback={
                "goal": "Demonstrate retrieval of the cited concept",
                "observed_evidence": f"Attempt {index:02d} surfaced the key idea",
                "next_action": "Schedule a follow-up review",
            },
            confidence_rating=((index - 1) % 5) + 1,
            elapsed_seconds=30 + (index % 20),
            evidence={
                "knowledge_node_id": node_id,
                "evidence_kind": "observed",
                # correctness is a Boolean column on EvidenceRecord; use True
                # most of the time and seed a few False rows so the data
                # isn't artificially uniform.
                "correctness": (index % 4) != 0,
                "normalized_score": 0.55 + ((index % 5) * 0.08),
                "knowledge_type": "conceptual",
                "demand_level": "medium",
            },
        )
        attempt_ids.append(attempt.id)
        # The evidence record id isn't returned by create_attempt; we query
        # it back from the attempt's relationship — each attempt produces
        # exactly one record (the evidence dict above has a scoring signal).
        ev_id = session.scalar(
            select(EvidenceRecord.id).where(EvidenceRecord.attempt_id == attempt.id)
        )
        if ev_id is None:
            raise RuntimeError(f"seed_minimum_demo: attempt {attempt.id} produced no evidence row")
        evidence_record_ids.append(ev_id)
    session.flush()

    # Review queue items covering all four REASON_CODES we care about.
    review_queue_item_ids: list[str] = []
    base_time = datetime.now(UTC)
    for index, reason_code in enumerate(SEED_REASON_CODES):
        item = create_review_queue_item(
            session,
            learner_id=learner.id,
            knowledge_node_id=node_ids[index % len(node_ids)],
            reason_code=reason_code,
            reason_explanation=f"Synthetic {reason_code} entry for demo.",
            due_at=base_time + timedelta(days=index),
            decision_log={"source": "demo-seed", "reason_code": reason_code},
            source_attempt_id=attempt_ids[index % len(attempt_ids)],
            source_evidence_record_id=evidence_record_ids[index % len(evidence_record_ids)],
        )
        review_queue_item_ids.append(item.id)
    session.flush()

    # One LLMSession row, mode=study-coach, trace_class=formative, fake provider.
    llm_session_ids: list[str] = []
    llm_session = LLMSession(
        mode="study-coach",
        trace_class="formative",
        provider="fake",
        model="fake-learning-policy",
        learner_id=learner.id,
        # COACHING_INTENSITIES: ("full", "light", "quiet"). ``light`` matches
        # the formative study-coach role best.
        coaching_intensity="light",
        input_tokens=120,
        output_tokens=80,
        cost_micro_usd=250,
        redaction_applied=False,
        redacted_span_count=0,
        external_export_allowed=False,
        response_summary="Demo formative coaching turn — synthetic content.",
        is_replay=False,
    )
    session.add(llm_session)
    session.flush()
    llm_session_ids.append(llm_session.id)

    return SeedResult(
        user_id=user.id,
        learner_id=learner.id,
        goal_id=goal.id,
        node_ids=tuple(node_ids),
        source_reference_ids=tuple(source_reference_ids),
        prompt_ids=tuple(prompt_ids),
        attempt_ids=tuple(attempt_ids),
        evidence_record_ids=tuple(evidence_record_ids),
        review_queue_item_ids=tuple(review_queue_item_ids),
        llm_session_ids=tuple(llm_session_ids),
    )


def _cycle_nodes(node_ids: list[str], target_count: int) -> list[str]:
    """Return ``target_count`` node ids by cycling through ``node_ids``.

    With 10 nodes and 30 prompts we get exactly 3 prompts per node when the
    cycle is in lockstep with the cognitive action triplet — but expressing
    it via cycle keeps the count flexible if the seed dimensions ever change.
    """
    if not node_ids:
        raise ValueError("node_ids must be non-empty")
    return [node_ids[(i // SEED_PROMPTS_PER_NOTE) % len(node_ids)] for i in range(target_count)]


__all__: tuple[str, ...] = (
    "SEED_COGNITIVE_ACTIONS",
    "SEED_NOTE_COUNT",
    "SEED_PROMPTS_PER_NOTE",
    "SEED_PROMPT_COUNT",
    "SEED_REASON_CODES",
    "SeedResult",
    "seed_minimum_demo",
)


# Mypy: silence the runtime-only Any leak from feedback's payload dicts.
_ATTEMPT_FEEDBACK_TYPE = dict[str, Any]
