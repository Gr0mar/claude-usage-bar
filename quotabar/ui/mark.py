"""QuotaBar's own mark: a gauge arc that fills as a quota is consumed.

Deliberately not Anthropic's spark. Their trademark guidelines allow a plain-text
statement that a tool works with Claude Code, but not their logo as another product's
identity - so the mark is a meter, which is what the app actually is.

One drawing serves the menu bar (as a template image), the dropdown header and the app
icon.
"""

from __future__ import annotations

import math

from AppKit import (
    NSAffineTransform,
    NSBezierPath,
    NSColor,
    NSGraphicsContext,
    NSImage,
    NSLineCapStyleRound,
)
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
#: The square the mark is drawn in wherever it appears beside text.
MARK_SIDE = 15.0


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


def _geometry(radius: float) -> tuple:
    """Ring radius and pen sizes that keep the whole mark - needle included - inside
    `radius`, so the silhouette is identical at every size it is drawn at."""
    width = radius * TRACK_RATIO
    dot = radius * DOT_RATIO
    return width, dot, radius - max(width / 2, dot)


def draw_mark(center_x: float, center_y: float, radius: float, color: NSColor,
              fill: float = DEFAULT_FILL) -> None:
    """Draws the gauge: a faint full ring, the filled part in `color`, and a needle.

    The dial reads the same way whatever it is drawn into. A flipped context - the
    dropdown view is one - would otherwise mirror the arc, so the header mark and the
    menu bar mark would open in opposite directions.
    """
    context = NSGraphicsContext.currentContext()
    flipped = bool(context is not None and context.isFlipped())
    if flipped:
        NSGraphicsContext.saveGraphicsState()
        mirror = NSAffineTransform.transform()
        mirror.translateXBy_yBy_(0.0, 2 * center_y)
        mirror.scaleXBy_yBy_(1.0, -1.0)
        mirror.concat()

    width, dot, ring = _geometry(radius)

    filled_to = START_DEGREES + (END_DEGREES - START_DEGREES) * min(max(fill, 0.0), 1.0)

    color.colorWithAlphaComponent_(TRACK_ALPHA).set()
    _stroke_arc(center_x, center_y, ring, width, START_DEGREES, END_DEGREES)

    color.set()
    _stroke_arc(center_x, center_y, ring, width, START_DEGREES, filled_to)

    angle = math.radians(filled_to)
    NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(
            center_x + math.cos(angle) * ring - dot,
            center_y + math.sin(angle) * ring - dot,
            dot * 2,
            dot * 2,
        )
    ).fill()

    if flipped:
        NSGraphicsContext.restoreGraphicsState()


def draw_mark_in_box(x: float, y: float, side: float, color: NSColor,
                     fill: float = DEFAULT_FILL) -> None:
    """Draws the mark to fill a square box whose lower-left corner is (x, y)."""
    draw_mark(x + side / 2, y + side / 2, side / 2, color, fill)


def menu_bar_image(side: float = MARK_SIDE, colored: bool = False) -> NSImage:
    """The menu bar icon: a template image by default, so macOS tints it.

    Drawn through a handler rather than into a fixed bitmap, so AppKit rasterises it at
    the display's scale - on a Retina screen the arc is as crisp as the one the dropdown
    draws, instead of a 15-point bitmap stretched to double size.
    """
    def render(rect) -> bool:
        draw_mark_in_box(0, 0, side, brand_color() if colored else NSColor.blackColor())
        return True

    image = NSImage.imageWithSize_flipped_drawingHandler_(
        NSMakeSize(side, side), False, render
    )
    image.setTemplate_(not colored)
    return image
