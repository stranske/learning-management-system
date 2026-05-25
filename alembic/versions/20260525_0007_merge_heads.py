"""Merge attempts and learning-goals heads.

Revision ID: 20260525_0007
Revises: 20260525_0006, 20260525_0006_attempts
"""

from __future__ import annotations

revision = "20260525_0007"
down_revision = ("20260525_0006", "20260525_0006_attempts")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge parallel head revisions into a single linear head."""
    pass


def downgrade() -> None:
    """Downgrade merge marker."""
    pass
