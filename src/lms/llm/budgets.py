"""Per-mode and global daily budget accounting for the LLM client wrapper.

The tracker is process-local rather than persistent; v1 ships a hard
kill-switch posture (Segment 10) so the value lies in fail-closed preflight
before a call is issued, not in cross-process spend reconciliation.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field

from lms.llm.exceptions import BudgetExceeded


@dataclass
class BudgetReservation:
    """Handle for spend reserved by :meth:`DailyBudgetTracker.reserve`.

    A reservation optimistically debits the tracker so concurrent calls see
    the in-flight spend during their own cap check. It is later reconciled to
    the actual cost via :meth:`DailyBudgetTracker.commit` or fully refunded via
    :meth:`DailyBudgetTracker.release`. ``settled`` guards against a
    reservation being committed/released more than once.
    """

    mode: str
    projected_cost_micro_usd: int
    settled: bool = False


@dataclass
class DailyBudgetTracker:
    """Track per-mode and global daily spend in micro-USD.

    The LLM routes run on FastAPI's sync threadpool and share a single
    ``@lru_cache``-d tracker, so the cap check and the spend update must be
    atomic: a plain read-then-update lets two concurrent calls both pass
    preflight against a stale spend and overshoot the cap. All mutations are
    serialized under ``_lock``, and the reserve/commit API makes the
    check-and-debit a single critical section.
    """

    mode_caps_micro_usd: Mapping[str, int]
    global_cap_micro_usd: int
    _mode_spend: dict[str, int] = field(default_factory=dict)
    _global_spend: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _check_caps_locked(self, mode: str, projected_cost_micro_usd: int) -> None:
        """Raise :class:`BudgetExceeded` if the projected cost breaches a cap.

        Caller MUST hold ``_lock``. Uses current spend (which already includes
        any in-flight reservations) so concurrent reservations stack correctly.
        """
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

    def _add_spend_locked(self, mode: str, delta_micro_usd: int) -> None:
        """Apply a (possibly negative) spend delta. Caller MUST hold ``_lock``."""
        self._global_spend += delta_micro_usd
        self._mode_spend[mode] = self._mode_spend.get(mode, 0) + delta_micro_usd

    def reserve(self, mode: str, projected_cost_micro_usd: int) -> BudgetReservation:
        """Atomically preflight and reserve projected spend before a call.

        The cap check and the optimistic debit happen in a single locked
        critical section, so two concurrent reservations cannot both pass
        against a stale spend. Raises :class:`BudgetExceeded` (reserving
        nothing) when the cap would be breached. Reconcile the reservation with
        :meth:`commit` on success or :meth:`release` on failure.
        """
        if projected_cost_micro_usd < 0:
            raise ValueError("projected_cost_micro_usd must be non-negative")
        with self._lock:
            self._check_caps_locked(mode, projected_cost_micro_usd)
            self._add_spend_locked(mode, projected_cost_micro_usd)
        return BudgetReservation(mode=mode, projected_cost_micro_usd=projected_cost_micro_usd)

    def commit(self, reservation: BudgetReservation, actual_cost_micro_usd: int) -> None:
        """Reconcile a reservation to the call's actual cost."""
        if actual_cost_micro_usd < 0:
            raise ValueError("actual_cost_micro_usd must be non-negative")
        with self._lock:
            if reservation.settled:
                return
            delta = actual_cost_micro_usd - reservation.projected_cost_micro_usd
            self._add_spend_locked(reservation.mode, delta)
            reservation.settled = True

    def release(self, reservation: BudgetReservation) -> None:
        """Refund a reservation in full (call failed; no spend occurred)."""
        with self._lock:
            if reservation.settled:
                return
            self._add_spend_locked(reservation.mode, -reservation.projected_cost_micro_usd)
            reservation.settled = True

    def preflight(self, mode: str, projected_cost_micro_usd: int) -> None:
        """Raise :class:`BudgetExceeded` if a call would breach a cap.

        Read-only check retained for callers that account spend out-of-band via
        :meth:`record`. Concurrent callers should prefer :meth:`reserve` /
        :meth:`commit`, which make the check-and-debit atomic.
        """
        if projected_cost_micro_usd < 0:
            raise ValueError("projected_cost_micro_usd must be non-negative")
        with self._lock:
            self._check_caps_locked(mode, projected_cost_micro_usd)

    def record(self, mode: str, cost_micro_usd: int) -> None:
        """Record actual cost after a successful call."""
        if cost_micro_usd < 0:
            raise ValueError("cost_micro_usd must be non-negative")
        with self._lock:
            self._add_spend_locked(mode, cost_micro_usd)

    def spent_micro_usd(self, mode: str | None = None) -> int:
        with self._lock:
            if mode is None:
                return self._global_spend
            return self._mode_spend.get(mode, 0)
