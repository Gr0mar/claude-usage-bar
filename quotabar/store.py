"""Owns the scan loop, the cache and the limits refresh, and publishes ready values.

Threading contract, which the rest of the app depends on:

* One background thread owns `_state` outright. Nothing else reads or mutates it, so
  there is no lock to hold across a scan or a cache write, and the menu never blocks.
* That thread publishes an immutable `Snapshot` in a single attribute assignment. The UI
  reads `store.snapshot` once per layout pass, so a repaint can never mix values from
  two different scans - the bug that made the dropdown measure one height and paint
  another.
* The main thread asks for work by setting flags (`set_range`, `refresh_now`,
  `rescan_from_scratch`) and waking the loop; it never touches the data.

The store knows nothing about AppKit: it calls `on_update` from the background thread
and the UI layer marshals that to the main thread.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

from . import live
from .aggregate import EMPTY_SUMMARY, Summary, summarize
from .limits import ChainedLimitsProvider, LimitsSnapshot, UNAVAILABLE
from .live import LiveSession
from .projection import WindowTracker
from .scanner import LogScanner, ScanState, StateCache
from .tokens import ZERO, TokenCounts

#: Selectable ranges, in days. The button copy lives in the UI layer.
RANGES: List[int] = [1, 7, 30]

#: How often the logs are checked for growth.
SCAN_INTERVAL = 5.0
#: How often quota windows are re-fetched. The usage endpoint rate-limits, so this is
#: deliberately slow, doubles on failure up to LIMITS_MAX_INTERVAL, and never fires more
#: often than LIMITS_MIN_INTERVAL even when the user asks for a refresh.
LIMITS_INTERVAL = 300.0
LIMITS_MAX_INTERVAL = 1800.0
LIMITS_MIN_INTERVAL = 60.0
#: A quota reading older than this is shown with its age rather than as current.
LIMITS_STALE_AFTER = LIMITS_INTERVAL

SPARKLINE_DAYS = 14
#: The cache is a few megabytes; during a busy session the logs change every tick, so
#: it is written at most this often rather than on every pass.
CACHE_INTERVAL = 60.0


@dataclass(frozen=True)
class Snapshot:
    """Everything the dropdown draws, from one consistent moment."""

    summary: Summary = EMPTY_SUMMARY
    today_cost: float = 0.0
    sparkline: List[float] = field(default_factory=list)
    limits: LimitsSnapshot = UNAVAILABLE
    live_session: Optional[LiveSession] = None
    burn_rate: float = 0.0
    local_five_hour: TokenCounts = ZERO
    range_days: int = 1
    #: When the five-hour window will hit 100% at the rate measured so far, if it will
    #: get there before it resets.
    five_hour_eta: Optional[datetime] = None
    #: False when ~/.claude/projects does not exist - nothing has been logged yet.
    logs_present: bool = True
    scanning: bool = False
    updated_at: Optional[datetime] = None
    #: Set when the scan loop caught an unexpected error, so the UI can say so.
    error: Optional[str] = None

    def limits_are_stale(self, now: Optional[datetime] = None) -> bool:
        if self.limits.fetched_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - self.limits.fetched_at).total_seconds() > LIMITS_STALE_AFTER


class UsageStore:
    def __init__(
        self,
        scanner: Optional[LogScanner] = None,
        cache: Optional[StateCache] = None,
        limits_provider=None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._scanner = scanner or LogScanner()
        self._cache = cache or StateCache()
        self._limits_provider = limits_provider or ChainedLimitsProvider.standard()
        #: Injectable so the polling schedule can be tested without waiting for it.
        self._clock = clock

        self._state: ScanState = self._cache.load() or ScanState()
        self._fingerprint: Optional[int] = None
        self._limits: LimitsSnapshot = UNAVAILABLE
        self._five_hour = WindowTracker()
        self._limits_source: Optional[str] = None

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._rescan = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_update: Optional[Callable[[], None]] = None

        self._range_days = RANGES[0]
        self._limits_interval = LIMITS_INTERVAL
        # Monotonic, so a clock correction cannot stall or spam the endpoint.
        # None means "never fetched", which is due immediately - monotonic() starts near
        # zero in a fresh process, so a 0.0 sentinel would delay the first read instead.
        self._limits_checked_at: Optional[float] = None
        self._limits_forced = False
        self._saved_at: Optional[float] = None
        self._unsaved = False
        self._scanning = False
        self._error: Optional[str] = None

        self.snapshot = Snapshot()
        self._publish()

    # -- lifecycle ---------------------------------------------------------

    def start(self, on_update: Callable[[], None]) -> None:
        self._on_update = on_update
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="usage-scan", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is None:
            self._save_if_due(force=True)
            return

        # Let an in-flight pass finish rather than leaving a .tmp behind.
        thread.join(timeout=2.0)
        if thread.is_alive():
            # The worker owns the state; writing it from here would serialise a
            # dictionary it is still mutating.
            return
        # Quitting is the one moment worth paying the write unconditionally.
        self._save_if_due(force=True)

    def refresh_now(self, include_limits: bool = False) -> None:
        """Asks the loop for a scan on its next tick, and optionally a quota re-fetch."""
        self._fingerprint = None
        if include_limits:
            self._limits_forced = True
        self._wake.set()

    def rescan_from_scratch(self) -> None:
        """Drops the cache and re-reads every log from the beginning."""
        self._rescan.set()
        self._wake.set()

    def set_range(self, days: int) -> None:
        self._range_days = days
        self._publish()
        self._wake.set()

    def refresh_once(self) -> None:
        """One guarded pass: rescan if asked, scan, fetch quota, publish.

        This is the loop body, exposed so the preview renderer and the tests can run
        exactly what the thread runs without an event loop. It never raises: a
        malformed log or a failing endpoint must not kill the thread, because a dead
        thread means the whole app silently freezes on its last numbers.
        """
        try:
            if self._rescan.is_set():
                self._rescan.clear()
                self._state = ScanState()
                self._cache.clear()
                self._fingerprint = None
            self._scan_if_needed()
            self._fetch_limits_if_due()
            self._error = None
        except Exception:
            self._error = traceback.format_exc(limit=1).strip().splitlines()[-1]
        finally:
            self._scanning = False

        # The live session and the burn rate age even when nothing was written.
        self._publish()

    # -- worker ------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh_once()
            if self._stop.is_set():
                break
            self._wake.wait(SCAN_INTERVAL)
            self._wake.clear()

    def _scan_if_needed(self) -> None:
        fingerprint = self._scanner.fingerprint()
        if fingerprint == self._fingerprint:
            return

        self._scanning = True
        self._publish()
        changed = self._scanner.scan(self._state)
        self._fingerprint = fingerprint
        self._scanning = False
        self._unsaved = self._unsaved or changed
        self._save_if_due()

    def _save_if_due(self, force: bool = False) -> None:
        if not self._unsaved:
            return
        elapsed = None if self._saved_at is None else self._clock() - self._saved_at
        if not force and elapsed is not None and elapsed < CACHE_INTERVAL:
            return
        self._cache.save(self._state)
        self._saved_at = self._clock()
        self._unsaved = False

    def _fetch_limits_if_due(self) -> None:
        never_fetched = self._limits_checked_at is None
        elapsed = 0.0 if never_fetched else self._clock() - self._limits_checked_at
        forced = self._limits_forced and elapsed >= LIMITS_MIN_INTERVAL
        if not never_fetched and not forced and elapsed < self._limits_interval:
            return

        self._limits_forced = False
        self._limits_checked_at = self._clock()
        if self._fetch_limits():
            self._limits_interval = LIMITS_INTERVAL
        else:
            # Usually a rate limit; ease off instead of hammering the endpoint.
            self._limits_interval = min(self._limits_interval * 2, LIMITS_MAX_INTERVAL)

    def _fetch_limits(self) -> bool:
        """Returns True when the fetch produced usable windows."""
        snapshot = self._limits_provider.fetch()
        # Keep the last good reading rather than blanking the header on one failed poll.
        if snapshot.has_data or not self._limits.has_data:
            self._limits = snapshot
        if snapshot.five_hour is not None:
            # The statusline source dates its readings by file mtime, which can be
            # hours behind the live endpoint; mixing the two would poison the slope.
            if snapshot.source != self._limits_source:
                self._five_hour = WindowTracker()
                self._limits_source = snapshot.source
            observed_at = min(snapshot.fetched_at or datetime.now(timezone.utc),
                              datetime.now(timezone.utc))
            self._five_hour.observe(
                snapshot.five_hour.used_percent, snapshot.five_hour.resets_at, observed_at
            )
        return snapshot.has_data

    def _publish(self) -> None:
        """Recomputes everything the UI shows and hands it over as one value."""
        now = datetime.now(timezone.utc)
        aggregate = self._state.aggregate
        recent = self._state.recent

        five_hour = self._limits.five_hour
        self.snapshot = Snapshot(
            summary=summarize(aggregate, self._range_days, now),
            today_cost=summarize(aggregate, 1, now).cost,
            sparkline=[cost for _, cost in summarize(aggregate, SPARKLINE_DAYS, now).daily_costs],
            limits=self._limits,
            live_session=live.current_session(recent, now),
            burn_rate=live.burn_rate(recent, now=now),
            local_five_hour=live.tokens_in_window(recent, timedelta(hours=5), now),
            range_days=self._range_days,
            five_hour_eta=self._five_hour.exhausted_at(
                five_hour.used_percent if five_hour else None,
                five_hour.resets_at if five_hour else None,
                now,
            ),
            logs_present=os.path.isdir(self._scanner.root),
            scanning=self._scanning,
            updated_at=now,
            error=self._error,
        )
        if self._on_update is not None:
            self._on_update()
