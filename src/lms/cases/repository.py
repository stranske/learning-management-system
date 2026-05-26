"""Repository helpers for transfer case shells."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lms.cases.models import (
    CASE_STATUSES,
    DECISION_POINT_TYPES,
    Case,
    CaseStep,
    DecisionPoint,
    EvidencePacket,
)
from lms.feedback.models import Rubric
from lms.graphs.models import OWNERSHIP_SCOPES, KnowledgeNode
from lms.sources.models import SourceReference


def create_case(
    session: Session,
    *,
    title: str,
    ownership_scope: str,
    description: str | None = None,
    rubric_id: str | None = None,
    knowledge_node_id: str | None = None,
    status: str = "draft",
    steps: list[dict[str, Any]] | None = None,
    evidence_packets: list[dict[str, Any]] | None = None,
) -> Case:
    """Create a case shell with optional ordered steps and evidence packets."""
    _require_scope(ownership_scope)
    _require_status(status)
    _validate_case_links(
        session,
        ownership_scope=ownership_scope,
        rubric_id=rubric_id,
        knowledge_node_id=knowledge_node_id,
    )
    _require_unique_orders(steps or [])
    case = Case(
        title=title,
        description=description,
        ownership_scope=ownership_scope,
        rubric_id=rubric_id,
        knowledge_node_id=knowledge_node_id,
        status=status,
    )
    for packet_data in evidence_packets or []:
        _require_source_reference(session, packet_data.get("source_reference_id"))
        case.evidence_packets.append(EvidencePacket(**packet_data))
    for step_data in sorted(steps or [], key=lambda item: item["step_order"]):
        case.steps.append(CaseStep(**step_data))
    session.add(case)
    session.flush()
    return get_case(session, case.id) or case


def get_case(session: Session, case_id: str) -> Case | None:
    """Return one case with ordered nested records loaded."""
    return session.scalar(
        select(Case)
        .options(
            selectinload(Case.steps).selectinload(CaseStep.decision_points),
            selectinload(Case.evidence_packets),
        )
        .where(Case.id == case_id)
        .execution_options(populate_existing=True)
    )


def list_cases(
    session: Session,
    *,
    ownership_scope: str | None = None,
    rubric_id: str | None = None,
    knowledge_node_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[Case]:
    """List case shells with common authoring filters."""
    statement = select(Case).options(selectinload(Case.steps), selectinload(Case.evidence_packets))
    if ownership_scope is not None:
        _require_scope(ownership_scope)
        statement = statement.where(Case.ownership_scope == ownership_scope)
    if rubric_id is not None:
        statement = statement.where(Case.rubric_id == rubric_id)
    if knowledge_node_id is not None:
        statement = statement.where(Case.knowledge_node_id == knowledge_node_id)
    if status is not None:
        _require_status(status)
        statement = statement.where(Case.status == status)
    statement = statement.order_by(Case.created_at.desc(), Case.id).limit(limit)
    return list(session.scalars(statement))


def add_case_step(
    session: Session,
    *,
    case_id: str,
    step_order: int,
    title: str,
    prompt: str,
    expected_work_product: str | None = None,
) -> CaseStep:
    """Append one ordered step to an existing case."""
    case = get_case(session, case_id)
    if case is None:
        raise ValueError("case was not found")
    _require_unique_orders([{"step_order": step.step_order} for step in case.steps] + [{"step_order": step_order}])
    step = CaseStep(
        case_id=case_id,
        step_order=step_order,
        title=title,
        prompt=prompt,
        expected_work_product=expected_work_product,
    )
    session.add(step)
    session.flush()
    return step


def add_evidence_packet(
    session: Session,
    *,
    case_id: str,
    title: str,
    summary: str | None = None,
    source_reference_id: str | None = None,
    packet_metadata: dict[str, Any] | None = None,
) -> EvidencePacket:
    """Add one evidence packet to an existing case."""
    if get_case(session, case_id) is None:
        raise ValueError("case was not found")
    _require_source_reference(session, source_reference_id)
    packet = EvidencePacket(
        case_id=case_id,
        title=title,
        summary=summary,
        source_reference_id=source_reference_id,
        packet_metadata=packet_metadata or {},
    )
    session.add(packet)
    session.flush()
    return packet


def add_decision_point(
    session: Session,
    *,
    case_step_id: str,
    title: str,
    prompt: str,
    decision_type: str,
    evidence_packet_id: str | None = None,
    options: list[dict[str, Any]] | None = None,
) -> DecisionPoint:
    """Add one decision point to a case step."""
    if decision_type not in DECISION_POINT_TYPES:
        raise ValueError(f"unknown decision type {decision_type!r}")
    step = session.get(CaseStep, case_step_id)
    if step is None:
        raise ValueError("case step was not found")
    if evidence_packet_id is not None:
        packet = session.get(EvidencePacket, evidence_packet_id)
        if packet is None or packet.case_id != step.case_id:
            raise ValueError("evidence packet must belong to the same case step's case")
    decision = DecisionPoint(
        case_step_id=case_step_id,
        title=title,
        prompt=prompt,
        decision_type=decision_type,
        evidence_packet_id=evidence_packet_id,
        options=options or [],
    )
    step.decision_points.append(decision)
    session.add(decision)
    session.flush()
    return decision


def serialize_case(case: Case) -> dict[str, object]:
    """Return a response-ready case payload."""
    return {
        "id": case.id,
        "title": case.title,
        "description": case.description,
        "ownership_scope": case.ownership_scope,
        "rubric_id": case.rubric_id,
        "knowledge_node_id": case.knowledge_node_id,
        "status": case.status,
        "steps": [serialize_case_step(step) for step in case.steps],
        "evidence_packets": [serialize_evidence_packet(packet) for packet in case.evidence_packets],
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def serialize_case_step(step: CaseStep) -> dict[str, object]:
    return {
        "id": step.id,
        "case_id": step.case_id,
        "step_order": step.step_order,
        "title": step.title,
        "prompt": step.prompt,
        "expected_work_product": step.expected_work_product,
        "decision_points": [serialize_decision_point(point) for point in step.decision_points],
        "created_at": step.created_at,
    }


def serialize_evidence_packet(packet: EvidencePacket) -> dict[str, object]:
    return {
        "id": packet.id,
        "case_id": packet.case_id,
        "title": packet.title,
        "summary": packet.summary,
        "source_reference_id": packet.source_reference_id,
        "packet_metadata": packet.packet_metadata,
        "created_at": packet.created_at,
    }


def serialize_decision_point(point: DecisionPoint) -> dict[str, object]:
    return {
        "id": point.id,
        "case_step_id": point.case_step_id,
        "evidence_packet_id": point.evidence_packet_id,
        "title": point.title,
        "prompt": point.prompt,
        "decision_type": point.decision_type,
        "options": point.options,
        "created_at": point.created_at,
    }


def _require_scope(scope: str) -> None:
    if scope not in OWNERSHIP_SCOPES:
        raise ValueError(f"unknown ownership scope {scope!r}")


def _require_status(status: str) -> None:
    if status not in CASE_STATUSES:
        raise ValueError(f"unknown case status {status!r}")


def _validate_case_links(
    session: Session,
    *,
    ownership_scope: str,
    rubric_id: str | None,
    knowledge_node_id: str | None,
) -> None:
    if rubric_id is not None:
        rubric = session.get(Rubric, rubric_id)
        if rubric is None or rubric.ownership_scope != ownership_scope:
            raise ValueError("rubric must exist and match case ownership_scope")
    if knowledge_node_id is not None:
        node = session.get(KnowledgeNode, knowledge_node_id)
        if node is None or node.ownership_scope != ownership_scope:
            raise ValueError("knowledge node must exist and match case ownership_scope")


def _require_source_reference(session: Session, source_reference_id: str | None) -> None:
    if source_reference_id is not None and session.get(SourceReference, source_reference_id) is None:
        raise ValueError("source reference was not found")


def _require_unique_orders(steps: list[dict[str, Any]]) -> None:
    orders = [int(step["step_order"]) for step in steps]
    if any(order < 1 for order in orders):
        raise ValueError("case step order must be positive")
    if len(set(orders)) != len(orders):
        raise ValueError("case step order must be unique")
