"""Per-mode and global daily budget accounting for the LLM client wrapper.

The tracker is process-local rather than persistent; v1 ships a hard
kill-switch posture (Segment 10) so the value lies in fail-closed preflight
before a call is issued, not in cross-process spend reconciliation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from lms.llm.exceptions import BudgetExceeded


@dataclass
class DailyBudgetTracker:
    """Track per-mode and global daily spend in micro-USD."""

    mode_caps_micro_usd: Mapping[str, int]
    global_cap_micro_usd: int
    _mode_spend: dict[str, int] = field(default_factory=dict)
    _global_spend: int = 0

    def preflight(self, mode: str, projected_cost_micro_usd: int) -> None:
        """Raise :class:`BudgetExceeded` if a call would breach a cap.

        The wrapper calls ``preflight`` before issuing the provider request so
        the kill-switch fires before money is spent. ``record`` is only called
        on successful completion.
        """
        if projected_cost_micro_usd < 0:
            raise ValueError("projected_cost_micro_usd must be non-negative")

        projected_global = self._global_spend + projected_cost_micro_usd
        if projected_global > self.global_cap_micro_usd:
            raise BudgetExceeded(
                f"global daily cap {self.global_cap_micro_usd} micro-USD "
                f"would be exceeded by {projected_cost_micro_usd} micro-USD "
                f"call (already spent {self._global_spend})"
            )

        mode_cap = self.mode_caps_micro_usd.get(mode)
        if mode_cap is None:
            return
        projected_mode = self._mode_spend.get(mode, 0) + projected_cost_micro_usd
        if projected_mode > mode_cap:
            raise BudgetExceeded(
                f"mode '{mode}' daily cap {mode_cap} micro-USD would be "
                f"exceeded by {projected_cost_micro_usd} micro-USD call "
                f"(already spent {self._mode_spend.get(mode, 0)})"
            )

    def record(self, mode: str, cost_micro_usd: int) -> None:
        """Record actual cost after a successful call."""
        if cost_micro_usd < 0:
            raise ValueError("cost_micro_usd must be non-negative")
        self._mode_spend[mode] = self._mode_spend.get(mode, 0) + cost_micro_usd
        self._global_spend += cost_micro_usd

    def spent_micro_usd(self, mode: str | None = None) -> int:
        if mode is None:
            return self._global_spend
        return self._mode_spend.get(mode, 0)
