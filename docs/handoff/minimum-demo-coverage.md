# Minimum Demo Coverage

This matrix maps the six Minimum Demo requirements to implemented surfaces or manual protocol steps.

Two automated commands cover the milestone gate, with different purposes:

| Command | What it does | Why use it |
| --- | --- | --- |
| `lms demo smoke` | Builds the six-part coverage summary from hard-coded fixtures in `src/lms/demo.py`. **No DB writes.** | CI-safe heartbeat — proves the renderer + matrix shape compile without any provider, secret, or DB. |
| `lms demo run` | Seeds a synthetic dataset through the **real** repository writers (`create_source_reference`, `create_prompt`, `publish_prompt`, `create_attempt` + evidence, `create_review_queue_item`, `LLMSession`), then derives the same six-part summary from `select(...)` queries against the seeded DB. | Verifies the **persistence wiring** of the Milestone-4 gate — no hard-coded counts can hide a writer regression. |

Neither command exercises real Claude API calls (`run` uses synthetic content + a fake `LLMSession` row with `provider=fake`) and neither claims real learning efficacy. The day-30 retention check is a separate manual protocol.

## Coverage matrix

| Requirement | Smoke evidence | Run evidence (real persistence) |
| --- | --- | --- |
| 10 notes | Fixture creates 10 `DemoNote` dataclasses with stable locators. | `SEED_NOTE_COUNT = 10` `SourceReference` rows via `create_source_reference` (source_type `internal-note`). |
| 30 prompts | Fixture: 3 source-cited prompts per note. | `SEED_PROMPT_COUNT = 30` `Prompt` rows (3 per node, one per cognitive action), each published via `publish_prompt`. |
| Attempts and verbose evidence | Fixture: one attempt + one evidence dataclass per prompt. | One `Attempt` + one `EvidenceRecord` per prompt via `create_attempt(..., evidence={...})`. |
| Review queue reason codes | Fixture lists `due-review`, `remediation`, `mixed-practice`, `new-instruction` (illustrative names; **not** valid in the production schema). | Seeds four **real** DB codes from `lms.scheduling.models.REASON_CODES`: `due-review`, `remediation`, `new-learning`, `overdue`. The fixture's `mixed-practice` / `new-instruction` names never matched the schema's `CheckConstraint`; the `run` path uses the canonical names. |
| Inspect mastery display | Fixture: one mastery row per topic. | One `EvidenceRecord.knowledge_node_id` per node populates the Inspect surface; counted via `count(distinct knowledge_node_id)`. |
| Study-coach session per topic and cost summary | Fixture: 10 `DemoLLMSession` rows. | At least one real `LLMSession` row with `mode=study-coach`, `trace_class=formative`, `provider=fake`; `daily_cost_micro_usd` sums real `cost_micro_usd` column values. **`run` only verifies the `LLMSession`/cost persistence + aggregation wiring (≥1 session row, correct daily-cost sum) — it does *not* assert one session per topic. The per-topic study-coach requirement remains part of the manual protocol (step 6 below).** |
| Day-30 retention check | Out of scope — see `docs/handoff/demo-retention-protocol.md`. | Out of scope — same. |

## Which path satisfies which gate

- **Milestone-4 persistence-wiring gate**: `lms demo run` plus the test `tests/demo/test_minimum_demo_run.py`, which queries the DB via `select(...)` and asserts the printed summary equals what's actually persisted.
- **Milestone-4 efficacy gate**: the manual day-30 retention protocol below. Neither automated command claims efficacy.

## Real Demo Manual Steps

1. Lock the 8-item retention protocol before choosing or authoring real demo prompts.
2. Import the real note slice and verify source locators.
3. Generate or approve the 30 prompts needed for the demo.
4. Run the learner attempts and verify evidence rows.
5. Check review queue reasons and Inspect mastery display.
6. Run one formative study-coach session per topic and review the daily cost summary.
7. At day 30, run the unaided free-recall procedure from the protocol.
