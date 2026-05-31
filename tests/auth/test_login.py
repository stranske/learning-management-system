"""Focused tests for login-route security helpers."""

from __future__ import annotations

from lms.auth.login import DEFAULT_POST_LOGIN_PATH, _safe_next_path


def test_safe_next_path_rejects_offsite() -> None:
    for candidate in ("http://evil.com", "//evil.com", "\\evil.com", "", None):
        assert _safe_next_path(candidate) == DEFAULT_POST_LOGIN_PATH


def test_safe_next_path_allows_same_origin_paths() -> None:
    assert _safe_next_path("/protected-html") == "/protected-html"
    assert _safe_next_path("/app/learner?tab=review") == "/app/learner?tab=review"
