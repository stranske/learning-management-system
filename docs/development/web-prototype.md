# Web Prototype

The M6 web prototype uses semantic FastAPI-rendered HTML and a no-build CSS layer.
New prototype surfaces should live under `/app/*`:

- `/app/learner` for learner work and review entry points.
- `/app/author` for goal, graph, prompt, rubric, template, and case authoring.
- `/app/support` for learner-safe inspection and troubleshooting.
- `/app/admin` for local prototype operations.

The legacy `/learn` and `/review` routes remain compatibility entry points for the
current tests and any saved local links.

## CSS Choice

Use Pico-style semantic CSS for this phase. The prototype vendors a minimal
Pico-compatible subset at `src/lms/ui/static/pico.min.css` and keeps LMS-specific
layout rules in `src/lms/ui/static/app.css`.

Do not add a Node toolchain, Tailwind, bundler, or SPA framework for M6 shell
work. The route surfaces should keep markup semantic enough that Pico defaults
style forms, buttons, sections, and navigation without component build steps.

## PWA Scaffold

The prototype serves:

- `/manifest.webmanifest`
- `/service-worker.js`
- `/static/ui/icons/icon-192.svg`
- `/static/ui/icons/icon-512.svg`

The service worker is a placeholder that claims the client but does not implement
offline sync. Offline sync and richer asset caching are intentionally deferred.

## Snapshot and visual testing

The prototype is judged on mobile-friendly usability with sparse demo data, so
M6 keeps rendered-content artifacts for each surface. There are two stages:
**HTML snapshots** (required, current) and a **Playwright harness** (deferred,
scaffolded). See `docs/product/development-testing-surfaces.md` (Design
Defaults) and the Phase 3 convergence report item C for the rationale.

### Stage 1 — HTML snapshots (required, current)

`tests/ui/test_m6_screenshots.py` renders every M6 surface through the FastAPI
`TestClient`, writes the rendered HTML to `docs/screenshots/m6-<surface>.html`,
and asserts structural smoke properties. It seeds sparse but representative data
(one learner, a goal, a published node, a prompt, an attempt with feedback, a
capability target with a recomputed estimate, a rubric, and a case) so the
artifacts show populated layouts rather than only empty states.

What this layer catches:

- the surface renders without crashing (HTTP 200) with sparse data,
- the mobile viewport meta tag is present on every surface,
- the committed HTML artifact stays a fast, reviewable structural smoke test.

What it does **not** catch: real browser layout, JS behavior, computed styles,
or accessibility-tree issues. Those are Stage 2.

Run it (the test writes the artifacts as a side effect, so this regenerates the
files under `docs/screenshots/`):

```bash
pytest tests/ui/test_m6_screenshots.py
```

Commit the regenerated artifacts when a surface changes shape so the diff
documents the layout change. The acceptance tests are
`test_m6_surface_html_snapshot_artifacts_exist` (one artifact per surface) and
`test_all_m6_surfaces_include_mobile_viewport` (viewport metadata everywhere).
Both require no browser binaries, Node toolchain, or external network.

### Stage 2 — Playwright harness (deferred, scaffolded)

`tests/ui/test_playwright_smoke.py` contains one mobile (375px) smoke test for
the learner dashboard. It is **skipped by default**, gated on the
`PLAYWRIGHT_AVAILABLE` environment variable, so it never runs in default CI and
never requires browser binaries there. `pytest-playwright` is declared as an
optional dependency group so activation is a one-line install:

```toml
[project.optional-dependencies]
visual = ["pytest-playwright>=0.5.0"]
```

Setting `PLAYWRIGHT_AVAILABLE=1` un-skips the smoke test. Activation therefore
needs two steps (the `playwright` import is performed lazily inside the test
body, so the module stays importable and collectable as one skipped test even
when the optional dependency is not installed):

```bash
pip install -e '.[visual]'   # install pytest-playwright
playwright install           # download the browser binaries
PLAYWRIGHT_AVAILABLE=1 pytest tests/ui/test_playwright_smoke.py
```

Activate Playwright as a later decision (M7 or M8), driven by evidence rather
than schedule:

- JS-rendered surfaces (e.g. LLM streaming) land and HTML snapshots can no
  longer represent the rendered DOM,
- accessibility audits become required for M8 dyslexic-reading work,
- a visual regression slips past the HTML snapshots.

Until one of those triggers, Playwright stays scaffolded so the migration is
additive and the required snapshot suite carries M6.

### Trade-offs

- **HTML snapshots** are cheap, browser-free, and fast. They prove "renders
  without crashing", viewport metadata, and structural smoke, and stay useful
  as fast structural checks even after Playwright becomes the visual-regression
  source of truth.
- **Playwright** is the future source of truth for real-browser visual and
  accessibility testing, but it carries browser-binary CI cost, so it is
  deferred until evidence justifies the cost.

Non-goals for the current milestone: making Playwright a Gate-required check,
adding Node / a JS toolchain / a SPA build pipeline, building a brittle full
visual-regression platform, or requiring external browser services in CI for
the required HTML-snapshot tests.
