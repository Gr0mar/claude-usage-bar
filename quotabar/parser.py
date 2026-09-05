"""Decodes Claude Code session-log lines into usage events.

Logs live in ~/.claude/projects/**/*.jsonl, one JSON object per line. Only `assistant`
lines carrying `message.usage` were billed; everything else is skipped.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

from .tokens import TokenCounts

#: Placeholder model the CLI writes for locally generated messages that were never billed.
SYNTHETIC_MODEL = "<synthetic>"


@dataclass(frozen=True)
class UsageEvent:
    #: Stable identity used to drop duplicate lines (a streaming retry writes the message twice).
    id: str
    timestamp: datetime
    model: str
    project: str
    session_id: str
    tokens: TokenCounts

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.timestamp(),
            "model": self.model,
            "project": self.project,
            "session_id": self.session_id,
            "tokens": self.tokens.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "UsageEvent":
        return cls(
            id=raw["id"],
            timestamp=datetime.fromtimestamp(raw["timestamp"], tz=timezone.utc),
            model=raw["model"],
            project=raw["project"],
            session_id=raw["session_id"],
            tokens=TokenCounts.from_dict(raw["tokens"]),
        )


def parse_timestamp(raw: str) -> Optional[datetime]:
    """Parses the ISO 8601 timestamps the logs use, with or without fractional seconds.

    Always returns an aware datetime: a naive one would raise on the first comparison
    against the scan cutoff and take the whole scan thread down with it.
    """
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_int(value: Any) -> int:
    """Token counts from a log line are untrusted: anything that is not a plain,
    finite number counts as zero rather than raising."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        return int(value)
    except (ValueError, OverflowError):
        return 0


def event_from_line(line: str, fallback_project: str) -> Optional[UsageEvent]:
    """Returns None for anything that is not a billed assistant response."""
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return None

    message = record.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    model = message.get("model")
    if not isinstance(usage, dict) or not isinstance(model, str) or not model:
        return None
    if model == SYNTHETIC_MODEL:
        return None

    timestamp = parse_timestamp(record.get("timestamp") or "")
    if timestamp is None:
        return None

    # `cache_creation` splits the write by TTL; the flat field is the pre-split fallback.
    creation = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    write_5m = creation.get("ephemeral_5m_input_tokens")
    write_1h = creation.get("ephemeral_1h_input_tokens")
    flat_write = _as_int(usage.get("cache_creation_input_tokens"))
    has_split = write_5m is not None or write_1h is not None

    tokens = TokenCounts(
        input=_as_int(usage.get("input_tokens")),
        output=_as_int(usage.get("output_tokens")),
        cache_write_5m=_as_int(write_5m) if has_split else flat_write,
        cache_write_1h=_as_int(write_1h) if has_split else 0,
        cache_read=_as_int(usage.get("cache_read_input_tokens")),
    )
    if tokens.total <= 0:
        return None

    parts = [part for part in (message.get("id"), record.get("requestId")) if isinstance(part, str)]
    identity = ":".join(parts)
    cwd = record.get("cwd")
    project = os.path.basename(cwd.rstrip("/")) if isinstance(cwd, str) and cwd else ""
    session = record.get("sessionId")
    uuid = record.get("uuid")

    return UsageEvent(
        id=identity or (uuid if isinstance(uuid, str) else f"{timestamp.timestamp()}:{tokens.total}"),
        timestamp=timestamp,
        model=model,
        project=project or fallback_project,
        session_id=session if isinstance(session, str) and session else fallback_project,
        tokens=tokens,
    )


def events_from_text(text: str, fallback_project: str) -> List[UsageEvent]:
    """Parses a log chunk, dropping repeated message identities within it."""
    seen = set()
    events: List[UsageEvent] = []
    for line in text.splitlines():
        event = event_from_line(line, fallback_project)
        if event is None or event.id in seen:
            continue
        seen.add(event.id)
        events.append(event)
    return events
