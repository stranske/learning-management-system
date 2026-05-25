"""Tests for the LMS module entrypoint."""

from __future__ import annotations

from typing import Any

import lms.__main__ as lms_main


def test_main_starts_uvicorn(monkeypatch: Any) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr("uvicorn.run", fake_run)

    lms_main.main()

    assert calls == [
        {
            "app": "lms.main:app",
            "host": "127.0.0.1",
            "port": 8000,
            "reload": True,
        }
    ]
