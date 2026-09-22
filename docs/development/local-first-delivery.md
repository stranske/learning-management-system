# Local-first course review packet

The [target-environment response, §F item 17](https://github.com/stranske/Ready/blob/main/research-program/artifacts/work-bundle/INFORMATION-REQUEST-RESPONSE.md) says:

> Nothing built in this environment today runs that way — every tool here is a local script, a COM-driven Office file, or a static HTML page opened locally; there is no server-hosted, database-backed application running anywhere I've seen.

For a bounded course-review use case, `scripts/export_offline_review_packet.py` reads a local JSON course graph and writes one HTML file. It imports only the Python standard library, makes no network calls, starts no web service, and needs no database. The output embeds its CSS and course content, so it can be opened directly from a local or shared folder.

From the repository root:

```bash
python scripts/export_offline_review_packet.py --fixture tests/fixtures/offline_course_minimal.json --out /tmp/lms-review.html
test -s /tmp/lms-review.html
```

The fixture shape is `course.title`, optional `course.summary`, and a `course.modules` list. Each module has a title and a `lessons` list; each lesson has a title and optional summary. The exporter validates these fields and escapes fixture text before writing HTML. It does not read the hosted LMS database or promise a full offline learning experience; the fixture is a small, reviewable curriculum snapshot.

Run the named smoke test with `python -m pytest tests/test_local_first_delivery.py::test_offline_packet_is_self_contained_html -q --no-cov`. It checks the fixture's course and lesson titles, inline styling, and absence of remote resource references. The hosted FastAPI, Postgres, and Render paths remain available for environments that support them.
