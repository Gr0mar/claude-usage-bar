"""When the current burn rate will exhaust a quota window.

The API reports how much of a window is used, not how fast it is being used, so the
rate is measured here: successive readings of the same window give a percent-per-hour
slope, and the slope gives an arrival time at 100%.

Only the window's own readings are used. Token counts from the logs cannot stand in,
because the quota is not a token count and its size is not published.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

#: Readings closer together than this say more about jitter than about a trend.
MIN_SPAN = timedelta(minutes=8)
#: Quota readings arrive every few minutes at best. Until one is overdue, the rate is
#: measured between readings; only after that does the clock start diluting it. Without
#: the grace period the predicted time would visibly creep forward on every UI tick.
GRACE = timedelta(minutes=6)
#: Older readings describe a burn rate that has since changed.
MAX_AGE = timedelta(hours=2)
#: Below this the window is barely moving and any arrival time would be fiction.
MIN_RATE_PER_HOUR = 1.0
#: Readings kept per window.
MAX_SAMPLES = 60


@dataclass(frozen=True)
class Sample:
    at: datetime
    percent: float


class WindowTracker:
    """Readings of one quota window, keyed by when that window resets.

    A new window (different reset time) starts the history over: the previous window's
    slope says nothing about the new one.
    """

    def __init__(self) -> None:
        self._resets_at: Optional[datetime] = None
        self._samples: List[Sample] = []

    @property
    def samples(self) -> List[Sample]:
        return list(self._samples)

    def observe(self, percent: Optional[float], resets_at: Optional[datetime],
                now: datetime) -> None:
        if percent is None:
            return
        if resets_at != self._resets_at:
            self._resets_at = resets_at
            self._samples = []

        if self._samples:
            last = self._samples[-1]
            # A window that went backwards without a new reset time is a fresh window
            # the server has not re-dated yet.
            if percent < last.percent:
                self._samples = []
            elif percent == last.percent:
                return

        self._samples.append(Sample(now, percent))
        del self._samples[:-MAX_SAMPLES]

    def rate_per_hour(self, now: datetime) -> Optional[float]:
        """Percent consumed per hour, or None when there is not enough to say.

        Once a reading is overdue the span runs to *now* rather than to the last
        reading. A window only reports a new percentage when it moves, so measuring
        between readings alone would freeze the rate at whatever it was when work
        stopped, and the app would keep predicting an exhaustion time through an idle
        evening. Letting the clock in after the grace period dilutes the rate until it
        falls below the floor and the prediction disappears on its own - while the
        grace period keeps it steady between scheduled readings.
        """
        usable = [sample for sample in self._samples if now - sample.at <= MAX_AGE]
        if len(usable) < 2:
            return None

        first = usable[0]
        last = usable[-1]
        end = max(last.at, now - GRACE)
        span = end - first.at
        if span < MIN_SPAN:
            return None

        rate = (last.percent - first.percent) / (span.total_seconds() / 3600.0)
        return rate if rate >= MIN_RATE_PER_HOUR else None

    def exhausted_at(self, percent: Optional[float], resets_at: Optional[datetime],
                     now: datetime) -> Optional[datetime]:
        """When the window hits 100% at the measured rate.

        Anchored to the last reading, not to the present moment. Measuring "time left"
        from now would push the predicted clock time forward by five seconds on every
        UI tick, so a user watching the dropdown would see the deadline running away
        from them on data that never changed.

        None when the rate is unknown, the window is already full, the prediction has
        already lapsed (the rate was an overestimate - the next reading will re-anchor
        it), or the reset lands first, in which case there is nothing to warn about.
        """
        if percent is None or percent >= 100 or not self._samples:
            return None
        rate = self.rate_per_hour(now)
        if rate is None:
            return None

        anchor = self._samples[-1]
        remaining = 100.0 - min(anchor.percent, percent)
        if remaining <= 0:
            return None

        eta = anchor.at + timedelta(hours=remaining / rate)
        if eta <= now:
            return None
        if resets_at is not None and eta >= resets_at:
            return None
        return eta
