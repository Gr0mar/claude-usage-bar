"""Launch at login via a user LaunchAgent - no admin rights, no installer."""

from __future__ import annotations

import os
import plistlib
import subprocess

LABEL = "deals.clutch.claude-usage-bar"
PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/{}.plist".format(LABEL))


def is_enabled() -> bool:
    return os.path.exists(PLIST_PATH)


def _launchctl(*arguments: str) -> bool:
    try:
        result = subprocess.run(["/bin/launchctl", *arguments], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def enable(app_path: str) -> None:
    """Registers the given .app (or executable) to start at login."""
    program = (
        [os.path.join(app_path, "Contents/MacOS/ClaudeUsageBar")]
        if app_path.endswith(".app")
        else [app_path]
    )
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    temporary = PLIST_PATH + ".tmp"
    with open(temporary, "wb") as handle:
        plistlib.dump(
            {
                "Label": LABEL,
                "ProgramArguments": program,
                "RunAtLoad": True,
                "KeepAlive": False,
                "ProcessType": "Interactive",
            },
            handle,
        )
    os.replace(temporary, PLIST_PATH)

    # is_enabled() reads the plist, so a failed bootstrap must not leave one behind
    # claiming the feature is on.
    if not _launchctl("bootstrap", "gui/{}".format(os.getuid()), PLIST_PATH):
        try:
            os.remove(PLIST_PATH)
        except OSError:
            pass


def disable() -> None:
    _launchctl("bootout", "gui/{}/{}".format(os.getuid(), LABEL))
    try:
        os.remove(PLIST_PATH)
    except OSError:
        pass


def toggle(app_path: str) -> None:
    disable() if is_enabled() else enable(app_path)
