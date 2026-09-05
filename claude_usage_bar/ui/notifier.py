"""Delivering a quota alert as a macOS notification.

UNUserNotificationCenter needs a signed bundle with a bundle id; when the app runs from
a checkout - or when the user has not granted permission - it is unavailable, and the
alert goes out through `osascript` instead. Both paths are best-effort: a notification
that cannot be delivered must never take the app down with it.
"""

from __future__ import annotations

import subprocess
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
        try:
            center.requestAuthorizationWithOptions_completionHandler_(
                UNAuthorizationOptionAlert | UNAuthorizationOptionSound,
                lambda granted, error: None,
            )
        except Exception:
            return None
        return center

    def deliver(self, alert: Alert) -> bool:
        """Returns True when the notification was handed off to the system."""
        return self._deliver_native(alert) or self._deliver_via_osascript(alert)

    def _deliver_native(self, alert: Alert) -> bool:
        if self._center is None:
            return False
        try:
            content = UNMutableNotificationContent.alloc().init()
            content.setTitle_(DISPLAY_NAME)
            content.setSubtitle_(alert.title)
            content.setBody_(alert.body)
            request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
                "quota-{}".format(alert.threshold), content, None
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
                ["/usr/bin/osascript", "-e", script], capture_output=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0


def _quote(text: str) -> str:
    """An AppleScript string literal."""
    return '"{}"'.format(text.replace("\\", "\\\\").replace('"', '\\"'))
