"""Recompute mastery estimates from evidence history."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import EvidenceRecord
from lms.graphs.models import OWNERSHIP_SCOPES, KnowledgeNode
from lms.mastery.policy import MasteryEstimatorPolicy


def mastery_estimates_for_learner(
    session: Session,
    learner_id: str,
    *,
    scope: str | None = None,
    policy: MasteryEstimatorPolicy | None = None,
) -> list[dict[str, Any]]:
    """Compute mastery; scoped callers filter source nodes before aggregation.

    Omitting scope retains the existing internal all-scope computation.
    """
    estimates, _ = mastery_estimates_with_evidence_for_learner(
        session,
        learner_id,
        scope=scope,
        policy=policy,
    )
    return estimates


def mastery_estimates_with_evidence_for_learner(
    session: Session,
    learner_id: str,
    *,
    scope: str | None = None,
    policy: MasteryEstimatorPolicy | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[EvidenceRecord]]]:
    """Compute mastery and return the grouped evidence used for the estimates."""
    policy = policy or MasteryEstimatorPolicy()
    statement = select(EvidenceRecord).where(EvidenceRecord.learner_id == learner_id)
    if scope is not None:
        if scope not in OWNERSHIP_SCOPES:
            raise ValueError(f"unknown ownership scope {scope!r}")
        statement = statement.join(
            KnowledgeNode, KnowledgeNode.id == EvidenceRecord.knowledge_node_id
        ).where(KnowledgeNode.ownership_scope == scope)
    records = list(
        session.scalars(
            statement.order_by(
                EvidenceRecord.knowledge_node_id,
                EvidenceRecord.observed_at,
                EvidenceRecord.created_at,
                EvidenceRecord.id,
            )
        )
    )
    by_node: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        by_node[record.knowledge_node_id].append(record)

    generated_at = datetime.now(UTC)
    estimates: list[dict[str, Any]] = []
    for node_id, node_records in sorted(by_node.items()):
        mastery, confidence = policy.estimate(node_records)
        last = node_records[-1]
        estimates.append(
            {
                "learner_id": learner_id,
                "knowledge_node_id": node_id,
                "current_estimate": mastery,
                "confidence": confidence,
                "evidence_count": len(node_records),
                "last_evidence_id": last.id,
                "last_evidence_at": last.observed_at,
                "estimator_version": policy.estimator_version,
                "model_attribution": policy.model_attribution,
                "generated_at": generated_at,
            }
        )
    return estimates, dict(by_node)
