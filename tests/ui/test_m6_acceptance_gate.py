"""End-to-end acceptance gate for the M6 author-to-learner prototype."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import User
from lms.capability.models import CapabilityTarget
from lms.cases.models import Case, WorkProduct
from lms.evidence.models import Attempt, EvidenceRecord
from lms.feedback.models import Rubric
from lms.graphs.models import KnowledgeNode
from lms.learners.models import LearningGoal
from lms.learners.repository import create_learner_for_user
from lms.prompts.models import Prompt, PromptVersion
from lms.sources.repository import create_source_reference


def _hidden_value(html: str, name: str) -> str:
    match = re.search(rf"name='{name}' value='([^']+)'", html)
    assert match is not None, f"expected hidden field {name!r}"
    return match.group(1)


def _assert_mobile_viewport(html: str) -> None:
    assert 'name="viewport"' in html
    assert "width=device-width" in html


def test_author_goal_node_prompt_rubric_and_learner_completion_path(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_user = User(username="m6-learner", display_name="M6 Learner")
        session.add(learner_user)
        session.flush()
        learner = create_learner_for_user(
            session,
            user_id=learner_user.id,
            display_name="M6 Learner",
        )
        source = create_source_reference(
            session,
            source_type="internal-note",
            stable_locator="demo://m6/source/retrieval-spacing",
            content="Retrieval practice with spaced review strengthens durable recall.",
            actor_id="author-ui",
        )
        session.commit()
        learner_id = learner.id
        source_id = source.id

    node_response = client.post(
        "/app/author/knowledge/nodes",
        data={
            "title": "Explain retrieval spacing",
            "description": "Use source evidence to explain why spaced retrieval helps memory.",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "published",
            "source_reference_id": source_id,
        },
    )
    assert node_response.status_code == 200
    assert "Knowledge node saved." in node_response.text

    with session_factory() as session:
        node_id = session.scalars(
            select(KnowledgeNode.id).where(KnowledgeNode.title == "Explain retrieval spacing")
        ).one()

    goal_response = client.post(
        "/app/author/goals",
        data={
            "learner_id": learner_id,
            "title": "Explain retrieval practice with evidence",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "active",
            "target_node_ids": node_id,
        },
    )
    assert goal_response.status_code == 200
    assert "Goal saved." in goal_response.text

    with session_factory() as session:
        goal_id = session.scalars(
            select(LearningGoal.id).where(
                LearningGoal.title == "Explain retrieval practice with evidence"
            )
        ).one()

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
            "authoring_actor": "browser-spoof",
            "body": "Explain why retrieval practice works better when reviews are spaced.",
        },
    )
    assert prompt_response.status_code == 200
    assert "Prompt saved as draft." in prompt_response.text

    with session_factory() as session:
        prompt = session.scalars(
            select(Prompt)
            .join(PromptVersion)
            .where(
                PromptVersion.body
                == "Explain why retrieval practice works better when reviews are spaced."
            )
        ).one()
        prompt_id = prompt.id

    publish_response = client.post(
        f"/prompts/{prompt_id}/publish",
        json={"reviewing_actor": "author-reviewer"},
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"

    rubric_response = client.post(
        "/app/author/rubrics",
        data={
            "title": "Source-backed explanation",
            "description": "Checks whether the learner uses the source and states the effect.",
            "ownership_scope": "personal",
            "status": "published",
            "authoring_actor": "author-ui",
            "prompt_id": prompt_id,
            "knowledge_node_id": node_id,
            "criterion_order": "1",
            "criterion_description": "Names spaced retrieval and cites supporting evidence.",
            "max_points": "4",
            "validity_scope": "M6 demo gate",
            "performance_levels": '{"meets":"Explains spacing with evidence"}',
        },
    )
    assert rubric_response.status_code == 200
    assert "Rubric created." in rubric_response.text

    with session_factory() as session:
        rubric_id = session.scalars(
            select(Rubric.id).where(Rubric.title == "Source-backed explanation")
        ).one()

    case_response = client.post(
        "/app/author/cases",
        data={
            "title": "Plan a spaced review",
            "description": "Transfer case for scheduling retrieval practice.",
            "ownership_scope": "personal",
            "rubric_id": rubric_id,
            "knowledge_node_id": node_id,
            "status": "published",
            "step_order": "1",
            "step_title": "Draft a review plan",
            "step_prompt": "Choose a next review date and justify it with evidence.",
            "expected_work_product": "short plan",
            "evidence_title": "Spacing evidence",
            "evidence_summary": "A brief source packet for spacing decisions.",
            "packet_metadata": '{"source":"m6-gate"}',
            "decision_title": "Pick the review spacing",
            "decision_prompt": "Which spacing choice best fits this learner?",
            "decision_type": "single-choice",
            "decision_options": (
                '[{"label":"Tomorrow","value":"tomorrow"},'
                '{"label":"Next week","value":"next-week"}]'
            ),
        },
    )
    assert case_response.status_code == 200
    assert "Case created." in case_response.text

    with session_factory() as session:
        case = session.scalars(select(Case).where(Case.title == "Plan a spaced review")).one()
        case_id = case.id
        case_step_id = case.steps[0].id

    author_home = client.get("/app/author")
    assert author_home.status_code == 200
    assert (
        "Explain retrieval practice with evidence"
        in client.get(f"/app/author/goals?learner_id={learner_id}").text
    )
    assert "Explain retrieval spacing" in client.get("/app/author/knowledge").text
    assert "Source-backed explanation" in client.get("/app/author/rubrics").text
    assert "Plan a spaced review" in client.get("/app/author/cases").text

    attempt_start = client.get(
        f"/app/learner/attempts?learner_id={learner_id}&prompt_id={prompt_id}"
    )
    assert attempt_start.status_code == 200
    _assert_mobile_viewport(attempt_start.text)
    assert "Your task" in attempt_start.text
    assert (
        "Provenance: human-authored; author author-ui; reviewer author-reviewer"
        in attempt_start.text
    )
    assert "demo://m6/source/retrieval-spacing" in attempt_start.text

    attempt_response = client.post(
        "/app/learner/attempts",
        data={
            "learner_id": learner_id,
            "prompt_id": prompt_id,
            "response_text": (
                "Spaced retrieval works because recalling the idea after a delay "
                "strengthens durable recall."
            ),
            "confidence_rating": "3",
            "reference_accessed": "true",
            "elapsed_seconds": "42",
        },
    )
    assert attempt_response.status_code == 200
    assert "Attempt recorded" in attempt_response.text

    with session_factory() as session:
        attempt = session.scalars(select(Attempt).where(Attempt.prompt_id == prompt_id)).one()
        rubric = session.scalars(
            select(Rubric).where(Rubric.title == "Source-backed explanation")
        ).one()
        criterion_id = rubric.criteria[0].id
        attempt_id = attempt.id

    score_response = client.post(
        "/rubric-scores",
        json={
            "rubric_id": rubric.id,
            "attempt_id": attempt_id,
            "scorer_type": "deterministic-test",
            "criterion_scores": [
                {
                    "criterion_id": criterion_id,
                    "points": 2.0,
                    "rationale": "Names spacing but needs a clearer source citation.",
                }
            ],
            "score_metadata": {"source": "m6_acceptance_gate"},
        },
    )
    assert score_response.status_code == 201

    feedback_view = client.get(
        f"/app/learner/attempts/feedback?learner_id={learner_id}&prompt_id={prompt_id}"
    )
    assert feedback_view.status_code == 200
    assert "Rubric score" in feedback_view.text
    assert "Revise the attempt using rubric feedback" in feedback_view.text
    assert "Source citations after attempt" in feedback_view.text

    target_response = client.post(
        "/app/learner/capability/targets",
        data={
            "learner_id": learner_id,
            "title": "Explain retrieval spacing with evidence",
            "target_node_ids": [node_id],
            "required_evidence_types": "rubric-score, transfer-case",
            "confidence_threshold": "0.85",
        },
    )
    assert target_response.status_code == 200
    assert "Saved your personal capability target." in target_response.text
    target_id = _hidden_value(target_response.text, "target_id")

    estimate_response = client.post(
        "/app/learner/capability/estimates", data={"target_id": target_id}
    )
    assert estimate_response.status_code == 200
    assert "Current capability estimate" in estimate_response.text
    estimate_id = _hidden_value(estimate_response.text, "estimate_id")

    gap_response = client.post(
        "/app/learner/capability/gap-analyses",
        data={"target_id": target_id, "estimate_id": estimate_id},
    )
    assert gap_response.status_code == 200
    assert "Current gaps" in gap_response.text
    assert "Transfer evidence needed" in gap_response.text
    assert "/app/learner/cases" in gap_response.text
    gap_analysis_id = _hidden_value(gap_response.text, "gap_analysis_id")

    plan_response = client.post(
        "/app/learner/capability/maintenance-plans",
        data={"target_id": target_id, "gap_analysis_id": gap_analysis_id},
    )
    assert plan_response.status_code == 200
    assert "Maintenance plan" in plan_response.text
    assert "Step 1:" in plan_response.text
    assert "Scheduled in your review queue." in plan_response.text
    assert "Open transfer cases" in plan_response.text

    case_list = client.get(f"/app/learner/cases?learner_id={learner_id}")
    assert case_list.status_code == 200
    _assert_mobile_viewport(case_list.text)
    assert "Plan a spaced review" in case_list.text
    assert "No work product submitted yet." in case_list.text

    case_detail = client.get(f"/app/learner/cases/{case_id}?learner_id={learner_id}")
    assert case_detail.status_code == 200
    assert "Draft a review plan" in case_detail.text
    assert "Spacing evidence" in case_detail.text
    assert "Submit work product" in case_detail.text

    work_product_response = client.post(
        f"/app/learner/cases/{case_id}/work-products",
        data={
            "learner_id": learner_id,
            "submission_type": "rationale",
            "case_step_id": case_step_id,
            "rubric_id": rubric_id,
            "body": "Review next week because spacing creates a useful retrieval delay.",
        },
    )
    assert work_product_response.status_code == 200
    assert "Work product submitted." in work_product_response.text
    assert "Submitted; awaiting scoring for transfer evidence." in work_product_response.text

    with session_factory() as session:
        work_product = session.scalars(
            select(WorkProduct).where(
                WorkProduct.case_id == case_id,
                WorkProduct.learner_id == learner_id,
            )
        ).one()
        work_product_id = work_product.id

    work_product_score = client.post(
        f"/work-products/{work_product_id}/score",
        json={
            "scorer_type": "deterministic-test",
            "criterion_scores": [
                {
                    "criterion_id": criterion_id,
                    "points": 3.5,
                    "rationale": "Applies spacing evidence to a new scheduling decision.",
                }
            ],
            "raw_score": 3.5,
            "max_score": 4.0,
            "transfer_distance": "near",
        },
    )
    assert work_product_score.status_code == 201, work_product_score.text
    score_payload = work_product_score.json()
    assert score_payload["status"] == "scored"

    with session_factory() as session:
        evidence = session.get(EvidenceRecord, score_payload["evidence_record_id"])
        assert evidence is not None
        assert evidence.validity_scope == f"transfer-case:{case_id}"
        assert evidence.transfer_distance == "near"

    refreshed_estimate = client.post(
        "/app/learner/capability/estimates", data={"target_id": target_id}
    )
    assert refreshed_estimate.status_code == 200
    refreshed_estimate_id = _hidden_value(refreshed_estimate.text, "estimate_id")
    refreshed_gap = client.post(
        "/app/learner/capability/gap-analyses",
        data={"target_id": target_id, "estimate_id": refreshed_estimate_id},
    )
    assert refreshed_gap.status_code == 200
    assert "Transfer evidence needed" not in refreshed_gap.text

    dashboard = client.get(f"/app/learner?learner_id={learner_id}")
    review_queue = client.get(f"/app/learner/review?learner_id={learner_id}")
    feedback_list = client.get(f"/app/learner/feedback?learner_id={learner_id}")
    capability_view = client.get(f"/app/learner/capability/targets/{target_id}")

    assert dashboard.status_code == 200
    _assert_mobile_viewport(dashboard.text)
    assert "Explain retrieval practice with evidence" in dashboard.text
    assert "Revise the attempt using rubric feedback" in dashboard.text
    assert "Explain retrieval spacing with evidence" in dashboard.text
    assert "Maintenance plan" in dashboard.text
    assert "Deterministic placeholder policy inspired by FSRS 4.5" in dashboard.text

    assert review_queue.status_code == 200
    assert "due-review" in review_queue.text
    assert f"node {node_id}" in review_queue.text

    assert feedback_list.status_code == 200
    assert "Improve rubric performance for Source-backed explanation" in feedback_list.text

    assert capability_view.status_code == 200
    assert "Current evidence score" in capability_view.text
    assert "Transfer evidence needed" not in capability_view.text
    assert "Maintenance plan" in capability_view.text

    with session_factory() as session:
        target = session.get(CapabilityTarget, target_id)
        assert target is not None
        assert target.ownership_scope == "personal"
        assert target.title == "Explain retrieval spacing with evidence"
