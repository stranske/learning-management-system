"""Apply-mode tests for typed JSONL imports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.export_import import import_jsonl
from lms.learners.models import Learner


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_apply_writes_after_dry_run_validation_passes(tmp_path: Path, db_session: Session) -> None:
    path = tmp_path / "valid.jsonl"
    _write_jsonl(
        path,
        [
            {
                "type": "User",
                "schema_version": 1,
                "record": {
                    "id": "user-1",
                    "username": "ada",
                    "display_name": "Ada",
                    "is_local": True,
                },
            },
            {
                "type": "Learner",
                "schema_version": 1,
                "record": {
                    "id": "learner-1",
                    "user_id": "user-1",
                    "display_name": "Ada",
                    "timezone": "UTC",
                    "locale": "en-US",
                },
            },
        ],
    )

    summary = import_jsonl(db_session, path, dry_run=False)
    db_session.commit()

    assert summary.counts == {"User": 1, "Learner": 1}
    assert db_session.get(User, "user-1") is not None
    assert db_session.get(Learner, "learner-1") is not None


def test_apply_rolls_back_on_partial_failure(tmp_path: Path, db_session: Session) -> None:
    path = tmp_path / "invalid.jsonl"
    _write_jsonl(
        path,
        [
            {
                "type": "User",
                "schema_version": 1,
                "record": {
                    "id": "user-1",
                    "username": "ada",
                    "display_name": "Ada",
                    "is_local": True,
                },
            },
            {
                "type": "User",
                "schema_version": 1,
                "record": {
                    "id": "user-2",
                    "username": "ada",
                    "display_name": "Duplicate username",
                    "is_local": True,
                },
            },
        ],
    )

    with pytest.raises(IntegrityError):
        import_jsonl(db_session, path, dry_run=False)

    assert db_session.query(User).count() == 0
