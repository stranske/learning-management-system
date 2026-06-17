# M6 Acceptance Gate

This handoff maps the executable M6 gate to the author and learner surfaces.

## Automated Gate

Run:

```bash
pytest tests/ui/test_m6_acceptance_gate.py::test_author_goal_node_prompt_rubric_and_learner_completion_path
```

The test creates the authoring objects through route-backed surfaces where the
prototype currently supports them, then uses direct repository setup only for
local identity and source fixture records.

| Gate step | Route or API | Assertion |
| --- | --- | --- |
| Create the learner and source fixture | repository fixture setup | learner and source ids exist for route-backed authoring |
| Create a published knowledge node | `POST /app/author/knowledge/nodes` | author knowledge page shows `Explain retrieval spacing` |
| Create a learning goal | `POST /app/author/goals` | author goals page shows `Explain retrieval practice with evidence` |
| Create and publish a prompt | `POST /app/author/prompts`, `POST /prompts/{id}/publish` | attempt page shows human-authored provenance and source locator |
| Create a rubric | `POST /app/author/rubrics` | author rubrics page shows `Source-backed explanation` |
| Create a transfer case | `POST /app/author/cases` | author cases page shows `Plan a spaced review` |
| Submit a learner attempt | `POST /app/learner/attempts` | feedback page shows the recorded attempt and source citations |
| Score with rubric feedback | `POST /rubric-scores` | feedback page shows rubric score and revision action |
| Create capability target | `POST /app/learner/capability/targets` | capability page shows personal target |
| Generate estimate and gap analysis | `POST /app/learner/capability/estimates`, `POST /app/learner/capability/gap-analyses` | capability page shows current evidence, weak-mastery, and transfer-evidence gaps |
| Generate maintenance plan | `POST /app/learner/capability/maintenance-plans` | dashboard and review queue show scheduled maintenance steps, including transfer-case routing |
| Submit a transfer-case work product | `GET /app/learner/cases`, `POST /app/learner/cases/{id}/work-products` | learner case page records the work product and shows it awaiting scoring |
| Score the work product | `POST /work-products/{id}/score` | scoring records rubric score plus case-scoped transfer evidence |
| Refresh capability evidence | `POST /app/learner/capability/estimates`, `POST /app/learner/capability/gap-analyses` | refreshed gap analysis no longer asks for transfer evidence already present |

## Manual Demo Path

1. Open `/app/author/knowledge` and create a published personal node.
2. Open `/app/author/goals` and create a learning goal for the demo learner that
   targets the node.
3. Open `/app/author/prompts`, create a prompt for that goal and node, then
   publish the prompt through the prompt API.
4. Open `/app/author/rubrics` and create a published rubric tied to the prompt
   and node.
5. Open `/app/author/cases` and create one transfer case with a decision point.
6. Open `/app/learner/attempts?learner_id=<learner-id>&prompt_id=<prompt-id>`,
   submit an answer, and score it with the rubric API.
7. Open `/app/learner/capability`, create a personal capability target for the
   node, recompute the estimate, generate a gap analysis, and create a
   maintenance plan.
8. Open `/app/learner/cases`, submit a work product for the transfer case, copy
   the work product id from the submission API response or the learner case
   work-products list, score it through `POST /work-products/{id}/score`, then
   recompute the capability estimate and gap analysis.
9. Verify `/app/learner`, `/app/learner/review`,
   `/app/learner/feedback`, and `/app/learner/capability/targets/<target-id>`
   all show the same learner path: rubric-scored feedback, source/provenance,
   current evidence, gap-analysis output, transfer-case evidence closure, and
   scheduled maintenance steps.
