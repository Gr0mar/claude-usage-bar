"""Renders the README's menu bar strip: the item as it sits up there all day.

    .venv/bin/python scripts/make-menubar.py docs/menubar.png

The same item at three points of a session, so the README shows the dial filling as the
quota goes. The numbers are synthetic, like the dropdown animation's - neither image
shows a real account. Drawn at 2x and stored that way, so it stays sharp on a Retina
screen; the README scales it down.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AppKit import (  # noqa: E402
    NSApplication,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGradient,
    NSGraphicsContext,
)
from Foundation import NSAttributedString, NSMakePoint, NSMakeRect  # noqa: E402

from quotabar import formatting as fmt  # noqa: E402
from quotabar.limits import LimitWindow, LimitsSnapshot, SOURCE_API  # noqa: E402
from quotabar.ui.mark import MARK_SIDE, draw_mark_in_box  # noqa: E402

#: The strip's height in points, and the scale it is drawn at; the width follows the
#: label, so the image is the item and not a stretch of empty bar.
HEIGHT = 24.0
SCALE = 2

#: A desktop's worth of colour behind the bar, so the strip reads as the menu bar and
#: not as a button - the real one is translucent over whatever the wallpaper is.
TOP = (0.16, 0.17, 0.20)
BOTTOM = (0.10, 0.11, 0.13)

#: The system draws menu bar items with this much air around them.
INSET = 8.0
GAP = 4.0
#: Air between the three readings, so they read as one item at three moments of a
#: session rather than as three items in one menu bar.
SPACING = 14.0

#: Early, halfway, nearly out - one item drawn at three points of the same session, so
#: the README shows that the dial moves with the quota instead of decorating the label.
READINGS = (7.0, 37.0, 85.0)


def _quota(used_percent: float) -> LimitsSnapshot:
    return LimitsSnapshot(five_hour=LimitWindow(used_percent), source=SOURCE_API)


def _label(limits: LimitsSnapshot) -> NSAttributedString:
    return NSAttributedString.alloc().initWithString_attributes_(
        fmt.menu_bar_label("five_hour", limits, 0.0),
        {
            NSFontAttributeName: NSFont.menuBarFontOfSize_(0),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
        },
    )


def _draw_item(x: float, limits: LimitsSnapshot) -> float:
    """Paints one menu bar item at `x` and returns the width it took."""
    label = _label(limits)
    width = INSET * 2 + MARK_SIDE + GAP + label.size().width

    NSGradient.alloc().initWithStartingColor_endingColor_(
        NSColor.colorWithSRGBRed_green_blue_alpha_(*TOP, 1.0),
        NSColor.colorWithSRGBRed_green_blue_alpha_(*BOTTOM, 1.0),
    ).drawInRect_angle_(NSMakeRect(x, 0, width, HEIGHT), -90.0)

    # The menu bar tints template images white on a dark desktop, and the dial stands
    # at the same reading as the percentage beside it.
    draw_mark_in_box(x + INSET, (HEIGHT - MARK_SIDE) / 2, MARK_SIDE, NSColor.whiteColor(),
                     fmt.gauge_fill("five_hour", limits))

    label.drawAtPoint_(NSMakePoint(x + INSET + MARK_SIDE + GAP,
                                   (HEIGHT - label.size().height) / 2))
    return width


def render() -> NSBitmapImageRep:
    quotas = [_quota(used) for used in READINGS]
    widths = [INSET * 2 + MARK_SIDE + GAP + _label(limits).size().width for limits in quotas]
    total = sum(widths) + SPACING * (len(widths) - 1)

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, int(round(total * SCALE)), int(HEIGHT * SCALE), 8, 4, True, False,
        "NSCalibratedRGBColorSpace", 0, 0
    )
    rep.setSize_((total, HEIGHT))

    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)

    x = 0.0
    for limits in quotas:
        x += _draw_item(x, limits) + SPACING

    NSGraphicsContext.restoreGraphicsState()
    return rep


def main() -> None:
    output = sys.argv[1] if len(sys.argv) > 1 else "docs/menubar.png"
    NSApplication.sharedApplication()

    data = render().representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    data.writeToFile_atomically_(output, True)
    print("wrote {} ({} bytes)".format(output, os.path.getsize(output)))


if __name__ == "__main__":
    main()
