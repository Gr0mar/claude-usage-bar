"""Renders the README animation: the dropdown, with the range switching under it.

    .venv/bin/python scripts/make-gif.py docs/dropdown.gif

Everything shown is synthetic (the same demo data as `preview.py --demo`), so the
animation never carries real project names or spend. Needs Pillow, which is a
development dependency only - the app itself does not use it.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AppKit import (  # noqa: E402
    NSAppearance,
    NSAppearanceNameDarkAqua,
    NSApplication,
    NSBitmapImageFileTypePNG,
)
from Foundation import NSMakeRect  # noqa: E402
from PIL import Image  # noqa: E402

from claude_usage_bar.scanner import LogScanner, StateCache  # noqa: E402
from claude_usage_bar.store import Snapshot, UsageStore  # noqa: E402
from claude_usage_bar.ui.panel import UsagePanel, WIDTH  # noqa: E402

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "preview", os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview.py")
)
preview = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preview)

#: (range in days, seconds to hold, show a projection)
STORYBOARD = [
    (1, 1.6, False),
    (7, 1.6, False),
    (30, 1.6, False),
    (1, 2.2, True),
]
SCALE = 2


def frame(store: UsageStore) -> Image.Image:
    panel = UsagePanel.alloc().initWithStore_(store)
    panel.refresh()
    height = panel.frame().size.height

    backdrop = preview.Backdrop.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, height))
    backdrop.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
    backdrop.addSubview_(panel)

    rect = backdrop.bounds()
    rep = backdrop.bitmapImageRepForCachingDisplayInRect_(rect)
    backdrop.cacheDisplayInRect_toBitmapImageRep_(rect, rep)
    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    return Image.open(io.BytesIO(bytes(data))).convert("RGB")


def main() -> None:
    output = sys.argv[1] if len(sys.argv) > 1 else "docs/dropdown.gif"
    NSApplication.sharedApplication()

    root = tempfile.mkdtemp(prefix="usage-bar-gif-")
    preview.write_demo_logs(root)
    store = UsageStore(
        scanner=LogScanner(root=root),
        cache=StateCache(path=os.path.join(root, "cache.json")),
        limits_provider=preview.DemoLimits(),
    )
    store.refresh_once()

    frames, durations = [], []
    for days, hold, projecting in STORYBOARD:
        store.set_range(days)
        if projecting:
            eta = datetime.now(timezone.utc) + timedelta(hours=1, minutes=52)
            store.snapshot = Snapshot(**{**store.snapshot.__dict__, "five_hour_eta": eta})
        frames.append(frame(store))
        durations.append(int(hold * 1000))

    # Every frame is the same size; the tallest one sets the canvas.
    width = max(image.width for image in frames)
    height = max(image.height for image in frames)
    canvas = [
        image if image.size == (width, height) else _pad(image, width, height)
        for image in frames
    ]
    canvas[0].save(
        output,
        save_all=True,
        append_images=canvas[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print("wrote {} ({} frames, {:.0f} KB)".format(output, len(canvas), os.path.getsize(output) / 1024))


def _pad(image: Image.Image, width: int, height: int) -> Image.Image:
    padded = Image.new("RGB", (width, height), image.getpixel((1, 1)))
    padded.paste(image, (0, 0))
    return padded


if __name__ == "__main__":
    main()
