"""Deterministic feedback template rendering helpers."""

from __future__ import annotations

from typing import Any

from lms.feedback.models import FeedbackTemplate
from lms.feedback.repository import render_feedback_template


def render(template: FeedbackTemplate, values: dict[str, Any]) -> str:
    """Render feedback template copy with repository validation rules."""
    return render_feedback_template(template, values)
