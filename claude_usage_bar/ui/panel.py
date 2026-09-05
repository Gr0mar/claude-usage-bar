"""The dropdown: one custom view that draws the whole report.

`_layout` lays the report out top to bottom and returns its height; with `draw=False`
it skips the painting and only measures, which is how the view sizes itself for the
menu. Both passes read the same immutable store snapshot, taken once per call, so the
measured height always matches what gets painted.
"""

from __future__ import annotations

from typing import List, Optional

import objc

from AppKit import (
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontWeightMedium,
    NSFontWeightRegular,
    NSFontWeightSemibold,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMutableParagraphStyle,
    NSParagraphStyleAttributeName,
    NSSegmentedControl,
    NSSegmentStyleRounded,
    NSTextAlignmentRight,
    NSView,
)
from Foundation import NSAttributedString, NSMakePoint, NSMakeRect, NSMakeSize

from .. import formatting as fmt
from .. import pricing
from ..limits import SOURCE_API, SOURCE_STATUSLINE
from ..store import RANGES, SPARKLINE_DAYS, Snapshot, UsageStore
from .mark import brand_color, draw_spark

WIDTH = 340.0
PADDING = 12.0
CONTENT = WIDTH - 2 * PADDING

#: Vertical rhythm.
LINE = 16.0
ROW_HEIGHT = 19.0
SECTION_GAP = 11.0
BAR_HEIGHT = 5.0
SPARK_HEIGHT = 26.0

#: Type scale.
TITLE = 12.0
HERO = 25.0
LABEL = 11.0
VALUE = 11.5
CAPTION = 10.0
MICRO = 9.5

#: The column where the tokens/savings block sits beside the hero number.
VALUE_COLUMN = 96.0
MAX_ROWS = 5

#: Button copy for the ranges the store offers, in the same order.
RANGE_LABELS = {1: "Today", 7: "7 days", 30: "30 days"}


def _attributes(size: float, weight, color, align_right: bool = False) -> dict:
    attributes = {
        NSFontAttributeName: NSFont.systemFontOfSize_weight_(size, weight),
        NSForegroundColorAttributeName: color,
    }
    if align_right:
        style = NSMutableParagraphStyle.alloc().init()
        style.setAlignment_(NSTextAlignmentRight)
        attributes[NSParagraphStyleAttributeName] = style
    return attributes


class UsagePanel(NSView):
    """A menu item view that renders the whole usage report."""

    def initWithStore_(self, store: UsageStore):
        self = objc.super(UsagePanel, self).initWithFrame_(NSMakeRect(0, 0, WIDTH, 100))
        if self is None:
            return None
        self._store = store
        self._segments = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(PADDING, 0, CONTENT, 22)
        )
        self._segments.setSegmentCount_(len(RANGES))
        self._segments.setSegmentStyle_(NSSegmentStyleRounded)
        for index, days in enumerate(RANGES):
            self._segments.setLabel_forSegment_(RANGE_LABELS.get(days, "{}d".format(days)), index)
        self._segments.setSelectedSegment_(0)
        self._segments.setTarget_(self)
        self._segments.setAction_("rangeChanged:")
        self.addSubview_(self._segments)
        self.refresh()
        return self

    # -- AppKit plumbing ---------------------------------------------------

    def isFlipped(self) -> bool:
        return True

    def rangeChanged_(self, sender) -> None:
        self._store.set_range(RANGES[sender.selectedSegment()])
        self.refresh()

    def refresh(self) -> None:
        """Re-measures against the current snapshot and repaints."""
        snapshot = self._store.snapshot
        for index, days in enumerate(RANGES):
            if days == snapshot.range_days:
                self._segments.setSelectedSegment_(index)
        height = self._layout(snapshot, draw=False)
        if abs(self.frame().size.height - height) > 0.5:
            self.setFrameSize_(NSMakeSize(WIDTH, height))
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect) -> None:
        self._layout(self._store.snapshot, draw=True)

    # -- drawing primitives ------------------------------------------------

    @objc.python_method
    def _text(self, text: str, x: float, y: float, size: float, weight, color,
              draw: bool = True, width: Optional[float] = None, align_right: bool = False) -> None:
        if not draw:
            return
        attributed = NSAttributedString.alloc().initWithString_attributes_(
            text, _attributes(size, weight, color, align_right)
        )
        # Always draw into a rect: drawAtPoint_ silently no-ops through PyObjC.
        box = width if width is not None else WIDTH - PADDING - x
        attributed.drawInRect_(NSMakeRect(x, y, box, attributed.size().height))

    @staticmethod
    def _rounded(x: float, y: float, width: float, height: float, radius: float, color) -> None:
        color.set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(x, y, max(width, 0), height), radius, radius
        ).fill()

    @objc.python_method
    def _divider(self, y: float, draw: bool) -> float:
        if draw:
            self._rounded(PADDING, y, CONTENT, 1, 0.5, NSColor.separatorColor())
        return y + SECTION_GAP

    # -- sections ----------------------------------------------------------

    @objc.python_method
    def _layout(self, snapshot: Snapshot, draw: bool) -> float:
        y = PADDING

        y = self._header(snapshot, y, draw)
        y = self._divider(y, draw)
        if snapshot.live_session is not None:
            y = self._live(snapshot, y, draw)
            y = self._divider(y, draw)
        y = self._totals(snapshot, y, draw)
        if snapshot.summary.by_project:
            y = self._divider(y, draw)
            y = self._breakdown(y, draw, "Top projects", snapshot.summary.by_project,
                                brand_color())
        if snapshot.summary.by_model:
            y = self._divider(y, draw)
            y = self._breakdown(y, draw, "Models", snapshot.summary.by_model,
                                NSColor.systemPurpleColor(), models=True)
        y = self._footer(snapshot, y + 4, draw)
        return y + PADDING - 4

    @objc.python_method
    def _header(self, snapshot: Snapshot, y: float, draw: bool) -> float:
        if draw:
            brand_color().set()
            draw_spark(PADDING + 7, y + 7, 7)
        self._text("Claude usage", PADDING + 18, y - 1, TITLE, NSFontWeightSemibold,
                   NSColor.labelColor(), draw)
        self._text(self._source_label(snapshot), PADDING, y, CAPTION, NSFontWeightRegular,
                   NSColor.tertiaryLabelColor(), draw, align_right=True)
        y += 20

        limits = snapshot.limits
        if limits.has_data:
            y = self._limit_bar(y, draw, "Session (5h)", limits.five_hour,
                                exhausted_at=snapshot.five_hour_eta)
            y = self._limit_bar(y, draw, "Weekly", limits.seven_day)
            return y

        self._text("Last 5h locally", PADDING, y, LABEL, NSFontWeightMedium,
                   NSColor.labelColor(), draw)
        self._text(fmt.tokens(snapshot.local_five_hour.total) + " tokens", PADDING, y, LABEL,
                   NSFontWeightRegular, NSColor.labelColor(), draw, align_right=True)
        y += LINE
        self._text("Quota percentages unavailable - showing the local token count.",
                   PADDING, y, CAPTION, NSFontWeightRegular,
                   NSColor.tertiaryLabelColor(), draw)
        return y + 15

    @objc.python_method
    def _source_label(self, snapshot: Snapshot) -> str:
        """Says where the quota reading came from, and how old it is once it is stale -
        a rate-limited endpoint can otherwise leave a half-hour-old number reading as
        current."""
        limits = snapshot.limits
        stale = snapshot.limits_are_stale()
        if limits.source == SOURCE_API:
            return "live · " + fmt.time_of_day(limits.fetched_at) if stale and limits.fetched_at else "live"
        if limits.source == SOURCE_STATUSLINE and limits.fetched_at:
            return "statusline · " + fmt.time_of_day(limits.fetched_at)
        return "local"

    @objc.python_method
    def _limit_bar(self, y: float, draw: bool, title: str, window, exhausted_at=None) -> float:
        self._text(title, PADDING, y, LABEL, NSFontWeightMedium, NSColor.labelColor(), draw)
        if window is None:
            self._text("n/a", PADDING, y, LABEL, NSFontWeightRegular,
                       NSColor.secondaryLabelColor(), draw, align_right=True)
            return y + 18

        used = window.used_percent
        tint = (
            NSColor.systemGreenColor() if used < 60
            else NSColor.systemOrangeColor() if used < 85
            else NSColor.systemRedColor()
        )
        self._text(fmt.percent(used), PADDING, y, LABEL, NSFontWeightSemibold,
                   NSColor.labelColor(), draw, align_right=True)
        y += LINE
        if draw:
            self._rounded(PADDING, y, CONTENT, BAR_HEIGHT, 2.5, NSColor.quaternaryLabelColor())
            self._rounded(PADDING, y, CONTENT * used / 100.0, BAR_HEIGHT, 2.5, tint)
        y += 8

        countdown = fmt.countdown(window.resets_at)
        if countdown:
            self._text(countdown, PADDING, y, CAPTION, NSFontWeightRegular,
                       NSColor.tertiaryLabelColor(), draw)
        if exhausted_at is not None:
            # Only shown when the measured burn rate would empty the window first.
            self._text("full around " + fmt.time_of_day(exhausted_at), PADDING, y, CAPTION,
                       NSFontWeightRegular, tint, draw, align_right=True)
        if countdown or exhausted_at is not None:
            y += 14
        return y + 2

    @objc.python_method
    def _live(self, snapshot: Snapshot, y: float, draw: bool) -> float:
        session = snapshot.live_session
        self._text("RUNNING NOW", PADDING, y, CAPTION, NSFontWeightSemibold,
                   NSColor.secondaryLabelColor(), draw)
        self._text(fmt.elapsed(session.duration), PADDING, y, CAPTION,
                   NSFontWeightRegular, NSColor.tertiaryLabelColor(), draw, align_right=True)
        y += LINE

        self._text(session.project, PADDING, y, TITLE, NSFontWeightMedium,
                   NSColor.labelColor(), draw, width=CONTENT - 70)
        self._text(fmt.money(session.cost), PADDING, y, TITLE, NSFontWeightSemibold,
                   NSColor.labelColor(), draw, align_right=True)
        y += 17

        detail = "{} · {} tokens".format(
            pricing.display_name(session.model), fmt.tokens(session.tokens.total)
        )
        self._text(detail, PADDING, y, 10.5, NSFontWeightRegular,
                   NSColor.secondaryLabelColor(), draw)
        self._text(fmt.money(snapshot.burn_rate) + "/h burn", PADDING, y, 10.5,
                   NSFontWeightRegular, NSColor.secondaryLabelColor(), draw, align_right=True)
        return y + LINE

    @objc.python_method
    def _totals(self, snapshot: Snapshot, y: float, draw: bool) -> float:
        summary = snapshot.summary
        self._segments.setFrameOrigin_(NSMakePoint(PADDING, y))
        y += 30

        self._text(fmt.money(summary.cost), PADDING, y, HERO, NSFontWeightSemibold,
                   NSColor.labelColor(), draw)
        self._text(fmt.tokens(summary.tokens.total) + " tokens", PADDING + VALUE_COLUMN, y + 1,
                   LABEL, NSFontWeightRegular, NSColor.labelColor(), draw)
        self._text(fmt.money(summary.cache_savings) + " saved by cache",
                   PADDING + VALUE_COLUMN, y + 15, CAPTION, NSFontWeightRegular,
                   NSColor.secondaryLabelColor(), draw)
        # The subscription is a flat fee: this is what the same usage would cost on the API.
        self._text("at API list prices, not your bill", PADDING + VALUE_COLUMN, y + 28, MICRO,
                   NSFontWeightRegular, NSColor.tertiaryLabelColor(), draw)
        y += 44

        self._sparkline(y, draw, snapshot.sparkline)
        y += 30
        self._text("Daily list price, last {} days".format(SPARKLINE_DAYS), PADDING, y, MICRO,
                   NSFontWeightRegular, NSColor.tertiaryLabelColor(), draw)
        return y + 14

    @objc.python_method
    def _sparkline(self, y: float, draw: bool, values: List[float]) -> None:
        if not draw or not values:
            return
        spacing = 2.0
        width = max((CONTENT - spacing * (len(values) - 1)) / len(values), 1.0)
        peak = max(max(values), 0.0001)
        accent = brand_color()
        faded = accent.colorWithAlphaComponent_(0.45)
        for index, value in enumerate(values):
            bar = max(SPARK_HEIGHT * value / peak, 1.5)
            self._rounded(
                PADDING + index * (width + spacing),
                y + SPARK_HEIGHT - bar,
                width,
                bar,
                1.5,
                accent if index == len(values) - 1 else faded,
            )

    @objc.python_method
    def _breakdown(self, y: float, draw: bool, title: str, slices, tint,
                   models: bool = False) -> float:
        self._text(title.upper(), PADDING, y, CAPTION, NSFontWeightSemibold,
                   NSColor.secondaryLabelColor(), draw)
        y += LINE

        rows = slices[:MAX_ROWS]
        peak = max((item.cost for item in rows), default=0.0)
        for item in rows:
            share = (item.cost / peak) if peak > 0 else 0.0
            if draw:
                self._rounded(PADDING, y, CONTENT * min(max(share, 0.0), 1.0), ROW_HEIGHT - 3,
                              3, tint.colorWithAlphaComponent_(0.14))
            name = pricing.display_name(item.name) if models else item.name
            detail = "no price" if item.unpriced else fmt.tokens(item.tokens.total)
            value = "—" if item.unpriced else fmt.money(item.cost)

            self._text(name, PADDING + 5, y + 1, VALUE, NSFontWeightRegular,
                       NSColor.labelColor(), draw, width=CONTENT - 120)
            self._text(detail, PADDING + 5, y + 2, CAPTION, NSFontWeightRegular,
                       NSColor.tertiaryLabelColor(), draw, width=CONTENT - 62, align_right=True)
            self._text(value, PADDING, y + 1, VALUE, NSFontWeightMedium,
                       NSColor.labelColor(), draw, align_right=True)
            y += ROW_HEIGHT
        return y + 2

    @objc.python_method
    def _footer(self, snapshot: Snapshot, y: float, draw: bool) -> float:
        if snapshot.error:
            self._text("Scan error: " + snapshot.error, PADDING, y, MICRO,
                       NSFontWeightRegular, NSColor.systemRedColor(), draw)
            return y + 13
        if snapshot.scanning:
            status = "Scanning logs…"
        elif snapshot.updated_at is not None:
            status = "Updated " + fmt.time_of_day(snapshot.updated_at)
        else:
            return y
        self._text(status, PADDING, y, MICRO, NSFontWeightRegular,
                   NSColor.tertiaryLabelColor(), draw)
        return y + 13
