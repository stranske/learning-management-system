# Issue #835: saved attempt context and delayed scoring

Verified locally on 2026-11-17 with Python 3.14.10. New attempts capture the
validated prompt version and task metadata at creation. Scoring copies that
snapshot, response metadata, confidence, reference access, hint use, support
level, and elapsed time into evidence before scheduling. The migration leaves
historical version and task context null. Synthetic prompt IDs without a
persisted Prompt remain supported with unknown context.

## Verified tasks

- [x] Add nullable attempt version and task-context columns, migration, and read/input schemas.
- [x] Capture and validate context at the shared attempt-creation boundary.
- [x] Submit the UI's presented version and reuse saved context during self-grading.
- [x] Preserve saved context and all attempt conditions in rubric evidence before scheduling.
- [x] Pass the named regression, including the actual FSRS engine input of Hard (2).
- [x] Demonstrate both deliberate failures and revert them, then pass the named regression.
- [x] Pass the entire rubric scoring test file.
- [x] Update existing schema, migration, and evidence fixtures while preserving synthetic callers.

## Deliberate break and revert

The named test is parametrized over combined assistance/low confidence and each
individual condition: low confidence, reference access, hint use, and support.
Every case scores a full-credit attempt saved against v1 after v2 is published.
It reloads persisted evidence and checks the saved version, metadata, observed
conditions, queue decision, card update, and the rating passed to the real FSRS
engine through a wrapping spy.

All three runs used the following command. `PYTEST_ADDOPTS` skips slow tests and
disables the repository-wide coverage gate for these targeted behavior checks.

```sh
PYTEST_ADDOPTS='--no-cov -m "not slow"' python3 -m pytest tests/feedback/test_rubric_scoring.py::test_rubric_evidence_preserves_attempt_conditions_and_prompt_version -q
```

First mutation: temporarily remove these kwargs from rubric `create_evidence_record`:

```diff
-        confidence_rating=attempt.confidence_rating,
-        reference_accessed=attempt.reference_accessed,
-        hint_used=attempt.hint_used,
-        support_level=attempt.support_level,
-        response_time_seconds=attempt.elapsed_seconds,
```

The evidence defaults erase the conditions and allow the full-credit rating to
reach the engine. Exit status **1**, **5 failed**; each case reports:

```text
>       assert engine_review.call_args.kwargs["rating_value"] == 2
E       assert 3 == 2
======================== 5 failed, 13 warnings in 0.89s ========================
```

The original source was restored before the second mutation, which substitutes
the currently published version for the saved version:

```diff
-        prompt_version_id=attempt.prompt_version_id,
+        prompt_version_id=session.get(Prompt, attempt.prompt_id).versions[-1].id,
```

Exit status **1**, **5 failed** at `assert evidence.prompt_version_id == version_id`.
An example actual assertion output is:

```text
E       AssertionError: assert '51e2e75d-5fe...-0286b0ee0984' == 'prompt-version-1'
E         - prompt-version-1
E         + 51e2e75d-5feb-4a6d-9d4f-0286b0ee0984
======================== 5 failed, 13 warnings in 0.89s ========================
```

Both mutations were reverted. The same named command then exited **0**:

```text
======================== 5 passed, 13 warnings in 0.79s ========================
```

## Other validation

```sh
PYTEST_ADDOPTS='--no-cov -m "not slow"' python3 -m pytest tests/feedback/test_rubric_scoring.py -q
```

Result: **205 passed**. The activity-attempt UI file also passed: **17 passed**.
The UI tests required an uncommitted temporary pytest plugin selecting the
installed uvloop backend for Starlette TestClient. The default asyncio portal
stalled in this sandbox; the temporary plugin changes no application behavior
or assertions and is outside the repository.

The related evidence, scheduling, rubric API, revision, and screenshot checks
passed: **516 passed**. Export/import checks passed: **154 passed, 4 skipped**
(existing skips). An earlier combined run reached its 90-second timeout without
reported failures; both smaller replacement runs completed successfully.

The required repository-wide formatting gate passed using one worker because
this sandbox rejects Black's multiprocessing socket setup:

```sh
BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
```

Result: **457 files would be left unchanged**.

Ruff passes for the changed Python files. Mypy passes for the changed production
modules and supporting evidence tests/fixtures (13 files). The broader selected
mypy run reports eight existing errors in the rubric/UI test files; checking
their original HEAD contents independently reproduces all eight.

## Original delivery blocker

The original implementation was subsequently delivered in commit `072aceb`.
The following records the restriction encountered during that earlier run.

Local staging failed with:

```text
fatal: Unable to create '/home/runner/work/learning-management-system/learning-management-system/.git/index.lock': Read-only file system
```

The implementation and this record remain in the working tree. No commit or
push was possible through local git. PR #839 was confirmed open and ready for
review (`draft=false`) through the GitHub connector. Its implementation
checkboxes should be updated after a runner with writable git metadata commits
and delivers the verified patch.

Posting the verification/blocker comment and adding the requested `needs-human`
label were both rejected by the tool permission policy: `MCP tool call requires
approval, but approval policy is never`. The PR checklist and labels were not
changed. The mutation record above is available locally for the runner to include
when delivering the patch.

## Follow-up: nullable model, schema, and migration verification

- [x] Verify the first additional PR task: nullable version/task-context model
  fields, matching API read schemas, and a migration that leaves legacy rows unknown.

The migration fixture now includes a real published prompt with two versions as
well as a synthetic prompt ID. Neither historical attempt acquires a version or
task snapshot. The test also checks the exact version foreign key and `RESTRICT`
policy and confirms downgrade removes both added columns. API create/read JSON
round trips cover explicit null context and an explicitly presented v1 after
v2 changes the current prompt's demand level.

A temporary migration mutation backfilled each matching legacy attempt with the
latest prompt version. The strengthened migration test failed with exit status
1: `('version-2', None, 'Old answer')` instead of `(None, None, 'Old answer')`.
The migration was restored before the passing verification run:

```sh
PYTEST_ADDOPTS='--no-cov -m "not slow"' python3 -m pytest tests/evidence/test_attempts.py tests/evidence/test_attempts_migration.py tests/feedback/test_rubric_scoring.py -q
```

Result: **265 passed**, including the named rubric regression and the full rubric
test file. Black's required repository-wide check passed for **457 files**;
Ruff and Mypy passed for both changed Python test files. Local staging still
fails because `.git/index.lock` cannot be created on the read-only filesystem.
The GitHub connector also rejected commit-tree creation, the blocker comment,
and the `needs-human` label with `MCP tool call requires approval, but approval
policy is never`. These follow-up changes remain uncommitted in the working
tree. PR #839 was verified open and ready for review (`draft=false`).
