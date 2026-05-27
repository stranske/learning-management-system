"""Merge revision requests and LLM feedback event heads.

Revision ID: 20260527_0027_merge_revision_requests_llm_feedback_events
Revises: 20260526_0026_revision_requests, 20260527_0026_llm_feedback_events
"""

from __future__ import annotations

revision = "20260527_0027_merge_revision_requests_llm_feedback_events"
down_revision = (
    "20260526_0026_revision_requests",
    "20260527_0026_llm_feedback_events",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge migration branches without changing schema."""


def downgrade() -> None:
    """Split migration branches without changing schema."""
