"""The Claude sunburst, drawn as a template image for the menu bar.

Eleven equal rays, each tapering from a wide base to a rounded tip, meeting at the
centre - the shape of Anthropic's Claude mark.
"""

from __future__ import annotations

import math

from AppKit import NSBezierPath, NSColor, NSImage
from Foundation import NSMakePoint, NSMakeSize

#: Claude's coral. Used wherever the mark is drawn in colour.
BRAND_RED = 0xD9 / 255.0
BRAND_GREEN = 0x77 / 255.0
BRAND_BLUE = 0x57 / 255.0


def brand_color() -> NSColor:
    return NSColor.colorWithSRGBRed_green_blue_alpha_(BRAND_RED, BRAND_GREEN, BRAND_BLUE, 1.0)

RAY_COUNT = 11
#: Ray width at the centre and at the tip, as fractions of the radius.
BASE_RATIO = 0.12
TIP_RATIO = 0.07


def draw_spark(center_x: float, center_y: float, radius: float) -> None:
    """Fills the mark with the colour that is already set."""
    base_width = radius * BASE_RATIO
    tip_width = radius * TIP_RATIO

    for index in range(RAY_COUNT):
        angle = (index / RAY_COUNT) * 2 * math.pi - math.pi / 2
        along_x, along_y = math.cos(angle), math.sin(angle)
        across_x, across_y = -along_y, along_x

        tip_x = center_x + along_x * (radius - tip_width)
        tip_y = center_y + along_y * (radius - tip_width)

        path = NSBezierPath.bezierPath()
        path.moveToPoint_(
            NSMakePoint(center_x + across_x * base_width, center_y + across_y * base_width)
        )
        path.lineToPoint_(
            NSMakePoint(tip_x + across_x * tip_width, tip_y + across_y * tip_width)
        )
        path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            NSMakePoint(tip_x, tip_y),
            tip_width,
            math.degrees(math.atan2(across_y, across_x)),
            math.degrees(math.atan2(-across_y, -across_x)),
            True,
        )
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
