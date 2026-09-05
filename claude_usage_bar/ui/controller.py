"""The status item: its label, its menu, and the wiring to the store."""

from __future__ import annotations

from AppKit import (
    NSApplication,
    NSImageLeft,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSUserDefaults,
    NSVariableStatusItemLength,
)
import objc
from Foundation import NSObject
from PyObjCTools import AppHelper

from .. import formatting as fmt
from ..alerts import QuotaAlerts
from ..identity import BUNDLE_ID
from ..store import UsageStore
from . import login_item
from .mark import menu_bar_image
from .notifier import Notifier
from .panel import UsagePanel

METRIC_KEY = "menuBarMetric"
COLORED_ICON_KEY = "coloredMenuBarIcon"
NOTIFY_KEY = "notifyOnQuota"
#: Preferences live in an explicit suite: the interpreter, not the bundle, owns the
#: default domain, so the app would otherwise forget settings between launch methods.
DEFAULTS_SUITE = BUNDLE_ID
METRICS = [
    ("five_hour", "5h quota"),
    ("today", "Today's cost"),
    ("seven_day", "Weekly quota"),
    ("icon", "Icon only"),
]


def _defaults() -> NSUserDefaults:
    return NSUserDefaults.alloc().initWithSuiteName_(DEFAULTS_SUITE)


class StatusItemController(NSObject):
    def initWithStore_appPath_(self, store: UsageStore, app_path: str):
        self = objc.super(StatusItemController, self).init()
        if self is None:
            return None
        self._store = store
        self._app_path = app_path

        self._item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        button = self._item.button()
        button.setImage_(menu_bar_image(colored=self._colored_icon()))
        button.setImagePosition_(NSImageLeft)

        self._notifier = Notifier()
        self._alerts = QuotaAlerts(enabled=self._notifications_enabled())
        self._panel = UsagePanel.alloc().initWithStore_(store)
        self._build_menu()
        self._item.setMenu_(self._menu)
        self._update_label()
        return self

    # -- menu --------------------------------------------------------------

    @objc.python_method
    def _build_menu(self) -> None:
        menu = NSMenu.alloc().init()
        menu.setDelegate_(self)

        panel_item = NSMenuItem.alloc().init()
        panel_item.setView_(self._panel)
        menu.addItem_(panel_item)
        menu.addItem_(NSMenuItem.separatorItem())

        metric_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Menu bar shows", None, ""
        )
        self._metric_menu = NSMenu.alloc().init()
        for key, title in METRICS:
            entry = self._metric_menu.addItemWithTitle_action_keyEquivalent_(
                title, "metricChosen:", ""
            )
            entry.setTarget_(self)
            entry.setRepresentedObject_(key)
        metric_item.setSubmenu_(self._metric_menu)
        menu.addItem_(metric_item)

        for title, action in (
            ("Refresh now", "refresh:"),
            ("Rescan all logs", "rescan:"),
        ):
            entry = menu.addItemWithTitle_action_keyEquivalent_(title, action, "")
            entry.setTarget_(self)

        self._notify_entry = menu.addItemWithTitle_action_keyEquivalent_(
            "Notify at 80% and 95%", "toggleNotifications:", ""
        )
        self._notify_entry.setTarget_(self)

        self._icon_entry = menu.addItemWithTitle_action_keyEquivalent_(
            "Orange icon", "toggleIconColor:", ""
        )
        self._icon_entry.setTarget_(self)

        self._login_entry = menu.addItemWithTitle_action_keyEquivalent_(
            "Launch at login", "toggleLogin:", ""
        )
        self._login_entry.setTarget_(self)

        menu.addItem_(NSMenuItem.separatorItem())
        quit_entry = menu.addItemWithTitle_action_keyEquivalent_("Quit", "quit:", "q")
        quit_entry.setTarget_(self)

        self._menu = menu

    def menuWillOpen_(self, menu) -> None:
        # Opening the menu re-reads the logs; quota windows keep their own slower cadence.
        self._store.refresh_now()
        self._panel.refresh()
        self._sync_menu_state()

    @objc.python_method
    def _sync_menu_state(self) -> None:
        current = self._metric()
        for index, (key, _) in enumerate(METRICS):
            self._metric_menu.itemAtIndex_(index).setState_(1 if key == current else 0)
        self._login_entry.setState_(1 if login_item.is_enabled() else 0)
        self._icon_entry.setState_(1 if self._colored_icon() else 0)
        self._notify_entry.setState_(1 if self._notifications_enabled() else 0)

    # -- actions -----------------------------------------------------------

    def refresh_(self, sender) -> None:
        self._store.refresh_now(include_limits=True)

    def rescan_(self, sender) -> None:
        self._store.rescan_from_scratch()

    def toggleNotifications_(self, sender) -> None:
        enabled = not self._notifications_enabled()
        _defaults().setBool_forKey_(enabled, NOTIFY_KEY)
        self._alerts.enabled = enabled
        self._sync_menu_state()

    def toggleIconColor_(self, sender) -> None:
        colored = not self._colored_icon()
        _defaults().setBool_forKey_(colored, COLORED_ICON_KEY)
        self._item.button().setImage_(menu_bar_image(colored=colored))
        self._sync_menu_state()

    def toggleLogin_(self, sender) -> None:
        login_item.toggle(self._app_path)
        self._sync_menu_state()

    def metricChosen_(self, sender) -> None:
        _defaults().setObject_forKey_(sender.representedObject(), METRIC_KEY)
        self._sync_menu_state()
        self._update_label()

    def quit_(self, sender) -> None:
        self._store.stop()
        NSApplication.sharedApplication().terminate_(None)

    # -- label -------------------------------------------------------------

    @objc.python_method
    def _notifications_enabled(self) -> bool:
        defaults = _defaults()
        if defaults.objectForKey_(NOTIFY_KEY) is None:
            return True  # on by default: the point of the app is to warn you in time
        return bool(defaults.boolForKey_(NOTIFY_KEY))

    @objc.python_method
    def _colored_icon(self) -> bool:
        return bool(_defaults().boolForKey_(COLORED_ICON_KEY))

    @objc.python_method
    def _metric(self) -> str:
        return _defaults().stringForKey_(METRIC_KEY) or "five_hour"

    @objc.python_method
    def _update_label(self) -> None:
        snapshot = self._store.snapshot
        text = fmt.menu_bar_label(self._metric(), snapshot.limits, snapshot.today_cost)
        self._item.button().setTitle_(" " + text if text else "")

    def storeUpdated(self) -> None:
        """Called on the main thread whenever the store has new numbers."""
        self._update_label()
        self._panel.refresh()
        self._check_quota_alert()

    @objc.python_method
    def _check_quota_alert(self) -> None:
        snapshot = self._store.snapshot
        window = snapshot.limits.five_hour
        alert = self._alerts.check(
            window.used_percent if window else None,
            window.resets_at if window else None,
            snapshot.five_hour_eta,
        )
        if alert is not None:
            self._notifier.deliver(alert)

    def onStoreUpdate(self) -> None:
        """Thread-safe entry point handed to the store."""
        AppHelper.callAfter(self.storeUpdated)
