"""Export a local course-graph JSON file as a self-contained HTML review packet."""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any


def _required_title(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must have a nonempty title")
    return value.strip()


def _optional_summary(value: Any, context: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{context} summary must be a string")
    return value.strip()


def _course_graph(raw: Any) -> tuple[str, str, list[tuple[str, list[tuple[str, str]]]]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("course"), dict):
        raise ValueError("fixture must contain a course object")
    course = raw["course"]
    title = _required_title(course.get("title"), "course")
    summary = _optional_summary(course.get("summary"), "course")
    modules = course.get("modules")
    if not isinstance(modules, list):
        raise ValueError("course modules must be a list")
    parsed = []
    for module_number, module in enumerate(modules, start=1):
        context = f"module {module_number}"
        if not isinstance(module, dict) or not isinstance(module.get("lessons"), list):
            raise ValueError(f"{context} must contain a lessons list")
        module_title = _required_title(module.get("title"), context)
        lessons = []
        for lesson_number, lesson in enumerate(module["lessons"], start=1):
            lesson_context = f"{context} lesson {lesson_number}"
            if not isinstance(lesson, dict):
                raise ValueError(f"{lesson_context} must be an object")
            lessons.append(
                (
                    _required_title(lesson.get("title"), lesson_context),
                    _optional_summary(lesson.get("summary"), lesson_context),
                )
            )
        parsed.append((module_title, lessons))
    return title, summary, parsed


def render_packet(raw: Any) -> str:
    """Render validated fixture content without scripts or remote resources."""
    title, summary, modules = _course_graph(raw)
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)} — Offline review packet</title>",
        "<style>body{font:1rem/1.5 system-ui,sans-serif;max-width:52rem;"
        "margin:2rem auto;padding:0 1rem;color:#18212b}"
        "section{border-top:1px solid #ccd4dd;margin-top:1.5rem}"
        "li{margin:.75rem 0}small{color:#52606d}</style></head><body>",
        "<main><p><small>Offline course review packet</small></p>",
        f"<h1>{escape(title)}</h1>",
    ]
    if summary:
        parts.append(f"<p>{escape(summary)}</p>")
    for module_title, lessons in modules:
        parts.append(f"<section><h2>{escape(module_title)}</h2><ol>")
        for lesson_title, lesson_summary in lessons:
            parts.append(f"<li><strong>{escape(lesson_title)}</strong>")
            if lesson_summary:
                parts.append(f"<p>{escape(lesson_summary)}</p>")
            parts.append("</li>")
        parts.append("</ol></section>")
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path, help="Local course-graph JSON file")
    parser.add_argument("--out", required=True, type=Path, help="Output HTML file")
    args = parser.parse_args()
    try:
        raw = json.loads(args.fixture.read_text(encoding="utf-8"))
        html = render_packet(raw)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote offline review packet: {args.out}")


if __name__ == "__main__":
    main()
