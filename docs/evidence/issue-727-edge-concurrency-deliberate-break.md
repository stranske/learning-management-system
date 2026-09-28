# Deliberate-break evidence for #666 (via #727)

Relates to source issue #666, merged PR #721 (merge
`93af0dfb244ec589f81bd40beedc3fdd43fd6b01`), and follow-up #727. This records
the executed fail→restore cycles for the two knowledge-edge invariants #666
required: writer serialization (cycle checks) and the database identity floor
(duplicate checks).

Run on 2026-09-28 at `main` head `2cac29abc3ae63a307f3bd1eebb446719d0e2a3d`.
Neither break was committed; `git diff --exit-code` was clean after each restore.

Command used for every run:

```bash
uv run pytest tests/graphs/test_edge_concurrency.py -q --no-cov -p no:cacheprovider -rf
```

Baseline (unmodified): `9 passed`.

## Break 1 — remove serialization

In `src/lms/graphs/repository.py`, make `_acquire_edge_scope_lock` return
before taking the scope lock:

```python
def _acquire_edge_scope_lock(session: Session, scope: str) -> None:
    ...
    return  # DELIBERATE BREAK: serialization removed
    table = knowledge_graph_scope_locks
```

Observed:

```
E       AssertionError: second writer traversed the graph before serialization
E       assert not True
E       AssertionError: second writer traversed the graph before serialization
E       assert not True
E               assert 1 == 0
FAILED tests/graphs/test_edge_concurrency.py::test_concurrent_cycle_creates_serialize_before_traversal
FAILED tests/graphs/test_edge_concurrency.py::test_concurrent_cycle_updates_serialize_before_traversal
FAILED tests/graphs/test_edge_concurrency.py::test_edge_and_audit_rollback_with_outer_transaction
========================= 3 failed, 6 passed in 3.62s ==========================
```

Both concurrent cycle tests (create and update paths) fail because the second
writer reaches cycle traversal before the first commits. The rollback test also
fails because, without the lock-opened write transaction, the edge survives the
outer rollback.

Restore (`git checkout src/lms/graphs/repository.py`), re-run:

```
============================== 9 passed in 5.64s ===============================
```

## Break 2 — drop the `UniqueConstraint`

In `src/lms/graphs/models.py`, remove `uq_knowledge_edges_identity` from
`KnowledgeEdge.__table_args__`:

```python
    __table_args__ = (
        # DELIBERATE BREAK: uq_knowledge_edges_identity removed
        CheckConstraint(
```

Observed:

```
E           AssertionError: assert 'uq_knowledge_edges_identity' in set()
E       Failed: DID NOT RAISE IntegrityError
E       Failed: DID NOT RAISE ValueError
E       Failed: DID NOT RAISE ValueError
FAILED tests/graphs/test_edge_concurrency.py::test_concurrent_duplicate_creates_leave_one_edge
FAILED tests/graphs/test_edge_concurrency.py::test_database_unique_floor_rejects_direct_duplicate
FAILED tests/graphs/test_edge_concurrency.py::test_create_translates_database_identity_conflict
FAILED tests/graphs/test_edge_concurrency.py::test_update_translates_database_identity_conflict
========================= 4 failed, 5 passed in 4.63s ==========================
```

The concurrent duplicate test, the direct database-floor test, and both
`IntegrityError` → duplicate `ValueError` translation tests fail once the
constraint is gone.

Restore (`git checkout src/lms/graphs/models.py`), re-run:

```
============================== 9 passed in 5.75s ===============================
```

## Result

Each invariant has named tests that fail when it is removed and pass when it is
restored, which satisfies the deliberate-break gate in #666.
