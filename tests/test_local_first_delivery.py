"""The offline course packet works without an LMS service or database."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_offline_review_packet.py"
FIXTURE = ROOT / "tests" / "fixtures" / "offline_course_minimal.json"


def test_offline_packet_is_self_contained_html(tmp_path: Path) -> None:
    output = tmp_path / "review.html"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(FIXTURE), "--out", str(output)],
        capture_output=True,
        text=True,
        check=True,
    )
    html = output.read_text(encoding="utf-8")
    assert "Wrote offline review packet" in completed.stdout
    assert html.startswith("<!doctype html>")
    assert "Investment Research Foundations" in html
    assert "Research process" in html
    assert "Frame the investment question" in html
    assert "Compare competing explanations" in html
    assert "<style>" in html
    assert "<script" not in html
    assert "http://" not in html and "https://" not in html
    assert "<link" not in html and "<img" not in html


def test_offline_packet_escapes_fixture_text(tmp_path: Path) -> None:
    fixture = tmp_path / "course.json"
    fixture.write_text(
        json.dumps(
            {
                "course": {
                    "title": "<Review>",
                    "modules": [
                        {"title": "Module", "lessons": [{"title": "<script>alert(1)</script>"}]}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "review.html"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(fixture), "--out", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    html = output.read_text(encoding="utf-8")
    assert "&lt;Review&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>" not in html


def test_invalid_course_graph_does_not_write_packet(tmp_path: Path) -> None:
    fixture = tmp_path / "course.json"
    fixture.write_text('{"course": {"title": "Course", "modules": "wrong"}}')
    output = tmp_path / "review.html"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(fixture), "--out", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "course modules must be a list" in completed.stderr
    assert not output.exists()
