import json

from sqlalchemy import select
from tests.conftest import db_session
from tests.scheduling.test_review_queue import _make_attempt

from lms.scheduling.fsrs_adapter import evidence_to_fsrs_rating
from lms.scheduling.models import ReviewCardState
from lms.scheduling.service import schedule_from_attempt

fixture = db_session.__wrapped__()
session = next(fixture)
try:
    attempt, evidence = _make_attempt(session, correctness=True, confidence_rating=5)
    evidence.raw_score = float("inf")
    evidence.max_score = 1.0
    session.flush()
    rating = evidence_to_fsrs_rating(evidence)
    item = schedule_from_attempt(session, attempt=attempt, evidence_record=evidence)
    session.commit()
    session.expire_all()
    card = session.scalars(select(ReviewCardState)).one()
    print(
        json.dumps(
            {
                "adapter_value": rating.value,
                "adapter_rule": rating.rule_id,
                "scheduler_signal": item.decision_log["signal"],
                "card_review_count": card.review_count,
                "persisted_due_date": card.due_at.isoformat(),
                "recorded_rating": item.decision_log["fsrs_rating"],
            },
            indent=2,
        )
    )
finally:
    fixture.close()
