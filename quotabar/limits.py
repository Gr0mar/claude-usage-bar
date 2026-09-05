"""Subscription quota windows: where they come from and how they are read.

Two sources, in order of freshness:

* the account's own usage endpoint at api.anthropic.com, authenticated with the OAuth
  token Claude Code already stored in the login keychain. Observed payload:
  ``{"five_hour": {"utilization": 21.0, "resets_at": "2026-09-05T17:29:59+00:00"}, ...}``
  - utilization is a percentage, resets_at an ISO 8601 string.
* the file the bundled statusline hook writes on every Claude Code turn, which needs no
  credentials but only refreshes while a session is running. That payload uses
  ``rate_limits.five_hour.used_percentage`` with an epoch ``resets_at``.

Neither payload is a published contract, so every failure degrades to "unavailable"
and the menu falls back to a local token count.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

KEYCHAIN_SERVICE = "Claude Code-credentials"
#: Cap on the response body we will read, so a hostile or broken endpoint cannot
#: exhaust memory in a process that runs all day.
MAX_RESPONSE_BYTES = 1_000_000
USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
STATUSLINE_PATH = os.path.expanduser("~/.claude/usage-bar/limits.json")

SOURCE_API = "api"
SOURCE_STATUSLINE = "statusline"
SOURCE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LimitWindow:
    #: 0-100.
    used_percent: float
    resets_at: Optional[datetime] = None

    def __post_init__(self):
        object.__setattr__(self, "used_percent", min(max(self.used_percent, 0.0), 100.0))


@dataclass(frozen=True)
class LimitsSnapshot:
    five_hour: Optional[LimitWindow] = None
    seven_day: Optional[LimitWindow] = None
    source: str = SOURCE_UNAVAILABLE
    fetched_at: Optional[datetime] = None

    @property
    def has_data(self) -> bool:
        return self.five_hour is not None or self.seven_day is not None


UNAVAILABLE = LimitsSnapshot()

_PERCENT_KEYS = ("used_percentage", "usedPercentage", "utilization", "percent")
_RESET_KEYS = ("resets_at", "resetsAt", "reset_at")


def _parse_reset(value: Any) -> Optional[datetime]:
    """Accepts both epoch seconds and the ISO 8601 strings the usage endpoint returns."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _window_from(node: dict) -> Optional[LimitWindow]:
    percent = None
    for key in _PERCENT_KEYS:
        value = node.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            percent = float(value)
            break
    if percent is None:
        return None

    reset = None
    for key in _RESET_KEYS:
        reset = _parse_reset(node.get(key))
        if reset is not None:
            break
    return LimitWindow(used_percent=percent, resets_at=reset)


def decode_windows(payload: Any) -> Tuple[Optional[LimitWindow], Optional[LimitWindow]]:
    """Pulls the five-hour and weekly windows out of a payload without assuming
    where in the tree they sit."""
    found = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, dict) and key in ("five_hour", "fiveHour", "seven_day", "sevenDay"):
                    canonical = "five_hour" if key in ("five_hour", "fiveHour") else "seven_day"
                    window = _window_from(value)
                    if window is not None and canonical not in found:
                        found[canonical] = window
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found.get("five_hour"), found.get("seven_day")


def read_access_token(runner=subprocess.run) -> Optional[str]:
    """Reads Claude Code's OAuth token from the login keychain.

    The token is used for exactly one thing: an authenticated GET to api.anthropic.com
    for this account's own quota windows. It is never written to disk or logged.
    """
    try:
        result = runner(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            # The first read raises a keychain dialog; a short timeout would kill it
            # while the user is still reading, and it would return every poll after.
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        stored = json.loads(result.stdout)
        oauth = stored.get("claudeAiOauth") or {}
        token = oauth.get("accessToken")
        expires_at = oauth.get("expiresAt")
    except (ValueError, AttributeError):
        return None
    if not token:
        return None
    if isinstance(expires_at, (int, float)) and expires_at / 1000 <= datetime.now(timezone.utc).timestamp():
        return None
    return token


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect.

    urllib replays request headers across redirects, so a 302 from a hostile or
    intercepted endpoint would forward the `Authorization: Bearer` token to another
    host. The usage endpoint has no legitimate reason to redirect, so any redirect
    is treated as a failure and the menu falls back to another source.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(newurl, code, "redirect refused", headers, fp)


class OAuthLimitsProvider:
    def __init__(self, endpoint: str = USAGE_ENDPOINT, timeout: float = 8.0,
                 token_reader=read_access_token) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.token_reader = token_reader

    def fetch(self) -> LimitsSnapshot:
        token = self.token_reader()
        if not token:
            return UNAVAILABLE

        request = urllib.request.Request(
            self.endpoint,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        try:
            opener = urllib.request.build_opener(_NoRedirect)
            with opener.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    return UNAVAILABLE
                payload = json.loads(response.read(MAX_RESPONSE_BYTES).decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return UNAVAILABLE

        five_hour, seven_day = decode_windows(payload)
        if five_hour is None and seven_day is None:
            return UNAVAILABLE
        return LimitsSnapshot(five_hour, seven_day, SOURCE_API, datetime.now(timezone.utc))


class StatuslineLimitsProvider:
    def __init__(self, path: str = STATUSLINE_PATH, max_age: timedelta = timedelta(hours=6)) -> None:
        self.path = path
        self.max_age = max_age

    def fetch(self) -> LimitsSnapshot:
        try:
            modified = datetime.fromtimestamp(os.path.getmtime(self.path), tz=timezone.utc)
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return UNAVAILABLE
        if datetime.now(timezone.utc) - modified > self.max_age:
            return UNAVAILABLE

        five_hour, seven_day = decode_windows(payload)
        if five_hour is None and seven_day is None:
            return UNAVAILABLE
        return LimitsSnapshot(five_hour, seven_day, SOURCE_STATUSLINE, modified)


class ChainedLimitsProvider:
    """Tries each provider in order and keeps the first snapshot that carries data."""

    def __init__(self, providers: List[Any]) -> None:
        self.providers = providers

    @classmethod
    def standard(cls) -> "ChainedLimitsProvider":
        return cls([OAuthLimitsProvider(), StatuslineLimitsProvider()])

    def fetch(self) -> LimitsSnapshot:
        for provider in self.providers:
            snapshot = provider.fetch()
            if snapshot.has_data:
                return snapshot
        return UNAVAILABLE
