"""The app's identity, in one place.

The bundle id decides where three things live - the cache directory, the preferences
suite and the LaunchAgent - so it is defined once here and read from here by the Python
code and by the install script.
"""

from __future__ import annotations

import os

BUNDLE_ID = "com.github.gr0mar.ClaudeUsageBar"
APP_NAME = "ClaudeUsageBar"
DISPLAY_NAME = "Claude Usage Bar"
LAUNCH_AGENT_LABEL = BUNDLE_ID

#: Identifiers used before the project was published, cleaned up on install.
LEGACY_BUNDLE_IDS = ("deals.clutch.ClaudeUsageBar",)
LEGACY_LAUNCH_AGENT_LABELS = ("deals.clutch.claude-usage-bar",)

CACHE_DIR = os.path.expanduser("~/Library/Caches/{}".format(BUNDLE_ID))
SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/{}".format(APP_NAME))
LAUNCH_AGENT_PATH = os.path.expanduser(
    "~/Library/LaunchAgents/{}.plist".format(LAUNCH_AGENT_LABEL)
)
