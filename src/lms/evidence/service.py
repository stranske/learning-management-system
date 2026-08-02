"""Attempt recording that keeps the learning loop connected.

Audit finding LMS-R2 (2026-08-01): ``POST /attempts`` and both UI attempt
forms persisted attempts (and even fully scored evidence) without ever
invoking the scheduler, so the spaced-retrieval loop silently stopped —
evidence existed but no review was ever queued. This service is the single
ingestion seam: whenever an attempt carries a scoring signal, the scheduler
and any configured remediation triggers run in the same transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import Attempt, EvidenceRecord
from lms.evidence.repository import create_attempt
from lms.scheduling.models import ReviewQueueItem
from lms.scheduling.service import apply_remediation_triggers, schedule_from_attempt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordedAttempt:
    """The attempt plus whatever the loop produced from it."""

    attempt: Attempt
    evidence_record: EvidenceRecord | None
    review_queue_item: ReviewQueueItem | None
    remediation_items: list[ReviewQueueItem]


def evidence_record_for_attempt(session: Session, attempt_id: str) -> EvidenceRecord | None:
    """Return the evidence record created with an attempt, if any."""
    return session.scalars(
        select(EvidenceRecord)
        .where(EvidenceRecord.attempt_id == attempt_id)
        .order_by(EvidenceRecord.id)
    ).first()


def schedule_for_evidence(
    session: Session,
    *,
    attempt: Attempt,
    evidence_record: EvidenceRecord,
) -> tuple[ReviewQueueItem, list[ReviewQueueItem]]:
    """Advance the loop for scored evidence: next review + remediation triggers."""
    queue_item = schedule_from_attempt(session, attempt=attempt, evidence_record=evidence_record)
    remediation_items = apply_remediation_triggers(
        session, attempt=attempt, evidence_record=evidence_record
    )
    return queue_item, remediation_items


def record_attempt(session: Session, **attempt_kwargs: Any) -> RecordedAttempt:
    """Persist an attempt and, when it carries scoring, schedule its follow-up.

    The caller commits. Unscored attempts (no evidence signal) persist exactly
    as before and await a scoring step (rubric scoring or learner
    self-grading), which runs :func:`schedule_for_evidence` itself.
    """
    attempt = create_attempt(session, **attempt_kwargs)
    evidence_record = evidence_record_for_attempt(session, attempt.id)
    queue_item: ReviewQueueItem | None = None
    remediation_items: list[ReviewQueueItem] = []
    if evidence_record is not None:
        queue_item, remediation_items = schedule_for_evidence(
            session, attempt=attempt, evidence_record=evidence_record
        )
    return RecordedAttempt(
        attempt=attempt,
        evidence_record=evidence_record,
        review_queue_item=queue_item,
        remediation_items=remediation_items,
    )
