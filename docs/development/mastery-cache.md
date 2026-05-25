# Mastery Cache Thresholds

Mastery estimates remain recomputed from `EvidenceRecord` history in v1. A materialized cache
should wait until a learner has either more than 5,000 evidence rows or p95 estimate latency
exceeds 250 ms for the Inspect and learner review surfaces.

Any future cache must store `estimator_version`, `model_attribution`, and the latest consumed
evidence id so estimates can be invalidated and regenerated from the durable evidence stream.
