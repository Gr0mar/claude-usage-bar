"""The Claude sunburst, drawn as a template image for the menu bar.

Eleven equal rays, each tapering from a wide base to a rounded tip, meeting at the
centre - the shape of Anthropic's Claude mark.
"""

from __future__ import annotations

import math

from AppKit import NSBezierPath, NSColor, NSImage, NSWindingRuleNonZero
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize

#: Claude's coral. Used wherever the mark is drawn in colour.
BRAND_RED = 0xD9 / 255.0
BRAND_GREEN = 0x77 / 255.0
BRAND_BLUE = 0x57 / 255.0


def brand_color() -> NSColor:
    return NSColor.colorWithSRGBRed_green_blue_alpha_(BRAND_RED, BRAND_GREEN, BRAND_BLUE, 1.0)

#: Relative ray lengths, going clockwise from twelve o'clock. The uneven rhythm is
#: what makes the mark read as a spark rather than a snowflake.
RAY_LENGTHS = (1.0, 0.78, 0.95, 0.72, 1.0, 0.80, 0.92, 0.70, 0.97, 0.75, 0.88)
RAY_COUNT = len(RAY_LENGTHS)
#: Ray half-width at the centre and at the tip, as fractions of the radius. The tips are
#: cut flat rather than rounded, which is what gives the mark its faceted look.
BASE_RATIO = 0.12
TIP_RATIO = 0.095
#: The solid core the rays grow out of.
CORE_RATIO = 0.145


def draw_spark(center_x: float, center_y: float, radius: float) -> None:
    """Fills the mark with the colour that is already set.

    Every ray goes into one path filled once with the non-zero rule: filled separately,
    their overlaps at the centre leave anti-aliasing seams that read as creases.
    """
    path = NSBezierPath.bezierPath()
    path.setWindingRule_(NSWindingRuleNonZero)

    core = radius * CORE_RATIO
    path.appendBezierPathWithOvalInRect_(
        NSMakeRect(center_x - core, center_y - core, core * 2, core * 2)
    )

    base_width = radius * BASE_RATIO
    tip_width = radius * TIP_RATIO

    for index, length in enumerate(RAY_LENGTHS):
        angle = (index / RAY_COUNT) * 2 * math.pi + math.pi / 2
        along_x, along_y = math.cos(angle), math.sin(angle)
        across_x, across_y = -along_y, along_x

        tip_x = center_x + along_x * radius * length
        tip_y = center_y + along_y * radius * length

        # A quadrilateral: wide at the core, narrower at the tip, cut off square.
        path.moveToPoint_(
            NSMakePoint(center_x + across_x * base_width, center_y + across_y * base_width)
        )
        path.lineToPoint_(NSMakePoint(tip_x + across_x * tip_width, tip_y + across_y * tip_width))
        path.lineToPoint_(NSMakePoint(tip_x - across_x * tip_width, tip_y - across_y * tip_width))
        path.lineToPoint_(
            NSMakePoint(center_x - across_x * base_width, center_y - across_y * base_width)
        )
        path.closePath()

    path.fill()


def menu_bar_image(side: float = 15.0, colored: bool = False) -> NSImage:
    """The menu bar icon.

    A template image by default, so macOS tints it for the light and dark menu bar and
    for whatever is behind it. `colored` opts into Claude's coral instead, which stays
    the same in both appearances.
    """
    image = NSImage.alloc().initWithSize_(NSMakeSize(side, side))
    image.lockFocus()
    (brand_color() if colored else NSColor.blackColor()).set()
    draw_spark(side / 2, side / 2, side / 2)
    image.unlockFocus()
    image.setTemplate_(not colored)
    return image
