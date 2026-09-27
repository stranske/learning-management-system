# PR #711 deliberate-break evidence disposition

This follow-up addresses issue #718 for merged PR #711 and its source issue
#580. It records what can be recovered from the durable pull-request record and
separately records a fresh reproduction of the required fail-to-restore cycle.
It does not claim that the fresh output was captured before the original merge.

## Historical record audit

The following command was run against the merged pull request:

```bash
gh pr view 711 -R stranske/learning-management-system --json body,comments
```

The PR body contains the required deliberate-break procedure, but neither the
body nor the comments contain an executed failure transcript. The historical
fail-to-revert output therefore cannot be recovered from the durable PR record.
The merge record identifies exact head
`aa396e49c2a1c7cebe59742856eb6ebef664cf97` and squash merge
`3bdd840da6dd9d658dc6f6da2d599def00b3a936`.

The final check state was read with:

```bash
gh pr checks 711 -R stranske/learning-management-system
```

The durable readback reports successful Gate, Python 3.12, Python 3.13, Ruff,
mypy, Compose smoke, health guards, backplane conformance, CodeRabbit, and
post-merge verifier contexts. Event-inapplicable jobs are reported as skipped;
they are not represented here as checks that passed.

## Fresh deliberate-break reproduction

At current `main` baseline `78a5913eab6c0f13c87d108be138b563bebcaff8`,
`render_packet` in `scripts/export_offline_review_packet.py` was temporarily
changed to return only:

```html
<html></html>
```

The change was not committed. The issue-named command was then run:

```bash
uv run pytest tests/test_local_first_delivery.py::test_offline_packet_is_self_contained_html -q --no-cov
```

Observed failure on 2026-09-27:

```text
FAILED tests/test_local_first_delivery.py::test_offline_packet_is_self_contained_html
>       assert html.startswith("<!doctype html>")
E       AssertionError: assert False
E        +  where False = '<html></html>\n'.startswith('<!doctype html>')
1 failed in 0.29s
```

## Restore and cleanup proof

After restoring the production implementation exactly, the same named command
passed:

```text
tests/test_local_first_delivery.py .                                     [100%]
1 passed in 0.25s
```

The documented CLI smoke command also produced a nonempty packet:

```bash
uv run python scripts/export_offline_review_packet.py \
  --fixture tests/fixtures/offline_course_minimal.json \
  --out /tmp/lms-review-718.html
test -s /tmp/lms-review-718.html
```

Observed output:

```text
Wrote offline review packet: /tmp/lms-review-718.html
```

Cleanup is proven by:

```bash
git diff --exit-code -- scripts/export_offline_review_packet.py
```

This disposition closes only the missing-evidence gap. It does not reopen or
change the already-merged product implementation.
