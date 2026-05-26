"""Repository helpers for competencies and competency evidence."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.audit.repository import record_audit_event
from lms.competencies.models import (
    COMPETENCY_STATUSES,
    EVIDENCE_ROLES,
    Competency,
    CompetencyEvidence,
)
from lms.evidence.models import EvidenceRecord
from lms.graphs.models import EDGE_TYPES, KNOWLEDGE_TYPES, OWNERSHIP_SCOPES, KnowledgeNode
from lms.graphs.repository import create_knowledge_edge


def _require_choice(value: str, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"unknown {label} {value!r}; expected one of {allowed}")
    return value


def _competency_graph_status(status: str) -> str:
    if status == "active":
        return "published"
    return status


def create_competency(
    session: Session,
    *,
    title: str,
    ownership_scope: str,
    target_knowledge_type: str,
    description: str | None = None,
    validity_scope: str | None = None,
    status: str = "draft",
) -> Competency:
    """Create an observable competency definition."""
    _require_choice(ownership_scope, OWNERSHIP_SCOPES, "ownership scope")
    _require_choice(target_knowledge_type, KNOWLEDGE_TYPES, "target knowledge type")
    _require_choice(status, COMPETENCY_STATUSES, "competency status")
    competency = Competency(
        title=title,
        description=description,
        ownership_scope=ownership_scope,
        target_knowledge_type=target_knowledge_type,
        validity_scope=validity_scope,
        status=status,
    )
    session.add(competency)
    session.flush()
    return competency


def get_competency(session: Session, competency_id: str) -> Competency | None:
    """Return one competency by id."""
    return session.get(Competency, competency_id)


def list_competencies(
    session: Session,
    *,
    ownership_scope: str | None = None,
    status: str | None = None,
    target_knowledge_type: str | None = None,
    limit: int = 100,
) -> Sequence[Competency]:
    """List competency definitions with optional scope/status/type filters."""
    statement = select(Competency)
    if ownership_scope is not None:
        _require_choice(ownership_scope, OWNERSHIP_SCOPES, "ownership scope")
        statement = statement.where(Competency.ownership_scope == ownership_scope)
    if status is not None:
        _require_choice(status, COMPETENCY_STATUSES, "competency status")
        statement = statement.where(Competency.status == status)
    if target_knowledge_type is not None:
        _require_choice(target_knowledge_type, KNOWLEDGE_TYPES, "target knowledge type")
        statement = statement.where(Competency.target_knowledge_type == target_knowledge_type)
    statement = statement.order_by(Competency.created_at.desc(), Competency.id).limit(limit)
    return list(session.scalars(statement))


def create_competency_evidence(
    session: Session,
    *,
    competency_id: str,
    knowledge_node_id: str,
    evidence_record_id: str,
    contribution_weight: float = 1.0,
    evidence_role: str = "supports",
    actor_id: str = "system:competencies",
) -> CompetencyEvidence:
    """Link evidence to a competency and create the graph support edge if needed."""
    competency = session.get(Competency, competency_id)
    if competency is None:
        raise ValueError("competency was not found")
    node = session.get(KnowledgeNode, knowledge_node_id)
    if node is None:
        raise ValueError("knowledge node was not found")
    evidence = session.get(EvidenceRecord, evidence_record_id)
    if evidence is None:
        raise ValueError("evidence record was not found")
    if node.ownership_scope != competency.ownership_scope:
        raise ValueError("knowledge node ownership_scope must match competency ownership_scope")
    if evidence.knowledge_node_id != node.id:
        raise ValueError("evidence record must reference the linked knowledge node")
    if not 0.0 <= contribution_weight <= 1.0:
        raise ValueError("contribution_weight must be between 0.0 and 1.0")
    _require_choice(evidence_role, EVIDENCE_ROLES, "evidence role")
    duplicate = session.execute(
        select(CompetencyEvidence.id).where(
            CompetencyEvidence.competency_id == competency.id,
            CompetencyEvidence.evidence_record_id == evidence.id,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ValueError("competency evidence link already exists")

    _ensure_supports_competency_edge(
        session,
        competency=competency,
        node=node,
        actor_id=actor_id,
    )
    link = CompetencyEvidence(
        competency_id=competency.id,
        knowledge_node_id=node.id,
        evidence_record_id=evidence.id,
        learner_id=evidence.learner_id,
        contribution_weight=contribution_weight,
        evidence_role=evidence_role,
    )
    session.add(link)
    session.flush()
    return link


def list_competency_evidence(
    session: Session,
    *,
    competency_id: str | None = None,
    learner_id: str | None = None,
    limit: int = 100,
) -> Sequence[CompetencyEvidence]:
    """List competency evidence links."""
    statement = select(CompetencyEvidence)
    if competency_id is not None:
        statement = statement.where(CompetencyEvidence.competency_id == competency_id)
    if learner_id is not None:
        statement = statement.where(CompetencyEvidence.learner_id == learner_id)
    statement = statement.order_by(
        CompetencyEvidence.created_at.desc(), CompetencyEvidence.id
    ).limit(limit)
    return list(session.scalars(statement))


def evidence_for_competency_learner(
    session: Session,
    *,
    competency_id: str,
    learner_id: str,
    limit: int = 100,
) -> Sequence[CompetencyEvidence]:
    """Return evidence contributing to one learner's current competency estimate."""
    return list_competency_evidence(
        session,
        competency_id=competency_id,
        learner_id=learner_id,
        limit=limit,
    )


def _ensure_supports_competency_edge(
    session: Session,
    *,
    competency: Competency,
    node: KnowledgeNode,
    actor_id: str,
) -> None:
    if "supports-competency" not in EDGE_TYPES:
        raise ValueError("knowledge graph does not support competency edges")
    existing = session.execute(
        select(KnowledgeNode.id).where(
            KnowledgeNode.id == competency.id,
        )
    ).scalar_one_or_none()
    if existing is None:
        competency_node = KnowledgeNode(
            id=competency.id,
            title=competency.title,
            description=competency.description,
            knowledge_type=competency.target_knowledge_type,
            ownership_scope=competency.ownership_scope,
            status=_competency_graph_status(competency.status),
            provenance="manual",
        )
        session.add(competency_node)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            action="create",
            entity_type="KnowledgeNode",
            entity_id=competency_node.id,
            source_subsystem="competencies",
            after_summary={
                "id": competency_node.id,
                "title": competency_node.title,
                "knowledge_type": competency_node.knowledge_type,
                "ownership_scope": competency_node.ownership_scope,
                "status": competency_node.status,
                "provenance": competency_node.provenance,
                "imported_from": competency_node.imported_from,
                "source_reference_id": competency_node.source_reference_id,
            },
        )
    from lms.graphs.models import KnowledgeEdge

    edge_exists = session.execute(
        select(KnowledgeEdge.id).where(
            KnowledgeEdge.source_node_id == node.id,
            KnowledgeEdge.target_node_id == competency.id,
            KnowledgeEdge.edge_type == "supports-competency",
            KnowledgeEdge.source_scope == competency.ownership_scope,
        )
    ).scalar_one_or_none()
    if edge_exists is None:
        create_knowledge_edge(
            session,
            source_node_id=node.id,
            target_node_id=competency.id,
            edge_type="supports-competency",
            scope=competency.ownership_scope,
            actor_id=actor_id,
            status=_competency_graph_status(competency.status),
            notes="Competency evidence link.",
            source_subsystem="competencies",
        )
