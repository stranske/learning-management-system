# Demo Retention Protocol

Status: locked before real item selection.

This protocol pre-registers the day-30 retention check for the Phase 1 Minimum Demo. It must be reviewed and left unchanged before the real project-owner demo items are selected. Any later change should be recorded as a protocol amendment with the date, reason, and affected items.

## Purpose

The Minimum Demo is not complete until the owner can show that the system's retrieval, review queue, Inspect, and study-coach surfaces produce durable learning evidence rather than only a working data path. The smoke test proves mechanics; this protocol governs the real day-30 check.

## Item Set

- Select 8 candidate items from the real personal-research-note slice before any demo prompts are authored.
- Assign 4 system-routed items to the full LMS loop: source-backed prompt, learner attempt, evidence record, scheduler review, Inspect display, and study-coach session when useful.
- Assign 4 passive comparison items to ordinary reading or note review without LMS scheduling or study-coach intervention.
- Keep the item list, assignment, source locator, and expected answer rubric in the demo notes packet.

## Day 0 Procedure

- Record the source locator and target concept for each item.
- Before any review or coaching, capture the owner's unaided pre-attempt.
- Capture confidence rating from 1 to 5 and elapsed seconds for the pre-attempt.
- Do not change item assignment after seeing day-0 performance.
- Author or approve source-cited prompts only after the item assignment is locked.

## System-Routed Treatment

- Import or seed the linked notes and source references.
- Generate or load the source-cited prompts needed for the item.
- Submit learner attempts with confidence ratings.
- Preserve verbose `EvidenceRecord` rows with scorer, support, retrieval demand, elapsed time, confidence, and validity scope.
- Let the review queue schedule follow-up work with reason codes.
- Use `study-coach` only in formative mode with `trace_class=formative`, source constraints, and cost accounting.

## Passive Comparison Treatment

- The owner may read or review the source notes normally.
- Do not route these items through the review scheduler.
- Do not create LMS evidence records or study-coach sessions for these items before day 30.
- Record any accidental exposure or practice as a protocol note.

## Day 30 Procedure

- Run the check 30 calendar days after day-0 item lock, allowing a 2-day grace window only if documented.
- Test all 8 items with day-30 unaided free recall before showing source notes, prompts, or prior answers.
- For each item, record recall quality as `complete`, `partial`, `gist-only`, or `missed`.
- Record elapsed seconds and confidence rating before feedback.
- After the unaided answer is captured, compare against the rubric and source locator.
- Summarize whether at least 3 items show useful retained knowledge that the owner would not otherwise have retained.

## Manual Demo Packet

The real project-owner run should include:

- locked item assignment table;
- day-0 unaided attempts;
- prompt and source-reference IDs for system-routed items;
- evidence and review queue excerpts;
- Inspect mastery snapshot;
- study-coach trace and daily cost summary;
- day-30 unaided free-recall table;
- final interpretation with limitations.

The result is empirical. The system may fail the retention test even when the smoke path passes.
