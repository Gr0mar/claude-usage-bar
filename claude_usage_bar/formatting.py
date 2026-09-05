"""Number and time formatting shared by the menu bar label and the dropdown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def money(value: float) -> str:
    if value >= 100:
        return "${:.0f}".format(value)
    if value >= 10:
        return "${:.1f}".format(value)
    if 0 < value < 0.01:
        return "<$0.01"
    return "${:.2f}".format(value)


def tokens(count: int) -> str:
    value = float(count)
    if value >= 1_000_000_000:
        return "{:.1f}B".format(value / 1_000_000_000)
    if value >= 1_000_000:
        return "{:.1f}M".format(value / 1_000_000)
    if value >= 1_000:
        return "{:.1f}k".format(value / 1_000)
    return str(int(value))


def percent(value: float) -> str:
    return "{:.0f}%".format(value)


def countdown(moment: Optional[datetime], now: Optional[datetime] = None) -> Optional[str]:
    """"resets in 2h 14m" style countdown; None when there is nothing to count down to."""
    if moment is None:
        return None
    now = now or datetime.now(timezone.utc)
    remaining = (moment - now).total_seconds()
    if remaining <= 0:
        return "resetting"
    hours, minutes = int(remaining) // 3600, (int(remaining) % 3600) // 60
    if hours >= 24:
        return "resets in {}d {}h".format(hours // 24, hours % 24)
    if hours:
        return "resets in {}h {}m".format(hours, minutes)
    return "resets in {}m".format(minutes)


def elapsed(delta: timedelta) -> str:
    minutes = int(delta.total_seconds()) // 60
    if minutes >= 60:
        return "{}h {}m".format(minutes // 60, minutes % 60)
    return "{}m".format(minutes)


def menu_bar_label(metric: str, limits, today_cost: float) -> str:
    """The text beside the menu bar icon.

    Quota metrics fall back to the spend when no window is available - the endpoint
    rate-limits, and a dollar sign makes it obvious this is not a percentage.
    """
    if metric == "icon":
        return ""
    if metric == "today":
        return money(today_cost)

    window = limits.five_hour if metric == "five_hour" else limits.seven_day
    if window is not None:
        return percent(window.used_percent)
    return money(today_cost)


def time_of_day(moment: datetime) -> str:
    return moment.astimezone().strftime("%H:%M")
