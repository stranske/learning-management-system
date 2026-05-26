# LLM eval gold sets

This directory holds versioned hand-curated transcripts that act as the
regression target for the `study-coach` (and adjacent) flows.

The first set is `study-coach-v1.jsonl`. It is the input to
`lms llm replay-eval <path> --dry-run` and to `LLMClient.replay(...)`.

## Why this exists

The project plan requires a 10-30 transcript gold set before the first
`study-coach` flow ships so model and prompt changes have a regression
target instead of relying on impressions. See
`docs/product/project-plan.md` (LLM operational requirements) and
`docs/product/early-design-decisions.md` Segments 3 and 10. Cost and routing
decisions (Segment 10) are validated against replays of this set, not against
production traces.

## Scope and privacy

Gold-set entries are small, prompt-style transcripts written by hand. They are
*not* harvested from real production traffic. Do not use verbatim personal
traces unless they have been intentionally retained, redacted, and explicitly
licensed for inclusion. The same redaction step (`lms.llm.redaction.redact_pii`)
that protects production traces runs on replay output, but the input prompt is
checked in to the repo, so the source must be safe to publish.

## Schema

Each line is a UTF-8 JSON object with these fields:

| Field                | Required | Type                  | Notes |
|----------------------|----------|-----------------------|-------|
| `entry_id`           | yes      | non-empty string      | Unique across the file. Use a `study-coach-v1-NNN` style id. |
| `scenario`           | yes      | string                | Must be one of the canonical scenarios (see below). |
| `mode`               | yes      | string                | One of `lms.llm.models.LLM_MODES`. |
| `trace_class`        | yes      | string                | One of `lms.llm.models.TRACE_CLASSES`. Prefer `ephemeral` for eval input. |
| `prompt`             | yes      | non-empty string      | The provider prompt body; explicit about policy expectations. |
| `expected_labels`    | yes      | list[string]          | Non-empty subset of the allowed labels (see below). |
| `expected_text`      | no       | string                | Optional reference response for human-in-the-loop review. |
| `source_constraints` | no       | list[string]          | Stable source identifiers the response is expected to cite. |
| `notes`              | no       | string                | Free-form rationale for reviewers; not used at runtime. |

Blank lines and `#`-prefixed comment lines are ignored by the loader, so the
file can carry section headings without breaking parsing.

### Allowed scenarios

`answer-seeking`, `confusion-repair`, `retrieval-prompt`, `hint-overuse`,
`high-confidence-weak-evidence`, `direct-explanation`, `quiet-mode`,
`passive-rereading`, `attempt-avoidance`, `rapid-guessing`,
`orientation-request`.

### Allowed expected labels

`asks_for_retrieval`, `gives_direct_explanation`, `flags_unverified_claim`,
`offers_next_action`, `respects_quiet_mode`. The canonical identifier list
lives in `src/lms/llm/eval_sets.py`; the labels are conceptually aligned with
the formative interaction policy (`src/lms/llm/interaction_policy.py`) and the
evaluation rubric in `docs/product/early-design-decisions.md` Segment 3.

## How to add entries

1. Pick the canonical scenario. If the case does not fit one, prefer to
   refine the case rather than adding a new scenario.
2. Write the prompt body with the policy expectation explicit (mode,
   scenario, learner message, what the coach is allowed to do).
3. Choose the smallest set of `expected_labels` that captures the required
   behavior. A response that includes more labels is fine; missing labels
   is what scoring flags.
4. Add the row to `study-coach-v1.jsonl` with a fresh `entry_id`.
5. Run `uv run pytest tests/llm/test_eval_set_schema.py --no-cov -q` to
   confirm schema validity.
6. Run `uv run lms llm replay-eval docs/llm/eval-sets/study-coach-v1.jsonl --dry-run`
   to confirm the file parses end-to-end.

## When to refresh the set

Refresh (rev the file to `study-coach-v2.jsonl`) when any of the following
happens:

- The formative interaction policy adds or removes a behavior.
- The expected-label list grows.
- The mode routing in `lms.llm.config.DEFAULT_MODE_MODELS` changes for a mode
  that ships replay scoring.

When you rev the file, copy the v1 entries forward unchanged so historical
regression baselines remain reproducible. Add v2-only entries with new ids.

## Replay command

```
uv run lms llm replay-eval docs/llm/eval-sets/study-coach-v1.jsonl --dry-run
```

`--dry-run` validates every entry against the schema and prints a per-scenario
summary without issuing provider calls. The non-dry-run mode replays through
`LLMClient.replay` with the CLI's fake provider. Configured-provider replays
are available through the Python API rather than this CLI command.
