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
