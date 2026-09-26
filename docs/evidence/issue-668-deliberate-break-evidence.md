# Deliberate-break evidence for #668 (via #700)

Relates to merged PR #680 and source issue #668. This documents the executed
fail→restore cycle for repository validation guards in
`src/lms/evidence/repository.py`.

## Break (temporary, not committed)

In `_validate_evidence_metadata`, comment out the ordering guard:

```python
# if raw_score is not None and max_score is not None and raw_score > max_score:
#     raise ValueError("raw_score must not exceed max_score")
```

## Named failing test

Command:

```bash
pytest tests/evidence/test_evidence_records.py::test_evidence_rejects_score_above_maximum -q --no-cov
```

Observed failure (2026-09-26, head `f0072c8`):

```
FAILED tests/evidence/test_evidence_records.py::test_evidence_rejects_score_above_maximum[False]
FAILED tests/evidence/test_evidence_records.py::test_evidence_rejects_score_above_maximum[True]
>       with pytest.raises(ValueError, match="raw_score must not exceed max_score"):
E       Failed: DID NOT RAISE ValueError
```

## Restore

Re-enable the guard (exact lines above). Re-run:

```bash
pytest tests/evidence/test_evidence_records.py::test_evidence_rejects_score_above_maximum \
  tests/evidence/test_evidence_records.py::test_create_evidence_record_rejects_invalid_metadata_without_poisoning_session \
  -q --no-cov
```

Result: **16 passed**.

## Acceptance mapping

- Guard location: `src/lms/evidence/repository.py` (`raw_score` vs `max_score` ordering).
- Targeted tests: `tests/evidence/test_evidence_records.py` (parametrized metadata rejections + score-above-maximum cases).
- Closes the verifier gap called out in #700 for #668 deliberate-break evidence.
