"""Service-backed learner knowledge profile aggregator.

`KnowledgeProfile` is a computed view: it combines mastery estimates produced by
`lms.mastery.service.mastery_estimates_for_learner` with verbose
`EvidenceRecord` rows so callers can summarize what a learner appears able to
do without persisting a duplicate mastery cache.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import SUPPORT_LEVELS, EvidenceRecord
from lms.graphs.models import KnowledgeNode
from lms.learners.schemas import KnowledgeProfileRead, SupportDependence
from lms.mastery.policy import MasteryEstimatorPolicy
from lms.mastery.service import mastery_estimates_for_learner


def knowledge_profiles_for_learner(
    session: Session,
    learner_id: str,
    *,
    ownership_scope: str,
    policy: MasteryEstimatorPolicy | None = None,
) -> list[KnowledgeProfileRead]:
    """Return per-node knowledge profiles for one learner in one ownership scope."""
    estimates = mastery_estimates_for_learner(session, learner_id, policy=policy)
    if not estimates:
        return []

    node_ids = [row["knowledge_node_id"] for row in estimates]
    nodes_in_scope: dict[str, KnowledgeNode] = {
        node.id: node
        for node in session.scalars(
            select(KnowledgeNode).where(
                KnowledgeNode.id.in_(node_ids),
                KnowledgeNode.ownership_scope == ownership_scope,
            )
        )
    }
    if not nodes_in_scope:
        return []

    in_scope_records = session.scalars(
        select(EvidenceRecord)
        .where(
            EvidenceRecord.learner_id == learner_id,
            EvidenceRecord.knowledge_node_id.in_(nodes_in_scope.keys()),
        )
        .order_by(EvidenceRecord.knowledge_node_id, EvidenceRecord.observed_at)
    )
    by_node: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in in_scope_records:
        by_node[record.knowledge_node_id].append(record)

    profiles: list[KnowledgeProfileRead] = []
    for estimate in estimates:
        node_id = estimate["knowledge_node_id"]
        node = nodes_in_scope.get(node_id)
        if node is None:
            continue
        records = by_node.get(node_id, [])
        support = _summarize_support_dependence(records)
        profiles.append(
            KnowledgeProfileRead(
                learner_id=learner_id,
                ownership_scope=ownership_scope,
                knowledge_node_id=node_id,
                knowledge_node_title=node.title,
                current_estimate=estimate["current_estimate"],
                confidence=estimate["confidence"],
                evidence_count=estimate["evidence_count"],
                last_evidence_id=estimate["last_evidence_id"],
                last_evidence_at=estimate["last_evidence_at"],
                support_dependence=support,
                next_evidence_needed=_classify_next_evidence(estimate, records),
            )
        )
    profiles.sort(key=lambda profile: profile.knowledge_node_id)
    return profiles


def _summarize_support_dependence(records: list[EvidenceRecord]) -> SupportDependence:
    counts: dict[str, int] = dict.fromkeys(SUPPORT_LEVELS, 0)
    hint_uses = 0
    reference_accesses = 0
    last_support_level = "none"
    for record in records:
        if record.support_level in counts:
            counts[record.support_level] += 1
        if record.hint_used:
            hint_uses += 1
        if record.reference_accessed:
            reference_accesses += 1
    if records:
        last_support_level = records[-1].support_level
    return SupportDependence(
        last_support_level=last_support_level,
        hint_use_count=hint_uses,
        reference_access_count=reference_accesses,
        support_level_counts=counts,
    )


def _classify_next_evidence(estimate: dict[str, Any], records: list[EvidenceRecord]) -> str:
    if not records:
        return "introduce"
    if estimate["current_estimate"] < 0.7 or estimate["confidence"] < 0.5:
        return "consolidate"
    last_demand = records[-1].demand_level
    if last_demand in (None, "low", "medium"):
        return "stretch"
    return "maintain"
