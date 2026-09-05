"""Delivering a quota alert as a macOS notification.

Through `osascript`, deliberately. The obvious alternative, UNUserNotificationCenter,
requires the calling process to *be* a bundled application: this app's launcher runs
the interpreter as a child of the bundle, so the process has no bundle identity of its
own, and asking that framework for the current notification centre segfaults rather
than failing politely. Nothing can be caught around that, so the framework is not
imported at all.

The trade-off is visible to users: alerts are attributed to Script Editor, and macOS
must be allowing its notifications for them to appear. The README says so.
"""

from __future__ import annotations

import subprocess
import threading

from ..alerts import Alert
from ..identity import DISPLAY_NAME

#: Long enough to outlast a busy notification daemon, short enough to give up.
TIMEOUT = 20


class Notifier:
    def deliver(self, alert: Alert) -> None:
        """Hands the alert to the system without blocking the caller.

        This runs from an AppKit callback on the main thread, and osascript can take
        seconds when the notification daemon is wedged - long enough to beachball the
        menu bar - so delivery happens on its own thread.
        """
        threading.Thread(target=self._deliver, args=(alert,), daemon=True).start()

    @staticmethod
    def _deliver(alert: Alert) -> bool:
        script = "display notification {} with title {} subtitle {}".format(
            _quote(alert.body), _quote(DISPLAY_NAME), _quote(alert.title)
        )
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e", script], capture_output=True, timeout=TIMEOUT
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0


def _quote(text: str) -> str:
    """An AppleScript string literal, with the characters that would break one removed."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", " ").replace("\r", " ")
    return '"{}"'.format("".join(character for character in escaped if character >= " "))
