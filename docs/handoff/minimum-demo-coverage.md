# Minimum Demo Coverage

This matrix maps the six Minimum Demo requirements to implemented surfaces or manual protocol steps. The CI-safe command is:

```bash
lms demo smoke
```

The command uses fake-provider data and does not claim real learning efficacy.

| Requirement | Smoke or manual evidence |
| --- | --- |
| 10 notes | `lms demo smoke` seeds 10 note records with stable source locators. |
| 30 prompts | The smoke path creates 3 source-cited prompts per note for recall, explanation, and application. |
| Attempts and verbose evidence | The smoke path creates one confidence-rated attempt and one evidence row per prompt. |
| Review queue reason codes | The smoke output includes `due-review`, `remediation`, `mixed-practice`, and `new-instruction`. |
| Inspect mastery display | The smoke path creates one Inspect-facing mastery row per topic. |
| Study-coach session per topic and cost summary | The smoke path creates one fake-provider `study-coach` session per topic with `trace_class=formative` and a daily cost total. |
| Day-30 retention check | `docs/handoff/demo-retention-protocol.md` governs the real owner-run check and states the protocol is locked before real item selection. |

## Real Demo Manual Steps

1. Lock the 8-item retention protocol before choosing or authoring real demo prompts.
2. Import the real note slice and verify source locators.
3. Generate or approve the 30 prompts needed for the demo.
4. Run the learner attempts and verify evidence rows.
5. Check review queue reasons and Inspect mastery display.
6. Run one formative study-coach session per topic and review the daily cost summary.
7. At day 30, run the unaided free-recall procedure from the protocol.
