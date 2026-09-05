"""Walks the session logs, parsing only the bytes each file has grown by.

Two properties matter here and both are load-bearing:

* **Exactly-once accounting.** Claude Code writes one log line per content block, and
  every line of the same API response repeats the same `message.id` and the same
  complete `usage` object. Those lines are often written seconds apart, so a response
  routinely straddles two scans. The scanner therefore remembers every event id it has
  already folded into the aggregate - without that, a third of all responses would be
  counted twice or more.
* **Idempotent re-reads.** Because of the id set, re-parsing a file from the start
  (after a truncation, a `/rewind`, or a from-scratch rescan) adds nothing that is
  already counted.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from .aggregate import UsageAggregate, day_keys
from .identity import CACHE_DIR
from .parser import UsageEvent, events_from_text

DEFAULT_ROOT = os.path.expanduser("~/.claude/projects")


def event_key(event_id: str) -> str:
    """The compact fingerprint stored for an event id."""
    return hashlib.blake2b(event_id.encode("utf-8"), digest_size=8).hexdigest()
#: How long raw events are kept for the live-session and burn-rate views.
RECENT_WINDOW = timedelta(hours=24)
#: Days of history kept in the aggregate. The UI never looks past 30.
HISTORY_DAYS = 90
#: The directory tree is re-walked at most this often; between walks only known files
#: are stat-ed. With a thousand logs that is the difference between a full crawl every
#: five seconds and a handful of syscalls.
WALK_INTERVAL = 60.0


@dataclass
class FileCursor:
    """How far into a log we have parsed, and what the file looked like then."""

    offset: int = 0
    size: int = 0
    mtime: float = 0.0

    def to_dict(self) -> dict:
        return {"offset": self.offset, "size": self.size, "mtime": self.mtime}

    @classmethod
    def from_dict(cls, raw) -> "FileCursor":
        # Older caches stored a bare integer offset.
        if isinstance(raw, (int, float)):
            return cls(offset=int(raw), size=int(raw))
        return cls(
            offset=int(raw.get("offset", 0)),
            size=int(raw.get("size", 0)),
            mtime=float(raw.get("mtime", 0.0)),
        )


@dataclass
class ScanState:
    """Everything the scanner carries between launches."""

    cursors: Dict[str, FileCursor] = field(default_factory=dict)
    aggregate: UsageAggregate = field(default_factory=UsageAggregate)
    #: Events from the recent window, kept raw so live-session and burn-rate stay exact.
    recent: List[UsageEvent] = field(default_factory=list)
    #: Fingerprints of every event already folded into the aggregate. Hashes rather
    #: than ids: fifty thousand full ids cost megabytes in the cache file, and a
    #: 64-bit digest collides at a rate far below the noise in the numbers.
    counted: Set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "version": 3,
            "cursors": {path: cursor.to_dict() for path, cursor in self.cursors.items()},
            "aggregate": self.aggregate.to_dict(),
            "recent": [event.to_dict() for event in self.recent],
            "counted": sorted(self.counted),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "ScanState":
        """Raises ValueError for anything this version cannot read, so the caller
        treats it as no cache and rescans rather than starting from junk."""
        if not isinstance(raw, dict) or raw.get("version") != 3:
            raise ValueError("unsupported cache payload")
        return cls(
            cursors={
                str(path): FileCursor.from_dict(value)
                for path, value in (raw.get("cursors") or {}).items()
            },
            aggregate=UsageAggregate.from_dict(raw.get("aggregate") or {}),
            recent=[UsageEvent.from_dict(item) for item in (raw.get("recent") or [])],
            counted=set(raw.get("counted") or []),
        )


class LogScanner:
    def __init__(self, root: str = DEFAULT_ROOT, recent_window: timedelta = RECENT_WINDOW,
                 history_days: int = HISTORY_DAYS) -> None:
        self.root = root
        self.recent_window = recent_window
        self.history_days = history_days
        self._cached_files: List[str] = []
        self._walked_at: float = 0.0

    def log_files(self, force_walk: bool = False) -> List[str]:
        """The .jsonl paths under the root, re-walked at most every WALK_INTERVAL."""
        import time as _time

        if force_walk or not self._cached_files or _time.monotonic() - self._walked_at > WALK_INTERVAL:
            found: List[str] = []
            for directory, _, names in os.walk(self.root):
                found.extend(os.path.join(directory, name) for name in names if name.endswith(".jsonl"))
            self._cached_files = found
            self._walked_at = _time.monotonic()
        return self._cached_files

    def fingerprint(self) -> Tuple[int, int, float]:
        """Cheap change detector: file count, total size, newest mtime."""
        total = 0
        newest = 0.0
        paths = self.log_files()
        for path in paths:
            try:
                stat = os.stat(path)
            except OSError:
                continue
            total += stat.st_size
            newest = max(newest, stat.st_mtime)
        return (len(paths), total, newest)

    def scan(self, state: ScanState, now: Optional[datetime] = None) -> bool:
        """Folds whatever is new into `state`. Returns True when anything changed."""
        now = now or datetime.now(timezone.utc)
        live_paths = set()
        changed = False

        for path in self.log_files(force_walk=True):
            live_paths.add(path)
            try:
                stat = os.stat(path)
            except OSError:
                continue

            cursor = state.cursors.get(path) or FileCursor()
            start = cursor.offset
            # A file that shrank was rewritten or rotated; one that changed without
            # growing was rewritten in place. Both are re-read from the beginning -
            # the counted-id set makes that free of double counting.
            if stat.st_size < cursor.offset or (
                stat.st_size == cursor.size and stat.st_mtime != cursor.mtime and cursor.mtime
            ):
                start = 0

            if stat.st_size <= start:
                state.cursors[path] = FileCursor(start, stat.st_size, stat.st_mtime)
                continue

            text, consumed = self._read_chunk(path, start)
            if not consumed or text is None:
                state.cursors[path] = FileCursor(start, stat.st_size, stat.st_mtime)
                continue

            fallback_project = os.path.basename(os.path.dirname(path))
            fresh = [
                event
                for event in events_from_text(text, fallback_project)
                if event_key(event.id) not in state.counted
            ]
            if fresh:
                state.aggregate.extend(fresh)
                state.recent.extend(fresh)
                state.counted.update(event_key(event.id) for event in fresh)
                changed = True
            state.cursors[path] = FileCursor(start + consumed, stat.st_size, stat.st_mtime)

        # Forget cursors for logs that no longer exist.
        if any(path not in live_paths for path in state.cursors):
            state.cursors = {path: c for path, c in state.cursors.items() if path in live_paths}
            changed = True

        if self._trim(state, now):
            changed = True
        return changed

    def _trim(self, state: ScanState, now: datetime) -> bool:
        """Drops events past the recent window and days past the history window."""
        cutoff = now - self.recent_window
        seen: Set[str] = set()
        trimmed = []
        for event in sorted(state.recent, key=lambda item: item.timestamp):
            if event.timestamp < cutoff or event.id in seen:
                continue
            seen.add(event.id)
            trimmed.append(event)
        changed = len(trimmed) != len(state.recent)
        state.recent = trimmed
        return state.aggregate.prune(day_keys(self.history_days, now)) or changed

    @staticmethod
    def _read_chunk(path: str, offset: int):
        """Reads up to and including the last complete line, so a half-written tail
        is left for the next pass instead of being dropped. Byte offsets, not text
        offsets - multi-byte characters would otherwise desynchronise the cursor."""
        try:
            with open(path, "rb") as handle:
                handle.seek(offset)
                data = handle.read()
        except OSError:
            return None, 0
        if not data:
            return None, 0
        cut = data.rfind(b"\n")
        if cut < 0:
            return None, 0
        complete = data[: cut + 1]
        return complete.decode("utf-8", errors="replace"), len(complete)


class StateCache:
    """Persists the scan state so a relaunch does not re-read the whole history."""

    DEFAULT_PATH = os.path.join(CACHE_DIR, "scan-state.json")

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self.path = path

    def load(self) -> Optional[ScanState]:
        """Any unreadable or unexpected cache is treated as no cache: the logs are the
        source of truth, so a rescan costs time, never correctness."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return ScanState.from_dict(json.load(handle))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def save(self, state: ScanState) -> None:
        directory = os.path.dirname(self.path)
        try:
            os.makedirs(directory, exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(state.to_dict(), handle)
            os.replace(temporary, self.path)
        except OSError:
            pass

    def clear(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass
