"""Regression coverage for deterministic latest-record selection."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.evidence.models import Attempt, EvidenceRecord
from lms.ui.api import _latest_attempt_summary


def test_latest_attempt_is_stable_under_tied_timestamps(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = api_client
    tied_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    with session_factory() as session:
        session.add_all(
            [
                Attempt(
                    id="attempt-a",
                    learner_id="learner-stable",
                    prompt_id="prompt-stable",
                    response_text="Inserted first",
                    confidence_rating=1,
                    feedback={},
                    created_at=tied_at,
                ),
                Attempt(
                    id="attempt-z",
                    learner_id="learner-stable",
                    prompt_id="prompt-stable",
                    response_text="Stable descending-id winner",
                    confidence_rating=5,
                    feedback={},
                    created_at=tied_at,
                ),
            ]
        )
        session.commit()

        summaries = [
            _latest_attempt_summary(
                session,
                learner_id="learner-stable",
                prompt_id="prompt-stable",
            )
            for _ in range(2)
        ]

    assert summaries == [
        "Latest evidence: confidence 5/5; correctness pending scoring evidence.",
        "Latest evidence: confidence 5/5; correctness pending scoring evidence.",
    ]


def test_inspect_evidence_page_is_stable_under_tied_timestamps(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    tied_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    inserted_ids = ["evidence-b", "evidence-a", "evidence-c"]
    with session_factory() as session:
        session.add_all(
            [
                EvidenceRecord(
                    id=record_id,
                    learner_id="learner-stable",
                    knowledge_node_id=f"node-{record_id}",
                    observed_at=tied_at,
                )
                for record_id in inserted_ids
            ]
        )
        session.commit()

    reads = [client.get("/inspect/learners/learner-stable/overview") for _ in range(2)]

    assert all(response.status_code == 200 for response in reads)
    assert [row["id"] for row in reads[0].json()["recent_evidence"]] == [
        "evidence-a",
        "evidence-b",
        "evidence-c",
    ]
    assert reads[1].json()["recent_evidence"] == reads[0].json()["recent_evidence"]
