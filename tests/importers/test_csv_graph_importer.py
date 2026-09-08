"""Tests for CSV knowledge graph imports."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.db.base import Base
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.importers.csv_graph import CsvGraphImportError, import_csv_graph
from lms.sources.models import SourceReference


def test_import_nodes_and_prerequisite_edges(tmp_path: Path, db_session: Session) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "\n".join(
            [
                "title,knowledge_type,prerequisites,ownership_scope,status,source_locator,source_range,description",
                "Probability Basics,conceptual,,personal,draft,outline.csv,row 2,Core terms",
                "Bayes Rule,procedural,Probability Basics,personal,draft,outline.csv,row 3,Apply Bayes",
                "Posterior Checks,judgment,Probability Basics|Bayes Rule,personal,draft,outline.csv,row 4,Check results",
            ]
        ),
        encoding="utf-8",
    )

    summary = import_csv_graph(db_session, csv_path, actor_id="user:alice")
    db_session.commit()

    assert summary.nodes == 3
    assert summary.edges == 3
    assert summary.source_references == 3
    assert summary.dry_run is False

    nodes = db_session.query(KnowledgeNode).order_by(KnowledgeNode.title).all()
    assert [node.title for node in nodes] == [
        "Bayes Rule",
        "Posterior Checks",
        "Probability Basics",
    ]
    assert {node.provenance for node in nodes} == {"imported"}
    assert {node.status for node in nodes} == {"draft"}
    assert all(node.source_reference_id for node in nodes)

    edges = db_session.query(KnowledgeEdge).all()
    assert len(edges) == 3
    assert {edge.edge_type for edge in edges} == {"prerequisite"}
    assert {edge.source_scope for edge in edges} == {"personal"}

    # Canonical direction (see ``KnowledgeEdge``): source -> target means
    # "source has prerequisite target". Bayes Rule lists Probability Basics as a
    # prerequisite, so the edge runs Bayes Rule -> Probability Basics. The
    # Markdown importer must produce edges in this same orientation.
    title_by_id = {node.id: node.title for node in nodes}
    directed = {
        (title_by_id[edge.source_node_id], title_by_id[edge.target_node_id]) for edge in edges
    }
    assert directed == {
        ("Bayes Rule", "Probability Basics"),
        ("Posterior Checks", "Probability Basics"),
        ("Posterior Checks", "Bayes Rule"),
    }

    assert db_session.query(SourceReference).count() == 3
    audit_events = db_session.query(AuditLog).all()
    assert {event.entity_type for event in audit_events} == {
        "KnowledgeNode",
        "KnowledgeEdge",
        "SourceReference",
    }


def test_unknown_prerequisite_fails_before_writes(tmp_path: Path, db_session: Session) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "\n".join(
            [
                "title,knowledge_type,prerequisites,ownership_scope,status,source_locator",
                "Bayes Rule,procedural,Probability Basics,personal,draft,outline.csv",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(CsvGraphImportError, match="unknown prerequisite"):
        import_csv_graph(db_session, csv_path)

    assert db_session.query(KnowledgeNode).count() == 0
    assert db_session.query(KnowledgeEdge).count() == 0
    assert db_session.query(SourceReference).count() == 0


def test_invalid_enum_rejected_in_dry_run(tmp_path: Path, db_session: Session) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "\n".join(
            [
                "title,knowledge_type,prerequisites,ownership_scope,status,source_locator",
                "Probability Basics,conceptual,,personal,draft,outline.csv",
                "Bayes Rule,not_a_type,Probability Basics,personal,draft,outline.csv",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(CsvGraphImportError, match="row 3: unknown knowledge type"):
        import_csv_graph(db_session, csv_path, dry_run=True)

    assert db_session.query(KnowledgeNode).count() == 0
    assert db_session.query(KnowledgeEdge).count() == 0
    assert db_session.query(SourceReference).count() == 0


@pytest.mark.parametrize("dry_run", [False, True])
def test_self_prerequisite_rejected_before_writes(
    tmp_path: Path, db_session: Session, dry_run: bool
) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "\n".join(
            [
                "title,knowledge_type,prerequisites,ownership_scope,status,source_locator",
                "Probability Basics,conceptual,Probability Basics,personal,draft,outline.csv",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(CsvGraphImportError, match="cannot list itself as a prerequisite"):
        import_csv_graph(db_session, csv_path, dry_run=dry_run)

    assert db_session.query(KnowledgeNode).count() == 0
    assert db_session.query(KnowledgeEdge).count() == 0
    assert db_session.query(SourceReference).count() == 0


def test_latin1_csv_raises_import_error(tmp_path: Path, db_session: Session) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_bytes(
        "\n".join(
            [
                "title,knowledge_type,prerequisites,ownership_scope,status,source_locator",
                "Café Basics,conceptual,,personal,draft,outline.csv",
            ]
        ).encode("latin-1")
    )

    with pytest.raises(CsvGraphImportError, match="expected UTF-8 text"):
        import_csv_graph(db_session, csv_path, dry_run=True)

    assert db_session.query(KnowledgeNode).count() == 0
    assert db_session.query(KnowledgeEdge).count() == 0
    assert db_session.query(SourceReference).count() == 0


def test_missing_required_column_fails_before_writes(tmp_path: Path, db_session: Session) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "\n".join(
            [
                "title,knowledge_type,prerequisites,ownership_scope,status",
                "Probability Basics,conceptual,,personal,draft",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(CsvGraphImportError, match="missing required columns: source_locator"):
        import_csv_graph(db_session, csv_path)

    assert db_session.query(KnowledgeNode).count() == 0
    assert db_session.query(KnowledgeEdge).count() == 0
    assert db_session.query(SourceReference).count() == 0


def test_dry_run_reports_counts_without_writes(tmp_path: Path, db_session: Session) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "\n".join(
            [
                "title,knowledge_type,prerequisites,ownership_scope,status,source_locator",
                "Probability Basics,conceptual,,personal,draft,outline.csv",
                "Bayes Rule,procedural,Probability Basics,personal,draft,outline.csv",
            ]
        ),
        encoding="utf-8",
    )

    summary = import_csv_graph(db_session, csv_path, dry_run=True)

    assert summary.nodes == 2
    assert summary.edges == 1
    assert summary.source_references == 2
    assert summary.dry_run is True
    assert db_session.query(KnowledgeNode).count() == 0


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("length", [2, 3])
def test_import_csv_graph_cycle_raises_csv_graph_import_error(
    tmp_path: Path, db_session: Session, dry_run: bool, length: int
) -> None:
    csv_path = tmp_path / "cycle.csv"
    csv_path.write_text(
        "title,knowledge_type,prerequisites,ownership_scope,status,source_locator\n"
        + "\n".join(
            f"Node {index},conceptual,node {(index + 1) % length},personal,draft,outline.csv"
            for index in range(length)
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        CsvGraphImportError, match=rf"Row {length + 1}: .*prerequisite cycle"
    ) as error:
        import_csv_graph(db_session, csv_path, dry_run=dry_run)

    if not dry_run:
        assert type(error.value.__cause__) is ValueError
        db_session.rollback()
    for model in (KnowledgeNode, KnowledgeEdge, SourceReference, AuditLog):
        assert db_session.query(model).count() == 0


def test_dry_run_accepts_diamond_and_separate_scope_graphs(
    tmp_path: Path, db_session: Session
) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "title,knowledge_type,prerequisites,ownership_scope,status,source_locator\n"
        "A,conceptual,B|C,personal,draft,outline.csv\n"
        "B,conceptual,D,personal,draft,outline.csv\n"
        "C,conceptual,D,personal,draft,outline.csv\n"
        "D,conceptual,,personal,draft,outline.csv\n"
        "A,conceptual,,institutional,draft,outline.csv\n"
        "B,conceptual,A,institutional,draft,outline.csv\n",
        encoding="utf-8",
    )

    summary = import_csv_graph(db_session, csv_path, dry_run=True)

    assert (summary.nodes, summary.edges) == (6, 5)
    for model in (KnowledgeNode, KnowledgeEdge, SourceReference, AuditLog):
        assert db_session.query(model).count() == 0


@pytest.mark.parametrize("dry_run", [False, True])
def test_cli_csv_cycle_exits_cleanly_without_persisting_rows(tmp_path: Path, dry_run: bool) -> None:
    csv_path = tmp_path / "cycle.csv"
    csv_path.write_text(
        "title,knowledge_type,prerequisites,ownership_scope,status,source_locator\n"
        "A,conceptual,B,personal,draft,outline.csv\n"
        "B,conceptual,A,personal,draft,outline.csv\n",
        encoding="utf-8",
    )
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"
    engine = create_engine(database_url)
    try:
        Base.metadata.create_all(engine)
        result = subprocess.run(
            [sys.executable, "-m", "lms", "import-graph", str(csv_path)]
            + (["--dry-run"] if dry_run else []),
            env={
                **os.environ,
                "DATABASE_URL": database_url,
                "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 1
        assert (
            "CSV graph import failed: Row 3: edge would create a prerequisite cycle"
            in result.stderr
        )
        assert "Traceback" not in result.stderr
        assert result.stdout == ""
        with Session(engine) as session:
            for model in (KnowledgeNode, KnowledgeEdge, SourceReference, AuditLog):
                assert session.query(model).count() == 0
    finally:
        engine.dispose()
