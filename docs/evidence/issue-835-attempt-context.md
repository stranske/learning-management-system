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

## Follow-up: shared attempt boundary verification

Reviewed commits `072aceb` and `98c17c1`; both contain the earlier implementation
and verification changes described above. The PR body still has unchecked
duplicates of implemented tasks. Updating the first verified model/schema task
in the PR body was rejected with `MCP tool call requires approval, but approval
policy is never`, so remote checklist reconciliation remains blocked.

- [x] Verify repository, service, and API creation with multiple prompt versions:
  omitted versions select the latest; explicit versions at either the attempt
  or evidence boundary retain the supplied older version, even without scoring.
- [x] Verify scored and unscored attempts preserve nested caller metadata and
  saved task metadata after the caller changes its input and the prompt's
  metadata, wording, and source references change.
- [x] Verify invalid evidence-level versions fail before creating attempts or
  evidence, and a valid attempt can subsequently commit without a rollback.

A temporary mutation replaced `response_metadata=deepcopy(response_metadata)`
with `response_metadata=response_metadata` at attempt creation. Both new
snapshot cases failed at the in-memory assertion: the stored object's nested
surface became `changed` instead of remaining `activity`. The production file
was restored before validation; only the test changes and this record remain.

```sh
PYTEST_ADDOPTS='--no-cov -m "not slow"' python3 -m pytest tests/evidence/test_attempts.py tests/evidence/test_evidence_records.py tests/evidence/test_attempts_migration.py tests/feedback/test_rubric_scoring.py -q
```

Result: **331 passed**, including all five named rubric regression cases and
the entire rubric scoring file. The required Black check passed for **457
files**, with `BLACK_NUM_WORKERS=1`. Ruff and Mypy passed for the changed test
file, and `git diff --check` passed.

Staging the test file failed because `.git/index.lock` cannot be created on the
read-only filesystem. Adding `needs-human` was also rejected by the connector's
approval policy. Delivery requires a runner with writable git metadata; PR body
reconciliation requires permission to update PR #839.

## Follow-up: migrated version reference enforcement

Reviewed commits `072aceb`, `98c17c1`, and `98def5b` before continuing.
They already contain the four requested production changes and the schema,
legacy migration, synthetic-caller, delayed-version, and condition-preservation
regressions. Their verified tasks should be checked in the PR body; the initial
checklist reconciliation attempt was rejected by the connector with
`MCP tool call requires approval, but approval policy is never`.

The first additional task now has database behavior assertions in
`tests/evidence/test_attempts_migration.py`, beyond foreign-key introspection.
With SQLite foreign-key enforcement enabled, an attempt can reference v1;
deleting that referenced version or replacing its ID with an unknown version
raises `IntegrityError`. Both failed operations preserve the saved v1 reference.
Returning the reference to null remains valid, and downgrade/re-upgrade still
preserves the historical rows.

Verification on 2026-11-17:

- [x] All four production tasks verified by review and the related passing tests.
- [x] Named rubric regression: **5 passed** after restoring both mutations.
- [x] Omitted condition kwargs: **5 failed**, actual FSRS rating **3 instead of 2**.
- [x] Replaced saved version with the current version: **5 failed** at the
  saved-v1 evidence assertion. Both temporary source mutations were reverted.
- [x] Related attempt, migration, and entire rubric scoring files: **276 passed**.
- [x] Final migrated-constraint check after lint fixes: **3 passed**.
- [x] UI activity-attempt file: **17 passed** with a temporary pytest plugin in
  `/tmp/issue835_uvloop.py` selecting the installed uvloop backend. The default
  asyncio run timed out after 40 seconds. No application behavior or assertions
  were changed by the temporary plugin.
- [x] Required repository-wide Black gate: **457 files unchanged**.
  Ruff and Mypy passed for the changed migration test; `git diff --check` passed.

Commands used `PYTEST_ADDOPTS='--no-cov -m "not slow"'` for the targeted behavior
checks. The named regression command and both temporary mutations are the same
as documented above. Fresh mutation logs are in `/tmp/issue835-conditions.log`,
`/tmp/issue835-version.log`, and `/tmp/issue835-restored.log`.

Delivery remains blocked: `git add tests/evidence/test_attempts_migration.py`
failed to create `.git/index.lock` on the read-only filesystem. The final PR
checklist update, blocker comment, and `needs-human` label were each rejected
with `MCP tool call requires approval, but approval policy is never`. The two
changed files remain uncommitted. PR #839 was verified open and ready for review
(`draft=false`) after these attempts.

Delivery remains blocked: staging the meaningful Python test change with
`git add tests/evidence/test_attempts_migration.py` fails because
`.git/index.lock` cannot be created on the read-only filesystem. A runner with
writable git metadata must commit the test change, and remote write permission
is required to reconcile the PR checkboxes and attach this verification record.

## Follow-up: evidence at the scheduling boundary

The four production tasks are already implemented at `f5bc245`. This round
strengthens the named rubric regression without replacing its existing cases:
each assistance/confidence case now runs with submission both before and after
v2 publication. Scoring reloads the attempt from the database, and a wrapper
copies the evidence fields as they enter the real scheduling service. Assertions
check the complete, independently specified v1 snapshot, saved response metadata,
all observed conditions, persisted evidence, and actual FSRS Hard (2).

Verified on 2026-11-17:

- [x] Nullable attempt models, schemas, and legacy migration fixtures pass.
- [x] Shared attempt creation and synthetic prompt callers pass.
- [x] UI presented-version validation and delayed self-grading pass.
- [x] Rubric evidence contains saved context and conditions before scheduling.
- [x] Expanded named regression: **10 passed**.
- [x] Omitted rubric condition kwargs: **10 failed**, actual FSRS **3 instead of 2**.
- [x] Replaced the saved version with the current version: **10 failed** because
  the scheduling input contains v2 instead of `prompt-version-1`.
- [x] Both temporary production mutations reverted; named regression: **10 passed**.
- [x] Related attempt, migration, evidence, and entire rubric scoring files:
  **336 passed**, including all **210** rubric scoring tests.
- [x] Activity-attempt UI and prompt API files: **26 passed**.
- [x] Required repository-wide Black check: **458 files unchanged**; Ruff and
  `git diff --check` pass. Black added the missing final newline to the existing
  task-context migration; its behavior is unchanged.

The named command and both mutations are the same as recorded above, with
`PYTEST_ADDOPTS='--no-cov -m "not slow"'`. Fresh logs are in
`/tmp/issue835-current-conditions.log`, `/tmp/issue835-current-version.log`, and
`/tmp/issue835-current-restored.log`. The larger passing run used:

```sh
PYTEST_ADDOPTS='--no-cov -m "not slow"' python3 -m pytest tests/evidence/test_attempts.py tests/evidence/test_attempts_migration.py tests/evidence/test_evidence_records.py tests/feedback/test_rubric_scoring.py -q
```

The default asyncio TestClient stalled: the UI run reached a 40-second timeout,
and a combined run was interrupted after the model-level tests when it stalled
in the prompt API file. The UI and prompt API replacement run passed with the
installed uvloop backend selected by a temporary plugin in
`/tmp/issue835_uvloop.py`. No repository fixtures or assertions were disabled.

Delivery remains blocked: `git add` for the prepared test, migration formatting,
and evidence record failed to create `.git/index.lock` on the read-only
filesystem. The PR checklist update, verification/blocker comment, and
`needs-human` label were each rejected with `MCP tool call requires approval,
but approval policy is never`. These changes remain uncommitted; remote
checkboxes are unchanged. PR #839 was verified open and ready (`draft=false`).
