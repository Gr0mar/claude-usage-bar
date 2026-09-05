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
            if percent < last.percent - 1:
                self._samples = []
            elif percent == last.percent:
                return

        self._samples.append(Sample(now, percent))
        del self._samples[:-MAX_SAMPLES]

    def rate_per_hour(self, now: datetime) -> Optional[float]:
        """Percent consumed per hour, or None when there is not enough to say."""
        usable = [sample for sample in self._samples if now - sample.at <= MAX_AGE]
        if len(usable) < 2:
            return None

        first, last = usable[0], usable[-1]
        span = last.at - first.at
        if span < MIN_SPAN:
            return None

        rate = (last.percent - first.percent) / (span.total_seconds() / 3600.0)
        return rate if rate >= MIN_RATE_PER_HOUR else None

    def exhausted_at(self, percent: Optional[float], resets_at: Optional[datetime],
                     now: datetime) -> Optional[datetime]:
        """When the window hits 100% at the measured rate.

        None when the rate is unknown, the window is already full, or the reset lands
        first - in which case there is nothing to warn about.
        """
        if percent is None or percent >= 100:
            return None
        rate = self.rate_per_hour(now)
        if rate is None:
            return None

        eta = now + timedelta(hours=(100.0 - percent) / rate)
        if resets_at is not None and eta >= resets_at:
            return None
        return eta
