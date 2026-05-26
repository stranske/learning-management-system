"""Tests for publication-gated learning targets."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.graphs.repository import create_knowledge_node, require_published_prompt_target
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.llm.authoring_assist import ProposalDraft, propose_authoring_drafts
from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig
from lms.llm.providers import FakeProvider
from lms.prompts.repository import publish_prompt, require_publishable_prompt
from lms.sources.repository import create_source_reference


def test_prompt_target_rejects_draft_node(db_session: Session) -> None:
    """Prompt authoring cannot target draft knowledge nodes."""
    node = create_knowledge_node(
        db_session,
        title="Draft concept",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="draft",
    )

    with pytest.raises(ValueError, match="published knowledge nodes"):
        require_published_prompt_target(db_session, node_id=node.id, scope="personal")


def test_prompt_target_accepts_published_node(db_session: Session) -> None:
    """Published knowledge nodes pass the prompt-target gate."""
    node = create_knowledge_node(
        db_session,
        title="Published concept",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )

    assert require_published_prompt_target(db_session, node_id=node.id, scope="personal") == node


def _seed_authoring_assist_dependencies(db_session: Session) -> dict[str, str]:
    user = User(id="user-cas", email="cas@example.test", username="cas", display_name="Cas")
    db_session.add(user)
    db_session.flush()
    node = create_knowledge_node(
        db_session,
        title="Spacing effect",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:cas",
        status="published",
    )
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Cas")
    goal = create_learning_goal(
        db_session,
        learner_id=learner.id,
        title="Master spacing",
        knowledge_type="conceptual",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    source = create_source_reference(
        db_session,
        source_type="url",
        stable_locator="https://example.test/spacing",
        content="spacing improves long-term retention",
        actor_id="user:cas",
    )
    db_session.commit()
    return {
        "node_id": node.id,
        "goal_id": goal.id,
        "source_id": source.id,
    }


def _build_proposal_client() -> LLMClient:
    config = LLMConfig(
        mode_models={**DEFAULT_MODE_MODELS, "authoring-assist": "fake-authoring-model"},
        global_daily_cap_micro_usd=1_000_000,
        default_provider="fake",
    )
    return LLMClient(
        config=config,
        providers={"fake": FakeProvider()},
        budget=DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=1_000_000),
    )


def test_scheduler_rejects_llm_proposed_unapproved_prompt(db_session: Session) -> None:
    """A scheduler-facing gate refuses unpublished LLM-proposed prompts."""
    ids = _seed_authoring_assist_dependencies(db_session)
    result = propose_authoring_drafts(
        db_session,
        client=_build_proposal_client(),
        source_reference_id=ids["source_id"],
        target_node_id=ids["node_id"],
        learning_goal_id=ids["goal_id"],
        actor_id="user:cas",
        draft=ProposalDraft(
            related_node_title="Spacing intervals",
            related_node_knowledge_type="conceptual",
            prompt_body="Explain why expanding spacing improves retention.",
            prompt_knowledge_type="conceptual",
            prompt_intended_cognitive_action="explain",
            prompt_demand_level="medium",
            prompt_expected_answer_form="short-text",
        ),
    )
    db_session.commit()

    assert result.prompt.authoring_method == "llm-generated"
    assert result.prompt.status == "draft"

    with pytest.raises(ValueError, match="not publishable"):
        require_publishable_prompt(result.prompt)

    publish_prompt(db_session, result.prompt, reviewing_actor="reviewer:dee")
    db_session.commit()

    assert require_publishable_prompt(result.prompt) is result.prompt
