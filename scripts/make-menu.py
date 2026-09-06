"""Renders the README's picture of the menu: what the item offers when you open it.

    .venv/bin/python scripts/make-menu.py docs/menu.png

A menu cannot be screenshotted without a hand on the mouse, so this draws it - from the
titles the app itself builds the menu out of, so renaming an item cannot leave a stale
picture behind. Drawn at 2x, like the menu bar strip beside it in the README.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AppKit import (  # noqa: E402
    NSApplication,
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGraphicsContext,
)
from Foundation import NSAttributedString, NSMakePoint, NSMakeRect  # noqa: E402

from quotabar.ui.controller import (  # noqa: E402
    ACTIONS,
    COLORED_ICON_TITLE,
    LOGIN_TITLE,
    METRIC_MENU_TITLE,
    METRICS,
    NOTIFY_TITLE,
    QUIT_TITLE,
)

SCALE = 2
FONT_SIZE = 13.5
ROW = 22.0
#: A separator row is shorter than an item row.
RULE = 11.0
#: Text starts past the column the checkmarks sit in.
CHECK_COLUMN = 10.0
TEXT_INSET = 25.0
TRAILING = 26.0
PADDING = 5.0
RADIUS = 8.0
#: How far the submenu overlaps its parent menu.
SUBMENU_OVERLAP = 6.0

SURFACE = (0.16, 0.16, 0.17, 1.0)
#: A hairline, so the dark panels keep an edge against a light README page.
BORDER = (1.0, 1.0, 1.0, 0.14)
HIGHLIGHT = (0.15, 0.39, 0.85, 1.0)
SEPARATOR = (1.0, 1.0, 1.0, 0.12)
TEXT = (1.0, 1.0, 1.0, 0.92)

#: Rows of the menu proper. `None` is a separator; the flags say which items are drawn
#: as chosen, which is the state a fresh install opens with.
SEPARATOR_ROW = None
ROWS = (
    (METRIC_MENU_TITLE, False, True),
    (ACTIONS[0][0], False, False),
    (ACTIONS[1][0], False, False),
    (NOTIFY_TITLE, True, False),
    (COLORED_ICON_TITLE, False, False),
    (LOGIN_TITLE, False, False),
    SEPARATOR_ROW,
    (QUIT_TITLE, False, False),
)
SUBMENU = tuple((title, index == 0, False) for index, (_, title) in enumerate(METRICS))


def _text(string: str, dimmed: bool = False) -> NSAttributedString:
    colour = NSColor.colorWithSRGBRed_green_blue_alpha_(*TEXT)
    return NSAttributedString.alloc().initWithString_attributes_(
        string,
        {
            NSFontAttributeName: NSFont.systemFontOfSize_(FONT_SIZE),
            NSForegroundColorAttributeName: colour.colorWithAlphaComponent_(
                0.55 if dimmed else TEXT[3]
            ),
        },
    )


def _size(rows) -> tuple:
    width = max(_text(title).size().width for title, _, _ in _items(rows))
    height = sum(ROW if row is not SEPARATOR_ROW else RULE for row in rows)
    return TEXT_INSET + width + TRAILING, height + 2 * PADDING


def _items(rows):
    return [row for row in rows if row is not SEPARATOR_ROW]


def _fill(rect, colour, radius: float = 0.0) -> None:
    NSColor.colorWithSRGBRed_green_blue_alpha_(*colour).set()
    if radius:
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius).fill()
    else:
        NSBezierPath.bezierPathWithRect_(rect).fill()


def _draw_menu(x: float, y: float, rows, highlighted: str = "") -> None:
    """Paints one menu panel with its lower-left corner at (x, y)."""
    width, height = _size(rows)
    panel = NSMakeRect(x, y, width, height)
    _fill(panel, SURFACE, RADIUS)
    NSColor.colorWithSRGBRed_green_blue_alpha_(*BORDER).set()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x + 0.5, y + 0.5, width - 1, height - 1), RADIUS, RADIUS
    ).stroke()

    top = y + height - PADDING
    for row in rows:
        if row is SEPARATOR_ROW:
            top -= RULE
            _fill(NSMakeRect(x + PADDING, top + RULE / 2, width - 2 * PADDING, 1), SEPARATOR)
            continue

        title, checked, submenu = row
        top -= ROW
        if title == highlighted:
            _fill(NSMakeRect(x + PADDING, top, width - 2 * PADDING, ROW), HIGHLIGHT, 4.0)

        label = _text(title)
        baseline = top + (ROW - label.size().height) / 2
        label.drawAtPoint_(NSMakePoint(x + TEXT_INSET, baseline))
        if checked:
            _text("✓").drawAtPoint_(NSMakePoint(x + CHECK_COLUMN, baseline))
        if submenu:
            arrow = _text("›")
            arrow.drawAtPoint_(NSMakePoint(x + width - TRAILING / 2 - arrow.size().width / 2,
                                           baseline))


def render() -> NSBitmapImageRep:
    menu_width, menu_height = _size(ROWS)
    sub_width, sub_height = _size(SUBMENU)
    width = menu_width + sub_width - SUBMENU_OVERLAP
    height = max(menu_height, sub_height)

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, int(round(width * SCALE)), int(round(height * SCALE)), 8, 4, True, False,
        "NSCalibratedRGBColorSpace", 0, 0
    )
    rep.setSize_((width, height))

    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)

    # No backdrop: the panels sit on whatever the page behind them is, as they do on a
    # desktop.
    _draw_menu(0, height - menu_height, ROWS, highlighted=METRIC_MENU_TITLE)
    # The submenu opens level with the row that owns it - the first one.
    _draw_menu(menu_width - SUBMENU_OVERLAP, height - sub_height, SUBMENU)

    NSGraphicsContext.restoreGraphicsState()
    return rep


def main() -> None:
    output = sys.argv[1] if len(sys.argv) > 1 else "docs/menu.png"
    NSApplication.sharedApplication()

    data = render().representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    data.writeToFile_atomically_(output, True)
    print("wrote {} ({} bytes)".format(output, os.path.getsize(output)))


if __name__ == "__main__":
    main()
