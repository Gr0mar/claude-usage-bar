"""The Claude mark, drawn from Anthropic's own artwork.

`assets/claude-mark.svg` is the official logo path (24x24 viewBox). It is parsed once
into an NSBezierPath and reused: the menu bar icon, the dropdown header and the app
icon all draw the same shape, so nothing here approximates it by hand.

The mark is Anthropic's trademark; this project is not affiliated with them and uses it
to identify what the app reports on.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from AppKit import NSAffineTransform, NSBezierPath, NSColor, NSImage, NSWindingRuleNonZero
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize

#: Claude's coral. Used wherever the mark is drawn in colour.
BRAND_RED = 0xD9 / 255.0
BRAND_GREEN = 0x77 / 255.0
BRAND_BLUE = 0x57 / 255.0

SVG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "claude-mark.svg")
#: The viewBox the artwork is drawn in.
VIEWBOX = 24.0

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_cached_path: Optional[NSBezierPath] = None


def brand_color() -> NSColor:
    return NSColor.colorWithSRGBRed_green_blue_alpha_(BRAND_RED, BRAND_GREEN, BRAND_BLUE, 1.0)


def _read_path_data() -> str:
    with open(SVG_PATH, "r", encoding="utf-8") as handle:
        svg = handle.read()
    match = re.search(r'\sd="([^"]+)"', svg)
    if match is None:
        raise ValueError("no path data in {}".format(SVG_PATH))
    return match.group(1)


def _build_path(data: str) -> NSBezierPath:
    """Turns SVG path data into a bezier path in the SVG's own coordinates.

    Only the commands the artwork uses are supported (plus the smooth and quadratic
    forms, which cost little); an unknown command raises rather than drawing something
    subtly wrong.
    """
    path = NSBezierPath.bezierPath()
    path.setWindingRule_(NSWindingRuleNonZero)

    tokens: List[str] = _TOKEN.findall(data)
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    previous_control = None

    def number() -> float:
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in "Zz":
                path.closePath()
                current = start
                continue
        relative = command.islower()
        upper = command.upper()

        if upper == "M":
            x, y = number(), number()
            current = (current[0] + x, current[1] + y) if relative else (x, y)
            path.moveToPoint_(NSMakePoint(*current))
            start = current
            # A second coordinate pair after a moveto is an implicit lineto.
            command = "l" if relative else "L"
        elif upper == "L":
            x, y = number(), number()
            current = (current[0] + x, current[1] + y) if relative else (x, y)
            path.lineToPoint_(NSMakePoint(*current))
        elif upper == "H":
            x = number()
            current = (current[0] + x if relative else x, current[1])
            path.lineToPoint_(NSMakePoint(*current))
        elif upper == "V":
            y = number()
            current = (current[0], current[1] + y if relative else y)
            path.lineToPoint_(NSMakePoint(*current))
        elif upper in ("C", "S", "Q", "T"):
            if upper == "C":
                points = [(number(), number()) for _ in range(3)]
            elif upper == "S":
                points = [(number(), number()) for _ in range(2)]
            elif upper == "Q":
                points = [(number(), number()) for _ in range(2)]
            else:
                points = [(number(), number())]
            if relative:
                points = [(current[0] + x, current[1] + y) for x, y in points]

            if upper == "C":
                control1, control2, end = points
            elif upper == "S":
                reflected = previous_control or current
                control1 = (2 * current[0] - reflected[0], 2 * current[1] - reflected[1])
                control2, end = points
            else:
                if upper == "Q":
                    quadratic, end = points
                else:
                    reflected = previous_control or current
                    quadratic = (2 * current[0] - reflected[0], 2 * current[1] - reflected[1])
                    end = points[0]
                control1 = (current[0] + 2.0 / 3 * (quadratic[0] - current[0]),
                            current[1] + 2.0 / 3 * (quadratic[1] - current[1]))
                control2 = (end[0] + 2.0 / 3 * (quadratic[0] - end[0]),
                            end[1] + 2.0 / 3 * (quadratic[1] - end[1]))

            path.curveToPoint_controlPoint1_controlPoint2_(
                NSMakePoint(*end), NSMakePoint(*control1), NSMakePoint(*control2)
            )
            previous_control = control2
            current = end
            continue
        else:
            raise ValueError("unsupported SVG command: {}".format(command))

        previous_control = None

    return path


def mark_path() -> NSBezierPath:
    """The mark in its 24x24 viewBox, y growing downward as SVG defines it."""
    global _cached_path
    if _cached_path is None:
        _cached_path = _build_path(_read_path_data())
    return _cached_path


def draw_spark(center_x: float, center_y: float, radius: float) -> None:
    """Fills the mark centred on the given point, with the colour already set."""
    scale = (radius * 2) / VIEWBOX
    transform = NSAffineTransform.transform()
    transform.translateXBy_yBy_(center_x - radius, center_y + radius)
    # SVG's y axis points down; AppKit's points up.
    transform.scaleXBy_yBy_(scale, -scale)

    shape = transform.transformBezierPath_(mark_path())
    shape.setWindingRule_(NSWindingRuleNonZero)
    shape.fill()


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
