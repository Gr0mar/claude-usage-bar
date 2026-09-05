"""Entry point: builds the store, the status item, and runs the AppKit loop."""

from __future__ import annotations

import os
import sys

import fcntl

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from PyObjCTools import AppHelper

from .identity import DISPLAY_NAME, SUPPORT_DIR
from .store import UsageStore
from .ui.controller import StatusItemController


def _app_path() -> str:
    """The path a login item should launch: the .app bundle when we run from one."""
    executable = os.path.realpath(sys.argv[0])
    marker = ".app/Contents/MacOS/"
    if marker in executable:
        return executable.split(marker)[0] + ".app"
    package = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(package), "scripts", "run.sh")


LOCK_PATH = os.path.join(SUPPORT_DIR, "instance.lock")


def _claim_single_instance():
    """Returns the held lock file, or None when another copy is already running.

    Two copies would race over one cache file, and the second menu bar icon is
    confusing. The lock is released by the kernel when the process exits, so a crash
    cannot leave the app permanently unable to start.
    """
    try:
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        handle = open(LOCK_PATH, "w")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError):
        return None
    return handle


def main() -> None:
    lock = _claim_single_instance()
    if lock is None:
        print("{} is already running.".format(DISPLAY_NAME))
        return

    application = NSApplication.sharedApplication()
    # Menu bar only: no Dock icon, no app switcher entry.
    application.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    store = UsageStore()
    controller = StatusItemController.alloc().initWithStore_appPath_(store, _app_path())
    store.start(controller.onStoreUpdate)

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
