"""Tests for learner-facing LLM nudge controls."""

from __future__ import annotations

from lms.llm.interaction_policy import InteractionContext, decide_interaction_policy

from .test_study_coach_policy import _client


def test_quiet_mode_honored_after_policy_reminder() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="study-coach",
            learner_id="learner-1",
            prompt_id="prompt-1",
            user_message="Can you help me think this through?",
            coaching_intensity="quiet",
        )
    )

    assert decision.response_style == "quiet-mode"
    assert decision.direct_answer_allowed is True
    assert decision.disabled_supports == ("formative-nudges",)
    assert "brief reminder" in decision.next_action


def test_assessment_restricted_session_ignores_nudge_disable() -> None:
    decision = decide_interaction_policy(
        InteractionContext(
            mode="practice",
            learner_id="learner-1",
            user_message="Can you help me think this through?",
            assessment_restricted=True,
            coaching_intensity="quiet",
        )
    )

    assert decision.response_style == "assessment-nudge"
    assert decision.direct_answer_allowed is False
    assert decision.disabled_supports == ("hints", "direct-feedback")


def test_llm_session_response_includes_controls_model_and_cost() -> None:
    with _client() as (client, session_factory):
        response = client.post(
            "/llm/sessions",
            json={
                "learner_id": "learner-1",
                "mode": "study-coach",
                "prompt_id": "prompt-1",
                "user_message": "Can you orient me first?",
                "coaching_intensity": "quiet",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["coaching_intensity"] == "quiet"
        assert body["model"] == "fake-learning-policy"
        assert body["cost_micro_usd"] == body["cost_summary"]["cost_micro_usd"]
        assert body["cost_summary"]["input_tokens"] > 0
        assert body["trace_control_state"] == "default"
        with session_factory() as session:
            from lms.llm.models import LLMSession

            stored = session.get(LLMSession, body["session_id"])
        assert stored is not None
        assert stored.coaching_intensity == "quiet"
