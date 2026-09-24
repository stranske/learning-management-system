"""Concurrency and migration coverage for knowledge-edge invariants."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from lms.audit.models import AuditLog
from lms.db.base import Base
from lms.graphs import repository as graph_repository
from lms.graphs.models import KnowledgeEdge, KnowledgeNode, knowledge_graph_scope_locks
from lms.graphs.repository import create_knowledge_edge, update_knowledge_edge
from lms.settings import get_settings


def _node(node_id: str, title: str) -> KnowledgeNode:
    return KnowledgeNode(
        id=node_id,
        title=title,
        knowledge_type="conceptual",
        ownership_scope="personal",
        status="published",
        provenance="manual",
    )


def _file_session_factory(path: Path) -> tuple[Any, sessionmaker[Session]]:
    engine = create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 5},
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory


def _run_competing_writes(
    first: Callable[[Session], None],
    second: Callable[[Session], None],
    factory: sessionmaker[Session],
    second_traversed: threading.Event,
) -> list[tuple[str, str]]:
    first_flushed = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    results: Queue[tuple[str, str]] = Queue()

    def run_first() -> None:
        with factory() as session:
            try:
                first(session)
                first_flushed.set()
                if not release_first.wait(timeout=5):
                    raise TimeoutError("first writer was not released")
                session.commit()
                results.put(("first", "committed"))
            except Exception as exc:  # pragma: no cover - asserted through result payload
                session.rollback()
                results.put(("first", f"{type(exc).__name__}: {exc}"))
                first_flushed.set()

    def run_second() -> None:
        if not first_flushed.wait(timeout=5):
            results.put(("second", "TimeoutError: first writer did not flush"))
            return
        with factory() as session:
            try:
                second_started.set()
                second(session)
                session.commit()
                results.put(("second", "committed"))
            except Exception as exc:
                session.rollback()
                results.put(("second", f"{type(exc).__name__}: {exc}"))

    first_thread = threading.Thread(target=run_first, name="graph-writer-first")
    second_thread = threading.Thread(target=run_second, name="graph-writer-second")
    first_thread.start()
    second_thread.start()
    assert second_started.wait(timeout=5), "second writer never attempted the locked operation"
    # With serialization the second writer cannot reach graph traversal yet.
    # Without it this wait observes the stale traversal before releasing the
    # first transaction, making the race deterministic rather than scheduler-dependent.
    traversed_before_release = second_traversed.wait(timeout=1)
    release_first.set()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not traversed_before_release, "second writer traversed the graph before serialization"
    return sorted([results.get_nowait(), results.get_nowait()])


def test_concurrent_cycle_creates_serialize_before_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A competing cycle check must observe the first writer after its commit."""
    engine, factory = _file_session_factory(tmp_path / "cycle-create.db")
    try:
        with factory() as session:
            session.add_all([_node("a", "A"), _node("b", "B"), _node("c", "C")])
            session.flush()
            create_knowledge_edge(
                session,
                source_node_id="b",
                target_node_id="c",
                edge_type="prerequisite",
                scope="personal",
                actor_id="seed",
            )
            session.commit()

        second_traversed = threading.Event()
        original_cycle_check = graph_repository._ordering_edge_closes_cycle

        def observed_cycle_check(*args: Any, **kwargs: Any) -> bool:
            result = original_cycle_check(*args, **kwargs)
            if threading.current_thread().name == "graph-writer-second":
                second_traversed.set()
            return result

        monkeypatch.setattr(graph_repository, "_ordering_edge_closes_cycle", observed_cycle_check)

        def first(session: Session) -> None:
            create_knowledge_edge(
                session,
                source_node_id="a",
                target_node_id="b",
                edge_type="prerequisite",
                scope="personal",
                actor_id="writer:first",
            )

        def second(session: Session) -> None:
            create_knowledge_edge(
                session,
                source_node_id="c",
                target_node_id="a",
                edge_type="key-prerequisite",
                scope="personal",
                actor_id="writer:second",
            )

        assert _run_competing_writes(first, second, factory, second_traversed) == [
            ("first", "committed"),
            ("second", "ValueError: edge would create a prerequisite cycle"),
        ]
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(KnowledgeEdge)) == 2
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 2
    finally:
        engine.dispose()


def test_concurrent_cycle_updates_serialize_before_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent retypes cannot both turn an acyclic graph cyclic."""
    engine, factory = _file_session_factory(tmp_path / "cycle-update.db")
    try:
        with factory() as session:
            session.add_all([_node("a", "A"), _node("b", "B"), _node("c", "C")])
            session.flush()
            create_knowledge_edge(
                session,
                source_node_id="b",
                target_node_id="c",
                edge_type="prerequisite",
                scope="personal",
                actor_id="seed",
            )
            first_edge = create_knowledge_edge(
                session,
                source_node_id="a",
                target_node_id="b",
                edge_type="analogy",
                scope="personal",
                actor_id="seed",
            )
            second_edge = create_knowledge_edge(
                session,
                source_node_id="c",
                target_node_id="a",
                edge_type="contrast",
                scope="personal",
                actor_id="seed",
            )
            first_id, second_id = first_edge.id, second_edge.id
            session.commit()

        second_traversed = threading.Event()
        original_cycle_check = graph_repository._ordering_edge_closes_cycle

        def observed_cycle_check(*args: Any, **kwargs: Any) -> bool:
            result = original_cycle_check(*args, **kwargs)
            if threading.current_thread().name == "graph-writer-second":
                second_traversed.set()
            return result

        monkeypatch.setattr(graph_repository, "_ordering_edge_closes_cycle", observed_cycle_check)

        def first(session: Session) -> None:
            edge = session.get(KnowledgeEdge, first_id)
            assert edge is not None
            update_knowledge_edge(session, edge, actor_id="writer:first", edge_type="prerequisite")

        def second(session: Session) -> None:
            edge = session.get(KnowledgeEdge, second_id)
            assert edge is not None
            update_knowledge_edge(session, edge, actor_id="writer:second", edge_type="encompassing")

        assert _run_competing_writes(first, second, factory, second_traversed) == [
            ("first", "committed"),
            ("second", "ValueError: edge would create a prerequisite cycle"),
        ]
        with factory() as session:
            assert session.get(KnowledgeEdge, first_id).edge_type == "prerequisite"  # type: ignore[union-attr]
            assert session.get(KnowledgeEdge, second_id).edge_type == "contrast"  # type: ignore[union-attr]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.entity_id == second_id, AuditLog.action == "update")
                )
                == 0
            )
    finally:
        engine.dispose()


def test_concurrent_duplicate_creates_leave_one_edge(tmp_path: Path) -> None:
    """Two concurrent identical creates leave one edge and reject the loser."""
    engine, factory = _file_session_factory(tmp_path / "duplicate-create.db")
    try:
        unique_names = {
            constraint["name"]
            for constraint in inspect(engine).get_unique_constraints("knowledge_edges")
        }
        assert "uq_knowledge_edges_identity" in unique_names
        with factory() as session:
            session.add_all([_node("a", "A"), _node("b", "B")])
            session.commit()

        def create_duplicate(session: Session) -> None:
            create_knowledge_edge(
                session,
                source_node_id="a",
                target_node_id="b",
                edge_type="analogy",
                scope="personal",
                actor_id=f"writer:{threading.current_thread().name}",
            )

        assert _run_competing_writes(
            create_duplicate,
            create_duplicate,
            factory,
            threading.Event(),
        ) == [
            ("first", "committed"),
            (
                "second",
                "ValueError: duplicate knowledge edge: an identical "
                "'analogy' edge already exists in scope 'personal'",
            ),
        ]
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(KnowledgeEdge)) == 1
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 1
    finally:
        engine.dispose()


def test_database_unique_floor_rejects_direct_duplicate(db_session: Session) -> None:
    """Direct writers cannot bypass the five-column edge identity invariant."""
    db_session.add_all([_node("a", "A"), _node("b", "B")])
    db_session.flush()
    identity = {
        "source_node_id": "a",
        "target_node_id": "b",
        "edge_type": "analogy",
        "source_scope": "personal",
        "target_scope": "personal",
    }
    db_session.add(KnowledgeEdge(id="edge-1", **identity))
    db_session.flush()
    with (
        pytest.raises(IntegrityError, match="UNIQUE constraint failed") as excinfo,
        db_session.begin_nested(),
    ):
        db_session.add(KnowledgeEdge(id="edge-2", **identity))
        db_session.flush()
    assert graph_repository._is_edge_identity_conflict(excinfo.value)


def test_create_translates_database_identity_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A create-time uniqueness race surfaces as the repository duplicate error."""
    db_session.add_all([_node("a", "A"), _node("b", "B")])
    db_session.add(
        KnowledgeEdge(
            id="edge-1",
            source_node_id="a",
            target_node_id="b",
            edge_type="analogy",
            source_scope="personal",
            target_scope="personal",
        )
    )
    db_session.flush()

    class _NoDuplicate:
        @staticmethod
        def first() -> None:
            return None

    monkeypatch.setattr(db_session, "scalars", lambda *args, **kwargs: _NoDuplicate())

    with pytest.raises(ValueError, match="duplicate knowledge edge"):
        create_knowledge_edge(
            db_session,
            source_node_id="a",
            target_node_id="b",
            edge_type="analogy",
            scope="personal",
            actor_id="writer",
        )


def test_update_translates_database_identity_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An update-time uniqueness race surfaces as the repository duplicate error."""
    db_session.add_all([_node("a", "A"), _node("b", "B")])
    existing = KnowledgeEdge(
        id="edge-1",
        source_node_id="a",
        target_node_id="b",
        edge_type="analogy",
        source_scope="personal",
        target_scope="personal",
    )
    candidate = KnowledgeEdge(
        id="edge-2",
        source_node_id="a",
        target_node_id="b",
        edge_type="contrast",
        source_scope="personal",
        target_scope="personal",
    )
    db_session.add_all([existing, candidate])
    db_session.flush()

    class _NoDuplicate:
        @staticmethod
        def first() -> None:
            return None

    monkeypatch.setattr(db_session, "scalars", lambda *args, **kwargs: _NoDuplicate())

    with pytest.raises(ValueError, match="duplicate knowledge edge"):
        update_knowledge_edge(
            db_session,
            candidate,
            actor_id="writer",
            edge_type="analogy",
        )


def test_edge_and_audit_rollback_with_outer_transaction(tmp_path: Path) -> None:
    """The operation savepoint must not commit edge or audit independently."""
    engine, factory = _file_session_factory(tmp_path / "rollback.db")
    try:
        with factory() as session:
            session.add_all([_node("a", "A"), _node("b", "B")])
            session.commit()
        with factory() as session:
            create_knowledge_edge(
                session,
                source_node_id="a",
                target_node_id="b",
                edge_type="analogy",
                scope="personal",
                actor_id="writer",
            )
            session.rollback()
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(KnowledgeEdge)) == 0
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
            assert (
                session.scalar(select(func.count()).select_from(knowledge_graph_scope_locks)) == 0
            )
    finally:
        engine.dispose()


def _alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    return Config("alembic.ini")


def test_migration_rejects_existing_duplicate_edges_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upgrade fails closed and leaves duplicate production data untouched."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration-duplicates.db'}"
    config = _alembic_config(database_url, monkeypatch)
    command.upgrade(config, "20260806_0035")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                    INSERT INTO knowledge_nodes
                        (id, title, knowledge_type, ownership_scope, status, provenance)
                    VALUES
                        ('a', 'A', 'conceptual', 'personal', 'published', 'manual'),
                        ('b', 'B', 'conceptual', 'personal', 'published', 'manual')
                    """))
            for edge_id in ("edge-1", "edge-2"):
                connection.execute(
                    text("""
                        INSERT INTO knowledge_edges
                            (id, source_node_id, target_node_id, edge_type,
                             source_scope, target_scope, is_graph_reference, status)
                        VALUES
                            (:id, 'a', 'b', 'analogy',
                             'personal', 'personal', false, 'draft')
                        """),
                    {"id": edge_id},
                )
        with pytest.raises(RuntimeError, match="duplicate knowledge edges exist"):
            command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM knowledge_edges")) == 2
            assert not inspect(connection).has_table("knowledge_graph_scope_locks")
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_migration_seeds_scope_locks_and_preserves_edge_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SQLite batch rebuild keeps inbound references and adds both lock rows."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration-success.db'}"
    config = _alembic_config(database_url, monkeypatch)
    command.upgrade(config, "head")
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            lock_scopes = (
                connection.execute(
                    text(
                        "SELECT source_scope FROM knowledge_graph_scope_locks ORDER BY source_scope"
                    )
                )
                .scalars()
                .all()
            )
            assert lock_scopes == ["institutional", "personal"]
            unique_names = {
                item["name"]
                for item in inspect(connection).get_unique_constraints("knowledge_edges")
            }
            assert "uq_knowledge_edges_identity" in unique_names
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()
        get_settings.cache_clear()
