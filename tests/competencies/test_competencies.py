"""Tests for competency repository helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.competencies.repository import (
    create_competency,
    create_competency_evidence,
    evidence_for_competency_learner,
)
from lms.evidence.repository import create_evidence_record
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.graphs.repository import create_knowledge_node


def test_competency_links_nodes_with_matching_ownership_scope(db_session: Session) -> None:
    """Competency evidence enforces scope consistency and graph edge compatibility."""
    personal_node = create_knowledge_node(
        db_session,
        title="Explain a causal mechanism",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    institutional_node = create_knowledge_node(
        db_session,
        title="Institutional benchmark",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )
    competency = create_competency(
        db_session,
        title="Causal reasoning",
        ownership_scope="personal",
        target_knowledge_type="conceptual",
        validity_scope="Current personal learning context.",
        status="active",
    )
    evidence = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id=personal_node.id,
        raw_score=4,
        normalized_score=0.8,
        max_score=5,
    )

    link = create_competency_evidence(
        db_session,
        competency_id=competency.id,
        knowledge_node_id=personal_node.id,
        evidence_record_id=evidence.id,
        contribution_weight=0.75,
        evidence_role="demonstrates",
    )
    db_session.commit()

    assert link.competency_id == competency.id
    edge = (
        db_session.query(KnowledgeEdge)
        .filter_by(
            source_node_id=personal_node.id,
            target_node_id=competency.id,
            edge_type="supports-competency",
        )
        .one()
    )
    assert edge.source_scope == "personal"
    assert edge.target_scope == "personal"
    assert edge.status == "published"
    audit = (
        db_session.query(AuditLog)
        .filter_by(
            entity_type="KnowledgeNode",
            entity_id=competency.id,
            action="create",
            source_subsystem="competencies",
        )
        .one()
    )
    assert audit.after_summary is not None
    assert audit.after_summary["status"] == "published"

    institutional_evidence = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id=institutional_node.id,
        raw_score=1,
        normalized_score=0.2,
        max_score=5,
    )
    with pytest.raises(ValueError, match="ownership_scope must match"):
        create_competency_evidence(
            db_session,
            competency_id=competency.id,
            knowledge_node_id=institutional_node.id,
            evidence_record_id=institutional_evidence.id,
        )


def test_competency_evidence_aggregates_existing_evidence_records(
    db_session: Session,
) -> None:
    """Aggregation helper returns only one learner's competency evidence links."""
    node = create_knowledge_node(
        db_session,
        title="Use evidence in explanations",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    competency = create_competency(
        db_session,
        title="Evidence-backed explanation",
        ownership_scope="personal",
        target_knowledge_type="judgment",
        status="active",
    )
    alice_evidence = create_evidence_record(
        db_session,
        learner_id="learner-alice",
        knowledge_node_id=node.id,
        raw_score=3,
        normalized_score=0.6,
        max_score=5,
    )
    bob_evidence = create_evidence_record(
        db_session,
        learner_id="learner-bob",
        knowledge_node_id=node.id,
        raw_score=5,
        normalized_score=1.0,
        max_score=5,
    )
    alice_link = create_competency_evidence(
        db_session,
        competency_id=competency.id,
        knowledge_node_id=node.id,
        evidence_record_id=alice_evidence.id,
        contribution_weight=0.6,
    )
    create_competency_evidence(
        db_session,
        competency_id=competency.id,
        knowledge_node_id=node.id,
        evidence_record_id=bob_evidence.id,
        contribution_weight=1.0,
    )
    db_session.commit()

    links = evidence_for_competency_learner(
        db_session,
        competency_id=competency.id,
        learner_id="learner-alice",
    )

    assert [link.id for link in links] == [alice_link.id]
    assert links[0].evidence_record_id == alice_evidence.id
    assert links[0].contribution_weight == 0.6


@pytest.mark.parametrize(
    ("competency_status", "graph_status"),
    [
        ("draft", "draft"),
        ("deprecated", "deprecated"),
    ],
)
def test_competency_graph_node_and_edge_preserve_non_active_status(
    db_session: Session,
    competency_status: str,
    graph_status: str,
) -> None:
    """Draft and deprecated competencies stay out of published graph views."""
    node = create_knowledge_node(
        db_session,
        title=f"{competency_status} source",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    competency = create_competency(
        db_session,
        title=f"{competency_status} competency",
        ownership_scope="personal",
        target_knowledge_type="conceptual",
        status=competency_status,
    )
    evidence = create_evidence_record(
        db_session,
        learner_id=f"learner-{competency_status}",
        knowledge_node_id=node.id,
        raw_score=4,
        normalized_score=0.8,
        max_score=5,
    )

    create_competency_evidence(
        db_session,
        competency_id=competency.id,
        knowledge_node_id=node.id,
        evidence_record_id=evidence.id,
    )
    db_session.commit()

    competency_node = db_session.get(KnowledgeNode, competency.id)
    assert competency_node is not None
    assert competency_node.status == graph_status
    edge = (
        db_session.query(KnowledgeEdge)
        .filter_by(
            source_node_id=node.id,
            target_node_id=competency.id,
            edge_type="supports-competency",
        )
        .one()
    )
    assert edge.status == graph_status


def test_competency_evidence_rejects_duplicate_evidence_link(
    db_session: Session,
) -> None:
    """One evidence record can contribute to a competency only once."""
    node = create_knowledge_node(
        db_session,
        title="Duplicate evidence node",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    competency = create_competency(
        db_session,
        title="Duplicate guarded competency",
        ownership_scope="personal",
        target_knowledge_type="judgment",
        status="active",
    )
    evidence = create_evidence_record(
        db_session,
        learner_id="learner-duplicate",
        knowledge_node_id=node.id,
        raw_score=3,
        normalized_score=0.6,
        max_score=5,
    )
    create_competency_evidence(
        db_session,
        competency_id=competency.id,
        knowledge_node_id=node.id,
        evidence_record_id=evidence.id,
    )

    with pytest.raises(ValueError, match="already exists"):
        create_competency_evidence(
            db_session,
            competency_id=competency.id,
            knowledge_node_id=node.id,
            evidence_record_id=evidence.id,
        )
