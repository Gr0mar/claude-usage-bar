import unittest
from datetime import datetime, timedelta, timezone

from quotabar import formatting as fmt
from quotabar.limits import LimitWindow, LimitsSnapshot


class FormattingTests(unittest.TestCase):
    def test_money_scales_precision_to_size(self):
        self.assertEqual(fmt.money(1234.5), "$1234")
        self.assertEqual(fmt.money(12.34), "$12.3")
        self.assertEqual(fmt.money(1.234), "$1.23")
        self.assertEqual(fmt.money(0.004), "<$0.01")
        self.assertEqual(fmt.money(0), "$0.00")

    def test_tokens_use_short_units(self):
        self.assertEqual(fmt.tokens(950), "950")
        self.assertEqual(fmt.tokens(12_300), "12.3k")
        self.assertEqual(fmt.tokens(4_500_000), "4.5M")
        self.assertEqual(fmt.tokens(2_100_000_000), "2.1B")

    def test_countdown_reads_as_a_sentence(self):
        now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(fmt.countdown(now + timedelta(minutes=45), now), "resets in 45m")
        self.assertEqual(fmt.countdown(now + timedelta(hours=2, minutes=14), now), "resets in 2h 14m")
        self.assertEqual(fmt.countdown(now + timedelta(days=2, hours=1), now), "resets in 2d 1h")
        self.assertEqual(fmt.countdown(now - timedelta(minutes=1), now), "resetting")
        self.assertIsNone(fmt.countdown(None, now))

    def test_elapsed(self):
        self.assertEqual(fmt.elapsed(timedelta(minutes=8)), "8m")
        self.assertEqual(fmt.elapsed(timedelta(hours=1, minutes=5)), "1h 5m")


class GaugeFillTests(unittest.TestCase):
    QUOTA = LimitsSnapshot(five_hour=LimitWindow(85.0), seven_day=LimitWindow(20.0))

    def test_the_dial_reads_the_five_hour_window(self):
        self.assertAlmostEqual(fmt.gauge_fill("five_hour", self.QUOTA), 0.85)

    def test_the_weekly_metric_moves_the_dial_to_the_weekly_window(self):
        self.assertAlmostEqual(fmt.gauge_fill("seven_day", self.QUOTA), 0.20)

    def test_a_cost_label_still_leaves_the_dial_on_the_session_quota(self):
        # A dial full of dollars has no full mark to fill towards.
        for metric in ("today", "icon"):
            self.assertAlmostEqual(fmt.gauge_fill(metric, self.QUOTA), 0.85)

    def test_no_reading_is_not_an_empty_dial(self):
        self.assertIsNone(fmt.gauge_fill("five_hour", LimitsSnapshot()))


class TimeOfDayTests(unittest.TestCase):
    #: Local time, so the formatter's conversion is a no-op and only the clock is tested.
    MORNING = datetime(2026, 9, 6, 8, 5, tzinfo=timezone.utc).astimezone()
    AFTERNOON = datetime(2026, 9, 6, 22, 47, tzinfo=timezone.utc).astimezone()

    def test_a_24_hour_clock_pads_the_hour_and_says_nothing_else(self):
        self.assertEqual(fmt.time_of_day(self.MORNING, hour12=False),
                         self.MORNING.strftime("%H:%M"))

    def test_a_12_hour_clock_drops_the_leading_zero_and_names_the_half(self):
        for moment in (self.MORNING, self.AFTERNOON):
            written = fmt.time_of_day(moment, hour12=True)
            self.assertTrue(written.endswith(" AM") or written.endswith(" PM"), written)
            self.assertEqual(written.split(":")[0], str(moment.hour % 12 or 12))

    def test_midnight_and_noon_are_12_not_0(self):
        midnight = self.MORNING.replace(hour=0, minute=30)
        noon = self.MORNING.replace(hour=12, minute=30)
        self.assertEqual(fmt.time_of_day(midnight, hour12=True), "12:30 AM")
        self.assertEqual(fmt.time_of_day(noon, hour12=True), "12:30 PM")

    def test_without_macos_to_ask_the_clock_is_24_hour(self):
        # The suite runs on a plain interpreter, so nothing can answer.
        self.assertIsNone(fmt.clock_is_12_hour())
        self.assertEqual(fmt.time_of_day(self.MORNING), self.MORNING.strftime("%H:%M"))


class MenuBarLabelTests(unittest.TestCase):
    QUOTA = LimitsSnapshot(LimitWindow(21.0), LimitWindow(4.0))
    NO_QUOTA = LimitsSnapshot()

    def test_quota_metrics_show_their_window(self):
        self.assertEqual(fmt.menu_bar_label("five_hour", self.QUOTA, 12.0), "21%")
        self.assertEqual(fmt.menu_bar_label("seven_day", self.QUOTA, 12.0), "4%")

    def test_the_label_falls_back_to_todays_cost_without_a_quota_window(self):
        # What every user sees while the usage endpoint is rate-limiting.
        self.assertEqual(fmt.menu_bar_label("five_hour", self.NO_QUOTA, 12.34), "$12.3")
        self.assertEqual(fmt.menu_bar_label("seven_day", self.NO_QUOTA, 12.34), "$12.3")

    def test_the_cost_metric_ignores_the_quota(self):
        self.assertEqual(fmt.menu_bar_label("today", self.QUOTA, 12.34), "$12.3")

    def test_the_icon_only_metric_has_no_text(self):
        self.assertEqual(fmt.menu_bar_label("icon", self.QUOTA, 12.34), "")


if __name__ == "__main__":
    unittest.main()
