"""Shared semantic HTML shell helpers for the LMS prototype."""

from __future__ import annotations

from html import escape

APP_ROUTES: tuple[tuple[str, str], ...] = (
    ("Learner", "/app/learner"),
    ("Author", "/app/author"),
    ("Support", "/app/support"),
    ("Admin", "/app/admin"),
)


def render_page(title: str, body: str, *, active_path: str | None = None) -> str:
    """Render a mobile-first HTML page using the shared prototype shell."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1f6feb">
  <title>LMS {escape(title)}</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="stylesheet" href="/static/ui/pico.min.css">
  <link rel="stylesheet" href="/static/ui/app.css">
</head>
<body>
  <header class="app-header">
    <nav aria-label="Application sections">
      <ul><li><strong>LMS</strong></li></ul>
      <ul>{_nav_items(active_path)}</ul>
    </nav>
  </header>
{body}
  <script src="/service-worker.js" defer></script>
</body>
</html>"""


def empty_state(title: str, detail: str) -> str:
    """Return a consistent empty-state block for prototype surfaces."""
    return (
        '<section class="empty-state" aria-label="Empty state">'
        f"<h2>{escape(title)}</h2>"
        f"<p>{escape(detail)}</p>"
        "</section>"
    )


def surface_stub(title: str, detail: str, *, active_path: str) -> str:
    """Render an intentionally empty app surface for later milestone work."""
    return render_page(
        title,
        f"""
        <main class="surface app-surface">
          <header>
            <p class="eyebrow">Prototype route</p>
            <h1>{escape(title)}</h1>
          </header>
          {empty_state(title, detail)}
        </main>
        """,
        active_path=active_path,
    )


def _nav_items(active_path: str | None) -> str:
    items: list[str] = []
    for label, href in APP_ROUTES:
        current = ' aria-current="page"' if href == active_path else ""
        items.append(f'<li><a href="{href}"{current}>{escape(label)}</a></li>')
    return "".join(items)
