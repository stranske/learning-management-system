"""Contract tests for author-side learning object routes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.audit.models import AuditLog
from lms.auth.login import require_authenticated_user
from lms.auth.models import User
from lms.feedback.models import Rubric, RubricCriterion
from lms.graphs.models import KnowledgeNode
from lms.graphs.repository import create_knowledge_node
from lms.learners.models import LearningGoal
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.prompts.models import Prompt, PromptDriftAcknowledgement, PromptVersion
from lms.prompts.repository import (
    acknowledge_prompt_drift,
    get_prompt,
    prompt_drift_status,
    version_prompt,
)
from lms.settings import Settings, get_settings
from lms.sources.repository import (
    compute_source_hash_for_reference,
    create_source_reference,
    scan_source_references,
)
from lms.ui import api as author_api


def test_author_can_create_goal_node_edge_and_prompt_from_ui(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        user = User(username="author", display_name="Author")
        session.add(user)
        session.flush()
        learner = create_learner_for_user(
            session,
            user_id=user.id,
            display_name="Demo learner",
        )
        source = create_source_reference(
            session,
            source_type="internal-note",
            stable_locator="demo://source/one",
            content="prototype source",
            actor_id="test-author",
        )
        session.commit()
        learner_id = learner.id
        source_id = source.id

    node_response = client.post(
        "/app/author/knowledge/nodes",
        data={
            "title": "Explain spaced retrieval",
            "description": "Learner can explain why retrieval spacing matters.",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "published",
            "source_reference_id": source_id,
        },
    )
    assert node_response.status_code == 200
    assert "Knowledge node saved." in node_response.text
    assert "Explain spaced retrieval" in node_response.text

    with session_factory() as session:
        node_id = session.query(KnowledgeNode).filter_by(title="Explain spaced retrieval").one().id

    goal_response = client.post(
        "/app/author/goals",
        data={
            "learner_id": learner_id,
            "title": "Master retrieval practice",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "active",
            "target_node_ids": node_id,
        },
    )
    assert goal_response.status_code == 200
    assert "Goal saved." in goal_response.text
    assert "Master retrieval practice" in goal_response.text

    with session_factory() as session:
        goal_id = session.query(LearningGoal).filter_by(title="Master retrieval practice").one().id

    prompt_response = client.post(
        "/app/author/prompts",
        data={
            "learning_goal_id": goal_id,
            "target_node_id": node_id,
            "knowledge_type": "conceptual",
            "intended_cognitive_action": "explain",
            "demand_level": "medium",
            "expected_answer_form": "short-text",
            "source_reference_ids": source_id,
            "authoring_actor": "spoofed-browser-author",
            "body": "Explain why spaced retrieval helps memory.",
        },
    )
    assert prompt_response.status_code == 200
    assert "Prompt saved as draft." in prompt_response.text
    assert "Explain why spaced retrieval helps memory." in prompt_response.text
    assert "provenance Provenance: human-authored; author author-ui" in prompt_response.text
    assert "drift current" in client.get("/app/author/prompts").text

    with session_factory() as session:
        prompt = (
            session.query(Prompt)
            .join(PromptVersion)
            .filter(PromptVersion.body == "Explain why spaced retrieval helps memory.")
            .one()
        )
        assert prompt.authoring_actor == "author-ui"


@pytest.mark.parametrize(
    "changes_during_save", [False, True], ids=["stable", "changes_during_save"]
)
def test_author_prompts_acknowledge_drift_records_reviewed_state(
    api_client: tuple[TestClient, sessionmaker[Session]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes_during_save: bool,
) -> None:
    """Author prompts POST acknowledge-drift records review and updates the surface."""
    client, session_factory = api_client
    note = tmp_path / "prompt-source.md"
    note.write_text("# Note\nstable text\n", encoding="utf-8")
    with session_factory() as session:
        node = create_knowledge_node(
            session,
            title="Drift target",
            knowledge_type="conceptual",
            scope="personal",
            status="published",
            actor_id="test-author",
        )
        learner = create_learner_for_user(
            session,
            user_id="author-drift",
            display_name="Drift learner",
        )
        goal = create_learning_goal(
            session,
            learner_id=learner.id,
            title="Drift goal",
            knowledge_type="conceptual",
            target_node_ids=[node.id],
            ownership_scope="personal",
        )
        source = create_source_reference(
            session,
            source_type="markdown-file",
            stable_locator=str(note),
            passage_range="L2-L2",
            actor_id="test-author",
        )
        session.commit()
        node_id = node.id
        goal_id = goal.id
        source_id = source.id

    create_response = client.post(
        "/app/author/prompts",
        data={
            "learning_goal_id": goal_id,
            "target_node_id": node_id,
            "knowledge_type": "conceptual",
            "intended_cognitive_action": "explain",
            "demand_level": "medium",
            "expected_answer_form": "short-text",
            "source_reference_ids": source_id,
            "body": "Prompt with markdown source",
        },
    )
    assert create_response.status_code == 200
    assert "drift current" in create_response.text

    note.write_text("# Note\nchanged passage\n", encoding="utf-8")
    with session_factory() as session:
        scan_source_references(session, base_path=tmp_path, actor_id="system:test")
        session.commit()

    listing = client.get("/app/author/prompts")
    assert listing.status_code == 200
    assert "drift stale" in listing.text
    assert "Acknowledge drift" in listing.text

    with session_factory() as session:
        prompt = (
            session.query(Prompt)
            .join(PromptVersion)
            .filter(PromptVersion.body == "Prompt with markdown source")
            .one()
        )
        prompt_id = prompt.id
        version_id = prompt.versions[-1].id
        reference = prompt.source_references[0]
        expected_states = {
            source_id: {
                "content_hash": reference.content_hash,
                "hash_algorithm": reference.hash_algorithm,
                "drift_status": "stale",
                "resolved_content_hash": compute_source_hash_for_reference(
                    source_type=reference.source_type,
                    stable_locator=reference.stable_locator,
                    passage_range=reference.passage_range,
                    content=None,
                    hash_algorithm=reference.hash_algorithm,
                ),
            }
        }

    assert f"name='prompt_version_id' value='{version_id}'" in listing.text
    digest_match = re.search(r"name='source_state_digest' value='([^']*)'", listing.text)
    assert digest_match is not None
    source_state_digest = digest_match.group(1)

    if changes_during_save:

        def change_file_then_acknowledge(*args: Any, **kwargs: Any) -> PromptDriftAcknowledgement:
            note.write_text("# Note\nunreviewed passage\n", encoding="utf-8")
            return acknowledge_prompt_drift(*args, **kwargs)

        monkeypatch.setattr(author_api, "acknowledge_prompt_drift", change_file_then_acknowledge)

    ack_response = client.post(
        f"/app/author/prompts/{prompt_id}/acknowledge-drift",
        data={
            "ownership_scope": "personal",
            "prompt_version_id": version_id,
            "source_state_digest": source_state_digest,
        },
    )
    assert ack_response.status_code == 200
    assert "Prompt drift acknowledged." in ack_response.text
    with session_factory() as session:
        loaded = get_prompt(session, prompt_id)
        assert loaded is not None
        acknowledgement = session.query(PromptDriftAcknowledgement).one()
        assert acknowledgement.acknowledged_source_states == expected_states
        assert prompt_drift_status(loaded) == ("stale" if changes_during_save else "current")
    if changes_during_save:
        assert "drift stale" in ack_response.text
        return
    assert "drift current" in client.get("/app/author/prompts").text

    note.write_text("# Note\nchanged passage again\n", encoding="utf-8")
    with session_factory() as session:
        scan_source_references(session, base_path=tmp_path, actor_id="system:test")
        session.commit()
    assert "drift stale" in client.get("/app/author/prompts").text


def test_author_prompts_acknowledge_drift_rejects_stale_version_submission(
    api_client: tuple[TestClient, sessionmaker[Session]],
    tmp_path: Path,
) -> None:
    """Submitting acknowledge-drift for v1 after v2 was created is rejected."""
    client, session_factory = api_client
    note = tmp_path / "prompt-version-race.md"
    note.write_text("# Note\noriginal passage\n", encoding="utf-8")
    with session_factory() as session:
        node = create_knowledge_node(
            session,
            title="Version race node",
            knowledge_type="conceptual",
            scope="personal",
            status="published",
            actor_id="test-author",
        )
        learner = create_learner_for_user(
            session,
            user_id="author-version-race",
            display_name="Version race learner",
        )
        goal = create_learning_goal(
            session,
            learner_id=learner.id,
            title="Version race goal",
            knowledge_type="conceptual",
            target_node_ids=[node.id],
            ownership_scope="personal",
        )
        source = create_source_reference(
            session,
            source_type="markdown-file",
            stable_locator=str(note),
            passage_range="L2-L2",
            actor_id="test-author",
        )
        session.commit()
        node_id = node.id
        goal_id = goal.id
        source_id = source.id

    client.post(
        "/app/author/prompts",
        data={
            "learning_goal_id": goal_id,
            "target_node_id": node_id,
            "knowledge_type": "conceptual",
            "intended_cognitive_action": "explain",
            "demand_level": "medium",
            "expected_answer_form": "short-text",
            "source_reference_ids": source_id,
            "body": "Version 1 body",
        },
    )
    note.write_text("# Note\nedited passage\n", encoding="utf-8")
    with session_factory() as session:
        scan_source_references(session, base_path=tmp_path, actor_id="system:test")
        session.commit()
        prompt_obj = (
            session.query(Prompt)
            .join(PromptVersion)
            .filter(PromptVersion.body == "Version 1 body")
            .one()
        )
        prompt_id = prompt_obj.id
        v1_id = prompt_obj.versions[-1].id

    listing = client.get("/app/author/prompts")
    assert listing.status_code == 200
    assert f"name='prompt_version_id' value='{v1_id}'" in listing.text

    with session_factory() as session:
        loaded_prompt = get_prompt(session, prompt_id)
        assert loaded_prompt is not None
        version_prompt(session, loaded_prompt, body="Version 2 body", actor_id="other-author")
        session.commit()

    stale_submit = client.post(
        f"/app/author/prompts/{prompt_id}/acknowledge-drift",
        data={
            "ownership_scope": "personal",
            "prompt_version_id": v1_id,
        },
    )
    assert stale_submit.status_code == 200
    assert "Prompt version changed before drift was acknowledged" in stale_submit.text
    assert "Prompt drift acknowledged." not in stale_submit.text
    with session_factory() as session:
        assert session.query(PromptDriftAcknowledgement).count() == 0


def test_author_prompts_acknowledge_drift_rejects_stale_source_state_digest(
    api_client: tuple[TestClient, sessionmaker[Session]],
    tmp_path: Path,
) -> None:
    """POST acknowledge-drift with an outdated source_state_digest is rejected."""
    client, session_factory = api_client
    note = tmp_path / "prompt-source-digest.md"
    note.write_text("# Note\nstable text\n", encoding="utf-8")
    with session_factory() as session:
        node = create_knowledge_node(
            session,
            title="Digest drift target",
            knowledge_type="conceptual",
            scope="personal",
            status="published",
            actor_id="test-author",
        )
        learner = create_learner_for_user(
            session,
            user_id="author-digest-drift",
            display_name="Digest drift learner",
        )
        goal = create_learning_goal(
            session,
            learner_id=learner.id,
            title="Digest drift goal",
            knowledge_type="conceptual",
            target_node_ids=[node.id],
            ownership_scope="personal",
        )
        source = create_source_reference(
            session,
            source_type="markdown-file",
            stable_locator=str(note),
            passage_range="L2-L2",
            actor_id="test-author",
        )
        session.commit()
        node_id = node.id
        goal_id = goal.id
        source_id = source.id

    client.post(
        "/app/author/prompts",
        data={
            "learning_goal_id": goal_id,
            "target_node_id": node_id,
            "knowledge_type": "conceptual",
            "intended_cognitive_action": "explain",
            "demand_level": "medium",
            "expected_answer_form": "short-text",
            "source_reference_ids": source_id,
            "body": "Prompt for digest race",
        },
    )
    note.write_text("# Note\nchanged passage\n", encoding="utf-8")
    with session_factory() as session:
        scan_source_references(session, base_path=tmp_path, actor_id="system:test")
        session.commit()
        prompt_obj = (
            session.query(Prompt)
            .join(PromptVersion)
            .filter(PromptVersion.body == "Prompt for digest race")
            .one()
        )
        prompt_id = prompt_obj.id

    listing = client.get("/app/author/prompts")
    version_match = re.search(r"name='prompt_version_id' value='([^']*)'", listing.text)
    digest_match = re.search(r"name='source_state_digest' value='([^']*)'", listing.text)
    assert version_match is not None and digest_match is not None
    stale_digest = digest_match.group(1)

    note.write_text("# Note\nchanged again before ack\n", encoding="utf-8")
    with session_factory() as session:
        scan_source_references(session, base_path=tmp_path, actor_id="system:test")
        session.commit()

    stale_submit = client.post(
        f"/app/author/prompts/{prompt_id}/acknowledge-drift",
        data={
            "ownership_scope": "personal",
            "prompt_version_id": version_match.group(1),
            "source_state_digest": stale_digest,
        },
    )
    assert stale_submit.status_code == 200
    assert "Source state changed before drift was acknowledged" in stale_submit.text
    assert "Prompt drift acknowledged." not in stale_submit.text
    with session_factory() as session:
        assert session.query(PromptDriftAcknowledgement).count() == 0


def test_author_prompts_acknowledge_drift_requires_authentication(
    api_client: tuple[TestClient, sessionmaker[Session]],
    tmp_path: Path,
) -> None:
    """Unauthenticated POST to acknowledge-drift is rejected when auth_required=True."""
    client, session_factory = api_client
    note = tmp_path / "auth-prompt-source.md"
    note.write_text("# Note\ninitial text\n", encoding="utf-8")
    with session_factory() as session:
        node = create_knowledge_node(
            session,
            title="Auth drift node",
            knowledge_type="conceptual",
            scope="personal",
            status="published",
            actor_id="test-author",
        )
        learner = create_learner_for_user(
            session,
            user_id="author-auth-drift",
            display_name="Auth drift learner",
        )
        goal = create_learning_goal(
            session,
            learner_id=learner.id,
            title="Auth drift goal",
            knowledge_type="conceptual",
            target_node_ids=[node.id],
            ownership_scope="personal",
        )
        source = create_source_reference(
            session,
            source_type="markdown-file",
            stable_locator=str(note),
            passage_range="L2-L2",
            actor_id="test-author",
        )
        session.commit()
        node_id = node.id
        goal_id = goal.id
        source_id = source.id

    client.post(
        "/app/author/prompts",
        data={
            "learning_goal_id": goal_id,
            "target_node_id": node_id,
            "knowledge_type": "conceptual",
            "intended_cognitive_action": "explain",
            "demand_level": "medium",
            "expected_answer_form": "short-text",
            "source_reference_ids": source_id,
            "body": "Auth protected prompt",
        },
    )
    note.write_text("# Note\nupdated text\n", encoding="utf-8")
    with session_factory() as session:
        scan_source_references(session, base_path=tmp_path, actor_id="system:test")
        session.commit()
        prompt_obj = (
            session.query(Prompt)
            .join(PromptVersion)
            .filter(PromptVersion.body == "Auth protected prompt")
            .one()
        )
        prompt_id = prompt_obj.id
        version_id = prompt_obj.versions[-1].id

    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_required=True,
        auth_secret_key="test-secret-not-for-prod",
    )

    unauthenticated = client.post(
        f"/app/author/prompts/{prompt_id}/acknowledge-drift",
        data={
            "ownership_scope": "personal",
            "prompt_version_id": version_id,
        },
        follow_redirects=False,
    )
    assert unauthenticated.status_code in (302, 401)
    with session_factory() as session:
        assert session.query(PromptDriftAcknowledgement).count() == 0


def test_author_ui_blocks_cross_scope_normal_edge(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        personal = create_knowledge_node(
            session,
            title="Personal node",
            knowledge_type="conceptual",
            scope="personal",
            actor_id="test-author",
            status="published",
        )
        institutional = create_knowledge_node(
            session,
            title="Institutional node",
            knowledge_type="conceptual",
            scope="institutional",
            actor_id="test-author",
            status="published",
        )
        session.commit()
        personal_id = personal.id
        institutional_id = institutional.id

    response = client.post(
        "/app/author/knowledge/edges",
        data={
            "source_node_id": personal_id,
            "target_node_id": institutional_id,
            "ownership_scope": "personal",
            "target_scope": "institutional",
            "edge_type": "prerequisite",
            "status": "draft",
            "confidence": "0.7",
        },
    )

    assert response.status_code == 200
    assert "cross-scope edges require is_graph_reference=True" in response.text


def test_author_knowledge_form_uses_unique_select_ids(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    response = client.get("/app/author/knowledge")

    assert response.status_code == 200
    assert 'id="node-ownership_scope"' in response.text
    assert 'id="edge-ownership_scope"' in response.text
    assert 'id="node-status"' in response.text
    assert 'id="edge-status"' in response.text
    assert 'id="ownership_scope"' not in response.text
    assert 'id="status"' not in response.text


def test_author_ui_derives_actor_identity_server_side(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        source = create_source_reference(
            session,
            source_type="internal-note",
            stable_locator="demo://source/actor",
            content="actor source",
            actor_id="test-author",
        )
        session.commit()
        source_id = source.id

    response = client.post(
        "/app/author/knowledge/nodes",
        data={
            "title": "Server actor node",
            "description": "Actor comes from the server.",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "published",
            "source_reference_id": source_id,
            "actor_id": "spoofed-browser-user",
        },
    )

    assert response.status_code == 200
    with session_factory() as session:
        node = session.query(KnowledgeNode).filter_by(title="Server actor node").one()
        audit = (
            session.query(AuditLog).filter_by(entity_type="KnowledgeNode", entity_id=node.id).one()
        )
        assert audit.actor_id == "author-ui"
        assert audit.source_subsystem == "author-ui"


def test_author_prompt_hint_redacts_local_only_sources(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        create_source_reference(
            session,
            source_type="internal-note",
            stable_locator="file:///private/local-note.md",
            content="local secret source",
            actor_id="test-author",
            source_visibility="local-only",
        )
        session.commit()

    response = client.get("/app/author/prompts")

    assert response.status_code == 200
    assert "file:///private/local-note.md" not in response.text
    assert "local-only source hidden" in response.text


@pytest.mark.parametrize("access", ["owner", "foreign", "missing", "empty"])
def test_author_goal_form_checks_deployed_learner_ownership(
    api_client: tuple[TestClient, sessionmaker[Session]], access: str
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        owner = User(username="goal-owner", display_name="Owner", is_local=False)
        other = User(username="goal-other", display_name="Other", is_local=False)
        session.add_all([owner, other])
        session.flush()
        own_learner = create_learner_for_user(session, user_id=owner.id, display_name="Owner")
        foreign_learner = create_learner_for_user(session, user_id=other.id, display_name="Other")
        node = create_knowledge_node(
            session,
            title="Goal target",
            knowledge_type="conceptual",
            scope="personal",
            actor_id="test-author",
            status="published",
        )
        session.commit()
        learner_ids = {
            "owner": own_learner.id,
            "foreign": foreign_learner.id,
            "missing": "nonexistent",
            "empty": "",
        }
        node_id = node.id

    app = cast(FastAPI, client.app)
    app.dependency_overrides[require_authenticated_user] = lambda: owner
    app.dependency_overrides[get_settings] = lambda: Settings(auth_required=True)
    response = client.post(
        "/app/author/goals",
        data={
            "learner_id": learner_ids[access],
            "title": "Authorized goal",
            "target_node_ids": node_id,
        },
    )
    with session_factory() as session:
        goals = session.query(LearningGoal).all()
        if access == "owner":
            assert response.status_code == 200, response.text
            assert "Goal saved." in response.text
            assert [(goal.learner_id, goal.title) for goal in goals] == [
                (own_learner.id, "Authorized goal")
            ]
        else:
            assert response.status_code == 404
            assert response.json() == {"detail": "Learner resource not found."}
            assert goals == []


@pytest.mark.parametrize(
    ("field", "value", "notice"),
    [
        ("max_points", "nan", "max_points must be a finite number"),
        ("max_points", "inf", "max_points must be a finite number"),
        ("max_points", "-inf", "max_points must be a finite number"),
        ("max_points", "0", "max_points must be a finite positive number"),
        ("max_points", "-5", "max_points must be a finite positive number"),
        ("criterion_order", "0", "criterion_order must be greater than or equal to 1"),
        ("criterion_order", "-1", "criterion_order must be greater than or equal to 1"),
    ],
)
def test_author_rubric_invalid_numbers_render_notice_without_partial_data(
    api_client: tuple[TestClient, sessionmaker[Session]],
    field: str,
    value: str,
    notice: str,
) -> None:
    """Malformed numbers render a notice and leave subsequent valid requests usable."""
    client, session_factory = api_client
    form = {
        "title": "Numeric rubric",
        "ownership_scope": "personal",
        "status": "draft",
        "authoring_actor": "user:alice",
        "criterion_order": "1",
        "criterion_description": "Uses evidence",
        "max_points": "0.5",
    }
    response = client.post("/app/author/rubrics", data={**form, field: value})
    assert response.status_code == 200
    assert notice in response.text
    assert "Rubric created." not in response.text
    with session_factory() as session:
        assert session.query(Rubric).count() == 0
        assert session.query(RubricCriterion).count() == 0
    response = client.post("/app/author/rubrics", data=form)
    assert response.status_code == 200
    assert "Rubric created." in response.text
    with session_factory() as session:
        assert session.query(Rubric).count() == 1
        criterion = session.query(RubricCriterion).one()
        assert (criterion.criterion_order, criterion.max_points) == (1, 0.5)
