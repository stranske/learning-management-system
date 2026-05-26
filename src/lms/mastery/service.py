"""Recompute mastery estimates from evidence history."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import EvidenceRecord
from lms.mastery.policy import MasteryEstimatorPolicy


def mastery_estimates_for_learner(
    session: Session,
    learner_id: str,
    *,
    policy: MasteryEstimatorPolicy | None = None,
) -> list[dict[str, Any]]:
    """Compute current mastery per knowledge node without persisting a cache."""
    estimates, _ = mastery_estimates_with_evidence_for_learner(
        session,
        learner_id,
        policy=policy,
    )
    return estimates


def mastery_estimates_with_evidence_for_learner(
    session: Session,
    learner_id: str,
    *,
    policy: MasteryEstimatorPolicy | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[EvidenceRecord]]]:
    """Compute mastery and return the grouped evidence used for the estimates."""
    policy = policy or MasteryEstimatorPolicy()
    records = list(
        session.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.learner_id == learner_id)
            .order_by(EvidenceRecord.knowledge_node_id, EvidenceRecord.observed_at)
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
