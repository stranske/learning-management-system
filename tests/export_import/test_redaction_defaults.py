"""Redaction defaults for export/import transport."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.export_import import export_jsonl
from lms.llm.models import LLMSession
from lms.sources.models import SourceReference


def test_default_export_excludes_local_only_source_body_and_pii(db_session: Session) -> None:
    db_session.add_all(
        [
            User(id="user-1", email="ada@example.com", username="ada", display_name="Ada"),
            SourceReference(
                id="source-1",
                source_type="markdown-file",
                stable_locator="/private/notes.md#one",
                content_hash="hash",
                source_visibility="local-only",
            ),
            LLMSession(
                id="llm-1",
                mode="study-coach",
                trace_class="formative",
                provider="fake",
                model="fake-model",
                response_summary="private coaching trace",
                external_export_allowed=True,
            ),
            LLMSession(
                id="llm-2",
                mode="practice",
                trace_class="evidence-grade",
                provider="fake",
                model="fake-model",
                response_summary="evidence summary",
                external_export_allowed=True,
            ),
        ]
    )
    db_session.commit()

    records = [json.loads(line) for line in export_jsonl(db_session)]
    by_type = {record["type"]: record for record in records if record["type"] != "LLMSession"}
    llm_ids = [record["record"]["id"] for record in records if record["type"] == "LLMSession"]

    assert "email" not in by_type["User"]["record"]
    assert by_type["SourceReference"]["record"]["source_visibility"] == "local-only"
    assert "body" not in by_type["SourceReference"]["record"]
    assert llm_ids == ["llm-2"]
