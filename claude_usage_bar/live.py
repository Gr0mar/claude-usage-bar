"""The session running right now, derived from recent log events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from . import pricing
from .parser import UsageEvent
from .tokens import ZERO, TokenCounts

#: A session counts as live while its log kept growing within this window.
LIVE_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True)
class LiveSession:
    project: str
    model: str
    tokens: TokenCounts
    cost: float
    started_at: datetime
    last_event_at: datetime

    @property
    def duration(self) -> timedelta:
        return self.last_event_at - self.started_at


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def current_session(events: List[UsageEvent], now: Optional[datetime] = None) -> Optional[LiveSession]:
    now = _now(now)
    if not events:
        return None
    latest = max(events, key=lambda event: event.timestamp)
    if now - latest.timestamp > LIVE_WINDOW:
        return None

    session_events = [event for event in events if event.session_id == latest.session_id]
    tokens = ZERO
    cost = 0.0
    for event in session_events:
        tokens = tokens + event.tokens
        cost += pricing.cost(event.tokens, event.model) or 0.0

    return LiveSession(
        project=latest.project,
        model=latest.model,
        tokens=tokens,
        cost=cost,
        started_at=min(event.timestamp for event in session_events),
        last_event_at=latest.timestamp,
    )


def burn_rate(events: Iterable[UsageEvent], window: timedelta = timedelta(hours=1),
              now: Optional[datetime] = None) -> float:
    """Spend over the trailing window, expressed as dollars per hour."""
    now = _now(now)
    seconds = window.total_seconds()
    if seconds <= 0:
        return 0.0
    cutoff = now - window
    cost = sum(
        pricing.cost(event.tokens, event.model) or 0.0
        for event in events
        if event.timestamp >= cutoff
    )
    return cost * 3600.0 / seconds


def tokens_in_window(events: Iterable[UsageEvent], window: timedelta,
                     now: Optional[datetime] = None) -> TokenCounts:
    """Tokens billed in the trailing window - the local stand-in for a quota window."""
    now = _now(now)
    cutoff = now - window
    total = ZERO
    for event in events:
        if event.timestamp >= cutoff:
            total = total + event.tokens
    return total
