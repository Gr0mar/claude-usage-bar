"""Deciding when a quota is worth interrupting someone about.

One notification per threshold per window: crossing 80% once is news, and the next
reading five seconds later is not. A new window (a different reset time) arms the
thresholds again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set, Tuple

from . import formatting as fmt

#: Percentages worth a notification.
THRESHOLDS: Tuple[float, ...] = (80.0, 95.0)


@dataclass(frozen=True)
class Alert:
    title: str
    body: str
    threshold: float


class QuotaAlerts:
    def __init__(self, window_name: str = "5-hour", thresholds: Tuple[float, ...] = THRESHOLDS,
                 enabled: bool = True) -> None:
        self.window_name = window_name
        self.thresholds = tuple(sorted(thresholds))
        self.enabled = enabled
        self._window: Optional[datetime] = None
        self._fired: Set[float] = set()

    def check(self, percent: Optional[float], resets_at: Optional[datetime],
              exhausted_at: Optional[datetime] = None,
              now: Optional[datetime] = None) -> Optional[Alert]:
        """The alert this reading warrants, or None."""
        if percent is None:
            return None
        if resets_at != self._window:
            self._window = resets_at
            self._fired = set()
        if not self.enabled:
            # Thresholds still arm and disarm while off, so switching notifications on
            # mid-window does not immediately fire for a threshold already passed.
            self._fired.update(t for t in self.thresholds if percent >= t)
            return None

        crossed = [t for t in self.thresholds if percent >= t and t not in self._fired]
        if not crossed:
            return None

        threshold = max(crossed)
        # Passing 95 while 80 was never sent means 80 is stale, not pending.
        self._fired.update(t for t in self.thresholds if percent >= t)

        return Alert(
            title="{} limit {}".format(self.window_name, fmt.percent(percent)),
            body=self._body(exhausted_at, resets_at, now),
            threshold=threshold,
        )

    @staticmethod
    def _body(exhausted_at: Optional[datetime], resets_at: Optional[datetime],
              now: Optional[datetime] = None) -> str:
        if exhausted_at is not None:
            return "Full around {} at this rate.".format(fmt.time_of_day(exhausted_at))
        countdown = fmt.countdown(resets_at, now)
        if countdown:
            return countdown.capitalize() + "."
        return "Usage is high."
