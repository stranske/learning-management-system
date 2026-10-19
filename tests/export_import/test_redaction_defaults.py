"""Redaction defaults for export/import transport."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.models import CapabilityEstimate
from lms.cases.models import EvidencePacket
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


def test_m5_redaction_excludes_inferred_capability_and_formative_llm_bodies(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            CapabilityEstimate(
                id="capability-estimate-1",
                target_id="capability-target-1",
                learner_id="learner-1",
                estimator_version="test",
                current_score=0.45,
                confidence=0.7,
                validity_scope="local demo",
                evidence_breakdown={"evidence-1": "weak"},
                commentary="Private inferred capability commentary.",
                commentary_redaction_class="internal-inferred-mastery",
            ),
            EvidencePacket(
                id="evidence-packet-1",
                case_id="case-1",
                title="Packet",
                source_reference_id="source-1",
                packet_metadata={"local_body": "private packet detail"},
            ),
            LLMSession(
                id="llm-formative",
                mode="study-coach",
                trace_class="formative",
                provider="fake",
                model="fake-model",
                response_summary="verbatim formative coaching trace",
                external_export_allowed=True,
            ),
            LLMSession(
                id="llm-evidence",
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
    by_type = {record["type"]: record["record"] for record in records}
    llm_ids = [record["record"]["id"] for record in records if record["type"] == "LLMSession"]

    assert by_type["CapabilityEstimate"]["commentary"] == (
        "[redacted: inferred capability commentary]"
    )
    assert by_type["EvidencePacket"]["packet_metadata"] == {}
    assert llm_ids == ["llm-evidence"]
    assert "verbatim formative coaching trace" not in "\n".join(
        json.dumps(record) for record in records
    )


def test_markdown_note_body_redacted_across_whole_default_export(db_session, tmp_path):
    from lms.graphs.models import KnowledgeNode
    from lms.importers.markdown import import_markdown_notes

    note = tmp_path / "private.md"
    sentinel = "SENTINEL_PRIVATE_BODY_757"
    note.write_text(f"# Public heading\n{sentinel}\n\n## Child heading\n{sentinel}\n")
    import_markdown_notes(db_session, note)
    db_session.commit()
    nodes = db_session.query(KnowledgeNode).all()
    assert all(sentinel in node.description for node in nodes)
    for options in ({}, {"include_source_content": "none"}):
        lines = list(export_jsonl(db_session, **options))
        assert sentinel not in "\n".join(lines)
        exported = [json.loads(line) for line in lines]
        exported_nodes = [r["record"] for r in exported if r["type"] == "KnowledgeNode"]
        assert {r["id"] for r in exported_nodes} == {n.id for n in nodes}
        assert all(r["description"] is None for r in exported_nodes)
        assert all(r["source_reference_id"] for r in exported_nodes)
        assert any(r["type"] == "KnowledgeEdge" for r in exported)
        assert all(r["record"]["content_hash"] for r in exported if r["type"] == "SourceReference")
    assert sentinel in "\n".join(
        export_jsonl(db_session, include_source_content="all", confirm_all=True)
    )
    assert all(sentinel in node.description for node in nodes), "export must not mutate local notes"
    from sqlalchemy import create_engine

    from lms.db.base import Base
    from lms.export_import import import_jsonl
    from lms.graphs.models import KnowledgeEdge

    source_ids = {node.id: node.source_reference_id for node in nodes}
    source_hashes = {source.id: source.content_hash for source in db_session.query(SourceReference)}
    graph_links = {
        edge.id: (edge.source_node_id, edge.target_node_id, edge.edge_type)
        for edge in db_session.query(KnowledgeEdge)
    }
    for mode in ("public-only", "none"):
        path = tmp_path / f"redacted-{mode}.jsonl"
        path.write_text(
            "\n".join(export_jsonl(db_session, include_source_content=mode)) + "\n",
            encoding="utf-8",
        )
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as destination:
                import_jsonl(destination, path, dry_run=False)
                destination.commit()
                destination.expunge_all()
                restored = destination.query(KnowledgeNode).all()
                assert {node.id: node.source_reference_id for node in restored} == source_ids
                assert all(node.description is None for node in restored)
                assert {
                    source.id: source.content_hash for source in destination.query(SourceReference)
                } == source_hashes
                assert {
                    edge.id: (edge.source_node_id, edge.target_node_id, edge.edge_type)
                    for edge in destination.query(KnowledgeEdge)
                } == graph_links
        finally:
            engine.dispose()


def test_public_imported_description_obeys_none_and_preserves_authored_text(db_session, tmp_path):
    from lms.graphs.models import KnowledgeNode
    from lms.importers.markdown import import_markdown_notes

    note = tmp_path / "public.md"
    sentinel = "SENTINEL_PUBLIC_BODY_757"
    note.write_text(f"# Heading\n{sentinel}\n")
    import_markdown_notes(db_session, note, source_visibility="public")
    db_session.add(
        KnowledgeNode(
            id="authored",
            title="Authored",
            description="Authored description",
            knowledge_type="factual",
            ownership_scope="personal",
            provenance="manual",
        )
    )
    db_session.add(
        KnowledgeNode(
            id="legacy",
            title="Legacy import",
            description="SENTINEL_UNBOUND_757",
            knowledge_type="factual",
            ownership_scope="personal",
            provenance="imported",
        )
    )
    db_session.commit()
    public = "\n".join(export_jsonl(db_session))
    assert sentinel in public
    assert "SENTINEL_UNBOUND_757" not in public
    none = "\n".join(export_jsonl(db_session, include_source_content="none"))
    assert sentinel not in none
    assert "Authored description" in none
