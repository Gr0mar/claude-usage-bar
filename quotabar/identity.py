"""The app's identity, in one place.

The bundle id decides where three things live - the cache directory, the preferences
suite and the LaunchAgent - so it is defined once here and read from here by the Python
code and by the install script.
"""

from __future__ import annotations

import os

VERSION = "1.2.0"
BUNDLE_ID = "com.github.gr0mar.QuotaBar"
APP_NAME = "QuotaBar"
DISPLAY_NAME = "QuotaBar"
LAUNCH_AGENT_LABEL = BUNDLE_ID


CACHE_DIR = os.path.expanduser("~/Library/Caches/{}".format(BUNDLE_ID))
SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/{}".format(APP_NAME))
LAUNCH_AGENT_PATH = os.path.expanduser(
    "~/Library/LaunchAgents/{}.plist".format(LAUNCH_AGENT_LABEL)
)
