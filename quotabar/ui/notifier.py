"""Delivering a quota alert as a macOS notification.

UNUserNotificationCenter needs a signed bundle with a bundle id; when the app runs from
a checkout - or when the user has not granted permission - it is unavailable, and the
alert goes out through `osascript` instead. Both paths are best-effort: a notification
that cannot be delivered must never take the app down with it.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Optional

from ..alerts import Alert
from ..identity import DISPLAY_NAME

try:  # UserNotifications is unavailable on older systems and outside a bundle.
    from UserNotifications import (
        UNAuthorizationOptionAlert,
        UNAuthorizationOptionSound,
        UNMutableNotificationContent,
        UNNotificationRequest,
        UNUserNotificationCenter,
    )
except ImportError:  # pragma: no cover - depends on the host system
    UNUserNotificationCenter = None


class Notifier:
    def __init__(self) -> None:
        self._granted = False
        self._center = self._authorized_center()

    @staticmethod
    def _authorized_center():
        if UNUserNotificationCenter is None:
            return None
        try:
            center = UNUserNotificationCenter.currentNotificationCenter()
        except Exception:
            return None
        if center is None:
            return None
        def remember(granted, error) -> None:
            # Without this the app would report every alert as delivered while macOS
            # dropped them, and the osascript fallback would never run.
            self._granted = bool(granted) and error is None

        try:
            center.requestAuthorizationWithOptions_completionHandler_(
                UNAuthorizationOptionAlert | UNAuthorizationOptionSound, remember
            )
        except Exception:
            return None
        return center

    def deliver(self, alert: Alert) -> None:
        """Hands the alert to the system, without blocking the caller.

        This runs from an AppKit callback on the main thread, and the osascript
        fallback can take seconds when the notification daemon is wedged - long enough
        to beachball the menu bar - so delivery happens on its own thread.
        """
        threading.Thread(target=self._deliver, args=(alert,), daemon=True).start()

    def _deliver(self, alert: Alert) -> bool:
        return self._deliver_native(alert) or self._deliver_via_osascript(alert)

    def _deliver_native(self, alert: Alert) -> bool:
        if self._center is None or not self._granted:
            return False
        try:
            content = UNMutableNotificationContent.alloc().init()
            content.setTitle_(DISPLAY_NAME)
            content.setSubtitle_(alert.title)
            content.setBody_(alert.body)
            # The identifier carries the window, so a new window's alert cannot replace
            # an earlier one the user has not read yet.
            identifier = "quota-{}-{}".format(alert.window_key, alert.threshold)
            request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
                identifier, content, None
            )
            self._center.addNotificationRequest_withCompletionHandler_(request, None)
            return True
        except Exception:
            self._center = None
            return False

    @staticmethod
    def _deliver_via_osascript(alert: Alert) -> bool:
        script = 'display notification {} with title {} subtitle {}'.format(
            _quote(alert.body), _quote(DISPLAY_NAME), _quote(alert.title)
        )
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e", script], capture_output=True, timeout=20
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0


def _quote(text: str) -> str:
    """An AppleScript string literal, with the characters that would break one removed."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", " ").replace("\r", " ")
    return '"{}"'.format("".join(character for character in escaped if character >= " "))
