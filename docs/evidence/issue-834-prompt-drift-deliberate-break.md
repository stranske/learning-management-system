# Issue #834: prompt snapshot drift deliberate-break evidence

Verifies that per-prompt drift is computed from immutable `PromptVersion` source
snapshots (and acknowledgements), not from live `SourceReference.drift_status`
alone.

## Break (reverted in the following commit)

In `prompt_drift_status`, replace snapshot comparison with source-only status:

```python
per_source = [reference.drift_status for reference in prompt.source_references]
return max(per_source, key=lambda status: _PROMPT_DRIFT_RANK[status])
```

After edit + scan both prompts are `stale`, but `rehash_source_reference` resets
the shared source to `current`. Source-only drift incorrectly reports both prompts
as `current` while version snapshots still hold the pre-rehash hashes.

## Named failing test

```sh
PYTEST_ADDOPTS='--no-cov' python3 -m pytest \
  tests/inspect/test_inspect_stale_prompts.py::test_prompt_versions_keep_source_hash_and_flag_drift_per_prompt -q
```

Observed failure (2026-11-17, branch `cursor/issue-834`):

```
FAILED tests/inspect/test_inspect_stale_prompts.py::test_prompt_versions_keep_source_hash_and_flag_drift_per_prompt
>       assert prompt_drift_status(after_rehash_a) == "stale"
E       AssertionError: assert 'current' == 'stale'
```

## Restore

Restore snapshot comparison via `_source_drift_for_reference`. Re-run:

```sh
PYTEST_ADDOPTS='--no-cov' python3 -m pytest tests/inspect/test_inspect_stale_prompts.py -q
```

Result: **4 passed**.