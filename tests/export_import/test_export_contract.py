"""Tests for the v1 typed JSONL export contract."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.export_import import ExportImportError, export_jsonl
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.sources.models import SourceReference


def test_export_emits_jsonl_typed_records_in_dependency_order(db_session: Session) -> None:
    user = User(id="user-1", email="ada@example.com", username="ada", display_name="Ada")
    source = SourceReference(
        id="source-1",
        source_type="markdown-file",
        stable_locator="docs/demo.md#one",
        content_hash="hash",
        source_visibility="local-only",
    )
    parent = KnowledgeNode(
        id="node-1",
        title="Parent",
        knowledge_type="factual",
        ownership_scope="personal",
        status="published",
        provenance="manual",
        source_reference_id=source.id,
    )
    child = KnowledgeNode(
        id="node-2",
        title="Child",
        knowledge_type="factual",
        ownership_scope="personal",
        status="published",
        provenance="manual",
    )
    edge = KnowledgeEdge(
        id="edge-1",
        source_node_id=parent.id,
        target_node_id=child.id,
        edge_type="prerequisite",
        source_scope="personal",
        target_scope="personal",
        status="published",
    )
    db_session.add_all([user, source, parent, child, edge])
    db_session.commit()

    records = [json.loads(line) for line in export_jsonl(db_session)]

    assert [record["type"] for record in records] == [
        "User",
        "SourceReference",
        "KnowledgeNode",
        "KnowledgeNode",
        "KnowledgeEdge",
    ]
    assert records[0]["schema_version"] == 1
    assert records[0]["record"]["id"] == "user-1"
    assert "email" not in records[0]["record"]


def test_export_requires_confirmation_for_all_pii(db_session: Session) -> None:
    db_session.add(User(id="user-1", email="ada@example.com", username="ada", display_name="Ada"))
    db_session.commit()

    try:
        list(export_jsonl(db_session, include_pii="all"))
    except ExportImportError as exc:
        assert "requires --yes-i-mean-it" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected confirmation failure")
