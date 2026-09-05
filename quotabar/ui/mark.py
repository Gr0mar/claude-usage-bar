"""QuotaBar's own mark: a gauge arc that fills as a quota is consumed.

Deliberately not Anthropic's spark. Their trademark guidelines allow a plain-text
statement that a tool works with Claude Code, but not their logo as another product's
identity - so the mark is a meter, which is what the app actually is.

One drawing serves the menu bar (as a template image), the dropdown header and the app
icon.
"""

from __future__ import annotations

import math

from AppKit import NSBezierPath, NSColor, NSImage, NSLineCapStyleRound
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize

#: Warm amber - a meter colour, not Claude's coral.
BRAND_RED = 0xE8 / 255.0
BRAND_GREEN = 0x8C / 255.0
BRAND_BLUE = 0x3F / 255.0

#: Where the gauge starts and ends, in AppKit degrees (0 is east, counterclockwise).
#: Bottom-left round to bottom-right, the way a dial reads.
START_DEGREES = 210.0
END_DEGREES = -30.0
#: Ring thickness and needle radius, as fractions of the mark's radius.
TRACK_RATIO = 0.2
DOT_RATIO = 0.15
#: How full the gauge is drawn when nothing says otherwise.
DEFAULT_FILL = 0.66
#: How faint the unfilled part of the ring is.
TRACK_ALPHA = 0.3


def brand_color() -> NSColor:
    return NSColor.colorWithSRGBRed_green_blue_alpha_(BRAND_RED, BRAND_GREEN, BRAND_BLUE, 1.0)


def _stroke_arc(center_x: float, center_y: float, ring: float, width: float,
                start: float, end: float) -> None:
    path = NSBezierPath.bezierPath()
    path.setLineWidth_(width)
    path.setLineCapStyle_(NSLineCapStyleRound)
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        NSMakePoint(center_x, center_y), ring, start, end, True
    )
    path.stroke()


def draw_mark(center_x: float, center_y: float, radius: float, color: NSColor,
              fill: float = DEFAULT_FILL) -> None:
    """Draws the gauge: a faint full ring, the filled part in `color`, and a needle."""
    width = radius * TRACK_RATIO
    ring = radius - width / 2

    filled_to = START_DEGREES + (END_DEGREES - START_DEGREES) * min(max(fill, 0.0), 1.0)

    color.colorWithAlphaComponent_(TRACK_ALPHA).set()
    _stroke_arc(center_x, center_y, ring, width, START_DEGREES, END_DEGREES)

    color.set()
    _stroke_arc(center_x, center_y, ring, width, START_DEGREES, filled_to)

    angle = math.radians(filled_to)
    dot = radius * DOT_RATIO
    NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(
            center_x + math.cos(angle) * ring - dot,
            center_y + math.sin(angle) * ring - dot,
            dot * 2,
            dot * 2,
        )
    ).fill()


def menu_bar_image(side: float = 15.0, colored: bool = False) -> NSImage:
    """The menu bar icon: a template image by default, so macOS tints it."""
    image = NSImage.alloc().initWithSize_(NSMakeSize(side, side))
    image.lockFocus()
    draw_mark(side / 2, side / 2, side / 2 - 0.5,
              brand_color() if colored else NSColor.blackColor())
    image.unlockFocus()
    image.setTemplate_(not colored)
    return image
