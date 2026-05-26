"""Tests for study-coach and practice interaction policy."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.llm.models  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.db.base import Base
from lms.db.session import get_session
from lms.llm.interaction_policy import InteractionContext, decide_interaction_policy
from lms.llm.models import LLMSession
from lms.main import create_app


def test_answer_seeking_during_retrieval_gets_retrieval_nudge() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="study-coach",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="Just tell me the answer.",
            retrieval_active=True,
        )
    )

    assert decision.response_style == "retrieval-nudge"
    assert decision.direct_answer_allowed is False
    assert decision.learning_risk == "retrieval-practice-bypass"


def test_direct_explanation_allowed_for_orientation() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="study-coach",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="Can you explain the big picture first?",
            retrieval_active=False,
        )
    )

    assert decision.response_style == "direct-explanation"
    assert decision.direct_answer_allowed is True
    assert decision.next_action.startswith("Give a concise explanation")


def test_hint_overuse_fades_support() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="study-coach",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="Can I have another hint?",
            hint_count=2,
        )
    )

    assert decision.response_style == "hint-fade"
    assert decision.direct_answer_allowed is False
    assert decision.learning_risk == "support-dependence"


def test_high_confidence_wrong_attempt_triggers_calibration_nudge() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="practice",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="I'm pretty sure this is right.",
            confidence_rating=5,
            recent_attempt_correct=False,
        )
    )

    assert decision.response_style == "calibration-nudge"
    assert decision.direct_answer_allowed is False
    assert decision.learning_risk == "miscalibrated-confidence"


def test_passive_rereading_gets_retrieval_activation() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="study-coach",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="Can you read it again please?",
        )
    )

    assert decision.response_style == "retrieval-activation"
    assert decision.behavior == "passive-rereading"
    assert decision.direct_answer_allowed is False


def test_rapid_guessing_triggers_pace_control() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="practice",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="Next.",
            recent_incorrect_streak=2,
            recent_attempt_latency_seconds=8,
        )
    )

    assert decision.response_style == "pace-control"
    assert decision.behavior == "rapid-guessing"
    assert decision.direct_answer_allowed is False


def test_attempt_avoidance_requires_attempt_first() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="study-coach",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="Can you do it for me without trying?",
        )
    )

    assert decision.response_style == "attempt-first"
    assert decision.behavior == "avoidance-of-attempts"
    assert decision.direct_answer_allowed is False


def test_assessment_restriction_disables_hints_and_direct_answers() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="practice",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="Please explain the approach.",
            assessment_restricted=True,
        )
    )

    assert decision.direct_answer_allowed is False
    assert decision.disabled_supports == ("hints", "direct-feedback")


@contextmanager
def _client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        yield client, session_factory
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_post_llm_sessions_runs_fake_provider_study_coach_turn() -> None:
    with _client() as (client, session_factory):
        response = client.post(
            "/llm/sessions",
            json={
                "learner_id": "learner-1",
                "mode": "study-coach",
                "prompt_id": "prompt-1",
                "user_message": "Tell me the answer",
                "retrieval_active": True,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["policy_decision"]["response_style"] == "retrieval-nudge"
        with session_factory() as session:
            stored = session.get(LLMSession, body["session_id"])
        assert stored is not None
        assert stored.mode == "study-coach"


def test_assessment_restricted_default_turn_blocks_direct_answer() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="practice",
            learner_id="learner-1",
            user_message="What should I try next?",
            assessment_restricted=True,
        )
    )

    assert decision.direct_answer_allowed is False
    assert decision.response_style == "assessment-nudge"
    assert "direct answer" in decision.next_action
