# Draft admission validation in the restricted sandbox

This is fresh, SQLite-only evidence from 2026-10-25. It is not the opener's
historical `run-20261025T0001` evidence, which is unavailable in this checkout.

The existing concurrency tests now fill and flush all remaining draft slots,
roll back, and verify the original count and learner timestamp before running
the competing loaders. They also verify that committed admissions preserve
the learner timestamp. Both backend parameters exercise these assertions;
the suite still collects 106 tests.

## Acceptance status

- [ ] Full suite: 106 passed, no skips. No PostgreSQL URL is configured; only
  PostgreSQL 18 is installed, and the sandbox denies TCP and Unix socket binds.
  The full-suite attempt also hangs at the first HTTP request. A minimal
  FastAPI `TestClient` request independently times out after 15 seconds.
- [ ] Historical original implementation: 6 concurrency failures. Those raw
  outputs are unavailable. The current SQLite tests produce **4 failures**
  for the count-then-decide control, including committed counts of 41 and 42.
  The fourth case, 39+2, fails the current assertion that the second admission
  must wait for the first transaction even when both batches are refused.
- [ ] Historical lock bypass: 8 failures, exact-byte restoration: 8 passed.
  The fresh SQLite-only control produces **4 failures**, followed by
  **4 passed** after exact-byte restoration in the isolated source copy.
- [x] Ruff, Black, and `git diff --check` pass. Black requires one worker here
  because its default multiprocessing forkserver cannot bind a Unix socket.

## Commands and controls

Focused verification:

```sh
python -m pytest --no-cov -q tests/maintenance/test_draft_approval.py \
  -k 'concurrent_load_respects_pending_draft_cap or cli_load_reserves_the_full_batch or reserved_draft_batch_rolls_back_with_outer_transaction' \
  -m 'not slow'
```

Result: **6 passed, 4 skipped, 96 deselected**. The skips are PostgreSQL cases.

The controls used a temporary copy of `src`, with pytest's `pythonpath`
configuration overridden to point at that copy. Only
`src/lms/maintenance/drafts.py` in the copy was changed:

- `count-then-decide.txt`: replace the body of `reserve_draft_capacity` with
  `return can_accept_drafts(session, learner_id=learner_id, wanted=wanted, now=now)`.
- `learner-lock-bypassed.txt`: remove the learner update and missing-learner
  check, preserving argument validation, flush, and the whole-batch check.
- `restored.txt`: restore the copy from the original bytes and rerun.

Each control ran `python -m pytest --no-cov -q -m 'not slow' -o pythonpath=<copy>/src
tests/maintenance/test_draft_approval.py -k
'concurrent_load_respects_pending_draft_cap and sqlite'`.

`source-sha256.txt` records all three source variants and verifies that the
restored copy and unchanged workspace source match the original bytes.

```sh
ruff check .
BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
git diff --check
```

Black checked 448 files. Staging the test change failed because `.git` is
read-only (`Unable to create .git/index.lock`). GitHub API access also fails,
so this run cannot post a blocker comment, set `needs-human`, or update PR
checkboxes. No PR was created or changed.

## Follow-up: waiting loaders after rollback

Reviewed commits `8c3e336` and `175c977`. The admission helper and full-batch
CLI call are already implemented. The PostgreSQL regression is present, but
fresh PostgreSQL verification remains blocked here. PR task reconciliation
could not be posted: the PR-body, comment, and label tools all require approval,
which this run's policy does not permit. PR #788 remains open and ready for review.

The concurrency regression now runs every boundary twice: once with the first
loader committing, and once with it flushing and rolling back. The waiting
loader must remain blocked until either transaction outcome and must see the
capacity returned by rollback. Final counts and unchanged learner timestamps
are checked in both cases.

Fresh results with Python 3.14.8:

- Named concurrency test: **8 passed, 8 skipped** (PostgreSQL).
- Deliberately bypass the learner update in an isolated source copy: **8 failed**,
  including committed queues of 41 and 42. Restore exact original bytes:
  **8 passed**. Original, restored, and workspace `drafts.py` SHA256:
  `216162a5f15ae06e0ecec8fe6b4cd7525cee88f7db8571a221b0f3996e86b674`.
- Full-file attempt: timed out after 25 seconds at the first HTTP test, after
  30 cases passed. A selection excluding the 16 HTTP cases:
  **90 passed, 8 PostgreSQL skips, 16 deselected**. No tests were disabled.
- Black's required repository-wide check: **448 files unchanged**. Ruff and
  `git diff --check` passed.

The installed PostgreSQL 18 server could initialize a temporary data directory,
but startup failed with `could not create IPv4 socket ... Operation not permitted`.
No PostgreSQL success is claimed for this follow-up. The original checkout's
commit attempt failed creating `.git/index.lock` because `.git` is read-only;
the source/test changes remain in the working tree for the automation runner.
