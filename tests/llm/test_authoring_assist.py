"""Tests for the authoring-assist proposal service."""

from __future__ import annotations

from typing import cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.audit.models import AuditLog
from lms.auth.login import require_authenticated_user
from lms.auth.models import User
from lms.graphs.repository import create_knowledge_node
from lms.learners.models import LearningGoal
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.llm import api as llm_api
from lms.llm.authoring_assist import ProposalDraft, propose_authoring_drafts
from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig
from lms.llm.models import LLMSession
from lms.llm.proposals import LLMProposal
from lms.llm.providers import FakeProvider
from lms.settings import Settings, get_settings
from lms.sources.models import SourceReference
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


def test_proposal_persists_provider_text_as_generated_artifacts(db_session: Session) -> None:
    """Persisted proposal content must come from the LLM response, not only the input draft."""
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

    generated_body = result.prompt.versions[0].body
    assert generated_body != _draft().prompt_body
    assert "Mode: authoring-assist" in generated_body
    assert "https://example.test/spaced-retrieval" in generated_body
    assert result.knowledge_node.description == generated_body


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


def test_proposal_links_knowledge_node_to_source_reference(db_session: Session) -> None:
    """The proposed knowledge node must link back to the originating SourceReference."""
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

    assert result.knowledge_node.source_reference_id == ids["source_id"]
    assert result.llm_proposal.source_reference_id == ids["source_id"]


def test_proposal_inherits_local_only_source_visibility(db_session: Session) -> None:
    """Proposals from local-only sources link to that source, inheriting its visibility constraint."""
    user = User(id="user-loc", email="loc@example.test", username="loc", display_name="Loc")
    db_session.add(user)
    db_session.flush()
    node = create_knowledge_node(
        db_session,
        title="Local concept",
        knowledge_type="factual",
        scope="personal",
        actor_id="user:loc",
        status="published",
    )
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Loc")
    goal = create_learning_goal(
        db_session,
        learner_id=learner.id,
        title="Local goal",
        knowledge_type="factual",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    local_source = create_source_reference(
        db_session,
        source_type="internal-note",
        stable_locator="internal:local-only-note",
        content="private local observation",
        actor_id="user:loc",
        source_visibility="local-only",
    )
    db_session.commit()

    result = propose_authoring_drafts(
        db_session,
        client=_build_client(),
        source_reference_id=local_source.id,
        target_node_id=node.id,
        learning_goal_id=goal.id,
        actor_id="user:loc",
        draft=ProposalDraft(
            related_node_title="Local subtopic",
            related_node_knowledge_type="factual",
            prompt_body="What does the local note say?",
            prompt_knowledge_type="factual",
            prompt_intended_cognitive_action="recall",
            prompt_demand_level="low",
            prompt_expected_answer_form="short-text",
        ),
        learner_id=learner.id,
    )
    db_session.commit()

    linked = db_session.get(SourceReference, result.knowledge_node.source_reference_id)
    assert linked is not None
    assert linked.source_visibility == "local-only"


def test_proposal_trace_and_cost_recorded_through_llm_wrapper(db_session: Session) -> None:
    """Proposals must record formative trace class and positive cost through the LLM wrapper."""
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

    stored = db_session.get(LLMSession, result.llm_session.id)
    assert stored is not None
    assert stored.trace_class == "formative"
    assert stored.cost_micro_usd > 0
    assert stored.input_tokens > 0
    assert stored.output_tokens > 0
    assert stored.mode == "authoring-assist"


def test_authoring_assist_route_uses_source_safe_fake_provider(db_session: Session) -> None:
    """The HTTP route's default fake provider must satisfy source constraints."""
    llm_api._default_client.cache_clear()
    ids = _seed_proposal_dependencies(db_session)

    response = llm_api.authoring_assist_propose_route(
        llm_api.AuthoringAssistProposeRequest(
            source_reference_id=ids["source_id"],
            target_node_id=ids["node_id"],
            learning_goal_id=ids["goal_id"],
            actor_id="user:bea",
            related_node_title="Retrieval interval calibration",
            related_node_knowledge_type="conceptual",
            prompt_body="Explain how interval calibration extends retention.",
            prompt_knowledge_type="conceptual",
            prompt_intended_cognitive_action="explain",
            prompt_demand_level="medium",
            prompt_expected_answer_form="short-text",
            related_node_description="Adjust gaps between practice.",
            edge_type="encompassing",
            learner_id=ids["learner_id"],
        ),
        db_session,
        current_user=User(id="user-bea"),
        settings=Settings(auth_required=False),
    )

    assert response.llm_model == "fake-learning-policy"
    assert response.node_status == "draft"
    assert response.prompt_authoring_method == "llm-generated"


def test_authoring_assist_route_validation_errors_are_422(
    db_session: Session, monkeypatch: MonkeyPatch
) -> None:
    """Repository and source-constraint failures should map to validation errors."""
    ids = _seed_proposal_dependencies(db_session)

    try:
        llm_api.authoring_assist_propose_route(
            llm_api.AuthoringAssistProposeRequest(
                source_reference_id=ids["source_id"],
                target_node_id="missing-node",
                learning_goal_id=ids["goal_id"],
                actor_id="user:bea",
                related_node_title="Retrieval interval calibration",
                related_node_knowledge_type="conceptual",
                prompt_body="Explain how interval calibration extends retention.",
                prompt_knowledge_type="conceptual",
                prompt_intended_cognitive_action="explain",
                prompt_demand_level="medium",
                prompt_expected_answer_form="short-text",
            ),
            db_session,
            current_user=User(id="user-bea"),
            settings=Settings(auth_required=False),
        )
    except HTTPException as exc:
        assert exc.status_code == 422
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected HTTPException")

    bad_provider = FakeProvider(responder=lambda _model, _prompt: "uncited generated text")
    bad_client = LLMClient(
        config=LLMConfig(
            mode_models={**DEFAULT_MODE_MODELS, "authoring-assist": "fake-authoring-model"},
            global_daily_cap_micro_usd=1_000_000,
            default_provider="fake",
        ),
        providers={"fake": bad_provider},
        budget=DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=1_000_000),
    )
    monkeypatch.setattr(llm_api, "_default_client", lambda: bad_client)
    try:
        llm_api.authoring_assist_propose_route(
            llm_api.AuthoringAssistProposeRequest(
                source_reference_id=ids["source_id"],
                target_node_id=ids["node_id"],
                learning_goal_id=ids["goal_id"],
                actor_id="user:bea",
                related_node_title="Retrieval interval calibration",
                related_node_knowledge_type="conceptual",
                prompt_body="Explain how interval calibration extends retention.",
                prompt_knowledge_type="conceptual",
                prompt_intended_cognitive_action="explain",
                prompt_demand_level="medium",
                prompt_expected_answer_form="short-text",
            ),
            db_session,
            current_user=User(id="user-bea"),
            settings=Settings(auth_required=False),
        )
    except HTTPException as exc:
        assert exc.status_code == 422
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected HTTPException")


@pytest.mark.parametrize(
    ("auth_required", "learner_kind", "goal_kind", "expected_status"),
    [
        (True, "own", "own", 200),
        (True, "omitted", "own", 200),
        (True, "null", "own", 200),
        (True, "foreign", "own", 404),
        (True, "missing", "own", 404),
        (True, "empty", "own", 404),
        (True, "own", "foreign", 404),
        (True, "second-own", "own", 404),
        (True, "omitted", "foreign", 404),
        (True, "null", "foreign", 404),
        (True, "own", "missing", 404),
        (False, "foreign", "own", 200),
        (False, "omitted", "foreign", 200),
    ],
)
def test_authoring_assist_route_learner_authorization(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: MonkeyPatch,
    auth_required: bool,
    learner_kind: str,
    goal_kind: str,
    expected_status: int,
) -> None:
    """Authorize both attribution and goal before provider access or draft writes."""
    client, session_factory = api_client
    with session_factory() as session:
        ids = _seed_proposal_dependencies(session)
        owner = session.get(User, "user-bea")
        assert owner is not None
        outsider = User(
            id="user-other", email="other@example.test", username="other", display_name="Other"
        )
        session.add(outsider)
        session.flush()
        foreign_learner = create_learner_for_user(
            session, user_id=outsider.id, display_name="Other"
        )
        second_learner = create_learner_for_user(session, user_id=owner.id, display_name="Second")
        foreign_goal = create_learning_goal(
            session,
            learner_id=foreign_learner.id,
            title="Other goal",
            knowledge_type="conceptual",
            target_node_ids=[ids["node_id"]],
            ownership_scope="personal",
        )
        session.commit()
        learner_ids = {
            "own": ids["learner_id"],
            "foreign": foreign_learner.id,
            "second-own": second_learner.id,
            "missing": "missing-learner",
            "empty": "",
            "null": None,
        }
        goal_ids = {"own": ids["goal_id"], "foreign": foreign_goal.id, "missing": "missing-goal"}

    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_settings] = lambda: Settings(auth_required=auth_required)
    app.dependency_overrides[require_authenticated_user] = lambda: owner
    provider_calls: list[bool] = []

    def build_client() -> LLMClient:
        provider_calls.append(True)
        assert expected_status == 200, "unauthorized request reached the provider"
        return _build_client()

    monkeypatch.setattr(llm_api, "_default_client", build_client)
    payload: dict[str, object] = {
        "source_reference_id": ids["source_id"],
        "target_node_id": ids["node_id"],
        "learning_goal_id": goal_ids[goal_kind],
        "actor_id": "user:bea",
        "related_node_title": "Retrieval interval calibration",
        "related_node_knowledge_type": "conceptual",
        "prompt_body": "Explain how interval calibration extends retention.",
        "prompt_knowledge_type": "conceptual",
        "prompt_intended_cognitive_action": "explain",
        "prompt_demand_level": "medium",
        "prompt_expected_answer_form": "short-text",
    }
    if learner_kind != "omitted":
        payload["learner_id"] = learner_ids[learner_kind]
    with patch.object(Session, "get", autospec=True, side_effect=Session.get) as get_record:
        response = client.post("/llm/authoring-assist/propose", json=payload)
    if auth_required and learner_kind in {"foreign", "missing", "empty"}:
        assert all(call.args[1] is not LearningGoal for call in get_record.call_args_list)
    assert response.status_code == expected_status, response.text
    with session_factory() as session:
        sessions = list(session.scalars(select(LLMSession)))
        proposals = list(session.scalars(select(LLMProposal)))
        if expected_status == 404:
            assert response.json() == {"detail": "Learner resource not found."}
            assert provider_calls == []
            assert sessions == []
            assert proposals == []
        else:
            assert provider_calls == [True]
            assert len(sessions) == len(proposals) == 1
            assert sessions[0].learner_id == payload.get("learner_id")
            assert response.json()["node_status"] == "draft"
