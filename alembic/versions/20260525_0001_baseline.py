"""Baseline database revision."""

from __future__ import annotations

revision = "20260525_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Establish an empty baseline for future model migrations."""
    pass


def downgrade() -> None:
    """Downgrade from the empty baseline."""
    pass
