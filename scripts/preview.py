"""Renders the dropdown to PNGs without opening the menu - a visual smoke test.

    .venv/bin/python scripts/preview.py [out_dir] [range_days] [--demo]

`--demo` renders synthetic logs and quota windows instead of your own, which is what
the screenshot in the README is made from - no real project names or spend.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AppKit import (  # noqa: E402
    NSAppearance,
    NSAppearanceNameAqua,
    NSAppearanceNameDarkAqua,
    NSApplication,
    NSBackingStoreBuffered,
    NSBitmapImageFileTypePNG,
    NSColor,
    NSRectFill,
    NSView,
    NSWindow,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMakeRect  # noqa: E402

from claude_usage_bar.limits import LimitWindow, LimitsSnapshot, SOURCE_API  # noqa: E402
from claude_usage_bar.scanner import LogScanner, StateCache  # noqa: E402
from claude_usage_bar.store import UsageStore  # noqa: E402
from claude_usage_bar.ui.panel import UsagePanel, WIDTH  # noqa: E402


DEMO_PROJECTS = [
    ("acme-web", "claude-opus-5", 9),
    ("payments-api", "claude-opus-5", 6),
    ("docs-site", "claude-sonnet-5", 4),
    ("infra-scripts", "claude-haiku-4-5", 2),
]


class DemoLimits:
    """Fixed quota windows, so the screenshot never shows a real account."""

    def fetch(self) -> LimitsSnapshot:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        return LimitsSnapshot(
            five_hour=LimitWindow(37.0, now + timedelta(hours=1, minutes=48)),
            seven_day=LimitWindow(64.0, now + timedelta(days=3, hours=5)),
            source=SOURCE_API,
            fetched_at=now,
        )


def write_demo_logs(root: str) -> None:
    """Writes a fortnight of plausible-looking sessions under `root`."""
    import json
    import random
    from datetime import datetime, timedelta, timezone

    random.seed(7)
    now = datetime.now(timezone.utc)
    for project, model, weight in DEMO_PROJECTS:
        directory = os.path.join(root, "-Users-demo-" + project)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "session.jsonl"), "w", encoding="utf-8") as handle:
            for day in range(14):
                for index in range(weight * random.randint(2, 5)):
                    moment = now - timedelta(days=day, minutes=index * 7 + day)
                    handle.write(json.dumps({
                        "type": "assistant",
                        "timestamp": moment.isoformat().replace("+00:00", "Z"),
                        "requestId": "req_{}_{}_{}".format(project, day, index),
                        "sessionId": "session_{}_{}".format(project, day),
                        "cwd": "/Users/demo/code/" + project,
                        "message": {
                            "id": "msg_{}_{}_{}".format(project, day, index),
                            "model": model,
                            "usage": {
                                "input_tokens": random.randint(20, 400),
                                "output_tokens": random.randint(200, 1800),
                                "cache_read_input_tokens": random.randint(40_000, 260_000),
                                "cache_creation": {
                                    "ephemeral_5m_input_tokens": random.randint(0, 2_000),
                                    "ephemeral_1h_input_tokens": random.randint(0, 9_000),
                                },
                            },
                        },
                    }) + "\n")


class Backdrop(NSView):
    """Paints the menu's own background so the preview matches what the user sees."""

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        NSColor.windowBackgroundColor().set()
        NSRectFill(self.bounds())


def render(store: UsageStore, appearance_name: str, path: str) -> str:
    panel = UsagePanel.alloc().initWithStore_(store)
    panel.refresh()
    height = panel.frame().size.height

    backdrop = Backdrop.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, height))
    backdrop.setAppearance_(NSAppearance.appearanceNamed_(appearance_name))
    backdrop.addSubview_(panel)

    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, WIDTH, height), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
    )
    window.setAppearance_(NSAppearance.appearanceNamed_(appearance_name))
    window.setContentView_(backdrop)

    rect = backdrop.bounds()
    rep = backdrop.bitmapImageRepForCachingDisplayInRect_(rect)
    backdrop.cacheDisplayInRect_toBitmapImageRep_(rect, rep)
    rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(
        path, True
    )
    return "{} ({:.0f}x{:.0f})".format(path, WIDTH, height)


def main() -> None:
    arguments = [value for value in sys.argv[1:] if not value.startswith("--")]
    demo = "--demo" in sys.argv
    out_dir = arguments[0] if arguments else "/tmp"
    days = int(arguments[1]) if len(arguments) > 1 else 1

    NSApplication.sharedApplication()

    if demo:
        import tempfile

        root = tempfile.mkdtemp(prefix="usage-bar-demo-")
        write_demo_logs(root)
        cache = StateCache(path=os.path.join(root, "cache.json"))
        store = UsageStore(scanner=LogScanner(root=root), cache=cache, limits_provider=DemoLimits())
    else:
        store = UsageStore()

    store.set_range(days)
    store.refresh_once()

    for name, appearance in (("dark", NSAppearanceNameDarkAqua), ("light", NSAppearanceNameAqua)):
        print(render(store, appearance, os.path.join(out_dir, "panel-{}.png".format(name))))
    snapshot = store.snapshot
    print("limits={}  range={}d  cost=${:.2f}".format(
        snapshot.limits.source, days, snapshot.summary.cost))


if __name__ == "__main__":
    main()
