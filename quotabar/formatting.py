"""Number and time formatting shared by the menu bar label and the dropdown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

#: Sentinel for "the system has not been asked yet", so a real None can be cached.
_UNSET = object()
_CLOCK_IS_12_HOUR = _UNSET


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


def clock_is_12_hour() -> Optional[bool]:
    """Whether macOS writes times as 10:47 AM rather than 10:47, or None off macOS.

    Read through ICU rather than the raw 24-hour default, because the choice comes from
    the region as often as from the switch in Settings. Cached: the answer only changes
    when the user changes it, and by then the app has been restarted.
    """
    global _CLOCK_IS_12_HOUR
    if _CLOCK_IS_12_HOUR is _UNSET:
        _CLOCK_IS_12_HOUR = _read_clock_preference()
    return _CLOCK_IS_12_HOUR


def _read_clock_preference() -> Optional[bool]:
    try:
        from Foundation import NSDateFormatter, NSLocale
    except ImportError:  # The test suite, and any non-macOS host.
        return None
    pattern = NSDateFormatter.dateFormatFromTemplate_options_locale_(
        "j:mm", 0, NSLocale.currentLocale()
    )
    return "a" in pattern if pattern else None


def time_of_day(moment: datetime, hour12: Optional[bool] = None) -> str:
    """A wall-clock time in the format this Mac writes times in.

    `hour12` overrides the system's choice; None asks the system, and falls back to the
    24-hour clock where nothing can be asked.
    """
    if hour12 is None:
        hour12 = clock_is_12_hour()
    local = moment.astimezone()
    if not hour12:
        return local.strftime("%H:%M")
    # %I pads the hour to two digits and no platform-independent flag drops that zero.
    return "{}:{} {}".format(local.hour % 12 or 12, local.strftime("%M"),
                             local.strftime("%p") or ("AM" if local.hour < 12 else "PM"))
