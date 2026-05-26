"""Dry-run validation tests for typed JSONL imports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from lms.export_import import ExportImportError, import_jsonl
from lms.learners.models import Learner


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_dry_run_validates_foreign_keys_without_writing(
    tmp_path: Path, db_session: Session
) -> None:
    path = tmp_path / "import.jsonl"
    _write_jsonl(
        path,
        [
            {
                "type": "Learner",
                "schema_version": 1,
                "record": {
                    "id": "learner-1",
                    "user_id": "missing-user",
                    "display_name": "Ada",
                    "timezone": "UTC",
                    "locale": "en-US",
                },
            }
        ],
    )

    with pytest.raises(ExportImportError, match="references missing User:missing-user"):
        import_jsonl(db_session, path, dry_run=True)

    assert db_session.query(Learner).count() == 0


def test_dry_run_rejects_non_object_jsonl_entries(tmp_path: Path, db_session: Session) -> None:
    path = tmp_path / "import.jsonl"
    path.write_text('["not", "an", "object"]\n', encoding="utf-8")

    with pytest.raises(ExportImportError, match="line 1: entry must be an object"):
        import_jsonl(db_session, path, dry_run=True)
