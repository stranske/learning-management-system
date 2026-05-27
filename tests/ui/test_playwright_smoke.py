"""Deferred Playwright visual smoke scaffold for the learner dashboard.

This module is intentionally inert in default CI. The required M6 smoke layer is
the browser-free HTML snapshot suite in :mod:`tests.ui.test_m6_screenshots`;
Playwright is the deferred ``[visual]`` optional dependency that a later
milestone activates when JS-rendered surfaces, accessibility audits, or a visual
regression that HTML snapshots missed justify it.

The single smoke test is skipped unless ``PLAYWRIGHT_AVAILABLE`` is set, so the
``playwright`` import is performed lazily inside the test body and the module
stays importable (and collectable as one skipped test) without the optional
dependency installed. See ``docs/development/web-prototype.md`` for activation
steps.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Mobile reference width from the M6 brief; the dashboard must read well here.
MOBILE_WIDTH = 375
MOBILE_HEIGHT = 812

_DASHBOARD_SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "docs" / "screenshots" / "m6-learner-dashboard.html"
)

_SKIP_REASON = "Playwright harness scaffolded; activate with PLAYWRIGHT_AVAILABLE=1"

playwright_only = pytest.mark.skipif(
    not os.environ.get("PLAYWRIGHT_AVAILABLE"),
    reason=_SKIP_REASON,
)


@playwright_only
def test_learner_dashboard_renders_at_mobile_width() -> None:
    """Render the learner-dashboard snapshot at 375px and assert it reads well.

    Activated only when ``PLAYWRIGHT_AVAILABLE`` is set and a browser is
    installed (``playwright install``). It loads the committed HTML snapshot so
    no running server is required for this scaffolded smoke pass.
    """
    from playwright.sync_api import sync_playwright

    assert (
        _DASHBOARD_SNAPSHOT.is_file()
    ), "learner-dashboard snapshot missing; run tests/ui/test_m6_screenshots.py first"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})
            page.goto(_DASHBOARD_SNAPSHOT.as_uri())
            assert page.viewport_size is not None
            assert page.viewport_size["width"] == MOBILE_WIDTH
            heading = page.locator("h1")
            assert heading.inner_text().strip() == "Learner dashboard"
        finally:
            browser.close()
