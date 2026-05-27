"""Repository helpers for transfer case shells."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lms.cases.models import (
    CASE_STATUSES,
    DECISION_POINT_TYPES,
    WORK_PRODUCT_STATUSES,
    WORK_PRODUCT_SUBMISSION_TYPES,
    Case,
    CaseStep,
    DecisionPoint,
    EvidencePacket,
    WorkProduct,
)
from lms.feedback.models import RevisionRequest, Rubric, RubricScore
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
    statement = select(Case).options(
        selectinload(Case.steps).selectinload(CaseStep.decision_points),
        selectinload(Case.evidence_packets),
    )
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
    _require_unique_orders(
        [{"step_order": step.step_order} for step in case.steps] + [{"step_order": step_order}]
    )
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


def create_work_product(
    session: Session,
    *,
    case_id: str,
    learner_id: str,
    submission_type: str,
    case_step_id: str | None = None,
    rubric_id: str | None = None,
    prompt_id: str | None = None,
    body: str | None = None,
    artifact_ref: str | None = None,
    status: str = "submitted",
) -> WorkProduct:
    """Record a learner work product submitted for a transfer case."""
    _require_submission_type(submission_type)
    _require_work_product_status(status)
    if status not in ("draft", "submitted"):
        raise ValueError("work product status on create must be draft or submitted")
    if body is None and artifact_ref is None:
        raise ValueError("work product must include a body or an artifact_ref")
    case = get_case(session, case_id)
    if case is None:
        raise ValueError("case was not found")
    if case_step_id is not None:
        step = session.get(CaseStep, case_step_id)
        if step is None or step.case_id != case_id:
            raise ValueError("case step must belong to the work product case")
    if rubric_id is not None:
        rubric = session.get(Rubric, rubric_id)
        if rubric is None or rubric.ownership_scope != case.ownership_scope:
            raise ValueError("rubric must exist and match the case ownership_scope")
    work_product = WorkProduct(
        case_id=case_id,
        learner_id=learner_id,
        submission_type=submission_type,
        case_step_id=case_step_id,
        rubric_id=rubric_id,
        prompt_id=prompt_id,
        body=body,
        artifact_ref=artifact_ref,
        status=status,
    )
    session.add(work_product)
    session.flush()
    return work_product


def get_work_product(session: Session, work_product_id: str) -> WorkProduct | None:
    """Return one work product by id."""
    return session.get(WorkProduct, work_product_id)


def list_work_products(
    session: Session,
    *,
    case_id: str | None = None,
    learner_id: str | None = None,
    case_step_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[WorkProduct]:
    """List work products with common case and learner filters."""
    statement = select(WorkProduct)
    if case_id is not None:
        statement = statement.where(WorkProduct.case_id == case_id)
    if learner_id is not None:
        statement = statement.where(WorkProduct.learner_id == learner_id)
    if case_step_id is not None:
        statement = statement.where(WorkProduct.case_step_id == case_step_id)
    if status is not None:
        _require_work_product_status(status)
        statement = statement.where(WorkProduct.status == status)
    statement = statement.order_by(WorkProduct.submitted_at.desc(), WorkProduct.id).limit(limit)
    return list(session.scalars(statement))


def score_work_product(
    session: Session,
    work_product: WorkProduct,
    *,
    scorer_type: str,
    criterion_scores: list[dict[str, Any]],
    raw_score: float,
    max_score: float,
    normalized_score: float | None = None,
    scorer_id: str | None = None,
    scorer_version: str | None = None,
    knowledge_node_id: str | None = None,
    transfer_distance: str = "case-transfer",
    validity_scope: str | None = None,
    score_metadata: dict[str, Any] | None = None,
) -> RubricScore:
    """Score a work product against its rubric and capture transfer evidence.

    Reuses the attempt/feedback/rubric-score/evidence stack: the submission is
    recorded as an attempt so a ``RubricScore`` can anchor to it, and a transfer
    ``EvidenceRecord`` carries the ``transfer_distance`` and case-scoped validity.
    """
    rubric_id = work_product.rubric_id
    if rubric_id is None:
        raise ValueError("work product requires a linked rubric to score")
    case = get_case(session, work_product.case_id)
    if case is None:
        raise ValueError("case was not found")
    resolved_node_id = knowledge_node_id or case.knowledge_node_id
    if resolved_node_id is None:
        rubric = session.get(Rubric, rubric_id)
        resolved_node_id = rubric.knowledge_node_id if rubric is not None else None
    if resolved_node_id is None:
        raise ValueError(
            "scoring a work product requires a knowledge node from the case, rubric, "
            "or an explicit knowledge_node_id"
        )
    if max_score <= 0:
        raise ValueError("max_score must be positive")
    if raw_score < 0:
        raise ValueError("raw_score must be non-negative")
    computed_normalized = (
        normalized_score if normalized_score is not None else raw_score / max_score
    )
    if not 0.0 <= computed_normalized <= 1.0:
        raise ValueError("normalized_score must be within the unit interval")

    # Local imports mirror the lazy cross-module repository pattern and avoid cycles.
    from lms.evidence.repository import create_attempt, create_evidence_record
    from lms.feedback.repository import create_rubric_score

    prompt_context = work_product.prompt_id or work_product.case_step_id or work_product.case_id
    response_text = work_product.body or f"[artifact] {work_product.artifact_ref}"
    attempt = create_attempt(
        session,
        learner_id=work_product.learner_id,
        prompt_id=prompt_context,
        response_text=response_text,
        feedback={
            "goal": "Score the transfer-case work product against its rubric.",
            "next_action": "Review the transfer evidence and decide on a revision.",
        },
    )
    scope_value = validity_scope or f"transfer-case:{work_product.case_id}"
    evidence = create_evidence_record(
        session,
        learner_id=work_product.learner_id,
        knowledge_node_id=resolved_node_id,
        attempt_id=attempt.id,
        prompt_id=attempt.prompt_id,
        evidence_kind="observed",
        transfer_distance=transfer_distance,
        validity_scope=scope_value,
        raw_score=raw_score,
        normalized_score=computed_normalized,
        max_score=max_score,
        answer_artifact_ref=work_product.artifact_ref,
        scorer_metadata={"source": "work-product", "work_product_id": work_product.id},
    )
    score = create_rubric_score(
        session,
        rubric_id=rubric_id,
        attempt_id=attempt.id,
        learner_id=work_product.learner_id,
        scorer_type=scorer_type,
        raw_score=raw_score,
        normalized_score=computed_normalized,
        max_score=max_score,
        criterion_scores=criterion_scores,
        scorer_id=scorer_id,
        scorer_version=scorer_version,
        evidence_record_id=evidence.id,
        score_metadata=score_metadata,
    )
    work_product.rubric_score_id = score.id
    work_product.status = "scored"
    session.flush()
    return score


def request_work_product_revision(
    session: Session,
    work_product: WorkProduct,
    *,
    feedback_record_id: str | None = None,
    feedback_action_id: str | None = None,
) -> RevisionRequest:
    """Open a revision request for a work product from case feedback."""
    # Local import mirrors the lazy cross-module repository pattern and avoids cycles.
    from lms.feedback.repository import create_revision_request

    request = create_revision_request(
        session,
        learner_id=work_product.learner_id,
        feedback_record_id=feedback_record_id,
        feedback_action_id=feedback_action_id,
        work_product_id=work_product.id,
    )
    session.flush()
    return request


def serialize_work_product(work_product: WorkProduct) -> dict[str, object]:
    """Return a response-ready work product payload."""
    return {
        "id": work_product.id,
        "case_id": work_product.case_id,
        "case_step_id": work_product.case_step_id,
        "learner_id": work_product.learner_id,
        "rubric_id": work_product.rubric_id,
        "prompt_id": work_product.prompt_id,
        "submission_type": work_product.submission_type,
        "body": work_product.body,
        "artifact_ref": work_product.artifact_ref,
        "status": work_product.status,
        "rubric_score_id": work_product.rubric_score_id,
        "revision_request_id": work_product.revision_request_id,
        "submitted_at": work_product.submitted_at,
        "created_at": work_product.created_at,
        "updated_at": work_product.updated_at,
    }


def _require_submission_type(submission_type: str) -> None:
    if submission_type not in WORK_PRODUCT_SUBMISSION_TYPES:
        raise ValueError(f"unknown work product submission type {submission_type!r}")


def _require_work_product_status(status: str) -> None:
    if status not in WORK_PRODUCT_STATUSES:
        raise ValueError(f"unknown work product status {status!r}")


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
    if (
        source_reference_id is not None
        and session.get(SourceReference, source_reference_id) is None
    ):
        raise ValueError("source reference was not found")


def _require_unique_orders(steps: list[dict[str, Any]]) -> None:
    orders = [int(step["step_order"]) for step in steps]
    if any(order < 1 for order in orders):
        raise ValueError("case step order must be positive")
    if len(set(orders)) != len(orders):
        raise ValueError("case step order must be unique")
