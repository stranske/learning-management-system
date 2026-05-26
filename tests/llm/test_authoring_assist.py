"""Tests for the authoring-assist proposal service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.auth.models import User
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.llm.authoring_assist import ProposalDraft, propose_authoring_drafts
from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig
from lms.llm.models import LLMSession
from lms.llm.providers import FakeProvider
from lms.sources.repository import create_source_reference


def _build_client() -> LLMClient:
    """Build a fake-provider LLM client for authoring-assist tests."""
    provider = FakeProvider()
    config = LLMConfig(
        mode_models={**DEFAULT_MODE_MODELS, "authoring-assist": "fake-authoring-model"},
        global_daily_cap_micro_usd=1_000_000,
        default_provider="fake",
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=1_000_000)
    return LLMClient(config=config, providers={"fake": provider}, budget=budget)


def _seed_proposal_dependencies(session: Session) -> dict[str, str]:
    user = User(id="user-bea", email="bea@example.test", username="bea", display_name="Bea")
    session.add(user)
    session.flush()
    node = create_knowledge_node(
        session,
        title="Spaced retrieval",
        knowledge_type="conceptual",
        scope="personal",
        status="published",
        actor_id="user:bea",
    )
    learner = create_learner_for_user(
        session,
        user_id=user.id,
        display_name="Bea",
    )
    goal = create_learning_goal(
        session,
        learner_id=learner.id,
        title="Learn spaced retrieval",
        knowledge_type="conceptual",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    source = create_source_reference(
        session,
        source_type="url",
        stable_locator="https://example.test/spaced-retrieval",
        content="spacing improves long-term retention by re-introducing forgetting",
        actor_id="user:bea",
    )
    session.commit()
    return {
        "node_id": node.id,
        "goal_id": goal.id,
        "source_id": source.id,
        "learner_id": learner.id,
    }


def _draft() -> ProposalDraft:
    return ProposalDraft(
        related_node_title="Retrieval interval calibration",
        related_node_knowledge_type="conceptual",
        related_node_description="Adjust gaps between practice based on recall success.",
        prompt_body="Explain how interval calibration extends retention.",
        prompt_knowledge_type="conceptual",
        prompt_intended_cognitive_action="explain",
        prompt_demand_level="medium",
        prompt_expected_answer_form="short-text",
        edge_type="encompassing",
    )


def test_proposed_node_and_prompt_are_draft_only(db_session: Session) -> None:
    """Authoring-assist proposals must create draft, llm-tagged artifacts."""
    ids = _seed_proposal_dependencies(db_session)
    result = propose_authoring_drafts(
        db_session,
        client=_build_client(),
        source_reference_id=ids["source_id"],
        target_node_id=ids["node_id"],
        learning_goal_id=ids["goal_id"],
        actor_id="user:bea",
        draft=_draft(),
        learner_id=ids["learner_id"],
    )
    db_session.commit()

    assert result.knowledge_node.status == "draft"
    assert result.knowledge_node.provenance == "llm-proposed"
    assert result.prompt.status == "draft"
    assert result.prompt.authoring_method == "llm-generated"
    assert result.knowledge_edge is not None
    assert result.knowledge_edge.status == "draft"


def test_proposal_records_model_and_session_id(db_session: Session) -> None:
    """Proposals must persist the LLM model and session id for audit and replay."""
    ids = _seed_proposal_dependencies(db_session)
    result = propose_authoring_drafts(
        db_session,
        client=_build_client(),
        source_reference_id=ids["source_id"],
        target_node_id=ids["node_id"],
        learning_goal_id=ids["goal_id"],
        actor_id="user:bea",
        draft=_draft(),
        learner_id=ids["learner_id"],
    )
    db_session.commit()

    assert result.llm_proposal.llm_model == "fake-authoring-model"
    assert result.llm_proposal.llm_session_id == result.llm_session.id
    assert result.llm_proposal.proposed_by == "user:bea"
    assert result.llm_proposal.knowledge_node_id == result.knowledge_node.id
    assert result.llm_proposal.prompt_id == result.prompt.id
    assert result.llm_proposal.source_reference_id == ids["source_id"]

    stored_session = db_session.get(LLMSession, result.llm_session.id)
    assert stored_session is not None
    assert stored_session.mode == "authoring-assist"
    assert stored_session.model == "fake-authoring-model"
    assert stored_session.trace_class in {"formative", "ephemeral"}
    assert stored_session.cost_micro_usd >= 0
    assert result.prompt.llm_model == "fake-authoring-model"


def test_proposal_records_audit_event(db_session: Session) -> None:
    """Proposals must leave an authoring audit trail for the reviewer."""
    ids = _seed_proposal_dependencies(db_session)
    result = propose_authoring_drafts(
        db_session,
        client=_build_client(),
        source_reference_id=ids["source_id"],
        target_node_id=ids["node_id"],
        learning_goal_id=ids["goal_id"],
        actor_id="user:bea",
        draft=_draft(),
        learner_id=ids["learner_id"],
    )
    db_session.commit()

    events = list(
        db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "Prompt",
                AuditLog.entity_id == result.prompt.id,
                AuditLog.action == "propose",
            )
        )
    )
    assert len(events) == 1
    summary = events[0].after_summary or {}
    assert summary.get("llm_proposal_id") == result.llm_proposal.id
    assert summary.get("llm_session_id") == result.llm_session.id
    assert summary.get("llm_model") == "fake-authoring-model"
