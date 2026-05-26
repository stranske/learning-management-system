"""Repository helpers for personal capability targets and estimates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.auth.models import utc_now
from lms.capability.models import (
    CAPABILITY_TARGET_STATUSES,
    CapabilityEstimate,
    CapabilityTarget,
    GapAnalysis,
    MaintenancePlan,
)
from lms.competencies.models import Competency, CompetencyEvidence
from lms.evidence.models import EvidenceRecord
from lms.graphs.models import KnowledgeNode
from lms.learners.models import Learner, LearningGoal
from lms.learners.repository import knowledge_profile_for_learner
from lms.mastery.service import mastery_estimates_for_learner
from lms.scheduling.repository import (
    create_review_queue_item,
    create_review_schedule,
    create_scheduler_decision,
    get_or_create_review_policy,
)

BreakdownRow = dict[str, object]


def create_capability_target(
    session: Session,
    *,
    learner_id: str,
    title: str,
    ownership_scope: str = "personal",
    description: str | None = None,
    learning_goal_id: str | None = None,
    target_node_ids: list[str] | None = None,
    target_competency_ids: list[str] | None = None,
    required_evidence_types: list[str] | None = None,
    confidence_threshold: float = 0.8,
    status: str = "active",
) -> CapabilityTarget:
    """Create a personal capability target with validated graph and competency links."""
    _require_personal_scope(ownership_scope)
    _require_status(status)
    _require_confidence_threshold(confidence_threshold)
    _require_learner(session, learner_id)
    goal = _load_learning_goal(
        session,
        learner_id=learner_id,
        learning_goal_id=learning_goal_id,
        ownership_scope=ownership_scope,
    )
    target_nodes = _load_target_nodes(
        session,
        target_node_ids=target_node_ids or [],
        ownership_scope=ownership_scope,
        goal=goal,
    )
    target_competencies = _load_target_competencies(
        session,
        target_competency_ids=target_competency_ids or [],
        ownership_scope=ownership_scope,
    )
    if not target_nodes and not target_competencies:
        raise ValueError("capability target requires at least one node or competency")

    target = CapabilityTarget(
        learner_id=learner_id,
        title=title,
        description=description,
        ownership_scope=ownership_scope,
        learning_goal_id=learning_goal_id,
        target_nodes=target_nodes,
        target_competencies=target_competencies,
        required_evidence_types=_normalized_strings(required_evidence_types or []),
        confidence_threshold=confidence_threshold,
        status=status,
    )
    session.add(target)
    session.flush()
    return target


def get_capability_target(session: Session, target_id: str) -> CapabilityTarget | None:
    """Return one capability target by id."""
    return session.get(CapabilityTarget, target_id)


def list_capability_targets(
    session: Session,
    *,
    learner_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[CapabilityTarget]:
    """List capability targets with optional learner and status filters."""
    statement = select(CapabilityTarget)
    if learner_id is not None:
        statement = statement.where(CapabilityTarget.learner_id == learner_id)
    if status is not None:
        _require_status(status)
        statement = statement.where(CapabilityTarget.status == status)
    statement = statement.order_by(CapabilityTarget.created_at.desc(), CapabilityTarget.id).limit(
        limit
    )
    return list(session.scalars(statement))


def update_capability_target(
    session: Session,
    target: CapabilityTarget,
    *,
    title: str | None = None,
    description: str | None = None,
    learning_goal_id: str | None = None,
    target_node_ids: list[str] | None = None,
    target_competency_ids: list[str] | None = None,
    required_evidence_types: list[str] | None = None,
    confidence_threshold: float | None = None,
    status: str | None = None,
) -> CapabilityTarget:
    """Update mutable capability target fields."""
    next_status = status if status is not None else target.status
    _require_status(next_status)
    if confidence_threshold is not None:
        _require_confidence_threshold(confidence_threshold)

    next_goal_id = learning_goal_id if learning_goal_id is not None else target.learning_goal_id
    goal = _load_learning_goal(
        session,
        learner_id=target.learner_id,
        learning_goal_id=next_goal_id,
        ownership_scope=target.ownership_scope,
    )
    if title is not None:
        target.title = title
    if description is not None:
        target.description = description
    target.learning_goal_id = next_goal_id
    if target_node_ids is not None:
        target.target_nodes = _load_target_nodes(
            session,
            target_node_ids=target_node_ids,
            ownership_scope=target.ownership_scope,
            goal=goal,
        )
    if target_competency_ids is not None:
        target.target_competencies = _load_target_competencies(
            session,
            target_competency_ids=target_competency_ids,
            ownership_scope=target.ownership_scope,
        )
    if required_evidence_types is not None:
        target.required_evidence_types = _normalized_strings(required_evidence_types)
    if confidence_threshold is not None:
        target.confidence_threshold = confidence_threshold
    target.status = next_status
    if not target.target_nodes and not target.target_competencies:
        raise ValueError("capability target requires at least one node or competency")
    session.flush()
    return target


def archive_capability_target(session: Session, target: CapabilityTarget) -> CapabilityTarget:
    """Archive a target without deleting its planning history."""
    target.status = "archived"
    session.flush()
    return target


def recompute_capability_estimate(
    session: Session,
    *,
    target_id: str,
    estimator_version: str = "capability-target-estimator-v1",
) -> CapabilityEstimate:
    """Persist a target-relative estimate from mastery and competency evidence."""
    target = get_capability_target(session, target_id)
    if target is None:
        raise ValueError("capability target was not found")
    if target.ownership_scope != "personal":
        raise ValueError("capability estimates only support personal targets")

    profile = knowledge_profile_for_learner(
        session,
        learner_id=target.learner_id,
        ownership_scope="personal",
    )
    raw_profile_items = profile.get("items", [])
    profile_item_values = raw_profile_items if isinstance(raw_profile_items, list) else []
    profile_items = {
        str(item["knowledge_node_id"]): item
        for item in profile_item_values
        if isinstance(item, dict)
    }
    mastery_by_node = {
        str(estimate["knowledge_node_id"]): estimate
        for estimate in mastery_estimates_for_learner(session, target.learner_id)
    }
    target_node_ids = [node.id for node in target.target_nodes]
    node_rows = [
        _node_breakdown_row(
            node_id=node_id,
            profile_item=profile_items.get(node_id),
            mastery_estimate=mastery_by_node.get(node_id),
        )
        for node_id in target_node_ids
    ]
    competency_rows = _competency_breakdown_rows(session, target)

    score_components = [_as_float(row["current_estimate"]) for row in node_rows]
    score_components.extend(_as_float(row["weighted_score"]) for row in competency_rows)
    current_score = (
        round(sum(score_components) / len(score_components), 4) if score_components else 0.0
    )

    confidence_components = [_as_float(row["confidence"]) for row in node_rows]
    confidence_components.extend(_as_float(row["confidence"]) for row in competency_rows)
    coverage = _coverage_factor(node_rows=node_rows, competency_rows=competency_rows)
    confidence = (
        round((sum(confidence_components) / len(confidence_components)) * coverage, 4)
        if confidence_components
        else 0.0
    )
    weak_node_ids = [
        str(row["knowledge_node_id"])
        for row in node_rows
        if _as_float(row["current_estimate"]) < target.confidence_threshold
        or _as_float(row["confidence"]) < target.confidence_threshold
    ]
    evidence_breakdown = _json_safe(
        {
            "target_node_estimates": node_rows,
            "competency_evidence": competency_rows,
            "required_evidence_types": target.required_evidence_types,
            "knowledge_profile_items": [
                profile_items[node_id] for node_id in target_node_ids if node_id in profile_items
            ],
            "coverage_factor": coverage,
        }
    )
    estimate = CapabilityEstimate(
        target_id=target.id,
        learner_id=target.learner_id,
        estimator_version=estimator_version,
        current_score=current_score,
        confidence=confidence,
        validity_scope=_validity_scope(target),
        evidence_breakdown=evidence_breakdown,
        weak_node_ids=weak_node_ids,
        commentary=_commentary(current_score=current_score, confidence=confidence),
        commentary_redaction_class="learner-facing-inferred-mastery",
    )
    session.add(estimate)
    session.flush()
    return estimate


def get_capability_estimate(session: Session, estimate_id: str) -> CapabilityEstimate | None:
    """Return one persisted estimate by id."""
    return session.get(CapabilityEstimate, estimate_id)


def list_capability_estimates(
    session: Session,
    *,
    learner_id: str | None = None,
    target_id: str | None = None,
    limit: int = 100,
) -> Sequence[CapabilityEstimate]:
    """List persisted capability estimates, newest first."""
    statement = select(CapabilityEstimate)
    if learner_id is not None:
        statement = statement.where(CapabilityEstimate.learner_id == learner_id)
    if target_id is not None:
        statement = statement.where(CapabilityEstimate.target_id == target_id)
    statement = statement.order_by(
        CapabilityEstimate.generated_at.desc(),
        CapabilityEstimate.id,
    ).limit(limit)
    return list(session.scalars(statement))


def create_gap_analysis(session: Session, *, estimate_id: str) -> GapAnalysis:
    """Persist a target-relative gap analysis from one capability estimate."""
    estimate = get_capability_estimate(session, estimate_id)
    if estimate is None:
        raise ValueError("capability estimate was not found")
    target = get_capability_target(session, estimate.target_id)
    if target is None:
        raise ValueError("capability target was not found")
    if target.ownership_scope != "personal":
        raise ValueError("gap analyses only support personal targets")
    if estimate.learner_id != target.learner_id:
        raise ValueError("capability estimate learner must match target learner")

    gap_items = _gap_items_for_estimate(target=target, estimate=estimate)
    recommended_action_types = _recommended_action_types(gap_items)
    analysis = GapAnalysis(
        target_id=target.id,
        estimate_id=estimate.id,
        learner_id=estimate.learner_id,
        gap_items=gap_items,
        severity=_analysis_severity(gap_items),
        required_evidence=target.required_evidence_types,
        recommended_action_types=recommended_action_types,
        ownership_scope=target.ownership_scope,
    )
    session.add(analysis)
    session.flush()
    return analysis


def get_gap_analysis(session: Session, analysis_id: str) -> GapAnalysis | None:
    """Return one persisted gap analysis by id."""
    return session.get(GapAnalysis, analysis_id)


def list_gap_analyses(
    session: Session,
    *,
    learner_id: str | None = None,
    target_id: str | None = None,
    estimate_id: str | None = None,
    limit: int = 100,
) -> Sequence[GapAnalysis]:
    """List persisted gap analyses, newest first."""
    statement = select(GapAnalysis)
    if learner_id is not None:
        statement = statement.where(GapAnalysis.learner_id == learner_id)
    if target_id is not None:
        statement = statement.where(GapAnalysis.target_id == target_id)
    if estimate_id is not None:
        statement = statement.where(GapAnalysis.estimate_id == estimate_id)
    statement = statement.order_by(GapAnalysis.generated_at.desc(), GapAnalysis.id).limit(limit)
    return list(session.scalars(statement))


def create_maintenance_plan(
    session: Session,
    *,
    gap_analysis_id: str,
    policy_version: str = "maintenance-plan-v1",
    now: datetime | None = None,
) -> MaintenancePlan:
    """Turn a gap analysis into plan steps plus linked scheduler records."""
    analysis = get_gap_analysis(session, gap_analysis_id)
    if analysis is None:
        raise ValueError("gap analysis was not found")
    target = get_capability_target(session, analysis.target_id)
    if target is None:
        raise ValueError("capability target was not found")
    if analysis.ownership_scope != "personal" or target.ownership_scope != "personal":
        raise ValueError("maintenance plans only support personal gap analyses")
    if analysis.learner_id != target.learner_id:
        raise ValueError("gap analysis learner must match capability target learner")

    generated_at = now or utc_now()
    plan = MaintenancePlan(
        target_id=target.id,
        gap_analysis_id=analysis.id,
        learner_id=analysis.learner_id,
        status="active",
        plan_steps=[],
        schedule_ids=[],
        rationale=_maintenance_plan_rationale(analysis),
        generated_at=generated_at,
        ownership_scope="personal",
    )
    session.add(plan)
    session.flush()

    steps: list[dict[str, object]] = []
    schedule_ids: list[str] = []
    for index, gap_item in enumerate(_list_of_dicts(analysis.gap_items), start=1):
        step = _maintenance_step(gap_item, step_number=index)
        knowledge_node_id = step.get("knowledge_node_id")
        if isinstance(knowledge_node_id, str) and knowledge_node_id:
            reason_code = str(step["reason_code"])
            due_at = _step_due_at(generated_at, reason_code=reason_code)
            policy = get_or_create_review_policy(
                session,
                reason_code=reason_code,
                policy_version=policy_version,
                name=f"Maintenance plan {reason_code}",
                settings={"source": "gap-analysis", "plan_id": plan.id},
                ownership_scope=analysis.ownership_scope,
            )
            decision_log = {
                "rule": "gap-analysis-maintenance-plan",
                "gap_analysis_id": analysis.id,
                "maintenance_plan_id": plan.id,
                "gap_item": gap_item,
                "step_number": index,
            }
            queue_item = create_review_queue_item(
                session,
                learner_id=analysis.learner_id,
                knowledge_node_id=knowledge_node_id,
                reason_code=reason_code,
                reason_explanation=str(step["rationale"]),
                due_at=due_at,
                priority=_step_priority(reason_code=reason_code),
                decision_log=decision_log,
            )
            schedule = create_review_schedule(
                session,
                learner_id=analysis.learner_id,
                knowledge_node_id=knowledge_node_id,
                reason_code=reason_code,
                due_at=due_at,
                policy_version=policy_version,
                review_policy_id=policy.id,
                review_queue_item_id=queue_item.id,
                ownership_scope=analysis.ownership_scope,
            )
            decision = create_scheduler_decision(
                session,
                learner_id=analysis.learner_id,
                knowledge_node_id=knowledge_node_id,
                reason_code=reason_code,
                decision_rationale=str(step["rationale"]),
                policy_version=policy_version,
                decision_log=decision_log,
                review_policy_id=policy.id,
                review_schedule_id=schedule.id,
                review_queue_item_id=queue_item.id,
                ownership_scope=analysis.ownership_scope,
            )
            schedule_ids.append(schedule.id)
            step["review_queue_item_id"] = queue_item.id
            step["review_schedule_id"] = schedule.id
            step["scheduler_decision_id"] = decision.id
        steps.append(step)

    plan.plan_steps = steps
    plan.schedule_ids = schedule_ids
    session.flush()
    return plan


def get_maintenance_plan(session: Session, plan_id: str) -> MaintenancePlan | None:
    """Return one maintenance plan by id."""
    return session.get(MaintenancePlan, plan_id)


def list_maintenance_plans(
    session: Session,
    *,
    learner_id: str | None = None,
    target_id: str | None = None,
    gap_analysis_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[MaintenancePlan]:
    """List maintenance plans, newest first."""
    statement = select(MaintenancePlan)
    if learner_id is not None:
        statement = statement.where(MaintenancePlan.learner_id == learner_id)
    if target_id is not None:
        statement = statement.where(MaintenancePlan.target_id == target_id)
    if gap_analysis_id is not None:
        statement = statement.where(MaintenancePlan.gap_analysis_id == gap_analysis_id)
    if status is not None:
        statement = statement.where(MaintenancePlan.status == status)
    statement = statement.order_by(
        MaintenancePlan.generated_at.desc(), MaintenancePlan.id
    ).limit(limit)
    return list(session.scalars(statement))


def serialize_capability_target(target: CapabilityTarget) -> dict[str, object]:
    """Return a response-ready capability target payload."""
    return {
        "id": target.id,
        "learner_id": target.learner_id,
        "title": target.title,
        "description": target.description,
        "ownership_scope": target.ownership_scope,
        "learning_goal_id": target.learning_goal_id,
        "required_evidence_types": target.required_evidence_types,
        "confidence_threshold": target.confidence_threshold,
        "status": target.status,
        "target_node_ids": [node.id for node in target.target_nodes],
        "target_competency_ids": [competency.id for competency in target.target_competencies],
        "created_at": target.created_at,
        "updated_at": target.updated_at,
    }


def serialize_capability_estimate(estimate: CapabilityEstimate) -> dict[str, object]:
    """Return a response-ready capability estimate payload."""
    return {
        "id": estimate.id,
        "target_id": estimate.target_id,
        "learner_id": estimate.learner_id,
        "generated_at": estimate.generated_at,
        "estimator_version": estimate.estimator_version,
        "current_score": estimate.current_score,
        "confidence": estimate.confidence,
        "validity_scope": estimate.validity_scope,
        "evidence_breakdown": estimate.evidence_breakdown,
        "weak_node_ids": estimate.weak_node_ids,
        "commentary": estimate.commentary,
        "commentary_redaction_class": estimate.commentary_redaction_class,
        "created_at": estimate.created_at,
    }


def serialize_gap_analysis(analysis: GapAnalysis) -> dict[str, object]:
    """Return a response-ready gap analysis payload."""
    return {
        "id": analysis.id,
        "target_id": analysis.target_id,
        "estimate_id": analysis.estimate_id,
        "learner_id": analysis.learner_id,
        "generated_at": analysis.generated_at,
        "gap_items": analysis.gap_items,
        "severity": analysis.severity,
        "required_evidence": analysis.required_evidence,
        "recommended_action_types": analysis.recommended_action_types,
        "ownership_scope": analysis.ownership_scope,
        "created_at": analysis.created_at,
    }


def serialize_maintenance_plan(plan: MaintenancePlan) -> dict[str, object]:
    """Return a response-ready maintenance plan payload."""
    return {
        "id": plan.id,
        "target_id": plan.target_id,
        "gap_analysis_id": plan.gap_analysis_id,
        "learner_id": plan.learner_id,
        "status": plan.status,
        "plan_steps": plan.plan_steps,
        "schedule_ids": plan.schedule_ids,
        "rationale": plan.rationale,
        "generated_at": plan.generated_at,
        "ownership_scope": plan.ownership_scope,
        "created_at": plan.created_at,
    }


def _require_personal_scope(ownership_scope: str) -> None:
    if ownership_scope != "personal":
        raise ValueError("capability targets only support ownership_scope='personal' in M5")


def _require_status(status: str) -> None:
    if status not in CAPABILITY_TARGET_STATUSES:
        raise ValueError(
            f"unknown capability target status {status!r}; expected one of "
            f"{CAPABILITY_TARGET_STATUSES}"
        )


def _require_confidence_threshold(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError("confidence_threshold must be between 0.0 and 1.0")


def _require_learner(session: Session, learner_id: str) -> None:
    if session.get(Learner, learner_id) is None:
        raise ValueError("learner must exist before creating a capability target")


def _load_learning_goal(
    session: Session,
    *,
    learner_id: str,
    learning_goal_id: str | None,
    ownership_scope: str,
) -> LearningGoal | None:
    if learning_goal_id is None:
        return None
    goal = session.get(LearningGoal, learning_goal_id)
    if goal is None or goal.learner_id != learner_id:
        raise ValueError("learning goal must belong to the target learner")
    if goal.ownership_scope != ownership_scope:
        raise ValueError("learning goal ownership_scope must match capability target scope")
    return goal


def _load_target_nodes(
    session: Session,
    *,
    target_node_ids: list[str],
    ownership_scope: str,
    goal: LearningGoal | None,
) -> list[KnowledgeNode]:
    if not target_node_ids:
        return []
    nodes = list(
        session.scalars(
            select(KnowledgeNode).where(
                KnowledgeNode.id.in_(target_node_ids),
                KnowledgeNode.ownership_scope == ownership_scope,
            )
        )
    )
    found_by_id = {node.id: node for node in nodes}
    missing = [node_id for node_id in target_node_ids if node_id not in found_by_id]
    if missing:
        raise ValueError(f"target knowledge nodes not found in this scope: {', '.join(missing)}")
    ordered_nodes = [found_by_id[node_id] for node_id in target_node_ids]
    if goal is not None:
        goal_node_ids = {node.id for node in goal.target_nodes}
        outside_goal = [node.id for node in ordered_nodes if node.id not in goal_node_ids]
        if outside_goal:
            raise ValueError("target nodes must be linked to the learning goal when provided")
    return ordered_nodes


def _load_target_competencies(
    session: Session,
    *,
    target_competency_ids: list[str],
    ownership_scope: str,
) -> list[Competency]:
    if not target_competency_ids:
        return []
    competencies = list(
        session.scalars(
            select(Competency).where(
                Competency.id.in_(target_competency_ids),
                Competency.ownership_scope == ownership_scope,
            )
        )
    )
    found_by_id = {competency.id: competency for competency in competencies}
    missing = [
        competency_id for competency_id in target_competency_ids if competency_id not in found_by_id
    ]
    if missing:
        raise ValueError(f"target competencies not found in this scope: {', '.join(missing)}")
    return [found_by_id[competency_id] for competency_id in target_competency_ids]


def _normalized_strings(values: list[str]) -> list[str]:
    normalized = [value.strip() for value in values if value.strip()]
    if len(set(normalized)) != len(normalized):
        raise ValueError("required_evidence_types must not contain duplicates")
    return normalized


def _node_breakdown_row(
    *,
    node_id: str,
    profile_item: dict[str, object] | None,
    mastery_estimate: dict[str, Any] | None,
) -> BreakdownRow:
    if profile_item is None and mastery_estimate is None:
        return {
            "knowledge_node_id": node_id,
            "current_estimate": 0.0,
            "confidence": 0.0,
            "evidence_count": 0,
            "last_evidence_id": None,
            "next_evidence_needed": "initial observed evidence",
        }
    source = profile_item or mastery_estimate or {}
    return {
        "knowledge_node_id": node_id,
        "current_estimate": source.get("current_estimate", 0.0),
        "confidence": source.get("confidence", 0.0),
        "evidence_count": source.get("evidence_count", 0),
        "last_evidence_id": source.get("last_evidence_id"),
        "next_evidence_needed": source.get("next_evidence_needed", "more independent evidence"),
    }


def _competency_breakdown_rows(
    session: Session,
    target: CapabilityTarget,
) -> list[BreakdownRow]:
    rows: list[BreakdownRow] = []
    for competency in target.target_competencies:
        links = list(
            session.scalars(
                select(CompetencyEvidence)
                .where(
                    CompetencyEvidence.competency_id == competency.id,
                    CompetencyEvidence.learner_id == target.learner_id,
                )
                .order_by(CompetencyEvidence.created_at, CompetencyEvidence.id)
            )
        )
        evidence_records = [
            record
            for record in (session.get(EvidenceRecord, link.evidence_record_id) for link in links)
            if record is not None
        ]
        weighted_score = _weighted_evidence_score(links=links, records=evidence_records)
        rows.append(
            {
                "competency_id": competency.id,
                "title": competency.title,
                "evidence_count": len(evidence_records),
                "evidence_record_ids": [record.id for record in evidence_records],
                "weighted_score": weighted_score,
                "confidence": round(min(1.0, 0.25 + len(evidence_records) * 0.15), 4),
            }
        )
    return rows


def _weighted_evidence_score(
    *,
    links: list[CompetencyEvidence],
    records: list[EvidenceRecord],
) -> float:
    if not records:
        return 0.0
    record_by_id = {record.id: record for record in records}
    weighted_score = 0.0
    total_weight = 0.0
    for link in links:
        record = record_by_id.get(link.evidence_record_id)
        if record is None:
            continue
        weight = link.contribution_weight
        weighted_score += _record_score(record) * weight
        total_weight += weight
    return round(weighted_score / total_weight, 4) if total_weight else 0.0


def _record_score(record: EvidenceRecord) -> float:
    if record.normalized_score is not None:
        return float(record.normalized_score)
    if record.raw_score is not None and record.max_score:
        return float(record.raw_score) / float(record.max_score)
    if record.correctness is not None:
        return 1.0 if record.correctness else 0.0
    return 0.5


def _coverage_factor(
    *,
    node_rows: list[BreakdownRow],
    competency_rows: list[BreakdownRow],
) -> float:
    expected = len(node_rows) + len(competency_rows)
    if expected == 0:
        return 0.0
    covered = sum(1 for row in node_rows if _as_int(row["evidence_count"]) > 0)
    covered += sum(1 for row in competency_rows if _as_int(row["evidence_count"]) > 0)
    return round(covered / expected, 4)


def _as_float(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    return 0.0


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        return int(value)
    return 0


def _json_safe(value: object) -> dict[str, object]:
    converted = _json_safe_value(value)
    if not isinstance(converted, dict):
        raise TypeError("capability estimate breakdown must be a JSON object")
    return converted


def _json_safe_value(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    return value


def _validity_scope(target: CapabilityTarget) -> str:
    return (
        f"Personal estimate for capability target {target.id} based on current learner "
        "evidence only; it is not a permanent certification or cross-learner ranking."
    )


def _commentary(*, current_score: float, confidence: float) -> str:
    if confidence < 0.5:
        return (
            "Current evidence suggests an early estimate, but confidence is low because "
            "the evidence base is still sparse."
        )
    if current_score >= 0.8:
        return "Current evidence suggests strong progress toward this capability target."
    return "Current evidence suggests more practice is needed for this capability target."


def _gap_items_for_estimate(
    *,
    target: CapabilityTarget,
    estimate: CapabilityEstimate,
) -> list[dict[str, object]]:
    breakdown = estimate.evidence_breakdown
    profile_items = {
        str(item["knowledge_node_id"]): item
        for item in _list_of_dicts(breakdown.get("knowledge_profile_items"))
        if "knowledge_node_id" in item
    }
    gap_items: list[dict[str, object]] = []
    for row in _list_of_dicts(breakdown.get("target_node_estimates")):
        node_id = str(row.get("knowledge_node_id", ""))
        if not node_id:
            continue
        profile_item = profile_items.get(node_id, {})
        gap_items.extend(
            _node_gap_items(
                target=target,
                row=row,
                profile_item=profile_item,
            )
        )
    for row in _list_of_dicts(breakdown.get("competency_evidence")):
        competency_id = str(row.get("competency_id", ""))
        if not competency_id:
            continue
        gap_items.extend(_competency_gap_items(target=target, row=row))
    return gap_items


def _node_gap_items(
    *,
    target: CapabilityTarget,
    row: dict[str, object],
    profile_item: dict[str, object],
) -> list[dict[str, object]]:
    node_id = str(row["knowledge_node_id"])
    current_estimate = _as_float(row.get("current_estimate", 0.0))
    confidence = _as_float(row.get("confidence", 0.0))
    evidence_count = _as_int(row.get("evidence_count", 0))
    next_evidence_needed = str(row.get("next_evidence_needed", "more evidence"))
    support_markers = profile_item.get("support_dependence_markers", [])
    markers = [str(marker) for marker in support_markers if isinstance(marker, str)] if isinstance(
        support_markers, list
    ) else []
    items: list[dict[str, object]] = []
    if evidence_count == 0:
        items.append(
            _gap_item(
                gap_type="missing_evidence",
                severity="high",
                recommended_action_type="collect-initial-evidence",
                knowledge_node_id=node_id,
                required_evidence=target.required_evidence_types,
                rationale="No observed evidence exists for this target node yet.",
                current_estimate=current_estimate,
                confidence=confidence,
            )
        )
    if current_estimate < target.confidence_threshold:
        items.append(
            _gap_item(
                gap_type="weak_mastery",
                severity="high" if current_estimate < 0.5 else "medium",
                recommended_action_type="remediation-practice",
                knowledge_node_id=node_id,
                required_evidence=target.required_evidence_types,
                rationale="Current evidence is below the target confidence threshold.",
                current_estimate=current_estimate,
                confidence=confidence,
            )
        )
    if evidence_count > 0 and confidence < target.confidence_threshold:
        items.append(
            _gap_item(
                gap_type="low_confidence_evidence",
                severity="medium",
                recommended_action_type="collect-stronger-evidence",
                knowledge_node_id=node_id,
                required_evidence=target.required_evidence_types,
                rationale="Evidence exists, but confidence coverage remains below the target threshold.",
                current_estimate=current_estimate,
                confidence=confidence,
            )
        )
    if markers:
        items.append(
            _gap_item(
                gap_type="support_dependence",
                severity="medium",
                recommended_action_type="independent-practice",
                knowledge_node_id=node_id,
                required_evidence=["independent evidence"],
                rationale="Recent evidence relied on support, hints, or references.",
                current_estimate=current_estimate,
                confidence=confidence,
                support_dependence_markers=markers,
            )
        )
    if _needs_transfer_evidence(target.required_evidence_types, next_evidence_needed):
        items.append(
            _gap_item(
                gap_type="transfer_evidence_needed",
                severity="medium",
                recommended_action_type="transfer-case",
                knowledge_node_id=node_id,
                required_evidence=["transfer-case"],
                rationale="The target still needs independent transfer evidence.",
                current_estimate=current_estimate,
                confidence=confidence,
            )
        )
    return items


def _competency_gap_items(
    *,
    target: CapabilityTarget,
    row: dict[str, object],
) -> list[dict[str, object]]:
    competency_id = str(row["competency_id"])
    evidence_count = _as_int(row.get("evidence_count", 0))
    weighted_score = _as_float(row.get("weighted_score", 0.0))
    confidence = _as_float(row.get("confidence", 0.0))
    items: list[dict[str, object]] = []
    if evidence_count == 0:
        items.append(
            _gap_item(
                gap_type="missing_evidence",
                severity="high",
                recommended_action_type="collect-competency-evidence",
                competency_id=competency_id,
                required_evidence=target.required_evidence_types,
                rationale="No learner evidence has been linked to this target competency.",
                current_estimate=weighted_score,
                confidence=confidence,
            )
        )
    elif weighted_score < target.confidence_threshold:
        items.append(
            _gap_item(
                gap_type="weak_mastery",
                severity="high" if weighted_score < 0.5 else "medium",
                recommended_action_type="remediation-practice",
                competency_id=competency_id,
                required_evidence=target.required_evidence_types,
                rationale="Competency evidence is below the target confidence threshold.",
                current_estimate=weighted_score,
                confidence=confidence,
            )
        )
    return items


def _gap_item(
    *,
    gap_type: str,
    severity: str,
    recommended_action_type: str,
    required_evidence: list[str],
    rationale: str,
    current_estimate: float,
    confidence: float,
    knowledge_node_id: str | None = None,
    competency_id: str | None = None,
    support_dependence_markers: list[str] | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "gap_type": gap_type,
        "severity": severity,
        "recommended_action_type": recommended_action_type,
        "required_evidence": required_evidence,
        "rationale": rationale,
        "current_estimate": round(current_estimate, 4),
        "confidence": round(confidence, 4),
    }
    if knowledge_node_id is not None:
        item["knowledge_node_id"] = knowledge_node_id
    if competency_id is not None:
        item["competency_id"] = competency_id
    if support_dependence_markers:
        item["support_dependence_markers"] = support_dependence_markers
    return item


def _recommended_action_types(gap_items: list[dict[str, object]]) -> list[str]:
    action_types = {
        str(item["recommended_action_type"])
        for item in gap_items
        if isinstance(item.get("recommended_action_type"), str)
    }
    return sorted(action_types)


def _analysis_severity(gap_items: list[dict[str, object]]) -> str:
    severities = {str(item.get("severity")) for item in gap_items}
    if "high" in severities:
        return "high"
    if "medium" in severities:
        return "medium"
    return "low"


def _needs_transfer_evidence(required_evidence_types: list[str], next_evidence_needed: str) -> bool:
    required = {value.lower() for value in required_evidence_types}
    return "transfer-case" in required or "transfer" in next_evidence_needed.lower()


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _maintenance_plan_rationale(analysis: GapAnalysis) -> str:
    action_count = len(_list_of_dicts(analysis.gap_items))
    return (
        f"Generated {action_count} evidence-maintenance step(s) from gap analysis "
        f"{analysis.id} for learner {analysis.learner_id}."
    )


def _maintenance_step(gap_item: dict[str, object], *, step_number: int) -> dict[str, object]:
    action_type = str(gap_item.get("recommended_action_type", "review"))
    reason_code = _reason_code_for_action(action_type)
    references = {
        key: gap_item[key]
        for key in (
            "prompt_id",
            "knowledge_node_id",
            "rubric_id",
            "case_id",
            "feedback_action_id",
            "competency_id",
        )
        if key in gap_item
    }
    step: dict[str, object] = {
        "step_number": step_number,
        "gap_type": str(gap_item.get("gap_type", "gap")),
        "action_type": action_type,
        "reason_code": reason_code,
        "status": "planned",
        "rationale": str(gap_item.get("rationale", "Plan the next evidence step.")),
        "references": references,
        "required_evidence": gap_item.get("required_evidence", []),
    }
    if isinstance(gap_item.get("knowledge_node_id"), str):
        step["knowledge_node_id"] = str(gap_item["knowledge_node_id"])
    if isinstance(gap_item.get("competency_id"), str):
        step["competency_id"] = str(gap_item["competency_id"])
    return step


def _reason_code_for_action(action_type: str) -> str:
    normalized = action_type.lower()
    if "remediation" in normalized or "practice" in normalized:
        return "remediation"
    if "initial" in normalized or "new" in normalized:
        return "new-learning"
    return "due-review"


def _step_due_at(now: datetime, *, reason_code: str) -> datetime:
    if reason_code == "remediation":
        return now
    if reason_code == "new-learning":
        return now + timedelta(days=1)
    return now + timedelta(days=3)


def _step_priority(*, reason_code: str) -> float:
    if reason_code == "remediation":
        return 0.9
    if reason_code == "new-learning":
        return 0.7
    return 0.6
