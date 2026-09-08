"""Tests for the v1 typed JSONL export contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.db.base import Base
from lms.export_import import ExportImportError, export_jsonl, import_jsonl
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


@pytest.mark.parametrize("include_pii", ["never", "all"])
@pytest.mark.parametrize("include_source_content", ["public-only", "all"])
@pytest.mark.parametrize("include_llm_traces", ["evidence-grade-only", "all"])
def test_export_excludes_password_hash_and_users_remain_importable(
    db_session: Session,
    tmp_path: Path,
    include_pii: str,
    include_source_content: str,
    include_llm_traces: str,
) -> None:
    password_hash = "synthetic-password-hash-for-export-regression"
    user = User(
        id="user-with-password",
        email="ada@example.com",
        username="ada",
        display_name="Ada",
        password_hash=password_hash,
    )
    db_session.add(user)
    db_session.commit()

    lines = list(
        export_jsonl(
            db_session,
            include_pii=include_pii,
            include_source_content=include_source_content,
            include_llm_traces=include_llm_traces,
            confirm_all="all" in (include_pii, include_source_content, include_llm_traces),
        )
    )
    assert len(lines) == 1
    record = json.loads(lines[0])["record"]
    assert "password_hash" not in record
    assert password_hash not in lines[0]
    assert ("email" in record) == (include_pii == "all")
    db_session.refresh(user)
    assert user.password_hash == password_hash

    path = tmp_path / "users.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            summary = import_jsonl(destination, path, dry_run=False)
            destination.commit()
            destination.expire_all()
            imported = destination.get(User, user.id)
            assert summary.counts == {"User": 1}
            assert imported is not None
            assert imported.username == user.username
            assert imported.password_hash is None
    finally:
        engine.dispose()
