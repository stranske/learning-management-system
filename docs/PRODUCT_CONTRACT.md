# Product contract — stranske/learning-management-system
_First draft generated 2026-09-20 from the audit scorecard; the repo owns this file from now on. A PR that adds a user-facing route, command or page adds a line here. The audit's Phase 1.5 scores every line below and prints any surface not listed as UNSCORED._

## Purpose
Turn notes into durable knowledge through retrieval practice, feedback, spaced review, progress and calibration.

## Primary journey
Author knowledge, goals and prompts → learner starts a question → answers and self-grades → receives feedback → completes scheduled review → views progress and capability plan.

## Core functions
| id | a <user> can … and sees … | entry point | probe (how to exercise it; vary these determinants) | status 2026-09-20 |
|---|---|---|---|---|
| CF1 | an author can build knowledge, goals and published prompts and sees reachable practice items | author pages and knowledge/goal/prompt APIs | create distinct nodes, goals and prompts; publish and read author pages | PARTIAL |
| CF2 | a learner can work a lesson and sees a persisted scored attempt and feedback | `/learn`, attempts UI and attempt/self-grade APIs | two learners answer six prompts correct vs incorrect; submit `/learn` without prompt_id | PARTIAL |
| CF3 | a learner can receive feedback and sees their goal, current gap and next action | feedback pages and `POST /feedback` | compare automatic feedback for 100% vs 0% learners; author feedback record | PARTIAL |
| CF4 | a learner can complete review and sees due date, reason and rationale reflecting their answer | reviews UI and review-queue APIs | correct vs incorrect six-prompt learners; compare queue then complete one item | WORKS |
| CF5 | a learner can view progress and mastery and sees node mastery and goal progress | learner dashboard and mastery/progress APIs | correct vs incorrect learners; diff estimates, progress and confidence | PARTIAL |
| CF6 | a learner can inspect calibration and sees confidence-bucket accuracy and overconfidence verdict | calibration and overview APIs | correct vs incorrect high-confidence learners; inspect JSON and learner pages | PARTIAL |
| CF7 | a learner can create a capability plan and sees named, prioritized gaps tied to reviews | capability page and targets/estimates/gaps/plans APIs | correct vs incorrect learners; diff scores, gap severity and plan actions | WORKS |

## Known gaps at draft time
- CF1: author flow requires source references and hand-pasted relationship UUIDs.
- CF2: the first-use `/learn` form submits an empty `prompt_id` and returns HTTP 500.
- CF3: automatic feedback is identical for opposite answer outcomes; only author-created feedback names a gap.
- CF5: mastery confidence is record-count-only (`0.71` for both 100% and 0% learners).
- CF6: calibration computation varies correctly but has no learner-facing HTML readout.
